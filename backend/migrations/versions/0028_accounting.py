"""Migration 0028 — modul accounting double-entry (PRD §5 & §7).

Menambahkan tabel: chart_of_accounts, journal_entries, journal_lines, fixed_assets,
depreciation_entries, budgets.

Backfill: TIDAK ADA. COA diisi lewat endpoint `POST /accounting/seed-coa`
(idempotent) atau `app/accounting_seed.py`, bukan dikarang di migrasi — supaya
perusahaan bisa memilih bagan akunnya sendiri tanpa harus menghapus baris migrasi.

Revision ID: 0028_accounting
Revises: 0027_printing_makloon
"""
from alembic import op
import sqlalchemy as sa


revision = "0028_accounting"
down_revision = "0027_printing_makloon"
branch_labels = None
depends_on = None


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _has_table("chart_of_accounts"):
        op.create_table(
            "chart_of_accounts",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("code", sa.String(24), nullable=False),
            sa.Column("name", sa.String(180), nullable=False),
            sa.Column("account_type", sa.String(20), nullable=False),
            sa.Column("normal_balance", sa.String(8), nullable=False),
            sa.Column("parent_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id"), nullable=True),
            sa.Column("cashflow_activity", sa.String(16), nullable=True),
            sa.Column("is_cash_account", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("code", name="uq_coa_code"),
        )
        op.create_index("ix_coa_code", "chart_of_accounts", ["code"])
        op.create_index("ix_coa_type", "chart_of_accounts", ["account_type"])

    if not _has_table("journal_entries"):
        op.create_table(
            "journal_entries",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("entry_no", sa.String(40), nullable=False),
            sa.Column("entry_date", sa.Date, nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("entry_source", sa.String(16), nullable=False, server_default="MANUAL"),
            sa.Column("source_ref", sa.String(120), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
            sa.Column("order_fk", sa.Integer, sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reversal_of_id", sa.Integer, sa.ForeignKey("journal_entries.id"), nullable=True),
            sa.Column("reversed_by_id", sa.Integer, sa.ForeignKey("journal_entries.id"), nullable=True),
            sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("posted_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("posted_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("entry_no", name="uq_journal_entry_no"),
        )
        op.create_index("ix_je_no", "journal_entries", ["entry_no"])
        op.create_index("ix_je_date", "journal_entries", ["entry_date"])
        op.create_index("ix_je_status", "journal_entries", ["status"])
        op.create_index("ix_je_source_ref", "journal_entries", ["source_ref"])
        op.create_index("ix_je_order", "journal_entries", ["order_fk"])

    if not _has_table("journal_lines"):
        op.create_table(
            "journal_lines",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("entry_id", sa.Integer, sa.ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False),
            sa.Column("line_no", sa.Integer, nullable=False, server_default="1"),
            sa.Column("account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id"), nullable=False),
            sa.Column("debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("order_fk", sa.Integer, sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_jl_entry", "journal_lines", ["entry_id"])
        op.create_index("ix_jl_account", "journal_lines", ["account_id"])
        op.create_index("ix_journal_lines_entry_account", "journal_lines", ["entry_id", "account_id"])

    if not _has_table("fixed_assets"):
        op.create_table(
            "fixed_assets",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("asset_code", sa.String(40), nullable=False),
            sa.Column("name", sa.String(180), nullable=False),
            sa.Column("category", sa.String(80), nullable=True),
            sa.Column("acquisition_date", sa.Date, nullable=False),
            sa.Column("acquisition_cost", sa.Numeric(18, 2), nullable=False),
            sa.Column("salvage_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("useful_life_months", sa.Integer, nullable=False),
            sa.Column("depreciation_method", sa.String(24), nullable=False, server_default="STRAIGHT_LINE"),
            sa.Column("accumulated_depreciation", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("disposed_date", sa.Date, nullable=True),
            sa.Column("disposal_proceeds", sa.Numeric(18, 2), nullable=True),
            sa.Column("asset_account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id"), nullable=True),
            sa.Column("depreciation_expense_account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id"), nullable=True),
            sa.Column("accumulated_account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id"), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("asset_code", name="uq_fixed_asset_code"),
        )
        op.create_index("ix_fa_code", "fixed_assets", ["asset_code"])
        op.create_index("ix_fa_status", "fixed_assets", ["status"])

    if not _has_table("depreciation_entries"):
        op.create_table(
            "depreciation_entries",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("asset_id", sa.Integer, sa.ForeignKey("fixed_assets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("period", sa.String(7), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("accumulated_after", sa.Numeric(18, 2), nullable=False),
            sa.Column("journal_entry_id", sa.Integer, sa.ForeignKey("journal_entries.id"), nullable=True),
            sa.Column("posted_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("asset_id", "period", name="uq_depreciation_asset_period"),
        )
        op.create_index("ix_dep_asset", "depreciation_entries", ["asset_id"])
        op.create_index("ix_dep_period", "depreciation_entries", ["period"])

    if not _has_table("budgets"):
        op.create_table(
            "budgets",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("period", sa.String(7), nullable=False),
            sa.Column("account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("period", "account_id", name="uq_budget_period_account"),
        )
        op.create_index("ix_budget_period", "budgets", ["period"])
        op.create_index("ix_budget_account", "budgets", ["account_id"])


def downgrade():
    for table in ("budgets", "depreciation_entries", "journal_lines", "journal_entries",
                  "fixed_assets", "chart_of_accounts"):
        if _has_table(table):
            op.drop_table(table)
