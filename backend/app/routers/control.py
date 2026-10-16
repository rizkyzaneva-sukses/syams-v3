"""Control System: papan status tahap order, master data, dan SLA berversi.

Hak ubah master data & SLA hanya CMO Manager (keputusan pemilik, 16 Okt 2026).
Semua peran yang boleh melihat Master Control boleh membaca papan ini.
"""
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..audit import log_audit
from ..auth import require_roles
from ..control_forecast import MAX_PLANNER_DAYS, capacity_feed, capacity_planner, forecast_engine
from ..control_models import GarmentType, OrderBlock, OrderStage, PicMaster, StageSlaItem, StageSlaVersion
from ..control_service import (AUTO_STAGES, BLOCK_EXTRA_ROLES, DEFAULT_OFF_STAGES, STAGE_CODES, STAGE_LABEL, STAGE_ROLES, STAGES,
                               SlaBook, block_out, build_board, ensure_control_defaults)
from ..database import get_db
from ..notifications import notify_roles
from ..models import Order, Role, User
from .master import MASTER_ROLES

router = APIRouter(prefix="/control", tags=["control"])
SETTINGS_ROLES = (Role.CMO_MANAGER,)
AUTO_BLOCK_ROLES = (Role.CMO_SUPPORT, Role.CFO_MANAGER, Role.SAMPLE_PIC)


def _order(db: Session, order_id: str, lock: bool = False) -> Order:
    query = db.query(Order).options(joinedload(Order.articles)).filter(Order.order_id == order_id)
    if lock:
        query = query.with_for_update(of=Order)
    order = query.first()
    if not order:
        raise HTTPException(404, "Order tidak ditemukan")
    return order


def _view(db: Session, order: Order) -> dict:
    return build_board(db, [order])[0]


def _stage_code(code: str) -> str:
    code = code.upper()
    if code not in STAGE_CODES:
        raise HTTPException(404, "Tahap tidak dikenal")
    return code


def _manual_stage(db: Session, order: Order, code: str, user: User) -> dict:
    """Pastikan tahap boleh diubah manual oleh user ini pada order ini; kembalikan tampilan tahapnya."""
    if code in AUTO_STAGES:
        raise HTTPException(409, "Tahap ini otomatis mengikuti alur CMO/Finance dan tidak diisi manual")
    if user.role not in STAGE_ROLES[code]:
        raise HTTPException(403, f"Tahap {STAGE_LABEL[code]} hanya bisa diubah oleh divisi yang memegangnya")
    view = _view(db, order)
    produces = next(s for s in view["stages"] if s["code"] == code)["toggleable"]
    if not produces:
        raise HTTPException(409, "Order ini tidak masuk produksi")
    spk = next(s for s in view["stages"] if s["code"] == "SPK_RELEASED")
    if spk["status"] != "SELESAI":
        raise HTTPException(409, "SPK belum direlease; tahap produksi belum bisa diisi")
    stage = next(s for s in view["stages"] if s["code"] == code)
    if stage["from_data"]:
        raise HTTPException(409, f"Tahap {STAGE_LABEL[code]} sudah selesai otomatis dari data modul lain "
                                 "(material, Production Queue, atau shipment); ubah di modul sumbernya")
    return stage


def _row(db: Session, order: Order, code: str) -> Optional[OrderStage]:
    return db.query(OrderStage).filter_by(order_fk=order.id, stage_code=code).first()


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: Optional[str] = Field(default=None, max_length=500)


class ReasonRequired(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=3, max_length=500)


class PicIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    pic_name: Optional[str] = Field(default=None, max_length=80)


class BlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    stage_code: Optional[str] = None
    problem: str = Field(min_length=3, max_length=1000)
    next_action: str = Field(min_length=3, max_length=1000)
    pic_name: Optional[str] = Field(default=None, max_length=80)


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: Optional[str] = Field(default=None, max_length=500)


# ───────────────────────────── Papan ─────────────────────────────

@router.get("/board")
def board(pic: Optional[str] = None, priority: Optional[str] = None, q: Optional[str] = None,
          include_closed: bool = False, limit: int = Query(300, ge=1, le=500),
          db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    query = db.query(Order).options(joinedload(Order.articles))
    if not include_closed:
        query = query.filter(Order.overall_status != "CLOSED")
    orders = query.order_by(Order.id).all()
    rows = build_board(db, orders)
    if pic and pic.upper() != "ALL":
        rows = [r for r in rows if (r["pic"] or "").upper() == pic.upper()]
    if priority and priority.upper() != "ALL":
        rows = [r for r in rows if r["priority"] == priority.upper()]
    if q and q.strip():
        term = q.strip().lower()
        rows = [r for r in rows if term in r["order_id"].lower() or term in r["buyer"].lower()
                or any(term in a.lower() for a in r["articles"])]
    rows.sort(key=lambda r: (r["priority_sort"], r["deadline"] is None, r["deadline"] or datetime.max.date(), r["order_id"]))
    summary = {
        "active_orders": sum(1 for r in rows if r["priority"] != "SELESAI"),
        "active_qty": sum(r["active_qty"] for r in rows),
        "urgent": sum(1 for r in rows if r["priority"] == "URGENT"),
        "attention": sum(1 for r in rows if r["priority"] == "PERHATIAN"),
        "progress": sum(1 for r in rows if r["priority"] == "PROGRES"),
        "done": sum(1 for r in rows if r["priority"] == "SELESAI"),
        "payment_outstanding": sum(1 for r in rows if r["payment"] == "OUTSTANDING" and r["priority"] != "SELESAI"),
    }
    return {"stages": [{"code": c, "label": l, "kind": k} for c, l, k in STAGES], "summary": summary,
            "rows": rows[:limit]}


def _active_views(db: Session) -> list[dict]:
    orders = db.query(Order).options(joinedload(Order.articles)).filter(Order.overall_status != "CLOSED") \
        .order_by(Order.id).all()
    return build_board(db, orders)


def _by_pic(views: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for v in views:
        if v["priority"] == "SELESAI":
            continue
        key = v["pic"] or "TANPA PIC"
        g = groups.setdefault(key, {"pic": key, "orders": 0, "qty": 0, "urgent": 0, "attention": 0, "progress": 0})
        g["orders"] += 1
        g["qty"] += v["active_qty"]
        g[{"URGENT": "urgent", "PERHATIAN": "attention", "PROGRES": "progress"}[v["priority"]]] += 1
    return sorted(groups.values(), key=lambda g: (-g["urgent"], -g["attention"], g["pic"]))


@router.get("/morning-priority")
def morning_priority(pic: Optional[str] = None, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(*MASTER_ROLES))):
    """Rekap meeting pagi (tab MORNING PRIORITY di sheet): merah / kuning / putih, bisa difilter per PIC."""
    views = [v for v in _active_views(db) if v["priority"] != "SELESAI"]
    counts = _by_pic(views)
    if pic and pic.upper() != "ALL":
        wanted = pic.upper()
        views = [v for v in views if (v["pic"] or "TANPA PIC").upper() == wanted]
    views.sort(key=lambda v: (v["priority_sort"], v["deadline"] is None, v["deadline"] or datetime.max.date(), v["order_id"]))
    return {"rows": views, "pics": counts,
            "totals": {"urgent": sum(v["priority"] == "URGENT" for v in views),
                       "attention": sum(v["priority"] == "PERHATIAN" for v in views),
                       "progress": sum(v["priority"] == "PROGRES" for v in views)}}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    """Master Dashboard (tab MASTER DASHBOARD + WIP CAPACITY di sheet)."""
    views = _active_views(db)
    live = [v for v in views if v["priority"] != "SELESAI"]
    tone = {"URGENT": "urgent", "PERHATIAN": "attention", "PROGRES": "progress"}
    wip_stage = []
    for code, label, _ in STAGES:
        here = [v for v in live if v["current_stage"] == code]
        wip_stage.append({"code": code, "label": label, "orders": len(here), "buyers": len({v["buyer"] for v in here}),
                          "qty": sum(v["active_qty"] for v in here),
                          **{name: sum(1 for v in here if tone[v["priority"]] == name) for name in tone.values()}})
    garments: dict[str, dict] = {}
    live_by_id = {v["order_id"]: v for v in live}
    for order in db.query(Order).options(joinedload(Order.articles)).filter(Order.overall_status != "CLOSED"):
        view = live_by_id.get(order.order_id)
        if not view:
            continue
        seen = set()
        for article in order.articles:
            name = (article.garment_type or "TANPA JENIS").upper()
            g = garments.setdefault(name, {"garment": name, "orders": 0, "qty": 0, "urgent_qty": 0, "attention_qty": 0, "progress_qty": 0})
            if name not in seen:
                g["orders"] += 1
                seen.add(name)
            g["qty"] += article.qty
            g[tone[view["priority"]] + "_qty"] += article.qty
    ordered = [g for g in garments.values()]
    ordered.sort(key=lambda g: (-g["qty"], g["garment"]))
    _, items = SlaBook(db).active()
    forecast = forecast_engine(views, items, date.today())
    return {
        "forecast_banner": forecast["banner"],
        "forecast_14d": [{"code": s["code"], "label": s["label"], "orders": s["orders_14d"], "load": s["load_14d"], "unit": s["unit"],
                          "load_pct": s["load_pct_14d"], "status": s["status"], "pic": s["pic"]} for s in forecast["stages"]],
        "summary": {"active_orders": len(live), "active_qty": sum(v["active_qty"] for v in live),
                    "urgent": sum(v["priority"] == "URGENT" for v in live),
                    "attention": sum(v["priority"] == "PERHATIAN" for v in live),
                    "progress": sum(v["priority"] == "PROGRES" for v in live),
                    "done": sum(v["priority"] == "SELESAI" for v in views)},
        "wip_by_stage": wip_stage, "wip_by_garment": ordered, "by_pic": _by_pic(views),
        "alerts": {"payment_outstanding": sum(v["payment"] == "OUTSTANDING" for v in live),
                   "urgent_operation": sum(v["priority"] == "URGENT" for v in live),
                   "attention_operation": sum(v["priority"] == "PERHATIAN" for v in live),
                   "open_problems": sum(len(v["open_blocks"]) for v in live),
                   "deadline_forecast_urgent": forecast["risk_counts"]["URGENT"]},
    }


@router.get("/capacity-planner")
def planner(start: Optional[date] = None, end: Optional[date] = None, db: Session = Depends(get_db),
            user: User = Depends(require_roles(*MASTER_ROLES))):
    """Capacity Planner: beban WIP sekarang dibanding kapasitas selama rentang tanggal."""
    start = start or date.today()
    end = end or (start + timedelta(days=29))
    if end < start:
        raise HTTPException(422, "Tanggal akhir tidak boleh sebelum tanggal mulai")
    if (end - start).days + 1 > MAX_PLANNER_DAYS:
        raise HTTPException(422, f"Rentang maksimal {MAX_PLANNER_DAYS} hari")
    _, items = SlaBook(db).active()
    return capacity_planner(_active_views(db), items, start, end)


@router.get("/forecast")
def forecast(db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    """Forecast Engine: tanggal tiap tahap, risiko deadline per order, dan beban 7/14/30 hari per tahap."""
    _, items = SlaBook(db).active()
    return forecast_engine(_active_views(db), items, date.today())


@router.get("/capacity-feed")
def capacity_feed_endpoint(db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    """Sisa kapasitas 7/14/30 hari untuk CMO sebelum menerima order baru."""
    _, items = SlaBook(db).active()
    return capacity_feed(_active_views(db), items, date.today())


@router.get("/orders/{order_id}")
def order_detail(order_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    order = _order(db, order_id)
    view = _view(db, order)
    history = db.query(OrderBlock).filter_by(order_fk=order.id).order_by(OrderBlock.id.desc()).all()
    view["blocks"] = [block_out(b) for b in history]
    return view


def _audit(db, user, action, order, detail, reason=None):
    log_audit(db, user, action, "OrderStage", order.id, detail, obj=order, source_module="ControlSystem", reason=reason)


@router.post("/orders/{order_id}/stages/{code}/done")
def stage_done(order_id: str, code: str, data: ReasonIn = ReasonIn(), db: Session = Depends(get_db),
               user: User = Depends(require_roles(*MASTER_ROLES))):
    code = _stage_code(code)
    order = _order(db, order_id, lock=True)
    _manual_stage(db, order, code, user)
    row = _row(db, order, code)
    if row and row.state == "DONE":
        raise HTTPException(409, "Tahap ini sudah selesai")
    if db.query(OrderBlock).filter_by(order_fk=order.id, stage_code=code, resolved_at=None).first():
        raise HTTPException(409, "Masih ada masalah terbuka di tahap ini; selesaikan masalahnya dulu")
    if row is None:
        row = OrderStage(order_fk=order.id, stage_code=code, state="DONE")
        db.add(row)
    row.state, row.done_at, row.done_by_id = "DONE", datetime.utcnow(), user.id
    if data.note:
        row.note = data.note
    db.flush()
    _audit(db, user, "STAGE_DONE", order, f"{STAGE_LABEL[code]} selesai")
    result = _view(db, order)
    nxt = result["current_stage"]
    if nxt and nxt not in AUTO_STAGES:
        notify_roles(db, [r.value for r in STAGE_ROLES[nxt]], f"Giliran {STAGE_LABEL[nxt]} — {order.order_id}",
                     f"{order.buyer}: {STAGE_LABEL[code]} selesai. Tahap berikutnya milik Anda.", "/master",
                     category="TASK")
    elif nxt is None:
        notify_roles(db, ["CMO_MANAGER", "COO_MANAGER"], f"Semua tahap {order.order_id} selesai", order.buyer, "/master")
    db.commit()
    return result


@router.post("/orders/{order_id}/stages/{code}/reopen")
def stage_reopen(order_id: str, code: str, data: ReasonRequired, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(*MASTER_ROLES))):
    code = _stage_code(code)
    order = _order(db, order_id, lock=True)
    _manual_stage(db, order, code, user)
    row = _row(db, order, code)
    if not row or row.state != "DONE":
        raise HTTPException(409, "Tahap ini belum selesai")
    later = [s for s in _view(db, order)["stages"] if s["status"] == "SELESAI" and s["kind"] == "manual"
             and STAGE_CODES.index(s["code"]) > STAGE_CODES.index(code)]
    if later:
        raise HTTPException(409, f"Buka dulu tahap yang sudah selesai setelahnya: {later[0]['label']}")
    if code in ("REVISI",):
        row.state, row.done_at, row.done_by_id = "ENABLED", None, None
    else:
        db.delete(row)
    _audit(db, user, "STAGE_REOPEN", order, f"{STAGE_LABEL[code]} dibuka kembali", reason=data.reason)
    db.commit()
    return _view(db, order)


@router.post("/orders/{order_id}/stages/{code}/skip")
def stage_skip(order_id: str, code: str, data: ReasonRequired, db: Session = Depends(get_db),
               user: User = Depends(require_roles(*MASTER_ROLES))):
    code = _stage_code(code)
    order = _order(db, order_id, lock=True)
    _manual_stage(db, order, code, user)
    row = _row(db, order, code)
    if row and row.state == "DONE":
        raise HTTPException(409, "Tahap sudah selesai; buka kembali dulu bila ingin melewatinya")
    if db.query(OrderBlock).filter_by(order_fk=order.id, stage_code=code, resolved_at=None).first():
        raise HTTPException(409, "Masih ada masalah terbuka di tahap ini")
    if row is None:
        row = OrderStage(order_fk=order.id, stage_code=code, state="SKIPPED")
        db.add(row)
    row.state, row.note = "SKIPPED", data.reason
    _audit(db, user, "STAGE_SKIP", order, f"{STAGE_LABEL[code]} dilewati", reason=data.reason)
    db.commit()
    return _view(db, order)


@router.post("/orders/{order_id}/stages/{code}/enable")
def stage_enable(order_id: str, code: str, data: ReasonIn = ReasonIn(), db: Session = Depends(get_db),
                 user: User = Depends(require_roles(*MASTER_ROLES))):
    code = _stage_code(code)
    order = _order(db, order_id, lock=True)
    _manual_stage(db, order, code, user)
    row = _row(db, order, code)
    if row and row.state == "DONE":
        raise HTTPException(409, "Tahap sudah selesai")
    if code in DEFAULT_OFF_STAGES:
        if row is None:
            row = OrderStage(order_fk=order.id, stage_code=code, state="ENABLED")
            db.add(row)
        row.state = "ENABLED"
    elif row:
        db.delete(row)
    _audit(db, user, "STAGE_ENABLE", order, f"{STAGE_LABEL[code]} dipakai kembali")
    db.commit()
    return _view(db, order)


@router.put("/orders/{order_id}/stages/{code}/pic")
def stage_pic(order_id: str, code: str, data: PicIn, db: Session = Depends(get_db),
              user: User = Depends(require_roles(Role.COO_MANAGER, Role.CMO_MANAGER))):
    code = _stage_code(code)
    order = _order(db, order_id, lock=True)
    if data.pic_name:
        pic = db.query(PicMaster).filter(PicMaster.name == data.pic_name.upper(), PicMaster.is_active.is_(True)).first()
        if not pic:
            raise HTTPException(422, "PIC tidak ada di daftar PIC aktif")
        data.pic_name = pic.name
    row = _row(db, order, code)
    if row is None:
        # Baris hanya untuk menyimpan PIC; state ENABLED = tahap tetap berjalan normal.
        # REVISI default mati, jangan dinyalakan hanya karena PIC-nya diganti.
        if code in DEFAULT_OFF_STAGES:
            raise HTTPException(409, "Aktifkan tahap ini dulu sebelum mengganti PIC")
        row = OrderStage(order_fk=order.id, stage_code=code, state="ENABLED")
        db.add(row)
    row.pic_name = data.pic_name
    _audit(db, user, "STAGE_PIC", order, f"PIC {STAGE_LABEL[code]} → {data.pic_name or 'default SLA'}")
    db.commit()
    return _view(db, order)


# ───────────────────────────── Masalah / block ─────────────────────────────

def _block_roles(code: Optional[str]) -> tuple:
    roles = set(BLOCK_EXTRA_ROLES)
    if code in AUTO_STAGES:
        roles |= set(AUTO_BLOCK_ROLES)
    elif code:
        roles |= set(STAGE_ROLES[code])
    else:
        roles |= set(AUTO_BLOCK_ROLES) | {Role.PRODUCTION_PIC, Role.PRINTING_PIC, Role.SHIPMENT_ADMIN}
    return tuple(roles)


@router.post("/orders/{order_id}/blocks", status_code=201)
def add_block(order_id: str, data: BlockIn, db: Session = Depends(get_db),
              user: User = Depends(require_roles(*MASTER_ROLES))):
    code = _stage_code(data.stage_code) if data.stage_code else None
    if user.role not in _block_roles(code):
        raise HTTPException(403, "Peran Anda tidak memegang tahap ini")
    order = _order(db, order_id, lock=True)
    if order.overall_status == "CLOSED":
        raise HTTPException(409, "Order sudah ditutup")
    pic = data.pic_name.upper() if data.pic_name else None
    if pic and not db.query(PicMaster).filter(PicMaster.name == pic, PicMaster.is_active.is_(True)).first():
        raise HTTPException(422, "PIC tidak ada di daftar PIC aktif")
    block = OrderBlock(order_fk=order.id, stage_code=code, problem=data.problem, next_action=data.next_action,
                       pic_name=pic, opened_by_id=user.id)
    db.add(block)
    db.flush()
    log_audit(db, user, "BLOCK_OPEN", "OrderBlock", block.id, f"{code or 'ORDER'}: {data.problem}", obj=order,
              source_module="ControlSystem")
    audience = {Role.COO_MANAGER, Role.CMO_MANAGER} | (set(STAGE_ROLES[code]) if code in STAGE_ROLES else set())
    notify_roles(db, sorted(r.value for r in audience), f"Masalah {STAGE_LABEL.get(code, 'ORDER')} — {order.order_id}",
                 f"{data.problem}. Next action: {data.next_action}", "/master", category="EXCEPTION", severity="CRITICAL")
    db.commit()
    return _view(db, order)


@router.post("/blocks/{block_id}/resolve")
def resolve_block(block_id: int, data: ResolveIn, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*MASTER_ROLES))):
    block = db.query(OrderBlock).filter_by(id=block_id).with_for_update().first()
    if not block:
        raise HTTPException(404, "Masalah tidak ditemukan")
    if block.resolved_at:
        raise HTTPException(409, "Masalah ini sudah diselesaikan")
    if user.role not in _block_roles(block.stage_code) and block.opened_by_id != user.id:
        raise HTTPException(403, "Peran Anda tidak memegang tahap ini")
    block.resolved_at, block.resolved_by_id, block.resolution_note = datetime.utcnow(), user.id, data.note
    order = db.get(Order, block.order_fk)
    log_audit(db, user, "BLOCK_RESOLVE", "OrderBlock", block.id, data.note or "selesai", obj=order,
              source_module="ControlSystem")
    if block.opened_by_id and block.opened_by_id != user.id:
        notify_roles(db, [], f"Masalah {order.order_id} sudah diselesaikan", data.note, "/master",
                     category="EXCEPTION", user_id=block.opened_by_id)
    db.commit()
    db.refresh(order)
    return _view(db, order)


# ───────────────────────────── Master data ─────────────────────────────

class GarmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=9999)


class GarmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = Field(default=None, ge=0, le=9999)


class PicIn2(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    role_label: Optional[str] = Field(default=None, max_length=120)
    is_active: bool = True


class PicPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    role_label: Optional[str] = Field(default=None, max_length=120)
    is_active: Optional[bool] = None


def _garment(g: GarmentType) -> dict:
    return {"id": g.id, "name": g.name, "is_active": g.is_active, "sort_order": g.sort_order}


def _pic(p: PicMaster) -> dict:
    return {"id": p.id, "name": p.name, "role_label": p.role_label, "is_active": p.is_active}


@router.get("/garment-types")
def list_garments(active_only: bool = False, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*MASTER_ROLES))):
    ensure_control_defaults(db)
    query = db.query(GarmentType)
    if active_only:
        query = query.filter(GarmentType.is_active.is_(True))
    return [_garment(g) for g in query.order_by(GarmentType.sort_order, GarmentType.name)]


@router.post("/garment-types", status_code=201)
def add_garment(data: GarmentIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*SETTINGS_ROLES))):
    item = GarmentType(name=data.name.upper(), is_active=data.is_active, sort_order=data.sort_order)
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Jenis pakaian sudah ada")
    log_audit(db, user, "CREATE", "GarmentType", item.id, item.name)
    db.commit()
    return _garment(item)


@router.patch("/garment-types/{item_id}")
def edit_garment(item_id: int, data: GarmentPatch, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(*SETTINGS_ROLES))):
    item = db.get(GarmentType, item_id)
    if not item:
        raise HTTPException(404, "Jenis pakaian tidak ditemukan")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value.upper() if key == "name" and value else value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Jenis pakaian sudah ada")
    log_audit(db, user, "UPDATE", "GarmentType", item.id, data.model_dump_json(exclude_unset=True))
    db.commit()
    return _garment(item)


@router.get("/pics")
def list_pics(active_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    ensure_control_defaults(db)
    query = db.query(PicMaster)
    if active_only:
        query = query.filter(PicMaster.is_active.is_(True))
    return [_pic(p) for p in query.order_by(PicMaster.name)]


@router.post("/pics", status_code=201)
def add_pic(data: PicIn2, db: Session = Depends(get_db), user: User = Depends(require_roles(*SETTINGS_ROLES))):
    item = PicMaster(name=data.name.upper(), role_label=data.role_label, is_active=data.is_active)
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "PIC sudah ada")
    log_audit(db, user, "CREATE", "PicMaster", item.id, item.name)
    db.commit()
    return _pic(item)


@router.patch("/pics/{item_id}")
def edit_pic(item_id: int, data: PicPatch, db: Session = Depends(get_db), user: User = Depends(require_roles(*SETTINGS_ROLES))):
    item = db.get(PicMaster, item_id)
    if not item:
        raise HTTPException(404, "PIC tidak ditemukan")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value.upper() if key == "name" and value else value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "PIC sudah ada")
    log_audit(db, user, "UPDATE", "PicMaster", item.id, data.model_dump_json(exclude_unset=True))
    db.commit()
    return _pic(item)


# ───────────────────────────── SLA berversi ─────────────────────────────

class SlaItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    stage_code: str
    duration_days: int = Field(ge=0, le=365)
    primary_pic: Optional[str] = Field(default=None, max_length=80)
    is_active: bool = True
    daily_capacity: int = Field(ge=0, le=10_000_000)
    capacity_unit: str = Field(min_length=1, max_length=16)
    warning_pct: float = Field(gt=0, le=1)
    note: Optional[str] = Field(default=None, max_length=200)


class SlaIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=5, max_length=500)
    items: list[SlaItemIn]


def _sla_out(version: StageSlaVersion, items: dict[str, StageSlaItem]) -> dict:
    return {"version": version.version, "change_reason": version.change_reason, "created_at": version.created_at,
            "changed_by_id": version.changed_by_id,
            "items": [{"stage_code": c, "label": l, "kind": k, "duration_days": items[c].duration_days,
                       "primary_pic": items[c].primary_pic, "is_active": items[c].is_active,
                       "daily_capacity": items[c].daily_capacity, "capacity_unit": items[c].capacity_unit,
                       "warning_pct": items[c].warning_pct, "note": items[c].note}
                      for c, l, k in STAGES if c in items]}


@router.get("/sla")
def active_sla(db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    ensure_control_defaults(db)
    version, items = SlaBook(db).active()
    return _sla_out(version, items)


@router.get("/sla/versions")
def sla_versions(db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    ensure_control_defaults(db)
    return [{"version": v.version, "change_reason": v.change_reason, "created_at": v.created_at,
             "changed_by_id": v.changed_by_id} for v in db.query(StageSlaVersion).order_by(StageSlaVersion.id.desc())]


@router.post("/sla", status_code=201)
def save_sla(data: SlaIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*SETTINGS_ROLES))):
    ensure_control_defaults(db)
    codes = [i.stage_code.upper() for i in data.items]
    if sorted(codes) != sorted(STAGE_CODES):
        raise HTTPException(422, "SLA harus memuat tepat 15 tahap, masing-masing satu kali")
    book = SlaBook(db)
    current_version, current_items = book.active()
    changed = False
    for item in data.items:
        old = current_items.get(item.stage_code.upper())
        new = (item.duration_days, item.primary_pic, item.is_active, item.daily_capacity, item.capacity_unit,
               item.warning_pct, item.note)
        if old is None or new != (old.duration_days, old.primary_pic, old.is_active, old.daily_capacity,
                                  old.capacity_unit, old.warning_pct, old.note):
            changed = True
    if not changed:
        raise HTTPException(409, "Tidak ada perubahan dibanding versi SLA aktif")
    version = StageSlaVersion(version=(current_version.version + 1) if current_version else 1,
                              change_reason=data.reason, changed_by_id=user.id)
    db.add(version)
    db.flush()
    for order, item in enumerate(data.items, start=1):
        db.add(StageSlaItem(version_fk=version.id, stage_code=item.stage_code.upper(), sort_order=STAGE_CODES.index(item.stage_code.upper()) + 1,
                            duration_days=item.duration_days, primary_pic=item.primary_pic, is_active=item.is_active,
                            daily_capacity=item.daily_capacity, capacity_unit=item.capacity_unit.upper(),
                            warning_pct=item.warning_pct, note=item.note))
    log_audit(db, user, "SLA_VERSION", "StageSlaVersion", version.id, f"v{version.version}: {data.reason}", reason=data.reason)
    db.commit()
    version, items = SlaBook(db).active()
    return _sla_out(version, items)
