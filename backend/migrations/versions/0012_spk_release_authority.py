"""Record explicit CMO approval of one locked SPK version."""
from alembic import op
import sqlalchemy as sa

revision = "0012_spk_release_authority"
down_revision = "0011_po_intake"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("spks") as batch:
        batch.add_column(sa.Column("released_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("released_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("released_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("release_prerequisites", sa.Text(), nullable=True))
        batch.add_column(sa.Column("release_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("correction_reason", sa.Text(), nullable=True))
        batch.create_foreign_key("fk_spks_released_by_users", "users", ["released_by"], ["id"])


def downgrade():
    raise RuntimeError("SPK release evidence migration is forward-only; restore a verified backup.")
