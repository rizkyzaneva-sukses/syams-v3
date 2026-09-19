"""Migration 0026 — `quotations.updated_at` (blueprint poin 3).

Latar: halaman "Pricing & Quotation" punya kolom "Updated at", tetapi
`models.Quotation` hanya punya `created_at`, sehingga kolomnya selalu "—".
Menggantinya dengan `created_at` akan menyesatkan karena labelnya "Updated".

Backfill: YA — baris lama diisi `created_at` supaya kolomnya bisa dibuat
non-null. Ini bukan data yang dikarang: nilai aslinya memang tidak pernah
tercatat, dan `created_at` adalah batas bawah yang benar (sebuah baris tidak
mungkin diubah sebelum ia dibuat). Frontend menampilkan "—" selama nilainya
null, jadi aman walau backfill tertunda.

Revision ID: 0026_quotation_updated
Revises: 0025_ceo_overrides
"""
from alembic import op
import sqlalchemy as sa


revision = "0026_quotation_updated"       # <= 32 karakter
down_revision = "0025_ceo_overrides"
branch_labels = None
depends_on = None


def _has_table(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table, column):
    if not _has_table(table):
        return False
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if not _has_table("quotations"):
        print("[0026] SKIP quotations: tabel belum ada")
        return
    if _has_column("quotations", "updated_at"):
        print("[0026] SKIP quotations.updated_at: kolom sudah ada")
        return

    # Tambah nullable dulu, isi dari created_at, baru jadikan non-null —
    # supaya migration tidak gagal pada tabel berisi data.
    op.add_column("quotations", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE quotations SET updated_at = created_at WHERE updated_at IS NULL")
    with op.batch_alter_table("quotations") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)
    print("[0026] ADD quotations.updated_at + backfill dari created_at")


def downgrade():
    # Kolom jejak waktu: menurunkannya berarti menghapus informasi waktu ubah.
    print("[0026] downgrade tidak menghapus kolom: penurunan harus manual")
