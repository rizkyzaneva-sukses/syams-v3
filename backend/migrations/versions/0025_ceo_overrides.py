"""Migration 0025 — tabel `ceo_overrides` (revisi #74).

Latar: router `ceo_override.py` sudah menolak override dengan 503 selama tabel
ini belum ada — supaya override tidak pernah berjalan tanpa jejak audit dan
rollback. Migration ini menyediakan tabelnya sesuai spesifikasi
`REQUESTS/ceo_batch2.md` apa adanya.

Backfill: TIDAK ADA — registry mulai kosong. Mengarang baris override historis
justru berbahaya: itu akan terlihat seperti keputusan CEO yang benar-benar
pernah tercatat.

Revision ID: 0025_ceo_overrides
Revises: 0024_printing_persist
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_ceo_overrides"           # <= 32 karakter
down_revision = "0024_printing_persist"
branch_labels = None
depends_on = None


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table, name):
    if not _has_table(table):
        return False
    return name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _create_index(name, table, columns, unique=False):
    if not _has_table(table) or _has_index(table, name):
        return False
    op.create_index(name, table, columns, unique=unique)
    return True


def upgrade():
    if not _has_table("ceo_overrides"):
        op.create_table(
            "ceo_overrides",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("override_no", sa.String(length=40), nullable=True),
            sa.Column("override_type", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="REQUESTED"),
            sa.Column("source_module", sa.String(length=80), nullable=False),
            sa.Column("source_entity", sa.String(length=80), nullable=False),
            sa.Column("source_entity_id", sa.Integer(), nullable=True),
            sa.Column("affected_entity", sa.String(length=160), nullable=False),
            sa.Column("original_value", sa.Text(), nullable=False),
            sa.Column("proposed_value", sa.Text(), nullable=False),
            sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("impact", sa.Text(), nullable=False),
            sa.Column("evidence_ref", sa.Text(), nullable=True),
            sa.Column("scope", sa.String(length=300), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("ceo_decision", sa.String(length=24), nullable=True),
            sa.Column("ceo_decision_reason", sa.Text(), nullable=True),
            sa.Column("ceo_decided_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("ceo_decided_at", sa.DateTime(), nullable=True),
            sa.Column("acknowledged_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
            sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
            sa.Column("rollback_reason", sa.Text(), nullable=True),
            sa.Column("correction_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("override_no", name="uq_ceo_overrides_override_no"),
        )
        print("[0025] CREATE ceo_overrides")
    else:
        print("[0025] SKIP ceo_overrides: tabel sudah ada")

    for index_name, cols in (("ix_ceo_overrides_override_type", ["override_type"]),
                             ("ix_ceo_overrides_status", ["status"]),
                             ("ix_ceo_overrides_source_entity_id", ["source_entity_id"])):
        _create_index(index_name, "ceo_overrides", cols)


def downgrade():
    # Registry override berisi keputusan CEO: jangan pernah dihapus otomatis.
    print("[0025] downgrade tidak menghapus tabel: penurunan harus manual")
