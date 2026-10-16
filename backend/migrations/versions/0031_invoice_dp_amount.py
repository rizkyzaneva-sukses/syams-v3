"""Migration 0031 — DP dalam Rupiah di invoice.

Menambahkan kolom invoices.dp_amount (Rp, default 0). Invoice lama tetap bernilai 0 —
DP lama tidak ditebak. Kebijakan bisnis lama yang menyimpan `minimum_dp_percent` tetap
terbaca: aplikasi menganggap DP minimum Rp 0 sampai CEO menetapkannya ulang dalam Rupiah.

Revision ID: 0031_invoice_dp_amount
Revises: 0030_control_system
"""
from alembic import op
import sqlalchemy as sa


revision = "0031_invoice_dp_amount"
down_revision = "0030_control_system"
branch_labels = None
depends_on = None


def _has_column(table, column):
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if not _has_column("invoices", "dp_amount"):
        op.add_column("invoices", sa.Column("dp_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("invoices", "dp_amount")
