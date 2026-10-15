"""Migration 0029 — modul lanjutan penutup gap BLUEPRINT/PRD.

Menambahkan tabel:
- Inventory/Purchasing (Riadi): suppliers, inventory_locations, materials,
  stock_movements, purchase_requests, purchase_request_lines, goods_receipts,
  goods_receipt_lines, material_gates
- HR Time (Yuni): attendance, leave_requests, leave_balances
- Banking (Lutfi): bank_accounts, bank_transactions
- Artwork (Diki): artworks, artwork_versions, artwork_handovers
- CRM (Cecep/Deby): leads, opportunities, sales_targets
- Platform: notifications, idempotency_keys

Backfill: TIDAK ADA — semua tabel mulai kosong. COA/material/master diisi lewat
endpoint seed (idempotent), bukan dikarang di migrasi.

Revision ID: 0029_modules
Revises: 0028_accounting
"""
from alembic import op
import sqlalchemy as sa


revision = "0029_modules"
down_revision = "0028_accounting"
branch_labels = None
depends_on = None


def _has(name):
    return name in sa.inspect(op.get_bind()).get_table_names()


def _id():
    return sa.Column("id", sa.Integer, primary_key=True)


def _ts():
    return [
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    ]


def upgrade():
    # ── INVENTORY / PURCHASING (Riadi) ────────────────────────────────────────
    if not _has("suppliers"):
        op.create_table("suppliers",
            _id(),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("name", sa.String(180), nullable=False),
            sa.Column("vendor_type", sa.String(24), nullable=False, server_default="SUPPLIER"),
            sa.Column("contact_person", sa.String(120)), sa.Column("phone", sa.String(60)),
            sa.Column("email", sa.String(160)), sa.Column("address", sa.Text),
            sa.Column("payment_terms", sa.String(120)), sa.Column("lead_time_days", sa.Integer),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("notes", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("code", name="uq_supplier_code"),
        )
        op.create_index("ix_supplier_code", "suppliers", ["code"])
        op.create_index("ix_supplier_vendor_type", "suppliers", ["vendor_type"])

    if not _has("inventory_locations"):
        op.create_table("inventory_locations",
            _id(),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("name", sa.String(180), nullable=False),
            sa.Column("location_type", sa.String(24), nullable=False, server_default="WAREHOUSE"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("code", name="uq_inventory_location_code"),
        )
        op.create_index("ix_inv_loc_code", "inventory_locations", ["code"])

    if not _has("materials"):
        op.create_table("materials",
            _id(),
            sa.Column("code", sa.String(60), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("category", sa.String(80)),
            sa.Column("unit", sa.String(40), nullable=False, server_default="pcs"),
            sa.Column("min_stock", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("reorder_point", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("standard_cost", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("default_supplier_id", sa.Integer, sa.ForeignKey("suppliers.id")),
            sa.Column("default_location_id", sa.Integer, sa.ForeignKey("inventory_locations.id")),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("notes", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("code", name="uq_material_code"),
        )
        op.create_index("ix_material_code", "materials", ["code"])
        op.create_index("ix_material_category", "materials", ["category"])

    if not _has("stock_movements"):
        op.create_table("stock_movements",
            _id(),
            sa.Column("material_id", sa.Integer, sa.ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("location_id", sa.Integer, sa.ForeignKey("inventory_locations.id"), nullable=False),
            sa.Column("movement_type", sa.String(24), nullable=False),
            sa.Column("qty", sa.Numeric(14, 4), nullable=False),
            sa.Column("unit_cost", sa.Numeric(18, 2)),
            sa.Column("order_fk", sa.Integer, sa.ForeignKey("orders.id", ondelete="SET NULL")),
            sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id", ondelete="SET NULL")),
            sa.Column("reference_type", sa.String(32)), sa.Column("reference_id", sa.Integer),
            sa.Column("reference_no", sa.String(80)), sa.Column("reason", sa.Text),
            sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_sm_material", "stock_movements", ["material_id"])
        op.create_index("ix_sm_location", "stock_movements", ["location_id"])
        op.create_index("ix_sm_type", "stock_movements", ["movement_type"])
        op.create_index("ix_sm_order", "stock_movements", ["order_fk"])
        op.create_index("ix_sm_article", "stock_movements", ["article_id"])
        op.create_index("ix_stock_material_location", "stock_movements", ["material_id", "location_id"])

    if not _has("purchase_requests"):
        op.create_table("purchase_requests",
            _id(),
            sa.Column("pr_no", sa.String(40), nullable=False),
            sa.Column("order_fk", sa.Integer, sa.ForeignKey("orders.id", ondelete="SET NULL")),
            sa.Column("requested_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("required_date", sa.Date),
            sa.Column("status", sa.String(24), nullable=False, server_default="DRAFT"),
            sa.Column("priority", sa.String(16), nullable=False, server_default="NORMAL"),
            sa.Column("notes", sa.Text),
            sa.Column("approved_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("approved_at", sa.DateTime), sa.Column("rejection_reason", sa.Text),
            sa.Column("converted_po_id", sa.Integer, sa.ForeignKey("purchase_orders.id")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("pr_no", name="uq_pr_no"),
        )
        op.create_index("ix_pr_no", "purchase_requests", ["pr_no"])
        op.create_index("ix_pr_status", "purchase_requests", ["status"])
        op.create_index("ix_pr_order", "purchase_requests", ["order_fk"])

    if not _has("purchase_request_lines"):
        op.create_table("purchase_request_lines",
            _id(),
            sa.Column("request_id", sa.Integer, sa.ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("material_id", sa.Integer, sa.ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("qty", sa.Numeric(14, 4), nullable=False),
            sa.Column("estimated_unit_cost", sa.Numeric(18, 2)), sa.Column("notes", sa.Text),
        )
        op.create_index("ix_prl_request", "purchase_request_lines", ["request_id"])
        op.create_index("ix_prl_material", "purchase_request_lines", ["material_id"])

    if not _has("goods_receipts"):
        op.create_table("goods_receipts",
            _id(),
            sa.Column("gr_no", sa.String(40), nullable=False),
            sa.Column("po_fk", sa.Integer, sa.ForeignKey("purchase_orders.id", ondelete="SET NULL")),
            sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id")),
            sa.Column("received_date", sa.Date),
            sa.Column("status", sa.String(24), nullable=False, server_default="DRAFT"),
            sa.Column("received_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("posted_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("posted_at", sa.DateTime), sa.Column("evidence_ref", sa.Text),
            sa.Column("notes", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("gr_no", name="uq_gr_no"),
        )
        op.create_index("ix_gr_no", "goods_receipts", ["gr_no"])
        op.create_index("ix_gr_status", "goods_receipts", ["status"])
        op.create_index("ix_gr_po", "goods_receipts", ["po_fk"])
        op.create_index("ix_gr_supplier", "goods_receipts", ["supplier_id"])

    if not _has("goods_receipt_lines"):
        op.create_table("goods_receipt_lines",
            _id(),
            sa.Column("receipt_id", sa.Integer, sa.ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("material_id", sa.Integer, sa.ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("location_id", sa.Integer, sa.ForeignKey("inventory_locations.id"), nullable=False),
            sa.Column("qty_ordered", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("qty_received", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("qty_rejected", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("unit_cost", sa.Numeric(18, 2)), sa.Column("notes", sa.Text),
        )
        op.create_index("ix_grl_receipt", "goods_receipt_lines", ["receipt_id"])
        op.create_index("ix_grl_material", "goods_receipt_lines", ["material_id"])

    if not _has("material_gates"):
        op.create_table("material_gates",
            _id(),
            sa.Column("order_fk", sa.Integer, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="NOT_REQUESTED"),
            sa.Column("required_qty", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("allocated_qty", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("shortage_qty", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("block_reason", sa.Text),
            sa.Column("evaluated_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("evaluated_at", sa.DateTime),
            sa.Column("released_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("released_at", sa.DateTime),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("article_id", name="uq_material_gate_article"),
        )
        op.create_index("ix_mg_order", "material_gates", ["order_fk"])
        op.create_index("ix_mg_article", "material_gates", ["article_id"])
        op.create_index("ix_mg_status", "material_gates", ["status"])

    # ── HR TIME (Yuni) ────────────────────────────────────────────────────────
    if not _has("attendance"):
        op.create_table("attendance",
            _id(),
            sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
            sa.Column("work_date", sa.Date, nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("check_in", sa.String(8)), sa.Column("check_out", sa.String(8)),
            sa.Column("overtime_hours", sa.Numeric(6, 2), nullable=False, server_default="0"),
            sa.Column("shift", sa.String(24)), sa.Column("notes", sa.Text),
            sa.Column("recorded_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("employee_id", "work_date", name="uq_attendance_emp_date"),
        )
        op.create_index("ix_att_emp", "attendance", ["employee_id"])
        op.create_index("ix_att_date", "attendance", ["work_date"])

    if not _has("leave_requests"):
        op.create_table("leave_requests",
            _id(),
            sa.Column("request_no", sa.String(40), nullable=False),
            sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
            sa.Column("leave_type", sa.String(24), nullable=False),
            sa.Column("start_date", sa.Date, nullable=False), sa.Column("end_date", sa.Date, nullable=False),
            sa.Column("days", sa.Numeric(6, 1), nullable=False),
            sa.Column("reason", sa.Text),
            sa.Column("status", sa.String(24), nullable=False, server_default="DRAFT"),
            sa.Column("submitted_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("decided_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("decided_at", sa.DateTime), sa.Column("decision_note", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("request_no", name="uq_leave_request_no"),
        )
        op.create_index("ix_lr_no", "leave_requests", ["request_no"])
        op.create_index("ix_lr_emp", "leave_requests", ["employee_id"])
        op.create_index("ix_lr_status", "leave_requests", ["status"])

    if not _has("leave_balances"):
        op.create_table("leave_balances",
            _id(),
            sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
            sa.Column("year", sa.Integer, nullable=False),
            sa.Column("leave_type", sa.String(24), nullable=False),
            sa.Column("entitled_days", sa.Numeric(6, 1), nullable=False, server_default="0"),
            sa.Column("used_days", sa.Numeric(6, 1), nullable=False, server_default="0"),
            sa.UniqueConstraint("employee_id", "year", "leave_type", name="uq_leave_balance"),
        )
        op.create_index("ix_lb_emp", "leave_balances", ["employee_id"])

    # ── BANKING (Lutfi) ───────────────────────────────────────────────────────
    if not _has("bank_accounts"):
        op.create_table("bank_accounts",
            _id(),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("bank_name", sa.String(120), nullable=False),
            sa.Column("account_no", sa.String(60), nullable=False),
            sa.Column("account_name", sa.String(180), nullable=False),
            sa.Column("currency", sa.String(8), nullable=False, server_default="IDR"),
            sa.Column("opening_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("gl_account_id", sa.Integer, sa.ForeignKey("chart_of_accounts.id")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("code", name="uq_bank_account_code"),
        )
        op.create_index("ix_ba_code", "bank_accounts", ["code"])

    if not _has("bank_transactions"):
        op.create_table("bank_transactions",
            _id(),
            sa.Column("bank_account_id", sa.Integer, sa.ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("txn_date", sa.Date, nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("reference", sa.String(120)), sa.Column("balance_after", sa.Numeric(18, 2)),
            sa.Column("import_batch", sa.String(60)),
            sa.Column("reconciliation_status", sa.String(24), nullable=False, server_default="UNRECONCILED"),
            sa.Column("matched_journal_line_id", sa.Integer, sa.ForeignKey("journal_lines.id")),
            sa.Column("matched_payment_id", sa.Integer, sa.ForeignKey("payments.id")),
            sa.Column("matched_at", sa.DateTime),
            sa.Column("matched_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_bt_account", "bank_transactions", ["bank_account_id"])
        op.create_index("ix_bt_date", "bank_transactions", ["txn_date"])
        op.create_index("ix_bt_status", "bank_transactions", ["reconciliation_status"])

    # ── ARTWORK (Diki) ────────────────────────────────────────────────────────
    if not _has("artworks"):
        op.create_table("artworks",
            _id(),
            sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("artwork_type", sa.String(24), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("current_version_no", sa.Integer, nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("article_id", "artwork_type", name="uq_artwork_article_type"),
        )
        op.create_index("ix_aw_article", "artworks", ["article_id"])

    if not _has("artwork_versions"):
        op.create_table("artwork_versions",
            _id(),
            sa.Column("artwork_id", sa.Integer, sa.ForeignKey("artworks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version_no", sa.Integer, nullable=False),
            sa.Column("file_ref", sa.String(500), nullable=False),
            sa.Column("file_name", sa.String(200)),
            sa.Column("buyer_reference", sa.String(200)), sa.Column("notes", sa.Text),
            sa.Column("status", sa.String(24), nullable=False, server_default="DRAFT"),
            sa.Column("submitted_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("approved_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("approved_at", sa.DateTime),
            sa.Column("superseded_by_id", sa.Integer, sa.ForeignKey("artwork_versions.id")),
            sa.Column("received_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("received_at", sa.DateTime),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("artwork_id", "version_no", name="uq_artwork_version_no"),
        )
        op.create_index("ix_av_artwork", "artwork_versions", ["artwork_id"])
        op.create_index("ix_av_status", "artwork_versions", ["status"])

    if not _has("artwork_handovers"):
        op.create_table("artwork_handovers",
            _id(),
            sa.Column("artwork_version_id", sa.Integer, sa.ForeignKey("artwork_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("to_pic", sa.String(120), nullable=False),
            sa.Column("handed_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("handover_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("printed", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("print_register_no", sa.String(80)),
            sa.Column("acknowledged_by_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("acknowledged_at", sa.DateTime), sa.Column("notes", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_ah_version", "artwork_handovers", ["artwork_version_id"])

    # ── CRM (Cecep/Deby) ──────────────────────────────────────────────────────
    if not _has("leads"):
        op.create_table("leads",
            _id(),
            sa.Column("lead_no", sa.String(40), nullable=False),
            sa.Column("source", sa.String(24), nullable=False, server_default="LAINNYA"),
            sa.Column("company_name", sa.String(200), nullable=False),
            sa.Column("contact_name", sa.String(160), nullable=False),
            sa.Column("phone", sa.String(40), nullable=False), sa.Column("email", sa.String(180), nullable=False),
            sa.Column("city", sa.String(120)), sa.Column("interested_product", sa.String(200)),
            sa.Column("estimated_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("status", sa.String(24), nullable=False, server_default="NEW"),
            sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("next_followup_date", sa.Date), sa.Column("notes", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("lead_no", name="uq_lead_no"),
        )
        op.create_index("ix_lead_no", "leads", ["lead_no"])
        op.create_index("ix_lead_status", "leads", ["status"])

    if not _has("opportunities"):
        op.create_table("opportunities",
            _id(),
            sa.Column("opportunity_no", sa.String(40), nullable=False),
            sa.Column("lead_id", sa.Integer, sa.ForeignKey("leads.id")),
            sa.Column("buyer_name", sa.String(200), nullable=False),
            sa.Column("stage", sa.String(24), nullable=False, server_default="PROSPECT"),
            sa.Column("estimated_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("probability_percent", sa.Integer, nullable=False, server_default="0"),
            sa.Column("expected_close_date", sa.Date),
            sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("order_fk", sa.Integer, sa.ForeignKey("orders.id")),
            sa.Column("lost_reason", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("opportunity_no", name="uq_opportunity_no"),
        )
        op.create_index("ix_opp_no", "opportunities", ["opportunity_no"])
        op.create_index("ix_opp_stage", "opportunities", ["stage"])

    if not _has("sales_targets"):
        op.create_table("sales_targets",
            _id(),
            sa.Column("period", sa.String(7), nullable=False),
            sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("owner_name", sa.String(120)),
            sa.Column("target_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("target_orders", sa.Integer, nullable=False, server_default="0"),
            sa.Column("notes", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("period", "owner_id", name="uq_sales_target_period_owner"),
        )
        op.create_index("ix_st_period", "sales_targets", ["period"])

    # ── PLATFORM (notifications + idempotency) ────────────────────────────────
    if not _has("notifications"):
        op.create_table("notifications",
            _id(),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("role_target", sa.String(40)),
            sa.Column("category", sa.String(24), nullable=False, server_default="SYSTEM"),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("body", sa.Text), sa.Column("link_path", sa.String(200)),
            sa.Column("severity", sa.String(16), nullable=False, server_default="INFO"),
            sa.Column("is_read", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("read_at", sa.DateTime), sa.Column("dedup_key", sa.String(160)),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_notif_user", "notifications", ["user_id"])
        op.create_index("ix_notif_role", "notifications", ["role_target"])
        op.create_index("ix_notif_read", "notifications", ["is_read"])
        op.create_index("ix_notif_created", "notifications", ["created_at"])
        op.create_index("ix_notif_dedup", "notifications", ["dedup_key"],
                        unique=True, postgresql_where=sa.text("dedup_key IS NOT NULL"))

    if not _has("idempotency_keys"):
        op.create_table("idempotency_keys",
            _id(),
            sa.Column("key", sa.String(160), nullable=False),
            sa.Column("scope", sa.String(80), nullable=False),
            sa.Column("request_hash", sa.String(64)),
            sa.Column("response_status", sa.Integer), sa.Column("response_body", sa.Text),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime),
            sa.UniqueConstraint("key", name="uq_idempotency_key"),
        )
        op.create_index("ix_idem_key", "idempotency_keys", ["key"])
        op.create_index("ix_idem_scope", "idempotency_keys", ["scope"])


def downgrade():
    for table in ("idempotency_keys", "notifications", "sales_targets", "opportunities", "leads",
                  "artwork_handovers", "artwork_versions", "artworks",
                  "bank_transactions", "bank_accounts",
                  "leave_balances", "leave_requests", "attendance",
                  "material_gates", "goods_receipt_lines", "goods_receipts",
                  "purchase_request_lines", "purchase_requests", "stock_movements",
                  "materials", "inventory_locations", "suppliers"):
        if _has(table):
            op.drop_table(table)
