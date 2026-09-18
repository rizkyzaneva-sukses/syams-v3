"""Align historical SPK preparation statuses with the document workflow."""
from alembic import op
import sqlalchemy as sa

revision = "0010_spk_document_flow"
down_revision = "0009_operational_closing"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE spks SET status = 'DRAFT' WHERE status = 'NEW'"))
    connection.execute(sa.text("UPDATE spks SET status = 'VOID' WHERE status = 'CANCELLED'"))


def downgrade():
    raise RuntimeError("SPK document workflow migration is forward-only; restore a verified backup.")
