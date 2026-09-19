"""Payments carry an explicit Order ID.

INT-ORDER-001 poin 3 and 4 require every transaction to be traceable to the same
Order ID, with Article ID where relevant. `payments` only linked through
`invoice_no`, which is a free-text string rather than a foreign key, so a payment
could be orphaned and could not be queried per order.

This adds `order_fk` plus an index.

Backfill IS done here because the link already exists in the data: every payment
names an invoice, and invoices already carry `order_fk`. Resolving it recovers
information that is genuinely present rather than inventing it. Payments whose
invoice cannot be resolved are left NULL and are reported by count in the log
line below — they stay visible instead of being silently guessed.
"""
from alembic import op
import sqlalchemy as sa


revision = "0022_payment_order_link"
down_revision = "0021_shipment_exception"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payments", sa.Column("order_fk", sa.Integer(), nullable=True))
    op.create_index("ix_payments_order_fk", "payments", ["order_fk"])

    conn = op.get_bind()
    # Resolusi lewat invoice_id bila ada, kalau tidak lewat invoice_no.
    updated = conn.execute(sa.text(
        "UPDATE payments SET order_fk = ("
        "  SELECT i.order_fk FROM invoices i"
        "  WHERE i.id = payments.invoice_id"
        "     OR (payments.invoice_id IS NULL AND i.invoice_no = payments.invoice_no)"
        "  ORDER BY i.id DESC LIMIT 1"
        ")"
    ))
    remaining = conn.execute(sa.text(
        "SELECT count(*) FROM payments WHERE order_fk IS NULL"
    )).scalar()
    print(f"[0022] payments diberi order_fk: {updated.rowcount}; masih NULL: {remaining}")


def downgrade():
    op.drop_index("ix_payments_order_fk", table_name="payments")
    op.drop_column("payments", "order_fk")
