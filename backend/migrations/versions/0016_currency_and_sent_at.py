"""Currency/terms on PO intake and quotations, plus quotation sent_at.

Blueprint REF-DEBY (revisi #9) poin 4 asks the PO Masuk queue for
"currency/terms" and poin 7 asks the Quotation queue for "currency" and
"sent_at". Those columns had no backing field, so the UI could only show a
placeholder. This adds the real fields:

* po_intakes.currency / po_intakes.payment_terms - currency and payment terms
  stated by the buyer on the incoming PO.
* quotations.currency - currency the quotation is priced in.
* quotations.sent_at - when Deby actually sent the quotation to the buyer,
  which is distinct from quotations.created_at (when the row was drafted).

Backfill is deliberately conservative: currency defaults to IDR because every
existing row is Rupiah-priced; sent_at stays NULL because the real send moment
was never recorded and inventing one would be worse than "not tracked".
"""
from alembic import op
import sqlalchemy as sa


revision = "0016_currency_and_sent_at"
down_revision = "0015_operator_attribution"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("po_intakes", sa.Column("currency", sa.String(length=8), nullable=False, server_default="IDR"))
    op.add_column("po_intakes", sa.Column("payment_terms", sa.String(length=255), nullable=True))
    op.add_column("quotations", sa.Column("currency", sa.String(length=8), nullable=False, server_default="IDR"))
    op.add_column("quotations", sa.Column("sent_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("quotations", "sent_at")
    op.drop_column("quotations", "currency")
    op.drop_column("po_intakes", "payment_terms")
    op.drop_column("po_intakes", "currency")
