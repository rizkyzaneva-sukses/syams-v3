"""Add the CMO customer PO inbox before Order activation."""
from alembic import op
import sqlalchemy as sa

revision = "0011_po_intake"
down_revision = "0010_spk_document_flow"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "po_intakes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("po_number", sa.String(100), nullable=True),
        sa.Column("buyer", sa.String(160), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("order_type", sa.String(32), nullable=True),
        sa.Column("buyer_deadline", sa.Date(), nullable=True),
        sa.Column("articles_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("document_name", sa.String(255), nullable=True),
        sa.Column("document_mime", sa.String(80), nullable=True),
        sa.Column("document_data", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="DRAFT"),
        sa.Column("missing_items_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("follow_up_note", sa.Text(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("order_fk", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True, unique=True),
        sa.Column("received_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("buyer", "po_number", name="uq_po_intake_buyer_number"),
    )


def downgrade():
    raise RuntimeError("PO intake migration is forward-only; restore a verified backup.")
