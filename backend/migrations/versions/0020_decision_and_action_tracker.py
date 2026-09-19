"""CEO Decision Needed + Action Tracker.

Revisi #72: decisions were free-form rows — CEO could pick any type and status,
owner was free text, and nothing tracked whether the decision was actually
carried out. There was no requester, source entity, evidence, options, impact or
recommendation.

This adds:
* structured decision columns on `ceo_decisions` (source, requester, context,
  evidence, options, recommendation, four impact dimensions, decision owner,
  typed action, decided_at, version)
* `ceo_action_items` — the Action Tracker. A decision that needs execution spawns
  an Action ID with an authorised owner, due date, follow-up, evidence, overdue
  escalation and completion verification.

Existing decision rows keep NULL in the new columns: that context was never
recorded, and inventing a requester, impact or recommendation would be worse than
an empty field. `version` backfills to 1 and `options_json` to an empty list,
because those are structural defaults rather than claims about history.
"""
from alembic import op
import sqlalchemy as sa


revision = "0020_decision_and_action_tracker"
down_revision = "0019_versioned_business_policy"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("source_module", sa.String(length=80), nullable=True),
        sa.Column("source_entity", sa.String(length=80), nullable=True),
        sa.Column("source_entity_id", sa.Integer(), nullable=True),
        sa.Column("requester_id", sa.Integer(), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("options_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("impact_financial", sa.Text(), nullable=True),
        sa.Column("impact_operational", sa.Text(), nullable=True),
        sa.Column("impact_customer", sa.Text(), nullable=True),
        sa.Column("impact_people", sa.Text(), nullable=True),
        sa.Column("decision_owner_id", sa.Integer(), nullable=True),
        sa.Column("decision_action", sa.String(length=32), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    ):
        op.add_column("ceo_decisions", column)

    op.create_table(
        "ceo_action_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_no", sa.String(length=40), nullable=True),
        sa.Column("decision_fk", sa.Integer(), sa.ForeignKey("ceo_decisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("authorized_owner_id", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OPEN"),
        sa.Column("next_follow_up", sa.Date(), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("escalated_at", sa.DateTime(), nullable=True),
        sa.Column("overdue_escalated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified_by_id", sa.Integer(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ceo_action_items_decision_fk", "ceo_action_items", ["decision_fk"])
    op.create_index("ix_ceo_action_items_status", "ceo_action_items", ["status"])


def downgrade():
    op.drop_index("ix_ceo_action_items_status", table_name="ceo_action_items")
    op.drop_index("ix_ceo_action_items_decision_fk", table_name="ceo_action_items")
    op.drop_table("ceo_action_items")
    for name in ("updated_at", "version", "decided_at", "decision_action", "decision_owner_id",
                 "impact_people", "impact_customer", "impact_operational", "impact_financial",
                 "recommendation", "options_json", "evidence_ref", "context", "requester_id",
                 "source_entity_id", "source_entity", "source_module"):
        op.drop_column("ceo_decisions", name)
