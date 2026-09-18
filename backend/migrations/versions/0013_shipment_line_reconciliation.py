"""Track packed shipment quantities per order article.

Existing shipment headers cannot be reconstructed into article quantities, so
they are retained as LEGACY (line_reconciliation_required=false).  New ORM
shipments default to requiring lines before they can be packed or dispatched.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_shipment_line_reconciliation"
down_revision = "0012_spk_release_authority"
branch_labels = None
depends_on = None


def upgrade():
    # The server default labels existing rows as legacy without inventing
    # quantities. API-created shipments explicitly set this field to True.
    # Keeping the default also avoids a second ALTER TABLE during startup.
    op.add_column(
        "shipments",
        sa.Column("line_reconciliation_required", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )

    op.create_table(
        "shipment_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shipment_fk", sa.Integer(), sa.ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("shipment_fk", "article_id", name="uq_shipment_line_article"),
    )
    op.create_index("ix_shipment_lines_shipment_fk", "shipment_lines", ["shipment_fk"])
    op.create_index("ix_shipment_lines_article_id", "shipment_lines", ["article_id"])


def downgrade():
    raise RuntimeError("Shipment reconciliation migration is forward-only; restore a verified backup.")
