"""Router accounting — COA, jurnal berpasangan, laporan keuangan, aset, budget.

Aturan keras yang ditegakkan DI SINI (bukan cuma di UI):
- Jurnal tidak balance -> 400. Tidak ada jalan pintas.
- Jurnal POSTED tidak bisa diedit/dihapus. Koreksi wajib lewat reversal.
- Laporan hanya membaca jurnal POSTED.
- Auto-posting dari invoice/payment bersifat idempotent lewat source_ref.
- Hak tulis: CFO_MANAGER + FINANCE_SUPPORT. CEO read-only (punya drill-down).
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user, require_roles
from ..audit import log_audit
from .. import models
from ..accounting_models import (ChartOfAccount, JournalEntry, JournalLine,
                                 FixedAsset, DepreciationEntry, Budget)
from .. import accounting_service as svc

router = APIRouter(prefix="/accounting", tags=["accounting"])

WRITE_ROLES = (models.Role.CFO_MANAGER, models.Role.FINANCE_SUPPORT)
ALL_ROLES = tuple(models.Role)


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Skema ────────────────────────────────────────────────────────────────────
class AccountIn(BaseModel):
    code: str = Field(min_length=2, max_length=24)
    name: str = Field(min_length=2, max_length=180)
    account_type: Literal["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"]
    parent_id: Optional[int] = None
    cashflow_activity: Optional[Literal["OPERATING", "INVESTING", "FINANCING"]] = None
    is_cash_account: bool = False
    description: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=180)
    is_active: Optional[bool] = None
    cashflow_activity: Optional[Literal["OPERATING", "INVESTING", "FINANCING"]] = None
    description: Optional[str] = None


class JournalLineIn(BaseModel):
    account_code: str
    debit: Decimal = Field(default=Decimal(0), ge=0)
    credit: Decimal = Field(default=Decimal(0), ge=0)
    description: Optional[str] = None
    order_fk: Optional[int] = None
    article_id: Optional[int] = None


class JournalIn(BaseModel):
    entry_date: date
    description: Optional[str] = None
    lines: list[JournalLineIn]
    order_fk: Optional[int] = None


class ReversalIn(BaseModel):
    entry_date: Optional[date] = None
    reason: str = Field(min_length=3, max_length=1000)


class AssetIn(BaseModel):
    asset_code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=180)
    category: Optional[str] = None
    acquisition_date: date
    acquisition_cost: Decimal = Field(gt=0)
    salvage_value: Decimal = Field(default=Decimal(0), ge=0)
    useful_life_months: int = Field(gt=0, le=1200)
    asset_account_id: Optional[int] = None
    depreciation_expense_account_id: Optional[int] = None
    accumulated_account_id: Optional[int] = None


class DepreciationRunIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")  # YYYY-MM


class BudgetIn(BaseModel):
    period: str = Field(min_length=4, max_length=7)
    account_id: int
    amount: Decimal
    notes: Optional[str] = None


def _account(code: str, db: Session) -> ChartOfAccount:
    acct = db.query(ChartOfAccount).filter_by(code=code).first()
    if acct is None:
        raise HTTPException(400, f"Akun '{code}' tidak ada di chart of accounts.")
    return acct


# ── Chart of Accounts ────────────────────────────────────────────────────────
@router.get("/accounts")
def list_accounts(
    account_type: Optional[str] = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(ChartOfAccount)
    if account_type:
        q = q.filter(ChartOfAccount.account_type == account_type)
    if active_only:
        q = q.filter(ChartOfAccount.is_active.is_(True))
    rows = q.order_by(ChartOfAccount.code).all()
    return [{"id": a.id, "code": a.code, "name": a.name, "account_type": a.account_type,
             "normal_balance": a.normal_balance, "parent_id": a.parent_id,
             "cashflow_activity": a.cashflow_activity, "is_cash_account": a.is_cash_account,
             "is_active": a.is_active, "description": a.description} for a in rows]


@router.post("/accounts", status_code=201)
def create_account(data: AccountIn, db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    if db.query(ChartOfAccount).filter_by(code=data.code).first():
        raise HTTPException(409, f"Akun dengan kode '{data.code}' sudah ada.")
    normal = svc.NORMAL_BALANCE[data.account_type]
    acct = ChartOfAccount(code=data.code, name=data.name, account_type=data.account_type,
                          normal_balance=normal, parent_id=data.parent_id,
                          cashflow_activity=data.cashflow_activity,
                          is_cash_account=data.is_cash_account, description=data.description)
    db.add(acct)
    log_audit(db, user, "CREATE", "ChartOfAccount", detail=f"Akun {data.code} - {data.name}",
              obj=acct, previous_status=None, new_status="ACTIVE", reason="Pembuatan akun baru")
    db.commit()
    db.refresh(acct)
    return {"id": acct.id, "code": acct.code, "name": acct.name, "account_type": acct.account_type,
            "normal_balance": acct.normal_balance}


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, data: AccountUpdate, db: Session = Depends(get_db),
                   user=Depends(require_roles(*WRITE_ROLES))):
    acct = db.get(ChartOfAccount, account_id)
    if acct is None:
        raise HTTPException(404, "Akun tidak ditemukan.")
    for field in ("name", "is_active", "cashflow_activity", "description"):
        val = getattr(data, field)
        if val is not None:
            setattr(acct, field, val)
    log_audit(db, user, "UPDATE", "ChartOfAccount", entity_id=acct.id, obj=acct, reason="Update akun")
    db.commit()
    return {"id": acct.id, "code": acct.code, "name": acct.name, "is_active": acct.is_active}


# ── Jurnal ───────────────────────────────────────────────────────────────────
@router.get("/journal-entries")
def list_journal(
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(JournalEntry)
    if status:
        q = q.filter(JournalEntry.status == status)
    if date_from:
        q = q.filter(JournalEntry.entry_date >= date_from)
    if date_to:
        q = q.filter(JournalEntry.entry_date <= date_to)
    entries = q.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc()).limit(limit).all()
    out = []
    for e in entries:
        lines = db.query(JournalLine).filter_by(entry_id=e.id).order_by(JournalLine.line_no).all()
        amap = {a.id: a for a in db.query(ChartOfAccount).all()}
        out.append({
            "id": e.id, "entry_no": e.entry_no, "entry_date": e.entry_date.isoformat(),
            "description": e.description, "status": e.status, "entry_source": e.entry_source,
            "source_ref": e.source_ref, "order_fk": e.order_fk,
            "reversal_of_id": e.reversal_of_id, "reversed_by_id": e.reversed_by_id,
            "total_debit": float(sum((Decimal(str(l.debit or 0)) for l in lines), Decimal(0))),
            "lines": [{"account_code": amap[l.account_id].code if l.account_id in amap else None,
                       "account_name": amap[l.account_id].name if l.account_id in amap else None,
                       "debit": float(l.debit or 0), "credit": float(l.credit or 0),
                       "description": l.description} for l in lines],
        })
    return out


@router.post("/journal-entries", status_code=201)
def create_journal(data: JournalIn, db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    lines = [l.model_dump() for l in data.lines]
    errors = svc.validate_lines(db, lines)
    if errors:
        raise HTTPException(400, "; ".join(errors))
    svc.resolve_account_ids(db, lines)
    entry = JournalEntry(entry_no=svc.next_entry_no(db), entry_date=data.entry_date,
                         description=data.description, entry_source="MANUAL",
                         status="DRAFT", order_fk=data.order_fk, created_by_id=user.id)
    db.add(entry)
    db.flush()
    svc.add_lines(db, entry, lines)
    log_audit(db, user, "CREATE", "JournalEntry", entity_id=entry.id, obj=entry,
              detail=f"Jurnal {entry.entry_no}", new_status="DRAFT", reason="Input jurnal manual")
    db.commit()
    db.refresh(entry)
    return {"id": entry.id, "entry_no": entry.entry_no, "status": entry.status}


def _get_entry(db: Session, entry_id: int) -> JournalEntry:
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "Jurnal tidak ditemukan.")
    return entry


@router.post("/journal-entries/{entry_id}/post")
def post_journal(entry_id: int, db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    entry = _get_entry(db, entry_id)
    if entry.status != "DRAFT":
        raise HTTPException(409, f"Jurnal berstatus {entry.status}; hanya DRAFT yang bisa diposting.")
    lines = db.query(JournalLine).filter_by(entry_id=entry.id).all()
    td = sum((Decimal(str(l.debit or 0)) for l in lines), Decimal(0))
    tc = sum((Decimal(str(l.credit or 0)) for l in lines), Decimal(0))
    if td != tc:
        raise HTTPException(400, f"Jurnal tidak balance: debit {td} != kredit {tc}.")
    entry.status = "POSTED"
    entry.posted_by_id = user.id
    entry.posted_at = datetime.utcnow()
    log_audit(db, user, "POST", "JournalEntry", entity_id=entry.id, obj=entry,
              previous_status="DRAFT", new_status="POSTED", reason="Posting jurnal")
    db.commit()
    return {"id": entry.id, "status": entry.status, "posted_at": entry.posted_at.isoformat()}


@router.post("/journal-entries/{entry_id}/reverse", status_code=201)
def reverse_journal(entry_id: int, data: ReversalIn, db: Session = Depends(get_db),
                    user=Depends(require_roles(*WRITE_ROLES))):
    """Koreksi jurnal lewat reversal — bukan edit/hapus (PRD §7)."""
    entry = _get_entry(db, entry_id)
    if entry.status != "POSTED":
        raise HTTPException(409, "Hanya jurnal POSTED yang bisa di-reverse.")
    if entry.reversed_by_id:
        raise HTTPException(409, "Jurnal ini sudah pernah di-reverse.")
    orig_lines = db.query(JournalLine).filter_by(entry_id=entry.id).order_by(JournalLine.line_no).all()
    rev = JournalEntry(entry_no=svc.next_entry_no(db), entry_date=data.entry_date or date.today(),
                       description=f"Reversal dari {entry.entry_no}: {data.reason}",
                       entry_source="MANUAL", status="POSTED", order_fk=entry.order_fk,
                       reversal_of_id=entry.id, created_by_id=user.id, posted_by_id=user.id,
                       posted_at=datetime.utcnow())
    db.add(rev)
    db.flush()
    for i, l in enumerate(orig_lines, 1):
        # Tukar debit <-> kredit.
        db.add(JournalLine(entry_id=rev.id, line_no=i, account_id=l.account_id,
                           debit=Decimal(str(l.credit or 0)), credit=Decimal(str(l.debit or 0)),
                           description=f"Reversal: {l.description or ''}".strip(),
                           order_fk=l.order_fk, article_id=l.article_id))
    # Jurnal asal TETAP berstatus POSTED. Kalau kita tandai REVERSED (yang berarti
    # dikecualikan dari laporan) SEKALIGUS menghitung jurnal pembaliknya, efeknya
    # dobel: pembalik tidak lagi membatalkan apa pun. Standar akuntansi: keduanya
    # tetap POSTED dan saling meniadakan; penanda "sudah dibalik" pakai
    # reversed_by_id saja (dipakai UI untuk badge, bukan untuk menyaring laporan).
    entry.reversed_by_id = rev.id
    log_audit(db, user, "REVERSE", "JournalEntry", entity_id=entry.id, obj=entry,
              previous_status="POSTED", new_status="POSTED",
              detail=f"Dibalik oleh {rev.entry_no}", reason=data.reason)
    db.commit()
    return {"reversal_id": rev.id, "reversal_entry_no": rev.entry_no,
            "original_status": entry.status, "original_reversed": True}


# ── Laporan ──────────────────────────────────────────────────────────────────
@router.get("/trial-balance")
def get_trial_balance(as_of: Optional[date] = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return svc.trial_balance(db, as_of)


@router.get("/income-statement")
def get_income_statement(date_from: date, date_to: date, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return svc.income_statement(db, date_from, date_to)


@router.get("/balance-sheet")
def get_balance_sheet(as_of: Optional[date] = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return svc.balance_sheet(db, as_of)


@router.get("/cash-flow")
def get_cash_flow(date_from: date, date_to: date, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return svc.cash_flow(db, date_from, date_to)


@router.get("/general-ledger/{account_id}")
def get_general_ledger(account_id: int, date_from: Optional[date] = None, date_to: Optional[date] = None,
                       db: Session = Depends(get_db), user=Depends(get_current_user)):
    gl = svc.general_ledger(db, account_id, date_from, date_to)
    if not gl:
        raise HTTPException(404, "Akun tidak ditemukan.")
    return gl


# ── Aset tetap & penyusutan ──────────────────────────────────────────────────
@router.get("/assets")
def list_assets(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(FixedAsset).order_by(FixedAsset.asset_code).all()
    return [{"id": a.id, "asset_code": a.asset_code, "name": a.name, "category": a.category,
             "acquisition_date": a.acquisition_date.isoformat(), "acquisition_cost": float(a.acquisition_cost),
             "salvage_value": float(a.salvage_value), "useful_life_months": a.useful_life_months,
             "accumulated_depreciation": float(a.accumulated_depreciation),
             "book_value": float(Decimal(a.acquisition_cost) - Decimal(a.accumulated_depreciation)),
             "monthly_depreciation": float(svc.monthly_depreciation(a)), "status": a.status} for a in rows]


@router.post("/assets", status_code=201)
def create_asset(data: AssetIn, db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    if db.query(FixedAsset).filter_by(asset_code=data.asset_code).first():
        raise HTTPException(409, f"Aset '{data.asset_code}' sudah ada.")
    if data.salvage_value >= data.acquisition_cost:
        raise HTTPException(400, "Nilai residu harus lebih kecil dari harga perolehan.")
    asset = FixedAsset(**data.model_dump())
    db.add(asset)
    log_audit(db, user, "CREATE", "FixedAsset", obj=asset, detail=f"Aset {data.asset_code}",
              new_status="ACTIVE", reason="Registrasi aset tetap")
    db.commit()
    db.refresh(asset)
    return {"id": asset.id, "asset_code": asset.asset_code, "monthly_depreciation": float(svc.monthly_depreciation(asset))}


@router.post("/depreciation/run")
def run_depreciation(data: DepreciationRunIn, db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    """Jalankan penyusutan garis lurus untuk satu periode YYYY-MM (idempotent)."""
    assets = db.query(FixedAsset).filter(FixedAsset.status == "ACTIVE").all()
    created, skipped = [], []
    for asset in assets:
        if db.query(DepreciationEntry).filter_by(asset_id=asset.id, period=data.period).first():
            skipped.append(asset.asset_code)
            continue
        monthly = svc.monthly_depreciation(asset)
        if monthly <= 0:
            skipped.append(asset.asset_code)
            continue
        book = Decimal(asset.acquisition_cost) - Decimal(asset.accumulated_depreciation)
        depreciable_left = book - Decimal(asset.salvage_value)
        amount = min(monthly, depreciable_left)
        if amount <= 0:
            skipped.append(asset.asset_code)
            continue
        asset.accumulated_depreciation = Decimal(asset.accumulated_depreciation) + amount
        entry = None
        # Posting jurnal kalau akun-akunnya diset.
        if asset.depreciation_expense_account_id and asset.accumulated_account_id:
            lines = [
                {"account_code": None, "_account_id": asset.depreciation_expense_account_id,
                 "debit": amount, "credit": Decimal(0), "description": f"Penyusutan {asset.name} {data.period}"},
                {"account_code": None, "_account_id": asset.accumulated_account_id,
                 "debit": Decimal(0), "credit": amount, "description": f"Akumulasi penyusutan {asset.name}"},
            ]
            entry = JournalEntry(entry_no=svc.next_entry_no(db), entry_date=date.today(),
                                 description=f"Penyusutan {asset.asset_code} periode {data.period}",
                                 entry_source="AUTO", source_ref=f"DEPRECIATION:{asset.id}:{data.period}",
                                 status="POSTED", created_by_id=user.id, posted_by_id=user.id,
                                 posted_at=datetime.utcnow())
            db.add(entry)
            db.flush()
            for i, l in enumerate(lines, 1):
                db.add(JournalLine(entry_id=entry.id, line_no=i, account_id=l["_account_id"],
                                   debit=l["debit"], credit=l["credit"], description=l["description"]))
        db.add(DepreciationEntry(asset_id=asset.id, period=data.period, amount=amount,
                                 accumulated_after=asset.accumulated_depreciation,
                                 journal_entry_id=entry.id if entry else None,
                                 posted_at=datetime.utcnow() if entry else None))
        created.append({"asset_code": asset.asset_code, "amount": float(amount),
                        "journal_entry_no": entry.entry_no if entry else None})
    log_audit(db, user, "RUN", "DepreciationEntry", detail=f"Penyusutan {data.period}: {len(created)} aset",
              reason=f"Jalankan penyusutan periode {data.period}")
    db.commit()
    return {"period": data.period, "created": created, "skipped": skipped}


@router.get("/depreciation")
def list_depreciation(period: Optional[str] = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(DepreciationEntry)
    if period:
        q = q.filter(DepreciationEntry.period == period)
    rows = q.order_by(DepreciationEntry.period.desc()).all()
    amap = {a.id: a for a in db.query(FixedAsset).all()}
    return [{"id": d.id, "asset_code": amap[d.asset_id].asset_code if d.asset_id in amap else None,
             "asset_name": amap[d.asset_id].name if d.asset_id in amap else None,
             "period": d.period, "amount": float(d.amount),
             "accumulated_after": float(d.accumulated_after),
             "journal_entry_id": d.journal_entry_id} for d in rows]


# ── Budget ───────────────────────────────────────────────────────────────────
@router.get("/budgets")
def list_budgets(period: Optional[str] = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(Budget)
    if period:
        q = q.filter(Budget.period == period)
    rows = q.all()
    amap = {a.id: a for a in db.query(ChartOfAccount).all()}
    return [{"id": b.id, "period": b.period, "account_id": b.account_id,
             "account_code": amap[b.account_id].code if b.account_id in amap else None,
             "account_name": amap[b.account_id].name if b.account_id in amap else None,
             "amount": float(b.amount), "notes": b.notes} for b in rows]


@router.post("/budgets", status_code=201)
def upsert_budget(data: BudgetIn, db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    acct = db.get(ChartOfAccount, data.account_id)
    if acct is None:
        raise HTTPException(400, "Akun tidak ditemukan.")
    b = db.query(Budget).filter_by(period=data.period, account_id=data.account_id).first()
    if b is None:
        b = Budget(period=data.period, account_id=data.account_id, amount=data.amount, notes=data.notes)
        db.add(b)
    else:
        b.amount = data.amount
        b.notes = data.notes
    log_audit(db, user, "UPSERT", "Budget", obj=b, detail=f"Budget {acct.code} {data.period}",
              reason="Set anggaran")
    db.commit()
    db.refresh(b)
    return {"id": b.id, "period": b.period, "amount": float(b.amount)}


@router.get("/budget-vs-actual")
def budget_vs_actual(period: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Realisasi vs anggaran per akun untuk satu periode (YYYY atau YYYY-MM)."""
    budgets = db.query(Budget).filter(Budget.period == period).all()
    if not budgets:
        return {"period": period, "rows": []}
    # Tentukan rentang tanggal dari periode.
    if len(period) == 7:
        y, mo = period.split("-")
        date_from = date(int(y), int(mo), 1)
        date_to = date(int(y) + (1 if int(mo) == 12 else 0), 1 if int(mo) == 12 else int(mo) + 1, 1)
    else:
        date_from = date(int(period), 1, 1)
        date_to = date(int(period) + 1, 1, 1)
    actual = svc.income_statement(db, date_from, date_to)
    actual_map = {r["code"]: r["amount"] for r in actual["revenue"] + actual["expense"]}
    amap = {a.id: a for a in db.query(ChartOfAccount).all()}
    rows = []
    for b in budgets:
        acct = amap.get(b.account_id)
        if not acct:
            continue
        act = Decimal(str(actual_map.get(acct.code, 0)))
        rows.append({"account_code": acct.code, "account_name": acct.name,
                     "account_type": acct.account_type, "budget": float(b.amount),
                     "actual": float(act), "variance": float(Decimal(b.amount) - act),
                     "usage_percent": float((act / Decimal(b.amount) * 100).quantize(Decimal("0.1"))) if b.amount else None})
    return {"period": period, "rows": rows}


# ── Auto-posting dari transaksi yang sudah ada (invoice / payment) ────────────
def _auto_entry(db: Session, source_ref: str, entry_date: date, description: str,
                lines: list, order_fk=None, user=None) -> JournalEntry | None:
    """Buat jurnal POSTED otomatis kalau source_ref belum pernah diposting.

    Idempotent: memanggil ulang dengan source_ref yang sama tidak menggandakan
    jurnal. Ini menjaga laporan tetap konsisten walaupun sync dijalankan berkali-kali.
    """
    existing = db.query(JournalEntry).filter_by(source_ref=source_ref).first()
    if existing:
        return None
    resolved = []
    amap = svc.account_map(db)
    for code, debit, credit, desc in lines:
        acct = amap.get(code)
        if acct is None:
            return None  # akun belum ada -> lewati, jangan bikin jurnal setengah
        resolved.append({"account_code": code, "_account_id": acct.id,
                         "debit": Decimal(str(debit)), "credit": Decimal(str(credit)), "description": desc})
    entry = JournalEntry(entry_no=svc.next_entry_no(db), entry_date=entry_date,
                         description=description, entry_source="AUTO", source_ref=source_ref,
                         status="POSTED", order_fk=order_fk,
                         created_by_id=user.id if user else None,
                         posted_by_id=user.id if user else None, posted_at=datetime.utcnow())
    db.add(entry)
    db.flush()
    svc.add_lines(db, entry, resolved)
    return entry


@router.post("/sync-transactions")
def sync_transactions(db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    """Posting otomatis dari invoice & pembayaran terverifikasi ke jurnal.

    Aturan posting:
    - Invoice terbit  : Debit Piutang Usaha (1-1200) / Kredit Pendapatan (4-1000).
    - Payment VERIFIED: Debit Bank (1-1100) / Kredit Piutang Usaha (1-1200).

    Hanya membaca transaksi yang sudah ada; tidak menebak. Idempotent lewat
    source_ref sehingga aman dijalankan berulang.
    """
    created = {"invoices": 0, "payments": 0, "skipped": 0}
    # Invoice
    for inv in db.query(models.Invoice).all():
        ref = f"INVOICE:{inv.invoice_no}"
        amount = Decimal(str(inv.amount or 0))
        if amount <= 0:
            created["skipped"] += 1
            continue
        edate = inv.created_at.date() if inv.created_at else date.today()
        e = _auto_entry(db, ref, edate, f"Invoice {inv.invoice_no}",
                        [("1-1200", amount, 0, f"AR invoice {inv.invoice_no}"),
                         ("4-1000", 0, amount, f"Pendapatan invoice {inv.invoice_no}")],
                        order_fk=inv.order_fk, user=user)
        if e:
            created["invoices"] += 1
    # Payment terverifikasi (atau legacy tanpa status = dianggap sah)
    for pay in db.query(models.Payment).all():
        status = pay.status or "VERIFIED"
        if status != "VERIFIED":
            continue
        amount = Decimal(str(pay.amount or 0))
        if amount <= 0:
            created["skipped"] += 1
            continue
        ref = f"PAYMENT:{pay.id}"
        edate = pay.payment_date or (pay.created_at.date() if pay.created_at else date.today())
        e = _auto_entry(db, ref, edate, f"Pembayaran {pay.invoice_no}",
                        [("1-1100", amount, 0, f"Kas masuk {pay.invoice_no}"),
                         ("1-1200", 0, amount, f"Pelunasan AR {pay.invoice_no}")],
                        order_fk=pay.order_fk, user=user)
        if e:
            created["payments"] += 1
    log_audit(db, user, "SYNC", "JournalEntry",
              detail=f"Auto-posting: {created['invoices']} invoice, {created['payments']} payment",
              reason="Sinkronisasi transaksi ke jurnal")
    db.commit()
    return created


@router.post("/seed-coa")
def seed_coa(db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    """Isi chart of accounts standar kalau belum ada (idempotent)."""
    from ..accounting_seed import seed_chart_of_accounts
    created = seed_chart_of_accounts(db)
    log_audit(db, user, "SEED", "ChartOfAccount", detail=f"Seed COA: {created} akun baru",
              reason="Inisialisasi chart of accounts")
    db.commit()
    return {"created": created, "total": db.query(ChartOfAccount).count()}
