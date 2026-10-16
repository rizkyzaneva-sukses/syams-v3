"""Ruang kerja CFO Manager: semua tugas keuangan sekarang di satu role (Finance Support dihapus).

Modul di sini melengkapi yang sudah ada (invoice, piutang, akuntansi, laporan laba rugi/neraca/arus kas):
  * kas kecil harian dan kas besar (kas besar otomatis diposting ke jurnal akuntansi)
  * master karyawan harian + input hasil produksi (dasar upah borongan)
  * data pembelian bahan (kain, benang, aksesoris) dan ringkasan stok per kategori
  * analisa COGS mingguan
  * ikhtisar tugas CFO (/cfo/workspace)

Hak tulis hanya CFO_MANAGER; CEO membaca (read-only).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..accounting_models import ChartOfAccount, JournalEntry
from ..accounting_seed import seed_chart_of_accounts
from ..accounting_service import add_lines, next_entry_no, resolve_account_ids, validate_lines
from ..audit import log_audit
from ..auth import require_roles
from ..cfo_models import CashEntry, DailyWorker, ProductionResult
from ..database import get_db
from ..inventory_models import GoodsReceipt, GoodsReceiptLine, Material, Supplier
from ..models import Invoice, MaterialConsumption, Order, ProductionCostEntry, Role, User
from .inventory import _stock_rows

router = APIRouter(prefix="/cfo", tags=["cfo-workspace"])
WRITE = (Role.CFO_MANAGER,)
READ = (Role.CFO_MANAGER, Role.CEO)
CASH_ACCOUNTS = {"1-1000": "Kas", "1-1100": "Bank"}
PROCESSES = ["CUTTING", "SORTIR", "PRINTING", "BORDIR", "QC S/B", "SEWING", "ACC", "QC", "PACKING", "LAINNYA"]
STOCK_GROUPS = {"KAIN": ["KAIN"], "BENANG": ["BENANG"], "AKSESORIS": ["AKSESORIS", "KEMASAN"]}
ZERO = Decimal(0)


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def _num(value) -> float:
    return float(_dec(value))


# ───────────────────────────── Kas kecil & kas besar ─────────────────────────────

class CashIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: str = Field(pattern="^(PETTY|BIG)$")
    entry_date: date
    direction: str = Field(pattern="^(IN|OUT)$")
    category: Optional[str] = Field(default=None, max_length=80)
    description: str = Field(min_length=2, max_length=500)
    amount: Decimal = Field(gt=0, le=Decimal("999999999999"))
    cash_account_code: Optional[str] = None
    counter_account_code: Optional[str] = None


def _cash_out(row: CashEntry, balance=None) -> dict:
    return {"id": row.id, "kind": row.kind, "entry_date": row.entry_date, "direction": row.direction,
            "category": row.category, "description": row.description, "amount": _num(row.amount),
            "cash_account_code": row.cash_account_code, "counter_account_code": row.counter_account_code,
            "journal_entry_id": row.journal_entry_id, "balance": balance, "created_at": row.created_at}


def _signed(row: CashEntry) -> Decimal:
    return _dec(row.amount) if row.direction == "IN" else -_dec(row.amount)


@router.post("/cash", status_code=201)
def add_cash(data: CashIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE))):
    if data.entry_date > date.today() + timedelta(days=1):
        raise HTTPException(422, "Tanggal tidak boleh di masa depan")
    row = CashEntry(kind=data.kind, entry_date=data.entry_date, direction=data.direction, category=data.category,
                    description=data.description, amount=data.amount, created_by_id=user.id)
    if data.kind == "BIG":
        cash_code = data.cash_account_code or "1-1000"
        if cash_code not in CASH_ACCOUNTS:
            raise HTTPException(422, "Akun kas harus 1-1000 (Kas) atau 1-1100 (Bank)")
        if not data.counter_account_code:
            raise HTTPException(422, "Kas besar wajib memilih akun lawan (mis. Pendapatan, Beban, Utang)")
        if data.counter_account_code == cash_code:
            raise HTTPException(422, "Akun lawan tidak boleh sama dengan akun kas")
        seed_chart_of_accounts(db)
        if not db.query(ChartOfAccount).filter_by(code=data.counter_account_code, is_active=True).first():
            raise HTTPException(422, f"Akun lawan {data.counter_account_code} tidak ditemukan")
        row.cash_account_code, row.counter_account_code = cash_code, data.counter_account_code
    db.add(row)
    db.flush()
    if data.kind == "BIG":
        amount = str(data.amount)
        debit_code, credit_code = ((row.cash_account_code, row.counter_account_code) if data.direction == "IN"
                                   else (row.counter_account_code, row.cash_account_code))
        lines = [{"account_code": debit_code, "debit": amount, "credit": 0, "description": data.description},
                 {"account_code": credit_code, "debit": 0, "credit": amount, "description": data.description}]
        errors = validate_lines(db, lines)
        if errors:
            raise HTTPException(422, "; ".join(errors))
        resolve_account_ids(db, lines)
        entry = JournalEntry(entry_no=next_entry_no(db), entry_date=data.entry_date, entry_source="AUTO",
                             description=f"Kas besar: {data.description}", source_ref=f"KAS:{row.id}", status="POSTED",
                             created_by_id=user.id, posted_by_id=user.id, posted_at=datetime.utcnow())
        db.add(entry)
        db.flush()
        add_lines(db, entry, lines)
        row.journal_entry_id = entry.id
    log_audit(db, user, "CREATE", "CashEntry", row.id, f"{row.kind} {row.direction} {row.amount}: {row.description}")
    db.commit()
    return _cash_out(row)


def _opening(db: Session, kind: str, before: date) -> Decimal:
    rows = db.query(CashEntry).filter(CashEntry.kind == kind, CashEntry.entry_date < before).all()
    return sum((_signed(r) for r in rows), ZERO)


@router.get("/cash")
def list_cash(kind: str = Query("PETTY", pattern="^(PETTY|BIG)$"), date_from: Optional[date] = None,
              date_to: Optional[date] = None, limit: int = Query(500, ge=1, le=1000),
              db: Session = Depends(get_db), user: User = Depends(require_roles(*READ))):
    start = date_from or date.today().replace(day=1)
    query = db.query(CashEntry).filter(CashEntry.kind == kind, CashEntry.entry_date >= start)
    if date_to:
        query = query.filter(CashEntry.entry_date <= date_to)
    rows = query.order_by(CashEntry.entry_date, CashEntry.id).limit(limit).all()
    balance = _opening(db, kind, start)
    opening = balance
    out = []
    for row in rows:
        balance += _signed(row)
        out.append(_cash_out(row, _num(balance)))
    total_in = sum((_dec(r.amount) for r in rows if r.direction == "IN"), ZERO)
    total_out = sum((_dec(r.amount) for r in rows if r.direction == "OUT"), ZERO)
    return {"kind": kind, "date_from": start, "opening_balance": _num(opening), "total_in": _num(total_in),
            "total_out": _num(total_out), "closing_balance": _num(opening + total_in - total_out), "rows": out}


@router.get("/cash/daily-report")
def cash_daily_report(day: Optional[date] = None, kind: str = Query("PETTY", pattern="^(PETTY|BIG)$"),
                      db: Session = Depends(get_db), user: User = Depends(require_roles(*READ))):
    """Laporan kas harian: saldo awal, mutasi hari itu, dan saldo akhir."""
    day = day or date.today()
    rows = db.query(CashEntry).filter(CashEntry.kind == kind, CashEntry.entry_date == day).order_by(CashEntry.id).all()
    opening = _opening(db, kind, day)
    total_in = sum((_dec(r.amount) for r in rows if r.direction == "IN"), ZERO)
    total_out = sum((_dec(r.amount) for r in rows if r.direction == "OUT"), ZERO)
    by_category: dict[str, Decimal] = {}
    for r in rows:
        if r.direction == "OUT":
            by_category[r.category or "Lainnya"] = by_category.get(r.category or "Lainnya", ZERO) + _dec(r.amount)
    return {"date": day, "kind": kind, "opening_balance": _num(opening), "total_in": _num(total_in),
            "total_out": _num(total_out), "closing_balance": _num(opening + total_in - total_out),
            "out_by_category": [{"category": k, "amount": _num(v)} for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])],
            "rows": [_cash_out(r) for r in rows]}


@router.delete("/cash/{entry_id}")
def delete_cash(entry_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE))):
    row = db.get(CashEntry, entry_id)
    if not row:
        raise HTTPException(404, "Catatan kas tidak ditemukan")
    if row.kind == "BIG":
        raise HTTPException(409, "Kas besar sudah diposting ke jurnal; koreksi lewat jurnal pembalik di Akuntansi")
    log_audit(db, user, "DELETE", "CashEntry", row.id, f"{row.entry_date} {row.direction} {row.amount}: {row.description}")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ───────────────────────────── Karyawan harian & hasil produksi ─────────────────────────────

class WorkerIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    process: Optional[str] = Field(default=None, max_length=40)
    rate_per_pcs: Decimal = Field(default=0, ge=0, le=Decimal("100000000"))
    is_active: bool = True
    notes: Optional[str] = Field(default=None, max_length=500)


class WorkerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    process: Optional[str] = Field(default=None, max_length=40)
    rate_per_pcs: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("100000000"))
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=500)


def _worker_out(w: DailyWorker) -> dict:
    return {"id": w.id, "name": w.name, "process": w.process, "rate_per_pcs": _num(w.rate_per_pcs),
            "is_active": w.is_active, "notes": w.notes}


@router.get("/workers")
def list_workers(active_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles(*READ))):
    query = db.query(DailyWorker)
    if active_only:
        query = query.filter(DailyWorker.is_active.is_(True))
    return [_worker_out(w) for w in query.order_by(DailyWorker.name)]


@router.post("/workers", status_code=201)
def add_worker(data: WorkerIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE))):
    if db.query(DailyWorker).filter(func.lower(DailyWorker.name) == data.name.lower()).first():
        raise HTTPException(409, "Nama karyawan sudah ada")
    worker = DailyWorker(name=data.name, process=(data.process or "").upper() or None, rate_per_pcs=data.rate_per_pcs,
                         is_active=data.is_active, notes=data.notes)
    db.add(worker)
    db.flush()
    log_audit(db, user, "CREATE", "DailyWorker", worker.id, worker.name)
    db.commit()
    return _worker_out(worker)


@router.patch("/workers/{worker_id}")
def edit_worker(worker_id: int, data: WorkerPatch, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE))):
    worker = db.get(DailyWorker, worker_id)
    if not worker:
        raise HTTPException(404, "Karyawan tidak ditemukan")
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and db.query(DailyWorker).filter(func.lower(DailyWorker.name) == changes["name"].lower(),
                                                          DailyWorker.id != worker.id).first():
        raise HTTPException(409, "Nama karyawan sudah ada")
    if "process" in changes:
        changes["process"] = (changes["process"] or "").upper() or None
    for key, value in changes.items():
        setattr(worker, key, value)
    log_audit(db, user, "UPDATE", "DailyWorker", worker.id, data.model_dump_json(exclude_unset=True))
    db.commit()
    return _worker_out(worker)


class ResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    result_date: date
    worker_fk: int
    process: str = Field(min_length=1, max_length=40)
    qty: int = Field(gt=0, le=1_000_000)
    order_id: Optional[str] = Field(default=None, max_length=64)
    rate: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("100000000"))
    notes: Optional[str] = Field(default=None, max_length=500)


def _result_out(r: ProductionResult, worker: DailyWorker | None, order_id: str | None) -> dict:
    return {"id": r.id, "result_date": r.result_date, "worker_fk": r.worker_fk, "worker": worker.name if worker else None,
            "order_id": order_id, "process": r.process, "qty": r.qty, "rate": _num(r.rate), "amount": _num(r.amount),
            "notes": r.notes}


@router.post("/production-results", status_code=201)
def add_result(data: ResultIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE))):
    worker = db.get(DailyWorker, data.worker_fk)
    if not worker or not worker.is_active:
        raise HTTPException(422, "Karyawan tidak ditemukan atau nonaktif")
    if data.result_date > date.today() + timedelta(days=1):
        raise HTTPException(422, "Tanggal tidak boleh di masa depan")
    order = None
    if data.order_id:
        order = db.query(Order).filter_by(order_id=data.order_id.strip().upper()).first()
        if not order:
            raise HTTPException(422, f"Order {data.order_id} tidak ditemukan")
    rate = data.rate if data.rate is not None else _dec(worker.rate_per_pcs)
    row = ProductionResult(result_date=data.result_date, worker_fk=worker.id, order_fk=order.id if order else None,
                           process=data.process.upper(), qty=data.qty, rate=rate, amount=rate * data.qty,
                           notes=data.notes, created_by_id=user.id)
    db.add(row)
    db.flush()
    log_audit(db, user, "CREATE", "ProductionResult", row.id, f"{worker.name} {row.process} {row.qty} pcs @ {rate}")
    db.commit()
    return _result_out(row, worker, order.order_id if order else None)


@router.get("/production-results")
def list_results(date_from: Optional[date] = None, date_to: Optional[date] = None, worker_fk: Optional[int] = None,
                 limit: int = Query(500, ge=1, le=1000), db: Session = Depends(get_db),
                 user: User = Depends(require_roles(*READ))):
    start = date_from or date.today() - timedelta(days=6)
    query = db.query(ProductionResult).filter(ProductionResult.result_date >= start)
    if date_to:
        query = query.filter(ProductionResult.result_date <= date_to)
    if worker_fk:
        query = query.filter(ProductionResult.worker_fk == worker_fk)
    rows = query.order_by(ProductionResult.result_date.desc(), ProductionResult.id.desc()).limit(limit).all()
    workers = {w.id: w for w in db.query(DailyWorker)}
    orders = {o.id: o.order_id for o in db.query(Order).filter(Order.id.in_([r.order_fk for r in rows if r.order_fk]))} if rows else {}
    by_worker: dict[int, dict] = {}
    by_day: dict[date, dict] = {}
    for r in rows:
        w = by_worker.setdefault(r.worker_fk, {"worker_fk": r.worker_fk, "worker": workers[r.worker_fk].name, "qty": 0, "amount": ZERO})
        w["qty"] += r.qty
        w["amount"] += _dec(r.amount)
        d = by_day.setdefault(r.result_date, {"date": r.result_date, "qty": 0, "amount": ZERO})
        d["qty"] += r.qty
        d["amount"] += _dec(r.amount)
    return {"date_from": start,
            "totals": {"qty": sum(r.qty for r in rows), "amount": _num(sum((_dec(r.amount) for r in rows), ZERO))},
            "by_worker": sorted(({**v, "amount": _num(v["amount"])} for v in by_worker.values()), key=lambda v: -v["amount"]),
            "by_day": sorted(({**v, "amount": _num(v["amount"])} for v in by_day.values()), key=lambda v: v["date"], reverse=True),
            "rows": [_result_out(r, workers.get(r.worker_fk), orders.get(r.order_fk)) for r in rows]}


@router.delete("/production-results/{result_id}")
def delete_result(result_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE))):
    row = db.get(ProductionResult, result_id)
    if not row:
        raise HTTPException(404, "Hasil produksi tidak ditemukan")
    log_audit(db, user, "DELETE", "ProductionResult", row.id, f"{row.result_date} worker={row.worker_fk} qty={row.qty}")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ───────────────────────────── Pembelian bahan & stok ─────────────────────────────

@router.get("/material-purchases")
def material_purchases(category: str = Query("KAIN", max_length=40), date_from: Optional[date] = None,
                       date_to: Optional[date] = None, db: Session = Depends(get_db),
                       user: User = Depends(require_roles(*READ))):
    """Data pembelian bahan (default kain) dari penerimaan barang (GR) yang sudah diposting."""
    start = date_from or date.today() - timedelta(days=30)
    query = (db.query(GoodsReceiptLine, GoodsReceipt, Material, Supplier)
             .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.receipt_id)
             .join(Material, Material.id == GoodsReceiptLine.material_id)
             .outerjoin(Supplier, Supplier.id == GoodsReceipt.supplier_id)
             .filter(GoodsReceipt.status == "POSTED", Material.category == category.upper(),
                     GoodsReceipt.received_date >= start))
    if date_to:
        query = query.filter(GoodsReceipt.received_date <= date_to)
    rows, weekly, total = [], {}, ZERO
    for line, gr, mat, sup in query.order_by(GoodsReceipt.received_date.desc(), GoodsReceipt.id.desc()):
        amount = _dec(line.qty_received) * _dec(line.unit_cost)
        total += amount
        monday = gr.received_date - timedelta(days=gr.received_date.weekday())
        week = weekly.setdefault(monday, {"week_start": monday, "qty": ZERO, "amount": ZERO})
        week["qty"] += _dec(line.qty_received)
        week["amount"] += amount
        rows.append({"received_date": gr.received_date, "gr_no": gr.gr_no, "supplier": sup.name if sup else None,
                     "material": mat.name, "code": mat.code, "unit": mat.unit, "qty": _num(line.qty_received),
                     "rejected": _num(line.qty_rejected), "unit_cost": _num(line.unit_cost), "amount": _num(amount)})
    return {"category": category.upper(), "date_from": start, "total_amount": _num(total),
            "weekly": [{**w, "qty": _num(w["qty"]), "amount": _num(w["amount"])} for w in sorted(weekly.values(), key=lambda w: w["week_start"], reverse=True)],
            "rows": rows}


@router.get("/stock-summary")
def stock_summary(db: Session = Depends(get_db), user: User = Depends(require_roles(*READ))):
    """Stok per kelompok (kain, benang, aksesoris/kemasan) lengkap dengan nilai persediaan."""
    materials = {m.id: m for m in db.query(Material).filter(Material.is_active.is_(True))}
    groups = {name: {"group": name, "items": {}, "value": ZERO, "below_reorder": 0} for name in STOCK_GROUPS}
    for row in _stock_rows(db, None):
        mat = materials.get(row["material_id"])
        if not mat:
            continue
        group = next((g for g, cats in STOCK_GROUPS.items() if (mat.category or "").upper() in cats), None)
        if not group:
            continue
        item = groups[group]["items"].setdefault(mat.id, {"material_id": mat.id, "code": mat.code, "name": mat.name,
                                                          "category": mat.category, "unit": mat.unit, "qty": ZERO,
                                                          "standard_cost": _num(mat.standard_cost),
                                                          "reorder_point": _num(mat.reorder_point)})
        item["qty"] += _dec(row["qty"])
    result = []
    for name, g in groups.items():
        items = []
        for item in g["items"].values():
            value = item["qty"] * Decimal(str(item["standard_cost"]))
            low = item["qty"] < Decimal(str(item["reorder_point"]))
            g["value"] += value
            g["below_reorder"] += 1 if low else 0
            items.append({**item, "qty": _num(item["qty"]), "value": _num(value), "below_reorder": low})
        items.sort(key=lambda i: i["name"])
        result.append({"group": name, "item_count": len(items), "total_value": _num(g["value"]),
                       "below_reorder": g["below_reorder"], "items": items})
    return {"groups": result, "total_value": _num(sum((Decimal(str(g["total_value"])) for g in result), ZERO))}


# ───────────────────────────── COGS mingguan ─────────────────────────────

@router.get("/cogs-weekly")
def cogs_weekly(weeks: int = Query(8, ge=1, le=26), db: Session = Depends(get_db), user: User = Depends(require_roles(*READ))):
    """Analisa COGS per minggu (Senin–Minggu): bahan terpakai + biaya produksi + upah borongan, dibagi output pcs."""
    this_monday = date.today() - timedelta(days=date.today().weekday())
    first = this_monday - timedelta(weeks=weeks - 1)
    buckets = {first + timedelta(weeks=i): {"week_start": first + timedelta(weeks=i), "material": ZERO, "conversion": ZERO,
                                            "wages": ZERO, "output_pcs": 0} for i in range(weeks)}

    def bucket(day):
        return buckets.get(day - timedelta(days=day.weekday()))

    for cons in db.query(MaterialConsumption).filter(MaterialConsumption.created_at >= datetime.combine(first, datetime.min.time())):
        b = bucket(cons.created_at.date())
        if b:
            b["material"] += _dec(cons.qty) * _dec(cons.actual_unit_cost)
    for cost in db.query(ProductionCostEntry).filter(ProductionCostEntry.created_at >= datetime.combine(first, datetime.min.time())):
        b = bucket(cost.created_at.date())
        if b:
            b["conversion"] += _dec(cost.amount)
    for res in db.query(ProductionResult).filter(ProductionResult.result_date >= first):
        b = bucket(res.result_date)
        if b:
            b["wages"] += _dec(res.amount)
            if res.process in ("PACKING", "QC"):
                b["output_pcs"] += res.qty
    rows, previous = [], None
    for week in sorted(buckets):
        b = buckets[week]
        total = b["material"] + b["conversion"] + b["wages"]
        per_pcs = (total / b["output_pcs"]).quantize(Decimal("0.01")) if b["output_pcs"] else None
        change = None
        if previous is not None and per_pcs is not None and previous > 0:
            change = _num(((per_pcs - previous) / previous * 100).quantize(Decimal("0.1")))
        previous = per_pcs if per_pcs is not None else previous
        rows.append({"week_start": week, "week_end": week + timedelta(days=6), "material": _num(b["material"]),
                     "conversion": _num(b["conversion"]), "wages": _num(b["wages"]), "total_cogs": _num(total),
                     "output_pcs": b["output_pcs"], "cogs_per_pcs": _num(per_pcs) if per_pcs is not None else None,
                     "change_pct": change})
    rows.reverse()
    return {"weeks": weeks, "basis": "Output = qty hasil produksi proses QC/PACKING", "rows": rows}


# ───────────────────────────── Ikhtisar tugas CFO ─────────────────────────────

@router.get("/workspace")
def workspace(db: Session = Depends(get_db), user: User = Depends(require_roles(*READ))):
    today = date.today()
    open_invoices = db.query(Invoice).filter(Invoice.status != "PAID").all()
    outstanding = sum((_dec(i.amount) - _dec(i.paid_amount) for i in open_invoices), ZERO)
    petty_rows = db.query(CashEntry).filter(CashEntry.kind == "PETTY", CashEntry.entry_date <= today).all()
    petty_balance = sum((_signed(r) for r in petty_rows), ZERO)
    results_today = db.query(ProductionResult).filter(ProductionResult.result_date == today).all()
    return {"tasks": [
        {"key": "invoice", "title": "Pembuatan invoice", "path": "/cfo/invoices", "metric": f"{len(open_invoices)} invoice belum lunas"},
        {"key": "production-results", "title": "Input hasil produksi", "path": "/cfo/production-results",
         "metric": f"{len(results_today)} catatan hari ini ({sum(r.qty for r in results_today)} pcs)"},
        {"key": "fabric-purchases", "title": "Data pembelian kain", "path": "/cfo/material-purchases", "metric": "Penerimaan kain (GR) per minggu"},
        {"key": "cogs", "title": "Analisa COGS mingguan", "path": "/cfo/cogs-weekly", "metric": "Bahan + biaya produksi + upah per pcs"},
        {"key": "petty-cash", "title": "Laporan kas kecil harian", "path": "/cfo/cash", "metric": f"Saldo kas kecil {int(petty_balance):,}".replace(",", ".")},
        {"key": "receivables", "title": "Data piutang harian", "path": "/cfo/receivables", "metric": f"Piutang berjalan {int(outstanding):,}".replace(",", ".")},
        {"key": "price-calculator", "title": "Kalkulator harga jual", "path": "/cfo/price-calculator", "metric": "HPP + margin → harga jual per pcs"},
        {"key": "workers", "title": "Master karyawan harian", "path": "/cfo/production-results", "metric": f"{db.query(DailyWorker).filter_by(is_active=True).count()} karyawan aktif"},
        {"key": "stock-fabric", "title": "Data stok kain", "path": "/cfo/stock", "metric": "Stok & nilai persediaan kain"},
        {"key": "stock-thread", "title": "Data stok benang / sewing", "path": "/cfo/stock", "metric": "Stok & nilai persediaan benang"},
        {"key": "stock-accessories", "title": "Data stok aksesoris / packing", "path": "/cfo/stock", "metric": "Stok & nilai aksesoris dan kemasan"},
        {"key": "big-cash", "title": "Input kas besar", "path": "/cfo/cash", "metric": "Otomatis diposting ke jurnal"},
        {"key": "income-statement", "title": "Laporan laba rugi", "path": "/accounting", "metric": "Akuntansi → Laba Rugi"},
        {"key": "balance-sheet", "title": "Laporan neraca", "path": "/accounting", "metric": "Akuntansi → Neraca"},
        {"key": "cash-flow", "title": "Laporan arus kas", "path": "/accounting", "metric": "Akuntansi → Arus Kas"},
    ]}
