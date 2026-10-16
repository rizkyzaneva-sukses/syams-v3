"""Logika Control System sesuai sheet lama "simulasi master control".

Aturan inti (diambil dari rumus sheet, bukan dikarang):
  * 15 tahap berurutan; tahap tak terpakai ditandai "-".
  * Tahap sekarang = tahap pertama yang belum SELESAI / "-".
  * Priority order: URGENT bila ada masalah terbuka atau tahap URGENT, PERHATIAN bila
    ada tahap PERHATIAN, SELESAI bila semua tahap selesai, selain itu PROGRES.
  * Active qty = total qty order, kecuali order SELESAI (0).
  * Durasi SLA per tahap dari SLA Engine; versi SLA berlaku sesuai tanggal order dibuat.

Yang dicatat PIC hanya fakta (tahap selesai / dilewati / ada masalah). Status
PROGRES / PERHATIAN / URGENT diturunkan dari SLA supaya tidak perlu diketik manual.
"""
import re
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models as m
from .control_models import (GarmentType, OrderBlock, OrderSequence, OrderStage, PicMaster,
                             StageSlaItem, StageSlaVersion)
from .flow_engine import FLOW_DEFINITIONS

# (kode, label, jenis) — jenis "auto" = diturunkan dari alur CMO/Finance yang sudah ada.
STAGES = [
    ("INVOICE", "INVOICE", "auto"),
    ("PPM", "PPM", "auto"),
    ("SAMPLE", "SAMPLE", "auto"),
    ("SPK_RELEASED", "SPK RELEASED", "auto"),
    ("BAHAN", "BAHAN", "manual"),
    ("CUTTING", "CUTTING", "manual"),
    ("SORTIR", "SORTIR", "manual"),
    ("PRINTING", "PRINTING", "manual"),
    ("BORDIR", "BORDIR", "manual"),
    ("QC_SB", "QC S/B", "manual"),
    ("SEWING", "SEWING", "manual"),
    ("ACC", "ACC", "manual"),
    ("QC_PACK", "QC/PACK", "manual"),
    ("REVISI", "REVISI", "manual"),
    ("SHIPPING", "SHIPPING", "manual"),
]
STAGE_CODES = [s[0] for s in STAGES]
STAGE_LABEL = {code: label for code, label, _ in STAGES}
AUTO_STAGES = {code for code, _, kind in STAGES if kind == "auto"}
DEFAULT_OFF_STAGES = {"REVISI"}  # sheet: "Jika tidak ada revisi gunakan '-'"

R = m.Role
_PROD = (R.COO_MANAGER, R.PRODUCTION_PIC)
_PRINT = (R.COO_MANAGER, R.PRINTING_PIC, R.PRODUCTION_PIC)
STAGE_ROLES = {
    "BAHAN": _PROD, "CUTTING": _PROD, "SORTIR": _PROD, "SEWING": _PROD, "ACC": _PROD,
    "QC_PACK": _PROD, "REVISI": _PROD,
    "PRINTING": _PRINT, "BORDIR": _PRINT, "QC_SB": _PRINT,
    "SHIPPING": (R.COO_MANAGER, R.SHIPMENT_ADMIN),
}
BLOCK_EXTRA_ROLES = (R.CMO_MANAGER, R.COO_MANAGER)

# (kode, durasi hari, PIC utama, kapasitas harian, satuan, catatan) — nilai dari tab SLA ENGINE.
DEFAULT_SLA = [
    ("INVOICE", 1, "CFO / CMO", 10, "ORDER", "DP / outstanding / selesai"),
    ("PPM", 1, "CMO", 10, "ORDER", "Persiapan PPM"),
    ("SAMPLE", 3, "FAHRUL", 4, "ARTICLE", "Pembuatan sample"),
    ("SPK_RELEASED", 1, "CMO", 10, "ORDER", "Release produksi"),
    ("BAHAN", 2, "RIADI", 500, "PCS", "Purchasing / kesiapan bahan"),
    ("CUTTING", 2, "SITI", 500, "PCS", None),
    ("SORTIR", 1, "SITI", 500, "PCS", None),
    ("PRINTING", 5, "IMAN", 500, "PCS", None),
    ("BORDIR", 4, "IMAN", 300, "PCS", "Jika tidak ada bordir, lewati tahap ini"),
    ("QC_SB", 1, "SITI", 500, "PCS", "QC printing/bordir"),
    ("SEWING", 3, "SITI", 450, "PCS", None),
    ("ACC", 2, "SITI", 500, "PCS", "Accessories"),
    ("QC_PACK", 1, "SITI", 500, "PCS", None),
    ("REVISI", 1, "SITI", 300, "PCS", "Aktifkan hanya bila ada revisi"),
    ("SHIPPING", 1, "CMO / COO", 500, "PCS", None),
]
DEFAULT_WARNING_PCT = 0.8
DEFAULT_GARMENTS = ["T-SHIRT", "HOODIE", "SWEATSHIRT", "JACKET", "PANTS", "SHORTS", "SHIRT", "JERSEY", "OTHER"]
DEFAULT_PICS = [
    ("SITI", "OPERATION / GM"), ("IMAN", "PRINTING / BORDIR"), ("FAHRUL", "SAMPLE / PRODUCT DEV"),
    ("RIADI", "PURCHASING"), ("CECEP", "CMO"), ("LUTFI", "CFO"), ("DEBI", "CMO ASSISTANT"),
    ("DIKI", "SAMPLE ASSISTANT"), ("YUNI", "CHRO"),
]
PRIORITY_SORT = {"URGENT": 1, "PERHATIAN": 2, "PROGRES": 3, "SELESAI": 4}


# ───────────────────────────── Order ID ─────────────────────────────

def next_order_id(db: Session, on_date: date | None = None) -> str:
    """SYM-YYMM-NNN, nomor naik per bulan. Baris counter dikunci agar tidak bentrok."""
    period = (on_date or date.today()).strftime("%y%m")
    prefix = f"SYM-{period}-"
    row = db.query(OrderSequence).filter_by(period=period).with_for_update().first()
    if row is None:
        highest = 0
        for (existing,) in db.query(m.Order.order_id).filter(m.Order.order_id.like(prefix + "%")):
            tail = existing[len(prefix):]
            if tail.isdigit():
                highest = max(highest, int(tail))
        row = OrderSequence(period=period, last_no=highest)
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            row = db.query(OrderSequence).filter_by(period=period).with_for_update().one()
    row.last_no += 1
    db.flush()
    return f"{prefix}{row.last_no:03d}"


# ───────────────────────────── Data awal ─────────────────────────────

def ensure_control_defaults(db: Session) -> None:
    """Isi master data awal dari sheet lama bila masih kosong. Aman dipanggil berulang."""
    if db.query(StageSlaVersion).first() is None:
        version = StageSlaVersion(version=1, change_reason="Standar awal dari sheet simulasi master control")
        db.add(version)
        db.flush()
        for order, (code, days, pic, cap, unit, note) in enumerate(DEFAULT_SLA, start=1):
            db.add(StageSlaItem(version_fk=version.id, stage_code=code, sort_order=order, duration_days=days,
                                primary_pic=pic, is_active=True, daily_capacity=cap, capacity_unit=unit,
                                warning_pct=DEFAULT_WARNING_PCT, note=note))
    if db.query(GarmentType).first() is None:
        for order, name in enumerate(DEFAULT_GARMENTS, start=1):
            db.add(GarmentType(name=name, sort_order=order))
    if db.query(PicMaster).first() is None:
        for name, role_label in DEFAULT_PICS:
            db.add(PicMaster(name=name, role_label=role_label))
    db.commit()


class SlaBook:
    """Semua versi SLA dimuat sekali supaya board tidak query per order."""

    def __init__(self, db: Session):
        self.versions = db.query(StageSlaVersion).order_by(StageSlaVersion.id).all()
        self.items: dict[int, dict[str, StageSlaItem]] = {}
        for item in db.query(StageSlaItem).all():
            self.items.setdefault(item.version_fk, {})[item.stage_code] = item

    def for_order(self, order) -> dict[str, StageSlaItem]:
        if not self.versions:
            return {}
        chosen = self.versions[0]
        for version in self.versions:
            if order.created_at is None or version.created_at <= order.created_at:
                chosen = version
        return self.items.get(chosen.id, {})

    def active(self) -> tuple[StageSlaVersion | None, dict[str, StageSlaItem]]:
        if not self.versions:
            return None, {}
        latest = self.versions[-1]
        return latest, self.items.get(latest.id, {})


# ───────────────────────────── Turunan status ─────────────────────────────

def parse_extra_total(text: str | None) -> int:
    """'M+2/L+1' → 3. Format bebas: semua angka setelah tanda + dijumlahkan."""
    return sum(int(n) for n in re.findall(r"\+\s*(\d+)", text or ""))


def _flow_for(order) -> list[str]:
    key = getattr(order.order_type, "value", order.order_type)
    return FLOW_DEFINITIONS.get(key, [])


def _auto_disposition(code: str, flow: list[str], step: str, spk_released: bool) -> str:
    """DONE | SKIP | PENDING untuk tahap yang diturunkan dari alur CMO/Finance."""
    idx = flow.index(step) if step in flow else 0

    def passed(name: str) -> bool:
        return name in flow and idx > flow.index(name)

    if code == "INVOICE":
        return "DONE" if passed("INVOICE") else "PENDING"
    if code == "PPM":
        if "PPM" not in flow:
            return "SKIP"
        return "DONE" if passed("PPM") else "PENDING"
    if code == "SAMPLE":
        if "SAMPLE" not in flow:
            return "SKIP"
        return "DONE" if passed("SAMPLE_APPROVED") else "PENDING"
    if code == "SPK_RELEASED":
        if "SPK" not in flow:
            return "SKIP"
        return "DONE" if (passed("SPK") or spk_released) else "PENDING"
    return "PENDING"


def build_order_view(order, sla: dict[str, StageSlaItem], rows: dict[str, OrderStage],
                     blocks: list[OrderBlock], spk_released_at: datetime | None, today: date,
                     derived: dict[str, datetime] | None = None, exceptions: list | None = None,
                     cmo: dict | None = None) -> dict:
    derived = derived or {}
    exceptions = exceptions or []
    flow = _flow_for(order)
    step = order.flow_step or "ORDER"
    produces = "PRODUCTION" in flow
    open_blocks = [b for b in blocks if b.resolved_at is None]
    blocked_stages = {b.stage_code for b in open_blocks if b.stage_code}

    dispositions: dict[str, str] = {}
    for code, _, kind in STAGES:
        if kind == "auto":
            dispositions[code] = _auto_disposition(code, flow, step, spk_released_at is not None)
            continue
        row = rows.get(code)
        if not produces:
            dispositions[code] = "SKIP"
        elif row and row.state == "DONE":
            dispositions[code] = "DONE"
        elif code in derived:
            dispositions[code] = "DONE"
        elif row and row.state == "SKIPPED":
            dispositions[code] = "SKIP"
        elif row and row.state == "ENABLED":
            dispositions[code] = "PENDING"
        else:
            dispositions[code] = "SKIP" if code in DEFAULT_OFF_STAGES else "PENDING"

    current = next((code for code, _, _ in STAGES if dispositions[code] == "PENDING"), None)
    spk_done = dispositions["SPK_RELEASED"] == "DONE"

    stages = []
    done_times: list[datetime] = []
    for code, label, kind in STAGES:
        item = sla.get(code)
        row = rows.get(code)
        disposition = dispositions[code]
        days = item.duration_days if item else 0
        started = due = None
        done_at = None
        if disposition == "DONE":
            status = "SELESAI"
            done_at = row.done_at if row and row.state == "DONE" and row.done_at else derived.get(code)
            if done_at:
                done_times.append(done_at)
        elif disposition == "SKIP":
            status = "-"
        elif code == current:
            status = "PROGRES"
            if kind == "manual" and spk_done:
                base = [spk_released_at or order.created_at] + done_times
                started = max(t for t in base if t)
                due = started.date() + timedelta(days=days)
                elapsed = (today - started.date()).days
                warn = item.warning_pct if item else DEFAULT_WARNING_PCT
                if today > due:
                    status = "URGENT"
                elif days > 0 and elapsed / days >= warn:
                    status = "PERHATIAN"
        else:
            status = ""
        if code in blocked_stages and disposition != "SKIP":
            status = "URGENT"
        stages.append({
            "code": code, "label": label, "kind": kind, "status": status, "is_current": code == current,
            "sla_days": days, "started_at": started, "due_date": due,
            "done_at": done_at,
            "from_data": disposition == "DONE" and kind == "manual" and not (row and row.state == "DONE"),
            "pic": (row.pic_name if row and row.pic_name else (item.primary_pic if item else None)),
            "pic_override": bool(row and row.pic_name), "has_block": code in blocked_stages,
            "toggleable": kind == "manual" and produces,
            "note": row.note if row else None,
        })

    statuses = {s["status"] for s in stages}
    red = [e for e in exceptions if (e.severity or "").upper() == "RED"]
    yellow = [e for e in exceptions if (e.severity or "").upper() == "YELLOW"]
    if current is None:
        priority = "SELESAI"
    elif open_blocks or red or "URGENT" in statuses:
        priority = "URGENT"
    elif "PERHATIAN" in statuses or yellow:
        priority = "PERHATIAN"
    else:
        priority = "PROGRES"

    qty = sum(a.qty for a in order.articles)
    cur_view = next((s for s in stages if s["is_current"]), None)
    latest_block = max(open_blocks, key=lambda b: b.opened_at) if open_blocks else None
    top_exception = (red + yellow)[0] if (red or yellow) else None
    if latest_block:
        next_action = latest_block.next_action
    elif top_exception is not None and top_exception.next_action:
        next_action = top_exception.next_action
    elif cur_view:
        next_action = f"Selesaikan {cur_view['label']}"
    else:
        next_action = ""
    pic = (latest_block.pic_name if latest_block and latest_block.pic_name else (cur_view["pic"] if cur_view else None))
    return {
        "order_id": order.order_id, "buyer": order.buyer, "order_type": getattr(order.order_type, "value", order.order_type),
        "order_date": order.order_date, "deadline": order.buyer_deadline,
        "articles": [a.article_code for a in order.articles],
        "garment_types": sorted({a.garment_type for a in order.articles if a.garment_type}),
        "extra_size": " | ".join(a.extra_size for a in order.articles if a.extra_size),
        "extra_total": sum(parse_extra_total(a.extra_size) for a in order.articles),
        "mockup_url": next((a.mockup_url for a in order.articles if a.mockup_url), None),
        "design_image_id": next((a.design_image_id for a in order.articles if a.design_image_id), None),
        "total_qty": qty, "active_qty": 0 if priority == "SELESAI" else qty,
        "payment": "LUNAS" if order.finance_status == "PAID" else "OUTSTANDING",
        **{"invoice_status": "BELUM TERBIT", "sample_status": "SKIP", "revision": None, "buyer_approval": "TIDAK PERLU",
           "spk_released": False, "ready_to_coo": False, **(cmo or {})},
        "stages": stages, "current_stage": current, "current_stage_label": STAGE_LABEL.get(current, "SELESAI"),
        "priority": priority, "priority_sort": PRIORITY_SORT[priority], "pic": pic,
        "problem": "; ".join([b.problem for b in open_blocks] + [f"[Exception] {e.title}" for e in red + yellow]),
        "exception_count": len(red) + len(yellow),
        "next_action": next_action,
        "open_blocks": [block_out(b) for b in open_blocks],
        "sla_pending": cur_view is not None and cur_view["due_date"] is not None,
    }


# Proses di Production Queue → tahap di papan. QC S/B (QC sablon/bordir) hanya otomatis bila rute
# artikel memuat proses 'QC S/B'; bila tidak, PIC menandainya manual.
PROCESS_TO_STAGE = {"CUTTING": "CUTTING", "SORTIR": "SORTIR", "PRINTING": "PRINTING", "BORDIR": "BORDIR",
                    "SEWING": "SEWING", "ACCESSORIES": "ACC", "ACC": "ACC", "QC": "QC_PACK", "PACKING": "QC_PACK",
                    "QC S/B": "QC_SB", "QC SB": "QC_SB", "QC SABLON": "QC_SB", "QC_SB": "QC_SB"}


def _as_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return None


def derive_done_times(db: Session, orders: list) -> dict[int, dict[str, datetime]]:
    """Tahap yang sudah selesai menurut data modul lain, supaya PIC tidak input dua kali.

    * BAHAN    : material order = READY (BOM + material request + PO diterima).
    * Proses   : semua proses yang ada di rute artikel untuk tahap itu punya catatan
                 Production Queue berstatus DONE.
    * SHIPPING : semua shipment sudah SHIPPED/DELIVERED.
    """
    ids = [o.id for o in orders]
    result: dict[int, dict[str, datetime]] = {i: {} for i in ids}
    if not ids:
        return result
    by_id = {o.id: o for o in orders}
    movements: dict[int, list] = {}
    for mv in db.query(m.ProductionMovement).join(m.Article, m.Article.id == m.ProductionMovement.article_id) \
            .filter(m.Article.order_fk.in_(ids)):
        movements.setdefault(mv.article_id, []).append(mv)
    po_dates: dict[int, list] = {}
    for po in db.query(m.PurchaseOrder).filter(m.PurchaseOrder.order_fk.in_(ids), m.PurchaseOrder.material_status == "READY"):
        po_dates.setdefault(po.order_fk, []).append(po.arrival_date)
    ship_dates: dict[int, list] = {}
    for shipment in db.query(m.Shipment).filter(m.Shipment.order_fk.in_(ids)):
        ship_dates.setdefault(shipment.order_fk, []).append(shipment)

    for order in orders:
        out = result[order.id]
        if order.material_status == "READY":
            dates = [d for d in po_dates.get(order.id, []) if d]
            out["BAHAN"] = _as_datetime(max(dates)) if dates else order.updated_at
        per_stage: dict[str, list[bool]] = {}
        latest: dict[str, datetime] = {}
        for article in order.articles:
            route = [p.strip().upper() for p in (article.production_route or "").replace("\u2192", ">").replace("->", ">").split(">") if p.strip()]
            for process in route:
                stage = PROCESS_TO_STAGE.get(process)
                if not stage:
                    continue
                rows = [mv for mv in movements.get(article.id, []) if mv.process.upper() == process]
                per_stage.setdefault(stage, []).append(bool(rows) and all(mv.status == "DONE" for mv in rows))
                for mv in rows:
                    when = mv.ended_at or mv.updated_at
                    if when and (stage not in latest or when > latest[stage]):
                        latest[stage] = when
        for stage, oks in per_stage.items():
            if oks and all(oks):
                out[stage] = latest.get(stage) or order.updated_at
        shipments = ship_dates.get(order.id, [])
        if shipments and all(s.status in ("SHIPPED", "DELIVERED") for s in shipments):
            dates = [s.shipped_date for s in shipments if s.shipped_date]
            out["SHIPPING"] = _as_datetime(max(dates)) if dates else order.updated_at
    return result


def derive_cmo_facts(db: Session, orders: list) -> dict[int, dict]:
    """Kolom CMO di sheet lama: status invoice, status sample, revisi, buyer approval, siap ke COO."""
    ids = [o.id for o in orders]
    if not ids:
        return {}
    totals: dict[int, list] = {}
    for inv in db.query(m.Invoice).filter(m.Invoice.order_fk.in_(ids)):
        t = totals.setdefault(inv.order_fk, [0, 0])
        t[0] += float(inv.amount or 0)
        t[1] += float(inv.paid_amount or 0)
    latest: dict[tuple, m.SampleRecord] = {}
    for rec in db.query(m.SampleRecord).filter(m.SampleRecord.order_fk.in_(ids)).order_by(m.SampleRecord.id):
        latest[(rec.order_fk, rec.article_id if rec.article_id else rec.article_code)] = rec
    spk_released = {s.order_fk for s in db.query(m.SPK.order_fk).filter(m.SPK.order_fk.in_(ids), m.SPK.status == "RELEASED")}
    out: dict[int, dict] = {}
    for order in orders:
        amount, paid = totals.get(order.id, [0, 0])
        if amount <= 0:
            invoice = "BELUM TERBIT"
        elif paid >= amount:
            invoice = "SELESAI"
        elif paid > 0:
            invoice = "DP"
        else:
            invoice = "OUTSTANDING"
        required = [a for a in order.articles if a.sample_required or getattr(order.order_type, "value", order.order_type) == "SAMPLE_ONLY"]
        records = [latest.get((order.id, a.id)) or latest.get((order.id, a.article_code)) for a in required]
        if not required:
            sample, approval, revision = "SKIP", "TIDAK PERLU", None
        else:
            got = [r for r in records if r]
            if got and len(got) == len(required) and all(r.status == "APPROVED" and r.customer_approved_by_id for r in got):
                sample, approval = "APPROVED", "APPROVED"
            elif any(r.status in ("REVISION", "REJECTED") for r in got):
                sample, approval = "REVISION", "PENDING"
            else:
                sample, approval = "PROGRES", "PENDING"
            top = max((r.sample_version or 1 for r in got), default=1)
            revision = f"REV-{top - 1:02d}"
        released = order.id in spk_released
        out[order.id] = {"invoice_status": invoice, "sample_status": sample, "revision": revision,
                         "buyer_approval": approval, "spk_released": released,
                         "ready_to_coo": bool(released and approval in ("APPROVED", "TIDAK PERLU"))}
    return out


def block_out(b: OrderBlock) -> dict:
    return {"id": b.id, "stage_code": b.stage_code, "problem": b.problem, "next_action": b.next_action,
            "pic_name": b.pic_name, "opened_at": b.opened_at, "resolved_at": b.resolved_at,
            "resolution_note": b.resolution_note}


def build_board(db: Session, orders: list, today: date | None = None) -> list[dict]:
    today = today or date.today()
    ids = [o.id for o in orders]
    book = SlaBook(db)
    if not book.versions:
        ensure_control_defaults(db)
        book = SlaBook(db)
    rows_by_order: dict[int, dict[str, OrderStage]] = {}
    blocks_by_order: dict[int, list[OrderBlock]] = {}
    spk_by_order: dict[int, datetime] = {}
    if ids:
        for row in db.query(OrderStage).filter(OrderStage.order_fk.in_(ids)):
            rows_by_order.setdefault(row.order_fk, {})[row.stage_code] = row
        for block in db.query(OrderBlock).filter(OrderBlock.order_fk.in_(ids)):
            blocks_by_order.setdefault(block.order_fk, []).append(block)
        for spk in db.query(m.SPK).filter(m.SPK.order_fk.in_(ids), m.SPK.status == "RELEASED"):
            when = spk.released_at or spk.created_at
            if spk.order_fk not in spk_by_order or when < spk_by_order[spk.order_fk]:
                spk_by_order[spk.order_fk] = when
    derived = derive_done_times(db, orders)
    cmo_facts = derive_cmo_facts(db, orders)
    exceptions_by_order: dict[int, list] = {}
    if ids:
        for item in db.query(m.ExceptionItem).filter(m.ExceptionItem.order_fk.in_(ids),
                                                     m.ExceptionItem.status.in_(["OPEN", "IN_PROGRESS"]),
                                                     m.ExceptionItem.confidential.is_(False)):
            exceptions_by_order.setdefault(item.order_fk, []).append(item)
    return [build_order_view(o, book.for_order(o), rows_by_order.get(o.id, {}), blocks_by_order.get(o.id, []),
                             spk_by_order.get(o.id), today, derived.get(o.id), exceptions_by_order.get(o.id), cmo_facts.get(o.id))
            for o in orders]
