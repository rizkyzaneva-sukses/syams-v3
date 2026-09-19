"""Structured status transitions on the audit trail.

INT-ORDER-001 poin 10 requires every status change to carry source_module,
actor, timestamp, previous_status, new_status and reason. The audit table only
had user_id/action/entity/entity_id/detail/created_at, so previous/new status
were occasionally smuggled into the free-text `detail` field and could not be
queried, filtered or reconstructed.

Columns added:
* audit_logs.source_module  - which module produced the change
* audit_logs.order_id       - the stable Order ID (SO-...) the change belongs to
* audit_logs.previous_status / new_status - the transition itself
* audit_logs.reason         - why, when the change is a correction

Existing rows keep NULL here: the old rows never recorded a machine-readable
transition, and backfilling one would mean inventing history.
"""
from alembic import op
import sqlalchemy as sa


revision = "0017_audit_status_transition"
down_revision = "0016_currency_and_sent_at"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_logs", sa.Column("source_module", sa.String(length=80), nullable=True))
    op.add_column("audit_logs", sa.Column("order_id", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("previous_status", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("new_status", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("reason", sa.Text(), nullable=True))
    op.create_index("ix_audit_logs_order_id", "audit_logs", ["order_id"])
    op.create_index("ix_audit_logs_source_module", "audit_logs", ["source_module"])


def downgrade():
    op.drop_index("ix_audit_logs_source_module", table_name="audit_logs")
    op.drop_index("ix_audit_logs_order_id", table_name="audit_logs")
    op.drop_column("audit_logs", "reason")
    op.drop_column("audit_logs", "new_status")
    op.drop_column("audit_logs", "previous_status")
    op.drop_column("audit_logs", "order_id")
    op.drop_column("audit_logs", "source_module")
