"""Migration 0027 — tabel `printing_makloon_jobs` (revisi #46).

Latar: jejak makloon/embroidery saat ini hanya DIPETAKAN dari
`production_movements.pic_name` (PIC di luar Printing/Iman). Itu heuristik:
qty kirim/kembali/diterima/ditolak, tanggal kirim/kembali, status inspeksi, dan
outstanding external WIP tidak punya tempat penyimpanan. Tabel ini
menyediakannya sesuai `REQUESTS/printing_ops.md`.

Backfill: TIDAK ADA — belum ada pekerjaan makloon yang tercatat sebagai entitas
terpisah. Mengarang baris dari `pic_name` akan terlihat seperti catatan qty yang
benar-benar pernah diisi, padahal tidak.

Revision ID: 0027_printing_makloon
Revises: 0026_quotation_updated
"""
from alembic import op
import sqlalchemy as sa


revision = "0027_printing_makloon"        # <= 32 karakter
down_revision = "0026_quotation_updated"
branch_labels = None
depends_on = None


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table, name):
    if not _has_table(table):
        return False
    return name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _create_index(name, table, columns):
    if not _has_table(table) or _has_index(table, name):
        return False
    op.create_index(name, table, columns)
    return True


def upgrade():
    if not _has_table("printing_makloon_jobs"):
        op.create_table(
            "printing_makloon_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("order_fk", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True),
            sa.Column("job_id", sa.String(length=120), nullable=False),
            sa.Column("process", sa.String(length=80), nullable=False, server_default="BORDIR"),
            sa.Column("vendor_id", sa.Integer(), nullable=True),
            sa.Column("vendor_name", sa.String(length=160), nullable=True),
            sa.Column("vendor_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("qty_sent", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("qty_returned", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("qty_accepted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("qty_rejected", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sent_date", sa.Date(), nullable=True),
            sa.Column("return_date", sa.Date(), nullable=True),
            sa.Column("inspection_status", sa.String(length=32), nullable=True),
            sa.Column("evidence_ref", sa.Text(), nullable=True),
            sa.Column("handoff_stage", sa.String(length=80), nullable=True),
            sa.Column("outstanding_external_wip", sa.Integer(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        print("[0027] CREATE printing_makloon_jobs")
    else:
        print("[0027] SKIP printing_makloon_jobs: tabel sudah ada")

    for index_name, cols in (("ix_printing_makloon_jobs_order_fk", ["order_fk"]),
                             ("ix_printing_makloon_jobs_job_id", ["job_id"]),
                             ("ix_printing_makloon_jobs_vendor_id", ["vendor_id"])):
        _create_index(index_name, "printing_makloon_jobs", cols)


def downgrade():
    # Catatan qty kirim/kembali ke vendor: jangan dihapus otomatis.
    print("[0027] downgrade tidak menghapus tabel: penurunan harus manual")
