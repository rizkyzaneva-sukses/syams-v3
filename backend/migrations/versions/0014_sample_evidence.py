"""Preserve sample evidence and CMO customer decisions in the database."""
from alembic import op
import sqlalchemy as sa


revision = "0014_sample_evidence"
down_revision = "0013_shipment_line_recon"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sample_records", sa.Column("customer_decision_at", sa.DateTime(), nullable=True))
    op.add_column("sample_records", sa.Column("customer_decision_reason", sa.Text(), nullable=True))
    op.create_table(
        "sample_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sample_fk", sa.Integer(), sa.ForeignKey("sample_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_mime", sa.String(length=120), nullable=False),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sample_evidence_sample_fk", "sample_evidence", ["sample_fk"])


def downgrade():
    raise RuntimeError("Sample evidence migration is forward-only; restore a verified backup.")
