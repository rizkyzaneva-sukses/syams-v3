"""Router banking — rekonsiliasi bank + posisi treasury (workspace Lutfi).

Ini modul Finance yang MENCOCOKKAN, bukan memposting: mutasi bank diimport dari
statement lalu direkonsiliasi terhadap baris jurnal atau payment yang SUDAH ada.
Aturan yang ditegakkan DI SINI (bukan cuma di UI):

1. **Reconcile butuh lawan yang nyata.** Tanpa ``journal_line_id`` atau
   ``payment_id`` → 400. Tidak ada "reconciled" yang tidak menunjuk ke apa pun.
2. **Mutasi yang sudah RECONCILED terkunci.** Reconcile ulang → 409. Koreksi
   lewat ``unreconcile`` (yang mencatat jejak audit), bukan timpa diam-diam.
3. **Import mutasi lewat JSON list**, bukan file — tidak ada pandas/openpyxl di
   dependency. Satu batch ditandai ``import_batch`` supaya bisa ditelusuri.
4. **Treasury dihitung dari jurnal POSTED** untuk akun COA ``is_cash_account``.
   Tidak ada tabel posisi terpisah yang bisa berbeda dari buku besar.
5. Hak tulis: CFO_MANAGER + FINANCE_SUPPORT. CEO read-only; semua peran
   terautentikasi boleh membaca.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user, require_roles
from ..audit import log_audit
from .. import models
from ..accounting_models import ChartOfAccount, JournalLine, JournalEntry
from .. import accounting_service as svc
from ..banking_models import BankAccount, BankTransaction, RECON_STATUSES

router = APIRouter(prefix="/banking", tags=["banking"])

WRITE_ROLES = (models.Role.CFO_MANAGER, models.Role.FINANCE_SUPPORT)
ALL_ROLES = tuple(models.Role)

# Jendela toleransi tanggal untuk saran pencocokan: mutasi bank dan jurnal bisa
# beda hari karena settlement/lag bank, jadi 7 hari dipakai sebagai batas.
MATCH_WINDOW_DAYS = 7

ZERO = Decimal("0.00")


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# ── Skema ────────────────────────────────────────────────────────────────────
class BankAccountIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    bank_name: str = Field(min_length=2, max_length=120)
    account_no: Optional[str] = Field(default=None, max_length=64)
    account_name: Optional[str] = Field(default=None, max_length=160)
    currency: str = Field(default="IDR", max_length=8)
    opening_balance: Decimal = Field(default=Decimal(0))
    gl_account_id: Optional[int] = None


class BankAccountUpdate(BaseModel):
    bank_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    account_no: Optional[str] = Field(default=None, max_length=64)
    account_name: Optional[str] = Field(default=None, max_length=160)
    currency: Optional[str] = Field(default=None, max_length=8)
    opening_balance: Optional[Decimal] = None
    is_active: Optional[bool] = None
    gl_account_id: Optional[int] = None


class BankTxnIn(BaseModel):
    txn_date: date
    description: Optional[str] = None
    debit: Decimal = Field(default=Decimal(0), ge=0)   # uang masuk
    credit: Decimal = Field(default=Decimal(0), ge=0)  # uang keluar
    reference: Optional[str] = Field(default=None, max_length=120)
    balance_after: Optional[Decimal] = None


class ImportIn(BaseModel):
    transactions: list[BankTxnIn]
    import_batch: Optional[str] = Field(default=None, max_length=60)


class ReconcileIn(BaseModel):
    journal_line_id: Optional[int] = None
    payment_id: Optional[int] = None
    note: Optional[str] = None


def _dec(value) -> Decimal:
    if value is None:
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "Angka tidak valid.")


def _num(value):
    return None if value is None else float(value)


def _iso(value):
    return value.isoformat() if value else None


def _get_account(db: Session, account_id: int) -> BankAccount:
    acct = db.get(BankAccount, account_id)
    if acct is None:
        raise HTTPException(404, "Akun bank tidak ditemukan.")
    return acct


def _get_txn(db: Session, txn_id: int) -> BankTransaction:
    txn = db.get(BankTransaction, txn_id)
    if txn is None:
        raise HTTPException(404, "Mutasi bank tidak ditemukan.")
    return txn


def _txn_amount(txn: BankTransaction) -> Decimal:
    """Nominal tunggal sebuah mutasi (masuk positif dari sisi debit)."""
    return _dec(txn.debit) if _dec(txn.debit) > 0 else _dec(txn.credit)


def _account_row(a: BankAccount) -> dict:
    return {
        "id": a.id, "code": a.code, "bank_name": a.bank_name,
        "account_no": a.account_no, "account_name": a.account_name,
        "currency": a.currency, "opening_balance": _num(_dec(a.opening_balance)),
        "is_active": a.is_active, "gl_account_id": a.gl_account_id,
        "created_at": _iso(a.created_at),
    }


def _txn_row(t: BankTransaction) -> dict:
    return {
        "id": t.id, "bank_account_id": t.bank_account_id,
        "txn_date": _iso(t.txn_date), "description": t.description,
        "debit": _num(_dec(t.debit)), "credit": _num(_dec(t.credit)),
        "reference": t.reference, "balance_after": _num(t.balance_after),
        "import_batch": t.import_batch,
        "reconciliation_status": t.reconciliation_status,
        "matched_journal_line_id": t.matched_journal_line_id,
        "matched_payment_id": t.matched_payment_id,
        "matched_at": _iso(t.matched_at), "matched_by_id": t.matched_by_id,
    }


# ── Bank Account CRUD ────────────────────────────────────────────────────────
@router.get("/accounts")
def list_bank_accounts(active_only: bool = False, db: Session = Depends(get_db),
                       user=Depends(get_current_user)):
    q = db.query(BankAccount)
    if active_only:
        q = q.filter(BankAccount.is_active.is_(True))
    return [_account_row(a) for a in q.order_by(BankAccount.code).all()]


@router.post("/accounts", status_code=201)
def create_bank_account(data: BankAccountIn, db: Session = Depends(get_db),
                        user=Depends(require_roles(*WRITE_ROLES))):
    if db.query(BankAccount).filter_by(code=data.code).first():
        raise HTTPException(409, f"Akun bank dengan kode '{data.code}' sudah ada.")
    if data.gl_account_id is not None and db.get(ChartOfAccount, data.gl_account_id) is None:
        raise HTTPException(400, "Akun COA (gl_account_id) tidak ditemukan.")
    acct = BankAccount(**data.model_dump())
    db.add(acct)
    log_audit(db, user, "CREATE", "BankAccount", obj=acct, detail=f"Akun bank {data.code}",
              new_status="ACTIVE", reason="Registrasi akun bank")
    db.commit()
    db.refresh(acct)
    return _account_row(acct)


@router.patch("/accounts/{account_id}")
def update_bank_account(account_id: int, data: BankAccountUpdate,
                        db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    acct = _get_account(db, account_id)
    if data.gl_account_id is not None and db.get(ChartOfAccount, data.gl_account_id) is None:
        raise HTTPException(400, "Akun COA (gl_account_id) tidak ditemukan.")
    for field in ("bank_name", "account_no", "account_name", "currency",
                  "opening_balance", "is_active", "gl_account_id"):
        val = getattr(data, field)
        if val is not None:
            setattr(acct, field, val)
    log_audit(db, user, "UPDATE", "BankAccount", entity_id=acct.id, obj=acct, reason="Update akun bank")
    db.commit()
    return _account_row(acct)


# ── Import & daftar mutasi ───────────────────────────────────────────────────
@router.post("/accounts/{account_id}/transactions", status_code=201)
def import_transactions(account_id: int, data: ImportIn, db: Session = Depends(get_db),
                        user=Depends(require_roles(*WRITE_ROLES))):
    """Import mutasi bank dari JSON list (bukan file) — batch ditandai.

    Tiap baris divalidasi: minimal salah satu debit/credit > 0 dan tidak boleh
    keduanya terisi sekaligus (uang tidak bisa masuk DAN keluar dalam satu baris).
    """
    acct = _get_account(db, account_id)
    if not data.transactions:
        raise HTTPException(400, "Tidak ada baris mutasi untuk diimport.")
    batch = data.import_batch or f"IMP-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    created = 0
    for i, row in enumerate(data.transactions, 1):
        debit, credit = _dec(row.debit), _dec(row.credit)
        if debit > 0 and credit > 0:
            raise HTTPException(400, f"Baris {i}: satu mutasi hanya boleh debit ATAU credit.")
        if debit == 0 and credit == 0:
            raise HTTPException(400, f"Baris {i}: nilai debit/credit tidak boleh nol keduanya.")
        db.add(BankTransaction(
            bank_account_id=acct.id, txn_date=row.txn_date, description=row.description,
            debit=debit, credit=credit, reference=row.reference,
            balance_after=row.balance_after, import_batch=batch,
            reconciliation_status="UNRECONCILED",
        ))
        created += 1
    log_audit(db, user, "IMPORT", "BankTransaction", entity_id=acct.id,
              detail=f"Import {created} mutasi ke {acct.code} (batch {batch})",
              reason="Import mutasi bank")
    db.commit()
    return {"bank_account_id": acct.id, "import_batch": batch, "imported": created}


@router.get("/accounts/{account_id}/transactions")
def list_transactions(account_id: int, status: Optional[str] = None,
                      date_from: Optional[date] = None, date_to: Optional[date] = None,
                      limit: int = Query(default=500, le=2000),
                      db: Session = Depends(get_db), user=Depends(get_current_user)):
    _get_account(db, account_id)
    q = db.query(BankTransaction).filter(BankTransaction.bank_account_id == account_id)
    if status:
        if status not in RECON_STATUSES:
            raise HTTPException(400, f"status harus salah satu dari {', '.join(RECON_STATUSES)}.")
        q = q.filter(BankTransaction.reconciliation_status == status)
    if date_from:
        q = q.filter(BankTransaction.txn_date >= date_from)
    if date_to:
        q = q.filter(BankTransaction.txn_date <= date_to)
    rows = q.order_by(BankTransaction.txn_date.desc(), BankTransaction.id.desc()).limit(limit).all()
    return [_txn_row(t) for t in rows]


# ── Saran pencocokan otomatis ────────────────────────────────────────────────
@router.get("/accounts/{account_id}/match-suggestions")
def match_suggestions(account_id: int, transaction_id: int,
                      db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Saran target pencocokan: nominal sama + tanggal beda ≤ 7 hari.

    Kandidat jurnal diambil dari baris jurnal pada akun COA bank (gl_account_id)
    yang sisi/ nominalnya sama dengan mutasi; kandidat payment dari tabel payments
    dengan nominal sama. Tidak ada penebakan: hanya yang benar-benar cocok yang
    dikembalikan, dan bila akun belum punya gl_account_id, saran jurnal kosong.
    """
    acct = _get_account(db, account_id)
    txn = _get_txn(db, transaction_id)
    if txn.bank_account_id != acct.id:
        raise HTTPException(400, "Mutasi ini bukan milik akun bank yang dipilih.")

    debit, credit = _dec(txn.debit), _dec(txn.credit)
    lo, hi = txn.txn_date - timedelta(days=MATCH_WINDOW_DAYS), txn.txn_date + timedelta(days=MATCH_WINDOW_DAYS)

    journal_suggestions = []
    if acct.gl_account_id is not None:
        q = (db.query(JournalLine, JournalEntry)
             .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
             .filter(JournalEntry.status == "POSTED",
                     JournalLine.account_id == acct.gl_account_id,
                     JournalEntry.entry_date >= lo, JournalEntry.entry_date <= hi))
        for line, entry in q.all():
            if _dec(line.debit) == debit and _dec(line.credit) == credit and (debit or credit):
                journal_suggestions.append({
                    "journal_line_id": line.id, "entry_no": entry.entry_no,
                    "entry_date": _iso(entry.entry_date), "description": line.description or entry.description,
                    "debit": _num(_dec(line.debit)), "credit": _num(_dec(line.credit)),
                    "days_diff": abs((entry.entry_date - txn.txn_date).days),
                })
    journal_suggestions.sort(key=lambda r: r["days_diff"])

    amount = debit if debit > 0 else credit
    payment_suggestions = []
    if amount > 0:
        pq = (db.query(models.Payment)
              .filter(models.Payment.amount == amount,
                      models.Payment.payment_date >= lo, models.Payment.payment_date <= hi))
        for p in pq.all():
            payment_suggestions.append({
                "payment_id": p.id, "invoice_no": p.invoice_no, "amount": _num(_dec(p.amount)),
                "payment_date": _iso(p.payment_date), "reference": getattr(p, "evidence_ref", None),
                "days_diff": abs((p.payment_date - txn.txn_date).days) if p.payment_date else None,
            })
    payment_suggestions.sort(key=lambda r: r["days_diff"] if r["days_diff"] is not None else 999)

    return {
        "transaction_id": txn.id, "bank_account_id": acct.id,
        "amount": _num(amount), "window_days": MATCH_WINDOW_DAYS,
        "journal_line_suggestions": journal_suggestions,
        "payment_suggestions": payment_suggestions,
    }


# ── Rekonsiliasi ─────────────────────────────────────────────────────────────
@router.post("/transactions/{txn_id}/reconcile")
def reconcile(txn_id: int, data: ReconcileIn, db: Session = Depends(get_db),
              user=Depends(require_roles(*WRITE_ROLES))):
    """Tandai mutasi bank sebagai RECONCILED dengan menunjuk baris jurnal / payment.

    Guardrail keras: sudah RECONCILED → 409; tanpa target valid → 400; target
    tidak ada → 400. Mutasi IGNORED tidak boleh direkonsiliasi tanpa di-aktifkan
    ulang (409) supaya keputusan "abaikan" tidak tertimpa diam-diam.
    """
    txn = _get_txn(db, txn_id)
    if txn.reconciliation_status == "RECONCILED":
        raise HTTPException(409, "Mutasi ini sudah RECONCILED. Unreconcile dulu bila ingin mengubah.")
    if txn.reconciliation_status == "IGNORED":
        raise HTTPException(409, "Mutasi ini ditandai IGNORED. Aktifkan ulang sebelum rekonsiliasi.")
    if data.journal_line_id is None and data.payment_id is None:
        raise HTTPException(400, "Rekonsiliasi butuh journal_line_id atau payment_id sebagai target.")
    if data.journal_line_id is not None and db.get(JournalLine, data.journal_line_id) is None:
        raise HTTPException(400, "Baris jurnal (journal_line_id) tidak ditemukan.")
    if data.payment_id is not None and db.get(models.Payment, data.payment_id) is None:
        raise HTTPException(400, "Pembayaran (payment_id) tidak ditemukan.")

    txn.reconciliation_status = "RECONCILED"
    txn.matched_journal_line_id = data.journal_line_id
    txn.matched_payment_id = data.payment_id
    txn.matched_at = datetime.utcnow()
    txn.matched_by_id = user.id
    log_audit(db, user, "RECONCILE", "BankTransaction", entity_id=txn.id,
              detail=f"match journal_line={data.journal_line_id} payment={data.payment_id}",
              obj=txn, previous_status="UNRECONCILED", new_status="RECONCILED",
              reason=data.note or "Rekonsiliasi mutasi bank")
    db.commit()
    db.refresh(txn)
    return _txn_row(txn)


@router.post("/transactions/{txn_id}/unreconcile")
def unreconcile(txn_id: int, db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    txn = _get_txn(db, txn_id)
    if txn.reconciliation_status not in ("RECONCILED", "MATCHED"):
        raise HTTPException(409, "Mutasi ini belum direkonsiliasi.")
    prev = txn.reconciliation_status
    txn.reconciliation_status = "UNRECONCILED"
    txn.matched_journal_line_id = None
    txn.matched_payment_id = None
    txn.matched_at = None
    txn.matched_by_id = None
    log_audit(db, user, "UNRECONCILE", "BankTransaction", entity_id=txn.id, obj=txn,
              previous_status=prev, new_status="UNRECONCILED", reason="Batalkan rekonsiliasi")
    db.commit()
    db.refresh(txn)
    return _txn_row(txn)


@router.post("/transactions/{txn_id}/ignore")
def ignore(txn_id: int, db: Session = Depends(get_db), user=Depends(require_roles(*WRITE_ROLES))):
    txn = _get_txn(db, txn_id)
    if txn.reconciliation_status == "RECONCILED":
        raise HTTPException(409, "Mutasi sudah RECONCILED. Unreconcile dulu sebelum mengabaikan.")
    prev = txn.reconciliation_status
    txn.reconciliation_status = "IGNORED"
    log_audit(db, user, "IGNORE", "BankTransaction", entity_id=txn.id, obj=txn,
              previous_status=prev, new_status="IGNORED", reason="Mutasi diabaikan (mis. biaya bank minor)")
    db.commit()
    db.refresh(txn)
    return _txn_row(txn)


# ── Ringkasan rekonsiliasi ───────────────────────────────────────────────────
@router.get("/accounts/{account_id}/reconciliation-summary")
def reconciliation_summary(account_id: int, db: Session = Depends(get_db),
                           user=Depends(get_current_user)):
    """Jumlah per status + selisih saldo bank (statement) vs saldo jurnal COA."""
    acct = _get_account(db, account_id)
    rows = db.query(BankTransaction).filter(BankTransaction.bank_account_id == account_id).all()
    counts = {s: 0 for s in RECON_STATUSES}
    stmt_balance = _dec(acct.opening_balance)
    for t in rows:
        counts[t.reconciliation_status] = counts.get(t.reconciliation_status, 0) + 1
        stmt_balance += _dec(t.debit) - _dec(t.credit)

    # Saldo menurut buku besar untuk akun COA yang ditaut (kalau ada).
    gl_balance = None
    gl_account = None
    if acct.gl_account_id is not None:
        coa = db.get(ChartOfAccount, acct.gl_account_id)
        if coa is not None:
            gl_account = {"id": coa.id, "code": coa.code, "name": coa.name}
            bal = svc.balances(db)
            gl_balance = _dec(bal.get(coa.code, {}).get("balance", 0))

    difference = None if gl_balance is None else stmt_balance - gl_balance
    return {
        "bank_account_id": acct.id, "code": acct.code,
        "opening_balance": _num(_dec(acct.opening_balance)),
        "statement_balance": _num(stmt_balance),
        "journal_balance": None if gl_balance is None else _num(gl_balance),
        "difference": None if difference is None else _num(difference),
        "reconciled": difference is not None and difference == 0,
        "gl_account": gl_account,
        "counts": counts,
        "total_transactions": len(rows),
    }


# ── Treasury ─────────────────────────────────────────────────────────────────
@router.get("/treasury")
def treasury(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Posisi kas & bank dari jurnal POSTED + daftar akun bank + saldo tertandingi.

    Sumber angka tunggal adalah buku besar (jurnal POSTED). BankAccount hanya
    memberi nama rekening dan saldo statement-nya untuk dibandingkan, bukan
    angka otoritatif — supaya treasury tidak pernah berbeda dari laporan keuangan.
    """
    cash_accounts = (db.query(ChartOfAccount)
                     .filter(ChartOfAccount.is_cash_account.is_(True))
                     .order_by(ChartOfAccount.code).all())
    bal = svc.balances(db)
    positions = []
    total = ZERO
    for coa in cash_accounts:
        row = bal.get(coa.code)
        amount = _dec(row["balance"]) if row else ZERO
        total += amount
        positions.append({
            "account_id": coa.id, "code": coa.code, "name": coa.name,
            "account_type": coa.account_type, "balance": _num(amount),
        })

    accounts = []
    for a in db.query(BankAccount).order_by(BankAccount.code).all():
        stmt = _dec(a.opening_balance)
        debit = db.query(func.coalesce(func.sum(BankTransaction.debit), 0)).filter(
            BankTransaction.bank_account_id == a.id).scalar()
        credit = db.query(func.coalesce(func.sum(BankTransaction.credit), 0)).filter(
            BankTransaction.bank_account_id == a.id).scalar()
        stmt += _dec(debit) - _dec(credit)
        gl_bal = None
        if a.gl_account_id is not None:
            coa = db.get(ChartOfAccount, a.gl_account_id)
            if coa is not None:
                gl_bal = _dec(bal.get(coa.code, {}).get("balance", 0))
        accounts.append({
            **_account_row(a),
            "statement_balance": _num(stmt),
            "journal_balance": None if gl_bal is None else _num(gl_bal),
            "difference": None if gl_bal is None else _num(stmt - gl_bal),
        })

    return {
        "as_of": date.today().isoformat(),
        "total_cash_and_bank": _num(total),
        "positions": positions,
        "bank_accounts": accounts,
        "rule": "Posisi kas/bank dihitung dari jurnal POSTED akun is_cash_account.",
    }
