"""Seed chart of accounts standar perusahaan manufaktur garmen BOS SYAMS.

Idempotent: aman dijalankan berulang. Kalau akun dengan kode yang sama sudah ada,
tidak ditimpa (kecuali nama/normal balance berbeda — itu akan dilewati agar tidak
merusak jurnal yang sudah ada).
"""
from decimal import Decimal

from sqlalchemy.orm import Session

from .accounting_models import ChartOfAccount, NORMAL_BALANCE

# (code, name, type, cashflow_activity, is_cash)
STANDARD_COA = [
    # ── ASET ──────────────────────────────────────────────────────────────
    ("1-1000", "Kas", "ASSET", "OPERATING", True),
    ("1-1100", "Bank", "ASSET", "OPERATING", True),
    ("1-1200", "Piutang Usaha (AR)", "ASSET", None, False),
    ("1-1300", "Piutang Lain-lain", "ASSET", None, False),
    ("1-1400", "Persediaan Bahan Baku", "ASSET", None, False),
    ("1-1500", "Persediaan Barang Dalam Proses (WIP)", "ASSET", None, False),
    ("1-1600", "Persediaan Barang Jadi", "ASSET", None, False),
    ("1-1700", "Pajak Dibayar Dimuka (PPN Masukan)", "ASSET", None, False),
    ("1-1800", "Aset Tetap — Peralatan", "ASSET", "INVESTING", False),
    ("1-1850", "Aset Tetap — Mesin", "ASSET", "INVESTING", False),
    ("1-1860", "Aset Tetap — Kendaraan", "ASSET", "INVESTING", False),
    ("1-1890", "Akumulasi Penyusutan Aset Tetap", "ASSET", None, False),  # contra-asset (saldo kredit)
    # ── LIABILITAS ────────────────────────────────────────────────────────
    ("2-1000", "Utang Usaha (AP)", "LIABILITY", None, False),
    ("2-1100", "Utang Gaji (Payroll)", "LIABILITY", None, False),
    ("2-1200", "Utang Pajak (PPN/PPh Keluaran)", "LIABILITY", None, False),
    ("2-1300", "Pendapatan Diterima Dimuka (DP)", "LIABILITY", None, False),
    ("2-1400", "Utang Bank / Pinjaman", "LIABILITY", "FINANCING", False),
    # ── EKUITAS ───────────────────────────────────────────────────────────
    ("3-1000", "Modal Disetor", "EQUITY", "FINANCING", False),
    ("3-2000", "Laba Ditahan", "EQUITY", None, False),
    ("3-3000", "Ikhtisar Laba Rugi", "EQUITY", None, False),
    # ── PENDAPATAN ────────────────────────────────────────────────────────
    ("4-1000", "Pendapatan Penjualan", "REVENUE", None, False),
    ("4-2000", "Pendapatan Jasa Makloon", "REVENUE", None, False),
    ("4-9000", "Potongan Penjualan", "REVENUE", None, False),  # contra-revenue
    # ── BEBAN ─────────────────────────────────────────────────────────────
    ("5-1000", "Harga Pokok Penjualan (HPP)", "EXPENSE", None, False),
    ("5-2000", "Beban Gaji Produksi Langsung", "EXPENSE", None, False),
    ("5-3000", "Beban Overhead Pabrik", "EXPENSE", None, False),
    ("6-1000", "Beban Gaji & Tunjangan (Non-Produksi)", "EXPENSE", None, False),
    ("6-2000", "Beban Sewa", "EXPENSE", None, False),
    ("6-3000", "Beban Listrik, Air & Telepon", "EXPENSE", None, False),
    ("6-4000", "Beban Pemasaran & Penjualan", "EXPENSE", None, False),
    ("6-5000", "Beban Administrasi & Umum", "EXPENSE", None, False),
    ("6-6000", "Beban Penyusutan", "EXPENSE", None, False),
    ("6-7000", "Beban Bunga & Administrasi Bank", "EXPENSE", None, False),
    ("6-8000", "Beban Lain-lain", "EXPENSE", None, False),
]


def seed_chart_of_accounts(db: Session) -> int:
    created = 0
    for code, name, atype, cashflow, is_cash in STANDARD_COA:
        if db.query(ChartOfAccount).filter_by(code=code).first():
            continue
        db.add(ChartOfAccount(code=code, name=name, account_type=atype,
                              normal_balance=NORMAL_BALANCE[atype],
                              cashflow_activity=cashflow, is_cash_account=is_cash))
        created += 1
    if created:
        db.commit()
    return created
