"""Migration 0032 — ruang kerja CFO, gambar tersimpan, spesifikasi SPK, dan penghapusan role Finance Support.

* Tabel baru: stored_images, cash_entries, daily_workers, production_results.
* articles: design_image_id, size_chart_image_id, fabric_type, print_type, embroidery_type, material_color,
  packaging, label_note, zipper_note, finishing_note (isi form SPK Syams).
* customers: phone, shipping_carrier, address (BUYER INFORMATION di SPK).
* Role FINANCE_SUPPORT dihapus dari aplikasi: akun yang memakainya dipindah ke CFO_MANAGER. Nilai enum lama
  sengaja dibiarkan di database PostgreSQL (menghapus nilai enum tidak aman); aplikasi tidak lagi memakainya.

Backfill: akun Finance Support → CFO Manager (satu-satunya perubahan data).

Revision ID: 0032_cfo_workspace_docs
Revises: 0031_invoice_dp_amount
"""
from alembic import op
import sqlalchemy as sa


revision = "0032_cfo_workspace_docs"
down_revision = "0031_invoice_dp_amount"
branch_labels = None
depends_on = None

ARTICLE_COLUMNS = [
    ("design_image_id", sa.Integer()), ("size_chart_image_id", sa.Integer()),
    ("fabric_type", sa.String(120)), ("print_type", sa.String(120)), ("embroidery_type", sa.String(120)),
    ("material_color", sa.String(120)), ("packaging", sa.String(40)), ("label_note", sa.String(200)),
    ("zipper_note", sa.String(200)), ("finishing_note", sa.String(300)),
]
CUSTOMER_COLUMNS = [("phone", sa.String(40)), ("shipping_carrier", sa.String(120)), ("address", sa.Text())]


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _has_column(table, column):
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    tables = _tables()
    if "stored_images" not in tables:
        op.create_table("stored_images",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("filename", sa.String(200)),
            sa.Column("mime", sa.String(40), nullable=False),
            sa.Column("width", sa.Integer), sa.Column("height", sa.Integer),
            sa.Column("data", sa.LargeBinary, nullable=False),
            sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()))
        op.create_index("ix_stored_images_kind", "stored_images", ["kind"])
    if "cash_entries" not in tables:
        op.create_table("cash_entries",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("kind", sa.String(8), nullable=False),
            sa.Column("entry_date", sa.Date, nullable=False),
            sa.Column("direction", sa.String(4), nullable=False),
            sa.Column("category", sa.String(80)),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("cash_account_code", sa.String(24)),
            sa.Column("counter_account_code", sa.String(24)),
            sa.Column("journal_entry_id", sa.Integer, sa.ForeignKey("journal_entries.id")),
            sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()))
        op.create_index("ix_cash_entries_kind", "cash_entries", ["kind"])
        op.create_index("ix_cash_entries_entry_date", "cash_entries", ["entry_date"])
    if "daily_workers" not in tables:
        op.create_table("daily_workers",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("process", sa.String(40)),
            sa.Column("rate_per_pcs", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("notes", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("name", name="uq_daily_workers_name"))
    if "production_results" not in tables:
        op.create_table("production_results",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("result_date", sa.Date, nullable=False),
            sa.Column("worker_fk", sa.Integer, sa.ForeignKey("daily_workers.id"), nullable=False),
            sa.Column("order_fk", sa.Integer, sa.ForeignKey("orders.id", ondelete="SET NULL")),
            sa.Column("process", sa.String(40), nullable=False),
            sa.Column("qty", sa.Integer, nullable=False),
            sa.Column("rate", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("notes", sa.Text),
            sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()))
        op.create_index("ix_production_results_result_date", "production_results", ["result_date"])
        op.create_index("ix_production_results_worker_fk", "production_results", ["worker_fk"])
        op.create_index("ix_production_results_order_fk", "production_results", ["order_fk"])
        op.create_index("ix_production_results_worker_date", "production_results", ["worker_fk", "result_date"])
    for name, type_ in ARTICLE_COLUMNS:
        if not _has_column("articles", name):
            op.add_column("articles", sa.Column(name, type_))
    for name, type_ in CUSTOMER_COLUMNS:
        if not _has_column("customers", name):
            op.add_column("customers", sa.Column(name, type_))

    # Role Finance Support dihapus: pindahkan ke CFO Manager.
    bind = op.get_bind()
    for table, column in (("users", "role"), ("notifications", "role_target"), ("exceptions", "owner_role")):
        if table in _tables():
            bind.execute(sa.text(f"UPDATE {table} SET {column} = 'CFO_MANAGER' WHERE {column} = 'FINANCE_SUPPORT'"))


def downgrade():
    for name, _ in CUSTOMER_COLUMNS:
        op.drop_column("customers", name)
    for name, _ in ARTICLE_COLUMNS:
        op.drop_column("articles", name)
    for table in ("production_results", "daily_workers", "cash_entries", "stored_images"):
        op.drop_table(table)
