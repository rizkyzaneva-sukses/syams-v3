"""Exception Centre: typed exceptions, escalation fields, no hard delete.

Revisi #73 asks every exception to carry a typed category, source entity,
severity rule, authorized owner, due date, evidence, impact, recommendation,
escalation reason, decision requirement, resolution/verification and audit —
and confidential HR cases to be restricted.

The table only had order_fk/severity/category/title/owner_role/owner_name/
due_date/next_action/status/created_at, so an exception was a free-text note with
no source, impact or escalation trail, and CEO could hard-delete it.

Backfill stays conservative: existing rows keep NULL for the new descriptive
columns because that information was never recorded, and `confidential` defaults
to false so no existing row silently becomes restricted.
"""
from alembic import op
import sqlalchemy as sa


revision = "0018_exception_centre"
down_revision = "0017_audit_status_transition"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("exceptions", sa.Column("source_module", sa.String(length=80), nullable=True))
    op.add_column("exceptions", sa.Column("source_entity", sa.String(length=80), nullable=True))
    op.add_column("exceptions", sa.Column("source_entity_id", sa.Integer(), nullable=True))
    op.add_column("exceptions", sa.Column("impact", sa.Text(), nullable=True))
    op.add_column("exceptions", sa.Column("recommendation", sa.Text(), nullable=True))
    op.add_column("exceptions", sa.Column("escalation_reason", sa.Text(), nullable=True))
    op.add_column("exceptions", sa.Column("decision_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("exceptions", sa.Column("evidence_ref", sa.Text(), nullable=True))
    op.add_column("exceptions", sa.Column("resolution_note", sa.Text(), nullable=True))
    op.add_column("exceptions", sa.Column("verified_by_id", sa.Integer(), nullable=True))
    op.add_column("exceptions", sa.Column("verified_at", sa.DateTime(), nullable=True))
    op.add_column("exceptions", sa.Column("created_by_id", sa.Integer(), nullable=True))
    op.add_column("exceptions", sa.Column("confidential", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("exceptions", sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.add_column("exceptions", sa.Column("updated_at", sa.DateTime(), nullable=True))


def downgrade():
    for column in ("updated_at", "resolved_at", "confidential", "created_by_id",
                   "verified_at", "verified_by_id", "resolution_note", "evidence_ref",
                   "decision_required", "escalation_reason", "recommendation", "impact",
                   "source_entity_id", "source_entity", "source_module"):
        op.drop_column("exceptions", column)
