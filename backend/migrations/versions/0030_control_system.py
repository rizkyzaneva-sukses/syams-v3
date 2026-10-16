"""Migration 0030 — Control System sesuai sheet lama.

Menambahkan tabel: garment_types, pic_masters, stage_sla_versions, stage_sla_items,
order_stages, order_blocks, order_sequences; dan kolom articles.extra_size / mockup_url.

Backfill: TIDAK ADA di migrasi. Master data awal (SLA versi 1, jenis pakaian, PIC)
diisi `control_service.ensure_control_defaults` saat aplikasi start — nilainya diambil
dari sheet lama dan idempotent. Order lama tidak diberi nomor ulang; Order ID baru
SYM-YYMM-NNN hanya berlaku untuk order yang dibuat setelah migrasi ini.

Revision ID: 0030_control_system
Revises: 0029_modules
"""
from alembic import op
import sqlalchemy as sa


revision = "0030_control_system"
down_revision = "0029_modules"
branch_labels = None
depends_on = None


def _has(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table, column):
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if not _has("garment_types"):
        op.create_table("garment_types",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("name", name="uq_garment_types_name"))
    if not _has("pic_masters"):
        op.create_table("pic_masters",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("role_label", sa.String(120)),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("name", name="uq_pic_masters_name"))
    if not _has("stage_sla_versions"):
        op.create_table("stage_sla_versions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("change_reason", sa.Text, nullable=False),
            sa.Column("changed_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("version", name="uq_stage_sla_versions_version"))
    if not _has("stage_sla_items"):
        op.create_table("stage_sla_items",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("version_fk", sa.Integer, sa.ForeignKey("stage_sla_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("stage_code", sa.String(24), nullable=False),
            sa.Column("sort_order", sa.Integer, nullable=False),
            sa.Column("duration_days", sa.Integer, nullable=False),
            sa.Column("primary_pic", sa.String(80)),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("daily_capacity", sa.Integer, nullable=False, server_default="0"),
            sa.Column("capacity_unit", sa.String(16), nullable=False, server_default="PCS"),
            sa.Column("warning_pct", sa.Float, nullable=False, server_default="0.8"),
            sa.Column("note", sa.String(200)),
            sa.UniqueConstraint("version_fk", "stage_code", name="uq_sla_item_stage"))
        op.create_index("ix_stage_sla_items_version_fk", "stage_sla_items", ["version_fk"])
    if not _has("order_stages"):
        op.create_table("order_stages",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("order_fk", sa.Integer, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("stage_code", sa.String(24), nullable=False),
            sa.Column("state", sa.String(12), nullable=False),
            sa.Column("done_at", sa.DateTime),
            sa.Column("done_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("pic_name", sa.String(80)),
            sa.Column("note", sa.Text),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("order_fk", "stage_code", name="uq_order_stage"))
        op.create_index("ix_order_stages_order_fk", "order_stages", ["order_fk"])
    if not _has("order_blocks"):
        op.create_table("order_blocks",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("order_fk", sa.Integer, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("stage_code", sa.String(24)),
            sa.Column("problem", sa.Text, nullable=False),
            sa.Column("next_action", sa.Text, nullable=False),
            sa.Column("pic_name", sa.String(80)),
            sa.Column("opened_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("opened_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("resolved_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("resolved_at", sa.DateTime),
            sa.Column("resolution_note", sa.Text))
        op.create_index("ix_order_blocks_order_fk", "order_blocks", ["order_fk"])
    if not _has("order_sequences"):
        op.create_table("order_sequences",
            sa.Column("period", sa.String(4), primary_key=True),
            sa.Column("last_no", sa.Integer, nullable=False, server_default="0"))
    if not _has_column("articles", "extra_size"):
        op.add_column("articles", sa.Column("extra_size", sa.String(120)))
    if not _has_column("articles", "mockup_url"):
        op.add_column("articles", sa.Column("mockup_url", sa.Text))


def downgrade():
    op.drop_column("articles", "mockup_url")
    op.drop_column("articles", "extra_size")
    for table in ("order_sequences", "order_blocks", "order_stages", "stage_sla_items",
                  "stage_sla_versions", "pic_masters", "garment_types"):
        op.drop_table(table)
