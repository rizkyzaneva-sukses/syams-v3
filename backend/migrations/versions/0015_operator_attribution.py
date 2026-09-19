"""Record which operator (human or agent) authored a revision and each status change.

Every proposal and every status change now carries an operator label, so the team
can see *who or what* produced a fix — for example "Hermes", "GPT", "Claude" or a
human name. Without it, an incorrect revision has no owner beyond the reporting
user, which is what this revision request asks to fix.
"""
from alembic import op
import sqlalchemy as sa


revision = "0015_operator_attribution"
down_revision = "0014_sample_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("revision_proposals", sa.Column("operator", sa.String(length=64), nullable=True))
    op.add_column("revision_status_events", sa.Column("operator", sa.String(length=64), nullable=True))


def downgrade():
    raise RuntimeError("Operator attribution migration is forward-only; restore a verified backup.")
