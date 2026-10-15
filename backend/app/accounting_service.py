"""Service accounting — jurnal berpasangan + laporan keuangan.

Semua laporan di modul ini HANYA membaca jurnal berstatus POSTED. Tidak ada
laporan yang menyentuh DRAFT, supaya angka yang keluar ke CEO/CFO bisa
dipertanggungjawabkan (PRD §7).

Konvensi tanda untuk laporan:
- Saldo akun dihitung ke arah normal_balance-nya (aset/beban -> debit,
  liabilitas/ekuitas/pendapatan -> kredit), jadi saldo selalu positif dalam
  kondisi sehat.
- Laba Rugi: pendapatan (kredit) - beban (debit).
- Neraca: Aset = Liabilitas + Ekuitas + Laba Periode Berjalan (laba ditahan
  dihitung sebagai akumulasi laba tahun-tahun sebelumnya yang belum ditutup).
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from .accounting_models import (ChartOfAccount, JournalEntry, JournalLine,
                                FixedAsset, DepreciationEntry, Budget, NORMAL_BALANCE)
from . import models

ZERO = Decimal("0.00")


def _dec(value):
    return Decimal(value or 0)


def next_entry_no(db: Session) -> str:
    year = date.today().year
    prefix = f"JE-{year}-"
    last = (db.query(JournalEntry.entry_no)
            .filter(JournalEntry.entry_no.like(prefix + "%"))
            .order_by(JournalEntry.entry_no.desc()).first())
    seq = int(last[0].split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:05d}"


def account_map(db: Session) -> dict:
    return {a.code: a for a in db.query(ChartOfAccount).all()}


def normalize_balance(account: ChartOfAccount, debit: Decimal, credit: Decimal) -> Decimal:
    """Saldo bertanda positif mengikuti arah normal akun."""
    if account.normal_balance == "DEBIT":
        return debit - credit
    return credit - debit


def validate_lines(db: Session, lines) -> list:
    """Validasi baris jurnal. Mengembalikan daftar error (kosong = valid)."""
    errors = []
    if len(lines) < 2:
        errors.append("Jurnal minimal harus punya 2 baris (debit & kredit).")
    total_debit = ZERO
    total_credit = ZERO
    codes = []
    for i, line in enumerate(lines, 1):
        debit = _dec(line.get("debit"))
        credit = _dec(line.get("credit"))
        code = line.get("account_code")
        codes.append(code)
        if debit < 0 or credit < 0:
            errors.append(f"Baris {i}: nilai debit/kredit tidak boleh negatif.")
        if debit > 0 and credit > 0:
            errors.append(f"Baris {i}: satu baris hanya boleh debit ATAU kredit.")
        if debit == 0 and credit == 0:
            errors.append(f"Baris {i}: nilai debit/kredit tidak boleh nol keduanya.")
        total_debit += debit
        total_credit += credit
    if total_debit != total_credit:
        errors.append(f"Jurnal tidak balance: debit {total_debit} != kredit {total_credit}.")
    found = {a.code for a in db.query(ChartOfAccount).filter(ChartOfAccount.code.in_([c for c in codes if c])).all()}
    for code in codes:
        if code and code not in found:
            errors.append(f"Akun '{code}' tidak ditemukan di chart of accounts.")
    return errors


def add_lines(db: Session, entry: JournalEntry, lines) -> None:
    for i, line in enumerate(lines, 1):
        db.add(JournalLine(
            entry_id=entry.id, line_no=i, account_id=line["_account_id"],
            debit=_dec(line.get("debit")), credit=_dec(line.get("credit")),
            description=line.get("description"),
            order_fk=line.get("order_fk"), article_id=line.get("article_id"),
        ))


def resolve_account_ids(db: Session, lines) -> None:
    """Tempelkan _account_id ke setiap baris dari account_code."""
    amap = account_map(db)
    for line in lines:
        acct = amap.get(line.get("account_code"))
        if acct is not None:
            line["_account_id"] = acct.id


def balances(db: Session, as_of: date | None = None, account_type: str | None = None) -> dict:
    """Saldo per akun (positif mengikuti normal balance) dari jurnal POSTED."""
    q = (db.query(ChartOfAccount.id, ChartOfAccount.code, ChartOfAccount.name,
                  ChartOfAccount.account_type, ChartOfAccount.normal_balance,
                  func.coalesce(func.sum(JournalLine.debit), 0),
                  func.coalesce(func.sum(JournalLine.credit), 0))
         .join(JournalLine, JournalLine.account_id == ChartOfAccount.id)
         .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
         .filter(JournalEntry.status == "POSTED"))
    if as_of:
        q = q.filter(JournalEntry.entry_date <= as_of)
    if account_type:
        q = q.filter(ChartOfAccount.account_type == account_type)
    q = q.group_by(ChartOfAccount.id, ChartOfAccount.code, ChartOfAccount.name,
                   ChartOfAccount.account_type, ChartOfAccount.normal_balance)
    out = {}
    for aid, code, name, atype, normal, debit, credit in q.all():
        debit, credit = _dec(debit), _dec(credit)
        out[code] = {
            "account_id": aid, "code": code, "name": name, "account_type": atype,
            "normal_balance": normal, "debit": debit, "credit": credit,
            "balance": (debit - credit) if normal == "DEBIT" else (credit - debit),
        }
    return out


def trial_balance(db: Session, as_of: date | None = None) -> dict:
    rows = list(balances(db, as_of).values())
    rows.sort(key=lambda r: r["code"])
    total_debit = sum((r["debit"] for r in rows), ZERO)
    total_credit = sum((r["credit"] for r in rows), ZERO)
    return {
        "as_of": (as_of or date.today()).isoformat(),
        "rows": [{"code": r["code"], "name": r["name"], "account_type": r["account_type"],
                  "debit": float(r["debit"]), "credit": float(r["credit"]),
                  "balance": float(r["balance"])} for r in rows],
        "total_debit": float(total_debit), "total_credit": float(total_credit),
        "balanced": total_debit == total_credit,
    }


def _sum_type(bal, atype, credit_side=False):
    total = ZERO
    for r in bal.values():
        if r["account_type"] != atype:
            continue
        # balance sudah bertanda normal; untuk laba rugi kita pakai arah pendapatan.
        total += r["balance"]
    return total


def income_statement(db: Session, date_from: date, date_to: date) -> dict:
    bal = balances(db, as_of=date_to)
    # Ambil saldo periode: hitung ulang hanya rentang tanggal.
    q = (db.query(ChartOfAccount.code, ChartOfAccount.name, ChartOfAccount.account_type,
                  func.coalesce(func.sum(JournalLine.debit), 0), func.coalesce(func.sum(JournalLine.credit), 0))
         .join(JournalLine, JournalLine.account_id == ChartOfAccount.id)
         .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
         .filter(JournalEntry.status == "POSTED", JournalEntry.entry_date >= date_from,
                 JournalEntry.entry_date <= date_to, ChartOfAccount.account_type.in_(["REVENUE", "EXPENSE"]))
         .group_by(ChartOfAccount.code, ChartOfAccount.name, ChartOfAccount.account_type))
    revenue, expense = [], []
    total_rev, total_exp = ZERO, ZERO
    for code, name, atype, debit, credit in q.all():
        debit, credit = _dec(debit), _dec(credit)
        if atype == "REVENUE":
            amt = credit - debit
            total_rev += amt
            revenue.append({"code": code, "name": name, "amount": float(amt)})
        else:
            amt = debit - credit
            total_exp += amt
            expense.append({"code": code, "name": name, "amount": float(amt)})
    return {
        "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
        "revenue": sorted(revenue, key=lambda r: r["code"]),
        "expense": sorted(expense, key=lambda r: r["code"]),
        "total_revenue": float(total_rev), "total_expense": float(total_exp),
        "net_income": float(total_rev - total_exp),
    }


def balance_sheet(db: Session, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    bal = balances(db, as_of=as_of)
    def rows_for(atype):
        return sorted([{"code": r["code"], "name": r["name"], "balance": float(r["balance"])}
                       for r in bal.values() if r["account_type"] == atype], key=lambda r: r["code"])
    assets = rows_for("ASSET")
    liabilities = rows_for("LIABILITY")
    equity = rows_for("EQUITY")
    # Total per seksi dihitung dari (debit - kredit) mentah, BUKAN dari saldo
    # bertanda. Dengan begitu akun contra (mis. Akumulasi Penyusutan, normal
    # KREDIT di dalam seksi ASET) otomatis MENGURANGI total aset — persis
    # perilaku neraca yang benar.
    def net(atype):
        return sum(((r["debit"] - r["credit"]) for r in bal.values() if r["account_type"] == atype), ZERO)
    total_assets = net("ASSET")
    total_liab = -net("LIABILITY")       # liabilitas normal kredit -> dibalik jadi positif
    total_equity = -net("EQUITY")
    rev = -net("REVENUE")                 # pendapatan normal kredit -> positif
    exp = net("EXPENSE")
    net_income = rev - exp
    total_equity_adj = total_equity + net_income
    return {
        "as_of": as_of.isoformat(),
        "assets": assets, "liabilities": liabilities, "equity": equity,
        "total_assets": float(total_assets), "total_liabilities": float(total_liab),
        "total_equity": float(total_equity_adj),
        "current_earnings": float(net_income),
        "total_liabilities_equity": float(total_liab + total_equity_adj),
        "balanced": total_assets == (total_liab + total_equity_adj),
    }


def cash_flow(db: Session, date_from: date, date_to: date) -> dict:
    """Arus kas metode langsung dari mutasi akun kas/bank."""
    cash_ids = [a.id for a in db.query(ChartOfAccount).filter(ChartOfAccount.is_cash_account.is_(True)).all()]
    buckets = {"OPERATING": ZERO, "INVESTING": ZERO, "FINANCING": ZERO, "UNCLASSIFIED": ZERO}
    if cash_ids:
        q = (db.query(ChartOfAccount.cashflow_activity,
                      func.coalesce(func.sum(JournalLine.debit), 0),
                      func.coalesce(func.sum(JournalLine.credit), 0))
             .join(JournalLine, JournalLine.account_id == ChartOfAccount.id)
             .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
             .filter(JournalEntry.status == "POSTED", ChartOfAccount.id.in_(cash_ids),
                     JournalEntry.entry_date >= date_from, JournalEntry.entry_date <= date_to)
             .group_by(ChartOfAccount.cashflow_activity))
        for activity, debit, credit in q.all():
            key = activity or "UNCLASSIFIED"
            buckets[key] = buckets.get(key, ZERO) + (_dec(debit) - _dec(credit))
    net_change = sum(buckets.values(), ZERO)
    return {
        "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
        "operating": float(buckets["OPERATING"]), "investing": float(buckets["INVESTING"]),
        "financing": float(buckets["FINANCING"]),
        "unclassified": float(buckets.get("UNCLASSIFIED", ZERO)),
        "net_change": float(net_change),
    }


def general_ledger(db: Session, account_id: int, date_from: date | None = None, date_to: date | None = None) -> dict:
    acct = db.get(ChartOfAccount, account_id)
    if acct is None:
        return {}
    q = (db.query(JournalEntry.entry_date, JournalEntry.entry_no, JournalEntry.description,
                  JournalLine.debit, JournalLine.credit, JournalLine.description, JournalLine.id)
         .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
         .filter(JournalEntry.status == "POSTED", JournalLine.account_id == account_id))
    if date_from:
        q = q.filter(JournalEntry.entry_date >= date_from)
    if date_to:
        q = q.filter(JournalEntry.entry_date <= date_to)
    q = q.order_by(JournalEntry.entry_date, JournalLine.id)
    rows, running = [], ZERO
    for edate, eno, edesc, debit, credit, ldesc, _lid in q.all():
        debit, credit = _dec(debit), _dec(credit)
        running += (debit - credit) if acct.normal_balance == "DEBIT" else (credit - debit)
        rows.append({"date": edate.isoformat(), "entry_no": eno,
                     "description": ldesc or edesc, "debit": float(debit), "credit": float(credit),
                     "running_balance": float(running)})
    return {"account": {"id": acct.id, "code": acct.code, "name": acct.name,
                        "account_type": acct.account_type, "normal_balance": acct.normal_balance},
            "rows": rows, "closing_balance": float(running)}


def monthly_depreciation(asset: FixedAsset) -> Decimal:
    depreciable = _dec(asset.acquisition_cost) - _dec(asset.salvage_value)
    if asset.useful_life_months <= 0:
        return ZERO
    return (depreciable / Decimal(asset.useful_life_months)).quantize(Decimal("0.01"))
