"""Modul accounting double-entry BOS SYAMS.

Melengkapi batas V0.2: PRD §5 (Finance: chart of accounts, double-entry journal,
COGS, P&L, balance sheet, cash flow, fixed assets/depreciation, budgets) dan
PRD §7 ("Finance menggunakan jurnal berpasangan; laporan keuangan hanya
berdasarkan posting tervalidasi. Perubahan jurnal melalui reversal, bukan edit
diam-diam").

Prinsip yang ditegakkan di level model + router:
1. Setiap jurnal WAJIB balance (total debit == total kredit). Tidak balance = ditolak.
2. Jurnal yang sudah POSTED tidak bisa diedit. Koreksi lewat REVERSAL — jurnal
   pembalik baru yang menunjuk jurnal asal, dan jurnal asal ditandai REVERSED.
3. Laporan (trial balance, laba rugi, neraca, cash flow) HANYA menghitung jurnal
   berstatus POSTED. DRAFT tidak pernah masuk laporan.
4. Akun punya normal balance (DEBIT untuk aset/beban, KREDIT untuk liabilitas/
   ekuitas/pendapatan) sehingga arah saldo dihitung konsisten.
"""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Text, Boolean, Date, DateTime,
                        Numeric, ForeignKey, UniqueConstraint, Index)
from .database import Base


# ── Tipe akun & normal balance ───────────────────────────────────────────────
ACCOUNT_TYPES = ("ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE")
NORMAL_BALANCE = {
    "ASSET": "DEBIT",
    "EXPENSE": "DEBIT",
    "LIABILITY": "CREDIT",
    "EQUITY": "CREDIT",
    "REVENUE": "CREDIT",
}


class ChartOfAccount(Base):
    """Bagan akun (chart of accounts)."""
    __tablename__ = "chart_of_accounts"
    id = Column(Integer, primary_key=True)
    code = Column(String(24), unique=True, nullable=False, index=True)
    name = Column(String(180), nullable=False)
    account_type = Column(String(20), nullable=False, index=True)  # ASSET/LIABILITY/EQUITY/REVENUE/EXPENSE
    normal_balance = Column(String(8), nullable=False)             # DEBIT/CREDIT
    parent_id = Column(Integer, ForeignKey("chart_of_accounts.id"), nullable=True)
    # Untuk laporan arus kas: OPERATING / INVESTING / FINANCING (khusus akun kas/bank).
    cashflow_activity = Column(String(16), nullable=True)
    is_cash_account = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class JournalEntry(Base):
    """Satu jurnal (header). Baris debit/kredit ada di JournalLine."""
    __tablename__ = "journal_entries"
    id = Column(Integer, primary_key=True)
    entry_no = Column(String(40), unique=True, nullable=False, index=True)
    entry_date = Column(Date, nullable=False, index=True)
    description = Column(Text, nullable=True)
    # MANUAL untuk jurnal yang diinput manusia; AUTO untuk hasil posting sistem.
    entry_source = Column(String(16), nullable=False, default="MANUAL")
    # Jejak sumber (mis. 'INVOICE:INV-001') supaya auto-posting idempotent.
    source_ref = Column(String(120), nullable=True, index=True)
    status = Column(String(16), nullable=False, default="DRAFT", index=True)  # DRAFT/POSTED/REVERSED
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="SET NULL"), nullable=True)
    reversal_of_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    reversed_by_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    posted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class JournalLine(Base):
    """Baris jurnal: satu sisi debit/kredit pada satu akun."""
    __tablename__ = "journal_lines"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no = Column(Integer, nullable=False, default=1)
    account_id = Column(Integer, ForeignKey("chart_of_accounts.id"), nullable=False, index=True)
    debit = Column(Numeric(18, 2), nullable=False, default=0)
    credit = Column(Numeric(18, 2), nullable=False, default=0)
    description = Column(Text, nullable=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="SET NULL"), nullable=True)
    __table_args__ = (Index("ix_journal_lines_entry_account", "entry_id", "account_id"),)


class FixedAsset(Base):
    """Aset tetap + penyusutan garis lurus."""
    __tablename__ = "fixed_assets"
    id = Column(Integer, primary_key=True)
    asset_code = Column(String(40), unique=True, nullable=False, index=True)
    name = Column(String(180), nullable=False)
    category = Column(String(80), nullable=True)
    acquisition_date = Column(Date, nullable=False)
    acquisition_cost = Column(Numeric(18, 2), nullable=False)
    salvage_value = Column(Numeric(18, 2), nullable=False, default=0)
    useful_life_months = Column(Integer, nullable=False)
    depreciation_method = Column(String(24), nullable=False, default="STRAIGHT_LINE")
    accumulated_depreciation = Column(Numeric(18, 2), nullable=False, default=0)
    status = Column(String(16), nullable=False, default="ACTIVE", index=True)  # ACTIVE/DISPOSED
    disposed_date = Column(Date, nullable=True)
    disposal_proceeds = Column(Numeric(18, 2), nullable=True)
    asset_account_id = Column(Integer, ForeignKey("chart_of_accounts.id"), nullable=True)
    depreciation_expense_account_id = Column(Integer, ForeignKey("chart_of_accounts.id"), nullable=True)
    accumulated_account_id = Column(Integer, ForeignKey("chart_of_accounts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class DepreciationEntry(Base):
    """Penyusutan per periode (YYYY-MM). Satu periode hanya sekali per aset."""
    __tablename__ = "depreciation_entries"
    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("fixed_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(String(7), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    accumulated_after = Column(Numeric(18, 2), nullable=False)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("asset_id", "period", name="uq_depreciation_asset_period"),)


class Budget(Base):
    """Anggaran per akun per periode (tahun)."""
    __tablename__ = "budgets"
    id = Column(Integer, primary_key=True)
    period = Column(String(7), nullable=False, index=True)  # 'YYYY' atau 'YYYY-MM'
    account_id = Column(Integer, ForeignKey("chart_of_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False, default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("period", "account_id", name="uq_budget_period_account"),)
