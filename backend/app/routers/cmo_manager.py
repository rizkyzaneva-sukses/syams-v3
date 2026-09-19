"""CMO Manager — Morning Priority (revisi #13 / #14, blueprint final CMO Manager).

Blueprint yang dikunci (revisi #14 poin 2, penjelasan revisi #13 poin 2):

    "MORNING PRIORITY: action-first, menampilkan prioritas artikel, kapasitas,
     bottleneck, SLA, PO/draft order menunggu review, quotation menunggu
     approval, sample decision, SPK siap Release to COO, exception, owner, due,
     evidence/gate, dan handoff berikutnya."

Halaman ini adalah ANTREAN KEPUTUSAN milik Cecep (CMO_MANAGER), bukan dashboard
analitik. Satu endpoint baca `GET /cmo/manager-priority` merakit seluruh antrean
tersebut dari tabel yang SUDAH ADA: orders, articles, po_intakes, quotations,
sample_records (+sample_evidence), spks, exceptions, capacity_snapshots,
production_plans, shipment_exceptions, users.

Aturan yang dipegang:
* READ-ONLY. Tidak ada tabel baru, tidak ada mutasi data.
* Permission ditegakkan di server, bukan hanya di UI: hanya CEO / CMO_MANAGER /
  CMO_SUPPORT yang boleh membaca; CFO dan COO mendapat 403.
* Setiap baris membawa `order_id` (dan `order_fk`) supaya UI bisa membuka Order
  terkait. Baris yang belum punya Order (PO intake masih DRAFT) membawa
  `order_link` = None + `source_link` ke dokumen sumbernya.
* Batas kewenangan (revisi #14 poin 9): CMO memegang customer truth, commercial
  validation, business priority, approval dan CMO SPK Release. Exception
  produksi/keuangan tetap milik COO/CFO/CEO, jadi antrean exception di sini
  hanya yang komersial/customer.
"""
from datetime import date, datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from .. import models as m

router = APIRouter(prefix="/cmo", tags=["cmo-manager"])

# Hanya pemilik customer truth yang boleh melihat antrean ini.
VIEW_ROLES = {"CEO", "CMO_MANAGER", "CMO_SUPPORT"}

# Kategori exception yang menjadi kewenangan CMO. Sisanya (produksi, keuangan,
# HR, QC, pengiriman operasional) tidak boleh muncul di Morning Priority Cecep.
COMMERCIAL_EXCEPTION_WORDS = (
    "sales", "customer", "buyer", "quotation", "quote", "order", "commercial",
    "commitment", "po ", "crm", "delivery", "pengiriman",
)

# Status PO intake yang masih menunggu keputusan Cecep (Deby sudah menyiapkan).
PO_PENDING_REVIEW = ("SUBMITTED",)
PO_STILL_PREPARING = ("DRAFT", "NEEDS_INFO")
# Status quotation yang menunggu approval CMO.
QUOTATION_PENDING = ("DRAFT", "SENT")
# Status SPK yang masih di tangan Deby (Generate/Preview/Print) — belum siap Release.
SPK_PRE_RELEASE = ("NEW", "DRAFT", "PREVIEWED")
# Status SPK yang sudah di-Release CMO dan diteruskan ke COO (handoff berikutnya).
SPK_RELEASED = ("RELEASED", "BATCH_RELEASED", "IN_PRODUCTION")


def _require_view(user):
    if user.role.value not in VIEW_ROLES:
        raise HTTPException(403, "Morning Priority CMO Manager tidak tersedia untuk peran ini.")


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _as_date(value):
    """Normalisasi Date/DateTime/str menjadi date untuk hitungan SLA."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_list(raw):
    """Baca kolom JSON berbentuk list tanpa memercayai bentuk mentahnya."""
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _live_articles(order):
    """Artikel aktif sebuah Order — dipakai untuk prioritas artikel & Demand Gap."""
    return list(order.articles or [])


def _order_article_codes(order):
    return [a.article_code for a in _live_articles(order)]


def _row(*, task_id, decision_type, priority_rank, order=None, buyer=None, article=None,
         article_qty=None, status=None, gate=None, evidence=None, next_action=None,
         owner="CMO_MANAGER", due=None, sla=None, sla_days=None, handoff=None,
         updated=None, severity="GREEN", source=None, source_link=None, order_link=None,
         open_target=None):
    """Satu baris antrean keputusan Morning Priority.

    Kolomnya sengaja seragam untuk seluruh seksi (revisi #13 poin 3): Task ID,
    Buyer ID, Order ID, Article ID bila ada, jenis keputusan, status,
    evidence/gate, prepared_by/source, decision owner, due/SLA, next handoff,
    updated_at.
    """
    return {
        "task_id": task_id,
        "decision_type": decision_type,
        "priority_rank": priority_rank,
        "order_id": order.order_id if order is not None else None,
        "order_fk": order.id if order is not None else None,
        "buyer": buyer or (order.buyer if order is not None else None),
        "customer_id": order.customer_id if order is not None else None,
        "article_code": article,
        "article_qty": article_qty,
        "status": status,
        "gate": gate,
        "evidence": evidence,
        "next_action": next_action,
        "owner": owner,
        "due": _iso(due),
        "sla": sla,
        "sla_days": sla_days,
        "handoff": handoff,
        "updated_at": _iso(updated),
        "severity": severity,
        "source": source,
        "source_link": source_link,
        "order_link": order_link if order_link is not None else (
            f"/orders/{order.order_id}" if order is not None else None),
        "open_target": open_target,
    }


def _sla(due, today):
    """Hitung umur SLA terhadap due date. Overdue = negatif hari."""
    due_date = _as_date(due)
    if due_date is None:
        return "TANPA_DUE", None
    days = (due_date - today).days
    if days < 0:
        return "OVERDUE", days
    if days == 0:
        return "DUE_TODAY", days
    if days <= 3:
        return "DUE_3_HARI", days
    if days <= 7:
        return "DUE_7_HARI", days
    return "AMAN", days


def _severity_for(sla):
    if sla == "OVERDUE":
        return "RED"
    if sla in ("DUE_TODAY", "DUE_3_HARI"):
        return "YELLOW"
    return "GREEN"


def _evidence_list(db, sample):
    """Bukti sample sebagai daftar {file_name, note, uploaded_at} — tanpa isi file."""
    rows = (db.query(m.SampleEvidence)
            .filter(m.SampleEvidence.sample_fk == sample.id)
            .order_by(m.SampleEvidence.id.asc()).all())
    return [{
        "file_name": ev.file_name,
        "file_mime": ev.file_mime,
        "note": ev.note,
        "uploaded_at": _iso(ev.created_at),
    } for ev in rows]


def _order_priority_score(order, today):
    """Prioritas artikel/order: makin dekat deadline, makin tinggi.

    Mengembalikan (bucket, urgency_days, alasan). Dipakai pada seksi
    ARTICLE_PRIORITY dan untuk mengurutkan seluruh antrean CMO.
    """
    deadline = _as_date(order.buyer_deadline)
    if deadline is None:
        return 4, None, "Deadline buyer belum diisi"
    days = (deadline - today).days
    if days < 0:
        return 0, days, f"Melewati deadline buyer {abs(days)} hari"
    if days <= 3:
        return 1, days, f"Deadline buyer {days} hari lagi"
    if days <= 7:
        return 2, days, f"Deadline buyer {days} hari lagi"
    if days <= 21:
        return 3, days, f"Deadline buyer {days} hari lagi"
    return 4, days, f"Deadline buyer {days} hari lagi"


def _capacity_payload(db):
    """Kapasitas & bottleneck per proses dari capacity_snapshots (data terakhir).

    Load melebihi kapasitas = bottleneck produksi. Ini informasi read-only untuk
    konteks CMO: Cecep tidak mengubah kapasitas (itu milik COO).
    """
    snapshots = (db.query(m.CapacitySnapshot)
                 .order_by(m.CapacitySnapshot.snapshot_date.desc(),
                           m.CapacitySnapshot.process.asc()).all())
    if not snapshots:
        return {"as_of": None, "processes": [], "bottlenecks": [],
                "total_capacity": 0, "total_planned_load": 0, "total_wip": 0,
                "utilization_percent": None,
                "note": "Belum ada snapshot kapasitas."}

    latest_by_process = {}
    for snap in snapshots:
        latest_by_process.setdefault(snap.process, snap)

    processes = []
    bottlenecks = []
    for process, snap in sorted(latest_by_process.items()):
        utilization = round((snap.planned_load / snap.capacity) * 100, 2) if snap.capacity else None
        entry = {
            "process": process,
            "snapshot_date": _iso(snap.snapshot_date),
            "capacity": snap.capacity,
            "planned_load": snap.planned_load,
            "wip": snap.current_wip,
            "utilization_percent": utilization,
            "overload_qty": max(0, (snap.planned_load or 0) - (snap.capacity or 0)),
            "bottleneck": bool(utilization is not None and utilization >= 100),
        }
        processes.append(entry)
        if entry["bottleneck"]:
            bottlenecks.append(entry)

    total_capacity = sum(p["capacity"] or 0 for p in processes)
    total_load = sum(p["planned_load"] or 0 for p in processes)
    return {
        "as_of": processes[0]["snapshot_date"] if processes else None,
        "processes": processes,
        "bottlenecks": bottlenecks,
        "total_capacity": total_capacity,
        "total_planned_load": total_load,
        "total_wip": sum(p["wip"] or 0 for p in processes),
        "utilization_percent": round((total_load / total_capacity) * 100, 2) if total_capacity else None,
        "note": "Read-only: kapasitas dan beban produksi milik COO.",
    }


def _order_stage(order):
    """Terjemahkan status internal menjadi tahap yang bisa dibaca Cecep."""
    mapping = {
        "ORDER": "Order sedang diverifikasi CMO",
        "INVOICE": "Menunggu proses pembayaran (CFO)",
        "SAMPLE": "Sampel sedang diproses",
        "SPK_RELEASED": "Pesanan siap diproduksi",
        "PRODUCTION": "Pesanan sedang diproduksi",
        "QC": "Pemeriksaan kualitas selesai",
        "SHIPMENT": "Pesanan siap dikirim",
        "SHIPPED": "Pesanan telah dikirim",
        "CLOSED": "Pesanan selesai",
    }
    return mapping.get(order.flow_step, order.flow_step or "Belum ada tahap")


@router.get("/manager-priority")
def manager_priority(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Morning Priority CMO Manager — satu antrean keputusan action-first."""
    _require_view(user)
    today = date.today()
    now = datetime.now(timezone.utc)

    queues = []

    # ------------------------------------------------------------------ 1. PO
    # PO / draft order menunggu review Cecep (Deby sudah submit & lengkap).
    urgent_po, preparing_po = [], []
    for po in (db.query(m.POIntake)
               .order_by(m.POIntake.updated_at.asc()).all()):
        missing = [str(x) for x in _parse_list(po.missing_items_json)]
        order = db.get(m.Order, po.order_fk) if po.order_fk else None
        sla, days = _sla(po.buyer_deadline, today)
        entry = _row(
            task_id=f"PO-{po.id}", decision_type="PO_REVIEW", priority_rank=1,
            order=order, buyer=po.buyer, status=po.status,
            gate=("Belum lengkap: " + ", ".join(missing)) if missing else "Dokumen & artikel lengkap",
            evidence=(f"PO {po.po_number or '-'} · dokumen {po.document_name or 'BELUM ADA'}"),
            next_action=("Review kelengkapan lalu terima atau tolak, kemudian aktifkan Order"
                         if po.status in PO_PENDING_REVIEW else
                         "Deby lengkapi kekurangan sebelum bisa direview"),
            due=po.buyer_deadline, sla=sla, sla_days=days,
            handoff=("Cecep accept → Order aktif → CFO pricing/invoice" if po.status in PO_PENDING_REVIEW
                     else "Deby lengkapi evidence → submit ke Cecep"),
            updated=po.updated_at, severity=_severity_for(sla) if po.status in PO_PENDING_REVIEW else "GRAY",
            source="Deby (CMO Support)", source_link=f"/cmo/po-inbox/{po.id}/edit",
            open_target=f"/cmo/po-inbox/{po.id}/edit",
        )
        (urgent_po if po.status in PO_PENDING_REVIEW else preparing_po).append(entry)
    queues.append({
        "key": "PO_REVIEW", "label": "PO / Draft Order Menunggu Review",
        "owner": "CMO_MANAGER", "priority_rank": 1,
        "handoff": "Cecep accept/reject & activate Order → CFO pricing",
        "rows": urgent_po + preparing_po,
    })

    # ------------------------------------------------------------- 2. QUOTATION
    quote_rows = []
    for quote in (db.query(m.Quotation).order_by(m.Quotation.created_at.asc()).all()):
        order = db.get(m.Order, quote.order_fk)
        pending = quote.status in QUOTATION_PENDING
        sla, days = _sla(quote.valid_until, today)
        margin = float(quote.margin_percent or 0)
        quote_rows.append(_row(
            task_id=f"QUO-{quote.id}", decision_type="QUOTATION_APPROVAL", priority_rank=2,
            order=order, buyer=order.buyer if order else None,
            article=", ".join(_order_article_codes(order)) if order else None,
            status=quote.status,
            gate=(f"Margin {margin}% · HPP {float(quote.hpp_total or 0):,.0f} {quote.currency} "
                  f"(batas CFO, CMO tidak mengubah HPP)"),
            evidence=f"Quotation {quote.quotation_no} · valid s/d {_iso(quote.valid_until) or '-'}",
            next_action=("Setujui/tolak lalu kirim ke buyer" if pending
                         else "Sudah diputuskan — pantau respons buyer"),
            due=quote.valid_until, sla=sla, sla_days=days,
            handoff="Approve → kirim ke buyer → buyer response → Order aktif",
            updated=quote.created_at,
            severity=_severity_for(sla) if pending else "GREEN",
            source="Deby (CMO Support) · basis harga CFO",
            open_target="/cmo/quotations",
        ))
    queues.append({
        "key": "QUOTATION_APPROVAL", "label": "Quotation Menunggu Approval",
        "owner": "CMO_MANAGER", "priority_rank": 2,
        "handoff": "Approve → send to buyer → CFO finance gate",
        "rows": quote_rows,
    })

    # ---------------------------------------------------------------- 3. SAMPLE
    sample_rows = []
    for sample in (db.query(m.SampleRecord).order_by(m.SampleRecord.id.asc()).all()):
        order = db.get(m.Order, sample.order_fk)
        evidence = _evidence_list(db, sample)
        decided = sample.customer_approved_by_id is not None or sample.customer_decision_at is not None
        sla, days = _sla(sample.completed_date or sample.requested_date, today)
        sample_rows.append(_row(
            task_id=f"SMP-{sample.id}", decision_type="SAMPLE_DECISION", priority_rank=3,
            order=order, buyer=order.buyer if order else None,
            article=sample.article_code, article_qty=None,
            status=sample.status,
            gate=(f"{len(evidence)} bukti terunggah" if evidence else "Bukti belum ada — Deby harus unggah"),
            evidence=("; ".join(e["file_name"] for e in evidence) if evidence else None),
            next_action=("Catat keputusan buyer (approve/reject) sesuai bukti" if not decided
                         else "Sudah diputuskan — lanjut ke SPK Generate"),
            due=sample.completed_date or sample.requested_date, sla=sla, sla_days=days,
            handoff="Keputusan buyer → SPK Generate (Deby) → CMO SPK Release",
            updated=sample.customer_decision_at or sample.created_at,
            severity=_severity_for(sla) if not decided else "GREEN",
            source="Deby (administrasi & evidence)",
            open_target="/cmo/samples",
        ))
    queues.append({
        "key": "SAMPLE_DECISION", "label": "Sample / PPM Decision",
        "owner": "CMO_MANAGER", "priority_rank": 3,
        "handoff": "Sample approved → SPK Generate → Release to COO",
        "rows": sample_rows,
    })

    # ------------------------------------------------------------------- 4. SPK
    spk_rows = []
    for spk in (db.query(m.SPK).order_by(m.SPK.id.asc()).all()):
        order = db.get(m.Order, spk.order_fk)
        if order is None:
            continue
        ready = spk.status not in SPK_PRE_RELEASE and spk.status not in SPK_RELEASED
        released = spk.status in SPK_RELEASED
        if spk.status == "VOID" and not spk.released_at:
            # SPK batal sebelum release: bukan antrean keputusan Cecep.
            continue
        sla, days = _sla(order.buyer_deadline, today)
        prerequisites = []
        if order.finance_gate_status not in ("VERIFIED", "APPROVED", "PAID"):
            prerequisites.append(f"finance gate {order.finance_gate_status}")
        samples = (db.query(m.SampleRecord)
                   .filter(m.SampleRecord.order_fk == order.id).all())
        needed = [s for s in samples if s.status not in ("NOT_REQUIRED",)]
        if needed and any(s.customer_approved_by_id is None for s in needed):
            prerequisites.append("Sample/PPM gate belum approved")
        quote = (db.query(m.Quotation).filter(m.Quotation.order_fk == order.id)
                 .order_by(m.Quotation.id.desc()).first())
        if quote is None:
            prerequisites.append("quotation belum ada")
        elif quote.status not in ("APPROVED", "ACCEPTED", "SENT"):
            prerequisites.append(f"quotation {quote.status}")
        spk_rows.append(_row(
            task_id=f"SPK-{spk.id}", decision_type="SPK_RELEASE", priority_rank=4,
            order=order, buyer=order.buyer,
            article=", ".join(_order_article_codes(order)) or None,
            status=spk.status,
            gate=("Siap Release" if ready else
                  ("Sudah di-Release CMO" if released else
                   ("Prasyarat kurang: " + ", ".join(prerequisites) if prerequisites
                    else "Perlu di-Generate/Print oleh Deby"))),
            evidence=(f"{spk.spk_no} v{spk.version} · "
                      f"released_by {spk.released_by or '-'} @ {_iso(spk.released_at) or '-'}"),
            next_action=("Periksa prasyarat lalu CMO SPK Release (handoff ke COO)" if ready
                         else "Pantau Batch Release & eksekusi COO"),
            due=order.buyer_deadline, sla=sla, sla_days=days,
            handoff=("Release to COO → Siti/COO Batch Release" if ready
                     else "COO Batch Release → produksi → delivery execution"),
            updated=spk.released_at or spk.created_at,
            severity=_severity_for(sla) if ready else "GREEN",
            source="Deby (Generate/Preview/Print) · Print bukan Release",
            open_target="/cmo/spk",
        ))
    queues.append({
        "key": "SPK_RELEASE", "label": "SPK Siap Release to COO",
        "owner": "CMO_MANAGER", "priority_rank": 4,
        "handoff": "CMO SPK Release → Release to COO → COO Batch Release",
        "rows": spk_rows,
    })

    # -------------------------------------------------------------- 5. EXCEPTION
    exception_rows = []
    for item in (db.query(m.ExceptionItem)
                 .filter(m.ExceptionItem.status.in_(["OPEN", "IN_PROGRESS"]))
                 .order_by(m.ExceptionItem.due_date.asc(),
                           m.ExceptionItem.id.asc()).all()):
        haystack = " ".join([item.category or "", item.title or "", item.source_module or ""]).lower()
        if not any(word in haystack for word in COMMERCIAL_EXCEPTION_WORDS):
            # Exception produksi/keuangan tetap milik COO/CFO/CEO.
            continue
        order = db.get(m.Order, item.order_fk) if item.order_fk else None
        sla, days = _sla(item.due_date, today)
        exception_rows.append(_row(
            task_id=f"EXC-{item.id}", decision_type="COMMERCIAL_EXCEPTION",
            priority_rank=5, order=order, buyer=order.buyer if order else item.owner_name,
            status=item.status,
            gate=f"{item.severity} · {item.category}",
            evidence=(item.evidence_ref or item.impact or "Belum ada bukti/dampak tercatat"),
            next_action=item.next_action or "Putuskan atau eskalasi ke CEO",
            owner=item.owner_role or "CMO_MANAGER",
            due=item.due_date, sla=sla, sla_days=days,
            handoff=("Eskalasi CEO" if item.decision_required else "Keputusan Cecep → audit"),
            updated=item.updated_at, severity=item.severity or _severity_for(sla),
            source=item.source_module or "Exception Center",
            open_target="/cmo/exception-center",
        ))
    queues.append({
        "key": "EXCEPTION_CENTER", "label": "Exception Center — Komersial & Customer",
        "owner": "CMO_MANAGER", "priority_rank": 5,
        "handoff": "Keputusan Cecep atau eskalasi CEO (bukan COO/CFO)",
        "rows": exception_rows,
    })

    # ------------------------------------------------------ 6. PRIORITAS ARTIKEL
    # Prioritas artikel/order aktif (bukan antrean keputusan, tapi urutan kerja).
    article_rows = []
    active_orders = (db.query(m.Order)
                     .filter(m.Order.overall_status != "CLOSED")
                     .order_by(m.Order.buyer_deadline.asc()).all())
    for order in active_orders:
        bucket, days, reason = _order_priority_score(order, today)
        live = _live_articles(order)
        total_qty = sum(int(a.qty or 0) for a in live)
        blocked = [f"{a.article_code}: {a.sample_status}"
                   for a in live if a.sample_required and a.sample_status not in ("APPROVED", "NOT_REQUIRED")]
        article_rows.append({
            "task_id": f"ART-{order.id}",
            "decision_type": "ARTICLE_PRIORITY",
            "priority_rank": bucket,
            "priority_label": ["KRITIS", "TINGGI", "SEDANG", "NORMAL", "BELUM_DIATUR"][bucket],
            "order_id": order.order_id,
            "order_fk": order.id,
            "buyer": order.buyer,
            "customer_id": order.customer_id,
            "articles": " + ".join(_order_article_codes(order)) or "Belum ada artikel",
            "article_code": ", ".join(_order_article_codes(order)) or None,
            "article_codes": _order_article_codes(order),
            "total_qty": total_qty,
            "status": order.overall_status,
            "stage": _order_stage(order),
            "gate": ("Sample artikel tertahan: " + "; ".join(blocked)) if blocked
                    else f"Finance gate {order.finance_gate_status}",
            "evidence": f"{len(live)} artikel · {total_qty} pcs",
            "next_action": ("Kejar sample/PPM dulu sebelum produksi" if blocked
                            else "Lanjutkan tahap berikutnya sesuai handoff"),
            "owner": "CMO_MANAGER",
            "due": _iso(order.buyer_deadline),
            "sla": _sla(order.buyer_deadline, today)[0],
            "sla_days": days,
            "handoff": _order_stage(order),
            "updated_at": _iso(order.updated_at),
            "severity": "RED" if bucket == 0 else ("YELLOW" if bucket == 1 else "GREEN"),
            "source": reason,
            "order_link": f"/orders/{order.order_id}",
            "open_target": f"/orders/{order.order_id}",
        })
    queues.append({
        "key": "ARTICLE_PRIORITY", "label": "Prioritas Artikel & Order",
        "owner": "CMO_MANAGER", "priority_rank": 6,
        "handoff": "Urutan kerja harian Cecep → Deby mengeksekusi administrasi",
        "rows": article_rows,
    })

    # ------------------------------------------------------------- 7. HANDOFFS
    # Handoff berikutnya: apa yang sedang berjalan di divisi lain setelah CMO.
    handoff_rows = []
    for plan in (db.query(m.ProductionPlan).order_by(m.ProductionPlan.id.asc()).all()):
        order = db.get(m.Order, plan.order_fk)
        handoff_rows.append(_row(
            task_id=f"PLAN-{plan.id}", decision_type="HANDOFF_COO_BATCH_RELEASE",
            priority_rank=2, order=order,
            status=plan.status,
            gate="COO Batch Release / rencana produksi",
            evidence=f"Rencana {_iso(plan.plan_date) or '-'} · {plan.notes or 'tanpa catatan'}",
            next_action="Monitor eksekusi COO — CMO tidak mengeksekusi produksi",
            owner="COO_MANAGER", due=plan.plan_date,
            sla=_sla(plan.plan_date, today)[0], sla_days=_sla(plan.plan_date, today)[1],
            handoff="COO produksi → QC → shipment (delivery execution milik COO)",
            updated=plan.updated_at, severity="GREEN",
            source="COO (Batch Release)", open_target="/coo/production",
        ))
    # Shipment outstanding yang belum diputuskan CEO: CMO memegang komitmen
    # customer-nya, CFO menilai uangnya, COO mengeksekusi pengirimannya.
    for ship_exc in (db.query(m.ShipmentException)
                     .filter(m.ShipmentException.ceo_decision.is_(None))
                     .order_by(m.ShipmentException.risk.asc().nullslast(),
                               m.ShipmentException.id.asc()).all()):
        order = db.get(m.Order, ship_exc.order_fk)
        sla, days = _sla(ship_exc.valid_until or ship_exc.payment_due, today)
        handoff_rows.append(_row(
            task_id=f"SHIPEXC-{ship_exc.id}", decision_type="HANDOFF_CUSTOMER_COMMITMENT",
            priority_rank=1, order=order, buyer=ship_exc.buyer,
            status=f"CFO {ship_exc.cfo_status or 'BELUM DINILAI'} · CEO {ship_exc.ceo_decision or 'MENUNGGU'}",
            gate=f"{ship_exc.exception_no or '-'} · outstanding {ship_exc.outstanding or 0}",
            evidence=ship_exc.reason or "Belum ada alasan tercatat",
            next_action=("CMO konfirmasi komitmen customer"
                         + (" (sudah dikonfirmasi)" if ship_exc.cmo_confirmed_at else " — belum dikonfirmasi")),
            owner="CMO_MANAGER",
            due=ship_exc.valid_until or ship_exc.payment_due, sla=sla, sla_days=days,
            handoff="Komitmen customer (CMO) → keputusan CEO → delivery execution (COO)",
            updated=ship_exc.cmo_confirmed_at or ship_exc.requested_at,
            severity=_severity_for(sla),
            source="Shipment outstanding exception (CEO/COO/CFO)",
            open_target="/cmo/buyer-crm",
        ))
    queues.append({
        "key": "NEXT_HANDOFF", "label": "Handoff Berikutnya",
        "owner": "COO_MANAGER / CFO_MANAGER", "priority_rank": 7,
        "handoff": "Batch Release → produksi → delivery execution → operational closing",
        "rows": handoff_rows,
    })

    # ------------------------------------------------------------------ RINGKASAN
    capacity = _capacity_payload(db)
    bottleneck_note = None
    if capacity["bottlenecks"]:
        bottleneck_note = "; ".join(
            f"{b['process']} kelebihan {b['overload_qty']} pcs (beban {b['planned_load']}/{b['capacity']})"
            for b in capacity["bottlenecks"])
    elif capacity["processes"]:
        bottleneck_note = "Tidak ada proses melebihi kapasitas pada snapshot terakhir."
    else:
        bottleneck_note = "Belum ada data kapasitas — Demand Gap tidak dapat dihitung."

    # Urutan kerja: seksi sesuai blueprint (PO → quotation → sample → SPK →
    # exception → prioritas artikel → handoff), di dalam seksi baris terurut
    # berdasarkan severity lalu sisa hari SLA.
    severity_weight = {"RED": 0, "YELLOW": 1, "GREEN": 2, "GRAY": 3}
    for queue in queues:
        queue["rows"].sort(key=lambda r: (
            severity_weight.get(r.get("severity"), 4),
            r.get("sla_days") if r.get("sla_days") is not None else 10_000,
            r.get("task_id") or "",
        ))

    action_rows = [r for q in queues if q["key"] not in ("ARTICLE_PRIORITY", "NEXT_HANDOFF")
                   for r in q["rows"]]
    overdue = [r for r in action_rows if r.get("sla") == "OVERDUE"]
    due_today = [r for r in action_rows if r.get("sla") == "DUE_TODAY"]
    must_decide = [r for r in action_rows
                   if r.get("owner") == "CMO_MANAGER" and r.get("sla") in ("OVERDUE", "DUE_TODAY", "DUE_3_HARI")]

    return {
        "as_of": now.isoformat(),
        "role": user.role.value,
        "viewer": {"id": user.id, "name": user.name, "role": user.role.value},
        "queues": queues,
        "totals": {q["key"]: len(q["rows"]) for q in queues},
        "total_actions": len(action_rows),
        "total_decisions": sum(1 for r in action_rows if r.get("owner") == "CMO_MANAGER"),
        "summary": {
            "overdue": len(overdue),
            "due_today": len(due_today),
            "must_decide_now": len(must_decide),
            "overdue_tasks": [r["task_id"] for r in overdue],
        },
        "capacity": capacity,
        "bottleneck": {
            "count": len(capacity["bottlenecks"]),
            "detail": bottleneck_note,
            "processes": [b["process"] for b in capacity["bottlenecks"]],
        },
        "master_control": {
            "mode": "read_only",
            "note": ("Data Master Control tampil read-only di Morning Priority: Cecep dapat "
                     "menetapkan business priority dan escalation reason; status operasional "
                     "dan keuangan hanya dibaca."),
        },
        "authority": {
            "held": ["customer truth", "commercial validation", "business priority",
                     "approval quotation/order", "CMO SPK Release"],
            "not_held": ["HPP/pricing/payment truth (CFO)", "Batch Release, produksi, "
                         "delivery execution, operational closing (COO)"],
        },
    }
