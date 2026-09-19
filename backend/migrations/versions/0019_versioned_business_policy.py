"""Versioned business policy.

Revisi #76: pricing policy was a single overwritten JSON row with no version,
effective date, change reason, or previous value.

This adds `business_policy_versions`: every change becomes its own row carrying
the policy snapshot, the previous snapshot, the effective window, the reason, and
who changed it. `system_config.business_policy` keeps holding the effective
policy so existing readers of get_policy() are untouched.

Existing deployments get one backfill row describing the currently effective
policy, attributed to the reason "Initial version captured on upgrade" — that is
labelled as a migration artefact rather than invented history, and no previous
value is fabricated.
"""
from alembic import op
import sqlalchemy as sa
from datetime import date, datetime


revision = "0019_versioned_business_policy"
down_revision = "0018_exception_centre"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "business_policy_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("previous_json", sa.Text(), nullable=True),
        sa.Column("proposed_by_id", sa.Integer(), nullable=True),
        sa.Column("changed_by_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_business_policy_versions_version", "business_policy_versions", ["version"])

    # Backfill satu baris untuk policy yang sedang berlaku, kalau ada.
    conn = op.get_bind()
    row = conn.execute(sa.text(
        "SELECT id, value FROM system_config WHERE key = 'business_policy'"
    )).fetchone()
    if row is not None and row[1]:
        # changed_by_id NOT NULL: pakai user pertama yang tersedia; kalau belum
        # ada user sama sekali, lewati backfill daripada memasukkan nilai palsu.
        owner = conn.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1")).fetchone()
        if owner is not None:
            # Nilai tanggal/waktu dihitung di Python, bukan diserahkan sebagai
            # objek fungsi SQLAlchemy. Mengirim sa.func.* sebagai parameter bind
            # gagal di PostgreSQL ("can't adapt type 'current_date'") dan membuat
            # container crash-loop saat migration jalan.
            # is_active dikirim sebagai boolean asli: literal 1 ditolak PostgreSQL
            # ("column is_active is of type boolean but expression is of type
            # integer"), walau SQLite menerimanya.
            conn.execute(sa.text(
                "INSERT INTO business_policy_versions "
                "(version, policy_json, effective_from, change_reason, previous_json, changed_by_id, is_active, created_at) "
                "VALUES (1, :policy, :today, :reason, NULL, :uid, :active, :now)"
            ), {"policy": row[1], "today": date.today(), "uid": owner[0], "active": True,
                "reason": "Initial version captured on upgrade", "now": datetime.utcnow()})


def downgrade():
    op.drop_index("ix_business_policy_versions_version", table_name="business_policy_versions")
    op.drop_table("business_policy_versions")
