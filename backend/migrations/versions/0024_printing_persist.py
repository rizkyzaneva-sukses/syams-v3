"""Migration 0024 — tabel printing persistensi (revisi #44, #45, #47).

Latar: router `printing_ops.py` sudah memakai `printing_daily_targets`,
`printing_handoffs`, dan `printing_defect_dispositions` sejak lama, tetapi
model & tabelnya belum pernah dibuat (hanya `printing_evidence` yang ada).
Akibatnya endpoint tulis mengembalikan 503 "schema belum siap" dan target
harian / partial handoff / disposition defect tidak bisa dipersist.

Spesifikasi mengikuti `REQUESTS/printing_schema.md` apa adanya — termasuk
larangan membuat index unique pada (target_date, process): target per
order/article boleh beberapa baris di tanggal+proses yang sama.

Backfill: TIDAK ADA. Endpoint tetap fallback ke `production_movements` selama
tabel kosong, jadi tidak ada data lama yang perlu dipindahkan atau dikarang.

Revision ID: 0024_printing_persist
Revises: 0023_batch2_schema
"""
from alembic import op
import sqlalchemy as sa


revision = "0024_printing_persist"        # <= 32 karakter
down_revision = "0023_batch2_schema"
branch_labels = None
depends_on = None


def _has_table(name):
    inspector = sa.inspect(op.get_bind())
    return name in inspector.get_table_names()


def _has_column(table, column):
    if not _has_table(table):
        return False
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table, name):
    if not _has_table(table):
        return False
    return name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _create_index(name, table, columns, unique=False):
    """Buat index hanya kalau belum ada (idempoten)."""
    if not _has_table(table) or _has_index(table, name):
        return False
    op.create_index(name, table, columns, unique=unique)
    return True


def upgrade():
    # ── 1. printing_daily_targets (revisi #47) ────────────────────────────
    if not _has_table("printing_daily_targets"):
        op.create_table(
            "printing_daily_targets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("process", sa.String(length=80), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column("target_qty", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(length=20), nullable=True, server_default="PCS"),
            sa.Column("order_fk", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True),
            sa.Column("set_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("set_at", sa.DateTime(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("previous_qty", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        print("[0024] CREATE printing_daily_targets")
    else:
        print("[0024] SKIP printing_daily_targets: tabel sudah ada")
    _create_index("ix_printing_daily_targets_target_date", "printing_daily_targets", ["target_date"])
    _create_index("ix_printing_daily_targets_process_date", "printing_daily_targets",
                  ["process", "target_date"])
    _create_index("ix_printing_daily_targets_set_by_id", "printing_daily_targets", ["set_by_id"])

    # ── 2. printing_handoffs (revisi #44) ─────────────────────────────────
    if not _has_table("printing_handoffs"):
        op.create_table(
            "printing_handoffs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("handoff_no", sa.String(length=80), nullable=False),
            sa.Column("job_id", sa.String(length=120), nullable=False),
            sa.Column("movement_id", sa.Integer(), sa.ForeignKey("production_movements.id", ondelete="SET NULL"), nullable=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True),
            sa.Column("order_fk", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("process", sa.String(length=80), nullable=False),
            sa.Column("stage", sa.String(length=80), nullable=True),
            sa.Column("next_stage", sa.String(length=80), nullable=False),
            sa.Column("lot_no", sa.String(length=80), nullable=True),
            sa.Column("batch_no", sa.String(length=120), nullable=True),
            sa.Column("qty_sent", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("qty_received", sa.Integer(), nullable=True),
            sa.Column("remaining", sa.Integer(), nullable=True),
            sa.Column("exception", sa.String(length=255), nullable=True),
            sa.Column("shift", sa.String(length=64), nullable=True),
            sa.Column("location", sa.String(length=120), nullable=True),
            sa.Column("evidence_ref", sa.Text(), nullable=True),
            sa.Column("sender", sa.String(length=120), nullable=True),
            sa.Column("receiver", sa.String(length=120), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="SENT"),
            sa.Column("exception_id", sa.Integer(), sa.ForeignKey("exceptions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("handoff_no", name="uq_printing_handoffs_handoff_no"),
        )
        print("[0024] CREATE printing_handoffs")
    else:
        print("[0024] SKIP printing_handoffs: tabel sudah ada")
    for index_name, cols in (("ix_printing_handoffs_handoff_no", ["handoff_no"]),
                             ("ix_printing_handoffs_job_id", ["job_id"]),
                             ("ix_printing_handoffs_movement_id", ["movement_id"]),
                             ("ix_printing_handoffs_article_id", ["article_id"]),
                             ("ix_printing_handoffs_order_fk", ["order_fk"]),
                             ("ix_printing_handoffs_status", ["status"])):
        _create_index(index_name, "printing_handoffs", cols)

    # ── 3. printing_defect_dispositions (revisi #45) ──────────────────────
    if not _has_table("printing_defect_dispositions"):
        op.create_table(
            "printing_defect_dispositions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("qc_id", sa.Integer(), sa.ForeignKey("qc_records.id", ondelete="SET NULL"), nullable=True),
            sa.Column("job_id", sa.String(length=120), nullable=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="SET NULL"), nullable=True),
            sa.Column("process", sa.String(length=80), nullable=True),
            sa.Column("defect_category", sa.String(length=80), nullable=False),
            sa.Column("defect_detail", sa.Text(), nullable=True),
            sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("origin", sa.String(length=32), nullable=True),
            sa.Column("severity", sa.String(length=20), nullable=False, server_default="MINOR"),
            sa.Column("disposition", sa.String(length=40), nullable=False),
            sa.Column("rework_owner", sa.String(length=120), nullable=True),
            sa.Column("rework_due", sa.Date(), nullable=True),
            sa.Column("rework_qc_id", sa.Integer(), sa.ForeignKey("qc_records.id", ondelete="SET NULL"), nullable=True),
            sa.Column("retest", sa.String(length=32), nullable=True),
            sa.Column("evidence_ref", sa.Text(), nullable=True),
            sa.Column("resolution_evidence_ref", sa.Text(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        print("[0024] CREATE printing_defect_dispositions")
    else:
        print("[0024] SKIP printing_defect_dispositions: tabel sudah ada")
    for index_name, cols in (("ix_printing_defect_dispositions_qc_id", ["qc_id"]),
                             ("ix_printing_defect_dispositions_job_id", ["job_id"]),
                             ("ix_printing_defect_dispositions_article_id", ["article_id"]),
                             ("ix_printing_defect_dispositions_disposition", ["disposition"])):
        _create_index(index_name, "printing_defect_dispositions", cols)

    # ── 4. kolom tambahan printing_evidence (revisi #41/#45) ──────────────
    # Kolom diisi null tanpa backfill: null berarti "belum diikat", bukan data
    # historis yang salah.
    #
    # `handoff_id`/`disposition_id` sengaja TANPA ForeignKey di migration ini:
    # `ADD COLUMN ... REFERENCES` ke tabel yang baru dibuat dalam transaksi yang
    # sama tidak didukung (SQLite: "Cannot add a REFERENCES column with non-NULL
    # default value"; PostgreSQL juga menolak FK ke tabel belum terlihat). Relasi
    # tetap ditegakkan di ORM (`models.PrintingEvidence`), dan kolomnya cukup
    # sebagai integer supaya bukti bisa diikat tanpa mengunci urutan migrasi.
    for column, definition in (
        ("handoff_id", sa.Column("handoff_id", sa.Integer(), nullable=True)),
        ("disposition_id", sa.Column("disposition_id", sa.Integer(), nullable=True)),
        ("kind", sa.Column("kind", sa.String(length=32), nullable=True)),
        ("file_path", sa.Column("file_path", sa.Text(), nullable=True)),
    ):
        if _has_column("printing_evidence", column):
            print(f"[0024] SKIP printing_evidence.{column}: kolom sudah ada")
            continue
        op.add_column("printing_evidence", definition)
        print(f"[0024] ADD printing_evidence.{column}")


def downgrade():
    # Jangan pernah menghapus tabel berisi data produksi dari migration otomatis.
    # Penurunan versi harus dilakukan manual dan sadar.
    print("[0024] downgrade tidak menghapus tabel: penurunan harus manual")
