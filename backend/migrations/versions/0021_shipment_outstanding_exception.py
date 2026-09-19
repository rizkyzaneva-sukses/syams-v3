"""CEO shipment outstanding exception, bound to one Shipment ID.

Revisi #75: the Shipment page showed finance/CEO state but there was no complete
exception workflow tied to a single release. Outstanding amount, risk, terms,
evidence, expiry and the single-release limit were missing.

Lifecycle enforced by this table:
  CFO requests  -> only when the finance gate is HOLD and a CFO assessment exists
  CMO confirms  -> customer confirmation recorded before any CEO decision
  CEO decides   -> APPROVE releases exactly one shipment; REJECT keeps the HOLD
  COO consumes  -> marks the exception used after the physical release

An approval never rewrites invoice, paid or outstanding: the money stays
receivable. The exception expires after one release (used_at) or valid_until.

No backfill: existing shipments never had an exception, so inventing rows would
create approvals nobody granted.
"""
from alembic import op
import sqlalchemy as sa


revision = "0021_shipment_outstanding_exception"
down_revision = "0020_decision_and_action_tracker"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shipment_exceptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exception_no", sa.String(length=40), nullable=True),
        sa.Column("shipment_fk", sa.Integer(), sa.ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_fk", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("buyer", sa.String(length=160), nullable=True),
        sa.Column("goods_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lines_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("shipment_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("invoice_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("invoice_paid", sa.Numeric(18, 2), nullable=True),
        sa.Column("outstanding", sa.Numeric(18, 2), nullable=True),
        sa.Column("payment_terms", sa.String(length=255), nullable=True),
        sa.Column("payment_due", sa.Date(), nullable=True),
        sa.Column("cfo_assessment", sa.Text(), nullable=True),
        sa.Column("cfo_status", sa.String(length=32), nullable=True),
        sa.Column("cfo_assessed_by_id", sa.Integer(), nullable=True),
        sa.Column("cfo_assessed_at", sa.DateTime(), nullable=True),
        sa.Column("cmo_customer_confirmation", sa.Text(), nullable=True),
        sa.Column("cmo_confirmed_by_id", sa.Integer(), nullable=True),
        sa.Column("cmo_confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=True),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("requested_by_id", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("ceo_decision", sa.String(length=32), nullable=True),
        sa.Column("ceo_decision_reason", sa.Text(), nullable=True),
        sa.Column("ceo_decided_by_id", sa.Integer(), nullable=True),
        sa.Column("ceo_decided_at", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("single_release", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_shipment_exceptions_shipment_fk", "shipment_exceptions", ["shipment_fk"])
    op.create_index("ix_shipment_exceptions_order_fk", "shipment_exceptions", ["order_fk"])


def downgrade():
    op.drop_index("ix_shipment_exceptions_order_fk", table_name="shipment_exceptions")
    op.drop_index("ix_shipment_exceptions_shipment_fk", table_name="shipment_exceptions")
    op.drop_table("shipment_exceptions")
