import enum
from datetime import datetime, date
from sqlalchemy import (Column, Integer, String, Float, Text, Boolean, Date,
    DateTime, Numeric, Enum, ForeignKey, UniqueConstraint, LargeBinary)
from sqlalchemy.orm import relationship
from .database import Base

class Role(str, enum.Enum):
    CEO = "CEO"
    CMO_MANAGER = "CMO_MANAGER"
    CMO_SUPPORT = "CMO_SUPPORT"
    CFO_MANAGER = "CFO_MANAGER"
    FINANCE_SUPPORT = "FINANCE_SUPPORT"
    COO_MANAGER = "COO_MANAGER"
    SAMPLE_PIC = "SAMPLE_PIC"
    PRINTING_PIC = "PRINTING_PIC"
    PRODUCTION_PIC = "PRODUCTION_PIC"
    CHRO_MANAGER = "CHRO_MANAGER"
    HR_SUPPORT = "HR_SUPPORT"
    SHIPMENT_ADMIN = "SHIPMENT_ADMIN"

class OrderType(str, enum.Enum):
    SAMPLE_ONLY = "SAMPLE_ONLY"
    SAMPLE_PRODUCTION = "SAMPLE_PRODUCTION"
    REPEAT_PRODUCTION = "REPEAT_PRODUCTION"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(180), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(Role), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    order_id = Column(String(64), unique=True, index=True, nullable=False)
    buyer = Column(String(160), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    finance_gate_status = Column(String(32), default="PENDING", nullable=False)
    finance_gate_notes = Column(Text, nullable=True)
    finance_verified_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    finance_term_kind = Column(String(20), nullable=True)
    required_dp_amount = Column(Numeric(18, 2), nullable=True)
    payment_evidence_ref = Column(Text, nullable=True)
    credit_due_date = Column(Date, nullable=True)
    order_type = Column(Enum(OrderType), nullable=False)
    order_date = Column(Date, default=date.today, nullable=False)
    buyer_deadline = Column(Date, nullable=True)
    finance_status = Column(String(32), default="UNPAID", nullable=False)
    material_status = Column(String(32), default="NOT_REQUESTED", nullable=False)
    shipment_status = Column(String(32), default="NOT_READY", nullable=False)
    customer_close_status = Column(String(32), default="OPEN", nullable=False)
    operational_close_status = Column(String(32), default="OPEN", nullable=False)
    financial_close_status = Column(String(32), default="OPEN", nullable=False)
    overall_status = Column(String(32), default="NEW", nullable=False)
    flow_step = Column(String(40), default="ORDER", nullable=False)
    projected_shipment = Column(Date, nullable=True)
    buffer_days = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    articles = relationship("Article", back_populates="order", cascade="all, delete-orphan")

class Article(Base):
    __tablename__ = "articles"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    article_code = Column(String(80), nullable=False)
    garment_type = Column(String(120), nullable=True)
    qty = Column(Integer, default=0, nullable=False)
    size_breakdown = Column(Text, nullable=True)
    sample_required = Column(Boolean, default=False, nullable=False)
    sample_status = Column(String(32), default="NOT_REQUIRED", nullable=False)
    production_route = Column(Text, nullable=True)
    production_status = Column(String(32), default="NOT_STARTED", nullable=False)
    order = relationship("Order", back_populates="articles")

class POIntake(Base):
    """Customer PO received by CMO Support, before an Order exists."""
    __tablename__ = "po_intakes"
    __table_args__ = (UniqueConstraint("buyer", "po_number", name="uq_po_intake_buyer_number"),)
    id = Column(Integer, primary_key=True)
    po_number = Column(String(100), nullable=True)
    buyer = Column(String(160), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    order_type = Column(String(32), nullable=True)
    buyer_deadline = Column(Date, nullable=True)
    articles_json = Column(Text, default="[]", nullable=False)
    notes = Column(Text, nullable=True)
    document_name = Column(String(255), nullable=True)
    document_mime = Column(String(80), nullable=True)
    document_data = Column(LargeBinary, nullable=True)
    status = Column(String(24), default="DRAFT", nullable=False)
    missing_items_json = Column(Text, default="[]", nullable=False)
    follow_up_note = Column(Text, nullable=True)
    review_note = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reviewed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    order_fk = Column(Integer, ForeignKey("orders.id"), unique=True, nullable=True)
    received_at = Column(Date, default=date.today, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    order = relationship("Order")

class ProductionMovement(Base):
    __tablename__ = "production_movements"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True)
    process = Column(String(80), nullable=False)
    qty_in = Column(Integer, default=0, nullable=False)
    qty_done = Column(Integer, default=0, nullable=False)
    qty_reject = Column(Integer, default=0, nullable=False)
    status = Column(String(32), default="WAITING", nullable=False)
    pic_name = Column(String(120), nullable=True)
    reject_reason = Column(Text, nullable=True)
    target_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class ExceptionItem(Base):
    __tablename__ = "exceptions"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    severity = Column(String(20), default="YELLOW", nullable=False)
    category = Column(String(100), nullable=False)
    title = Column(String(200), nullable=False)
    owner_role = Column(String(80), nullable=True)
    owner_name = Column(String(120), nullable=True)
    due_date = Column(Date, nullable=True)
    next_action = Column(Text, nullable=True)
    status = Column(String(32), default="OPEN", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class CapacitySnapshot(Base):
    __tablename__ = "capacity_snapshots"
    id = Column(Integer, primary_key=True)
    snapshot_date = Column(Date, nullable=False)
    process = Column(String(80), nullable=False)
    capacity = Column(Integer, default=0, nullable=False)
    planned_load = Column(Integer, default=0, nullable=False)
    current_wip = Column(Integer, default=0, nullable=False)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    assigned_to_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(32), default="OPEN", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class RevisionProposal(Base):
    __tablename__ = "revision_proposals"
    id = Column(Integer, primary_key=True)
    module_name = Column(String(120), nullable=False)
    bug_description = Column(Text, nullable=False)
    expected_behavior = Column(Text, nullable=False)
    image_data = Column(LargeBinary, nullable=True)
    image_mime = Column(String(40), nullable=True)
    reported_by_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    owner_role = Column(String(40), nullable=True)
    status = Column(String(24), default="REVISI", nullable=False)
    status_note = Column(Text, nullable=True)
    status_updated_at = Column(DateTime, nullable=True)
    status_updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

class RevisionStatusEvent(Base):
    __tablename__ = "revision_status_events"
    id = Column(Integer, primary_key=True)
    proposal_id = Column(Integer, ForeignKey("revision_proposals.id"), nullable=False, index=True)
    from_status = Column(String(24), nullable=False)
    to_status = Column(String(24), nullable=False)
    note = Column(Text, nullable=True)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(80), nullable=False)
    entity = Column(String(80), nullable=False)
    entity_id = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), unique=True, nullable=False)
    country = Column(String(80), nullable=True)
    contact_name = Column(String(120), nullable=True)
    contact_info = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Quotation(Base):
    __tablename__ = "quotations"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    quotation_no = Column(String(80), unique=True, nullable=False)
    amount = Column(Numeric(18,2), default=0, nullable=False)
    pricing_breakdown = Column(Text, nullable=True)
    hpp_total = Column(Numeric(18,2), default=0, nullable=False)
    margin_amount = Column(Numeric(18,2), default=0, nullable=False)
    margin_percent = Column(Numeric(8,2), default=0, nullable=False)
    payment_plan = Column(Text, nullable=True)
    approval_reason = Column(Text, nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ceo_approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ceo_approval_reason = Column(Text, nullable=True)
    valid_until = Column(Date, nullable=True)
    status = Column(String(32), default="DRAFT", nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class SampleRecord(Base):
    __tablename__ = "sample_records"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    article_code = Column(String(80), nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True, index=True)
    status = Column(String(32), default="PROCESS", nullable=False)
    customer_approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    requested_date = Column(Date, nullable=True)
    completed_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class SPK(Base):
    __tablename__ = "spks"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    spk_no = Column(String(80), unique=True, nullable=False)
    status = Column(String(32), default="NEW", nullable=False)
    version = Column(Integer, default=1, nullable=False)
    snapshot = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    released_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    released_at = Column(DateTime, nullable=True)
    released_version = Column(Integer, nullable=True)
    release_prerequisites = Column(Text, nullable=True)
    release_reason = Column(Text, nullable=True)
    correction_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class MaterialRequest(Base):
    __tablename__ = "material_requests"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    item_name = Column(String(200), nullable=False)
    qty = Column(Numeric(12,2), default=0, nullable=False)
    unit = Column(String(40), nullable=True)
    status = Column(String(32), default="REQUESTED", nullable=False)
    requested_by = Column(String(120), nullable=True)
    required_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class BOMItem(Base):
    __tablename__ = "bom_items"
    __table_args__ = (UniqueConstraint("article_id", "material_name", "unit", name="uq_bom_article_material_unit"),)
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True)
    material_name = Column(String(200), nullable=False)
    unit = Column(String(40), nullable=False)
    qty_per_unit = Column(Numeric(12, 4), nullable=False)
    planned_unit_cost = Column(Numeric(18, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class MaterialConsumption(Base):
    __tablename__ = "material_consumptions"
    id = Column(Integer, primary_key=True)
    bom_item_id = Column(Integer, ForeignKey("bom_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    qty = Column(Numeric(12, 4), nullable=False)
    actual_unit_cost = Column(Numeric(18, 2), nullable=False)
    evidence_ref = Column(Text, nullable=False)
    recorded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class ProductionCostEntry(Base):
    __tablename__ = "production_cost_entries"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(20), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    evidence_ref = Column(Text, nullable=False)
    recorded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class CostReview(Base):
    __tablename__ = "cost_reviews"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True)
    reviewed_total = Column(Numeric(18, 2), nullable=False)
    evidence_ref = Column(Text, nullable=False)
    reviewed_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reviewed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id = Column(Integer, primary_key=True)
    po_no = Column(String(80), unique=True, nullable=False)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    item = Column(String(200), nullable=True)
    qty = Column(Numeric(12,2), default=0, nullable=True)
    unit = Column(String(40), nullable=True)
    supplier = Column(String(180), nullable=True)
    amount = Column(Numeric(18,2), default=0, nullable=False)
    status = Column(String(32), default="PENDING", nullable=False)
    arrival_date = Column(Date, nullable=True)
    material_status = Column(String(32), default="WAITING", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    invoice_no = Column(String(80), unique=True, nullable=False)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(18,2), default=0, nullable=False)
    paid_amount = Column(Numeric(18,2), default=0, nullable=False)
    opening_paid_amount = Column(Numeric(18,2), default=0, nullable=False)
    reconciliation_status = Column(String(32), default="VERIFIED", nullable=False)
    reconciliation_evidence = Column(Text, nullable=True)
    reconciled_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(32), default="UNPAID", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    invoice_no = Column(String(80), nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True, index=True)
    amount = Column(Numeric(18,2), nullable=False)
    payment_date = Column(Date, nullable=True)
    method = Column(String(80), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class QCRecord(Base):
    __tablename__ = "qc_records"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    article_code = Column(String(80), nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True, index=True)
    rework_parent_id = Column(Integer, ForeignKey("qc_records.id"), nullable=True)
    process = Column(String(80), nullable=False)
    total_checked = Column(Integer, default=0, nullable=False)
    total_pass = Column(Integer, default=0, nullable=False)
    total_reject = Column(Integer, default=0, nullable=False)
    reject_reason = Column(Text, nullable=True)
    inspector = Column(String(120), nullable=True)
    status = Column(String(32), default="PASS", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Shipment(Base):
    __tablename__ = "shipments"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    shipment_no = Column(String(80), unique=True, nullable=False)
    status = Column(String(32), default="NOT_READY", nullable=False)
    finance_gate = Column(String(32), default="PENDING", nullable=False)
    packing_status = Column(String(32), default="PENDING", nullable=False)
    finance_assessed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_outstanding = Column(Numeric(18,2), nullable=True)
    ceo_approval = Column(String(32), nullable=True)
    notes = Column(Text, nullable=True)
    delivery_date = Column(Date, nullable=True)
    shipped_date = Column(Date, nullable=True)
    tracking_no = Column(String(120), nullable=True)
    # Rows created before shipment_lines existed remain explicitly marked as
    # legacy.  New rows must reconcile their article quantities before packing.
    line_reconciliation_required = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    lines = relationship("ShipmentLine", back_populates="shipment", cascade="all, delete-orphan")

class ShipmentLine(Base):
    __tablename__ = "shipment_lines"
    __table_args__ = (UniqueConstraint("shipment_fk", "article_id", name="uq_shipment_line_article"),)
    id = Column(Integer, primary_key=True)
    shipment_fk = Column(Integer, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="RESTRICT"), nullable=False, index=True)
    qty = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    shipment = relationship("Shipment", back_populates="lines")
    article = relationship("Article")

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    employee_no = Column(String(80), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    division = Column(String(120), nullable=True)
    position = Column(String(120), nullable=True)
    employment_status = Column(String(32), default="ACTIVE", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class TrainingRecord(Base):
    __tablename__ = "training_records"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(200), nullable=False)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    result = Column(String(80), nullable=True)
    evaluator = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class PerformanceRecord(Base):
    __tablename__ = "performance_records"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    period = Column(String(60), nullable=False)
    quality = Column(Float, nullable=True)
    responsibility = Column(Float, nullable=True)
    discipline = Column(Float, nullable=True)
    spiritual = Column(Float, nullable=True)
    attitude = Column(Float, nullable=True)
    skill = Column(Float, nullable=True)
    total_score = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class EmployeeIssue(Base):
    __tablename__ = "employee_issues"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    issue_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(String(20), default="YELLOW", nullable=False)
    status = Column(String(32), default="OPEN", nullable=False)
    reported_by = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class CEODecision(Base):
    __tablename__ = "ceo_decisions"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    decision_type = Column(String(100), nullable=False)
    subject = Column(String(300), nullable=False)
    decision = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    owner_name = Column(String(120), nullable=True)
    due_date = Column(Date, nullable=True)
    action_status = Column(String(32), default="OPEN", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class SystemConfig(Base):
    __tablename__ = "system_config"
    id = Column(Integer, primary_key=True)
    key = Column(String(120), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, onupdate=datetime.utcnow, nullable=False)

class ProductionPlan(Base):
    __tablename__ = "production_plans"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_date = Column(Date, nullable=True)
    status = Column(String(32), default="PLANNING", nullable=False)
    notes = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    order = relationship("Order", backref="production_plans")

class DeliveryConfirmation(Base):
    __tablename__ = "delivery_confirmations"
    id = Column(Integer, primary_key=True)
    shipment_fk = Column(Integer, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    confirmed_by_customer = Column(String(160), nullable=True)
    confirmation_date = Column(Date, nullable=True)
    feedback = Column(Text, nullable=True)
    status = Column(String(32), default="PENDING", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    shipment = relationship("Shipment", backref="delivery_confirmations")

class OrderClosing(Base):
    __tablename__ = "order_closings"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_close_status = Column(String(32), default="OPEN", nullable=False)
    operational_close_status = Column(String(32), default="OPEN", nullable=False)
    financial_close_status = Column(String(32), default="OPEN", nullable=False)
    order_close_status = Column(String(32), default="OPEN", nullable=False)
    closed_by = Column(String(120), nullable=True)
    close_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    order = relationship("Order", backref="order_closings")
