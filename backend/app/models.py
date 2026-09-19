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
    currency = Column(String(8), default="IDR", nullable=False)
    payment_terms = Column(String(255), nullable=True)
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
    # ── Revisi #43/#46: kontrak Job Card & internal production ────────────────
    # Nullable: NULL berarti "belum diisi", bukan nilai historis yang salah.
    job_notes = Column(Text, nullable=True)
    colors = Column(String(255), nullable=True)
    placement = Column(String(255), nullable=True)
    size_spec = Column(Text, nullable=True)
    technique = Column(String(120), nullable=True)
    vendor_type = Column(String(32), nullable=True)
    machine = Column(String(120), nullable=True)
    team = Column(String(80), nullable=True)
    shift = Column(String(64), nullable=True)
    requirement_version = Column(String(120), nullable=True, index=True)
    locked_at = Column(DateTime, nullable=True)
    batch_id = Column(String(64), nullable=True, index=True)
    route_version = Column(String(40), nullable=True)
    approved_artwork_version = Column(String(60), nullable=True)
    priority = Column(String(20), nullable=True)
    sla_due_date = Column(Date, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    evidence_ref = Column(Text, nullable=True)
    # Revisi #54: handoff dan movement terhubung langsung, bukan direkonstruksi.
    handoff_id = Column(Integer, ForeignKey("production_handoffs.id", ondelete="SET NULL"), nullable=True, index=True)
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
    # Revisi #73: exception wajib punya sumber, dampak, rekomendasi, alasan
    # eskalasi, dan penanda butuh keputusan CEO — bukan sekadar judul bebas.
    source_module = Column(String(80), nullable=True)
    source_entity = Column(String(80), nullable=True)
    source_entity_id = Column(Integer, nullable=True)
    impact = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)
    escalation_reason = Column(Text, nullable=True)
    decision_required = Column(Boolean, default=False, nullable=False)
    evidence_ref = Column(Text, nullable=True)
    resolution_note = Column(Text, nullable=True)
    verified_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Confidential: kasus HR bersifat terbatas, hanya owner role + CEO.
    confidential = Column(Boolean, default=False, nullable=False)
    # Revisi #37: ikatan langsung exception↔sample (dan versinya) supaya
    # "exception sample milik saya" bisa difilter tanpa string source_entity.
    sample_fk = Column(Integer, ForeignKey("sample_records.id", ondelete="SET NULL"), nullable=True, index=True)
    sample_version = Column(Integer, nullable=True)
    scope = Column(String(16), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
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
    operator = Column(String(64), nullable=True)

class RevisionStatusEvent(Base):
    __tablename__ = "revision_status_events"
    id = Column(Integer, primary_key=True)
    proposal_id = Column(Integer, ForeignKey("revision_proposals.id"), nullable=False, index=True)
    from_status = Column(String(24), nullable=False)
    to_status = Column(String(24), nullable=False)
    note = Column(Text, nullable=True)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    operator = Column(String(64), nullable=True)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(80), nullable=False)
    entity = Column(String(80), nullable=False)
    entity_id = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)
    # INT-ORDER-001 poin 10: setiap perubahan status menyimpan modul sumber,
    # status lama, status baru, dan alasan bila dikoreksi. Sebelumnya informasi
    # ini hanya dititipkan sebagai teks bebas di `detail`, jadi tidak bisa
    # ditelusuri atau difilter.
    source_module = Column(String(80), nullable=True)
    order_id = Column(String(64), nullable=True)
    previous_status = Column(String(64), nullable=True)
    new_status = Column(String(64), nullable=True)
    reason = Column(Text, nullable=True)
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
    currency = Column(String(8), default="IDR", nullable=False)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Blueprint poin 3: halaman Pricing & Quotation punya kolom "Updated at".
    # Tanpa kolom ini, UI hanya bisa menampilkan "—" (menggantinya dengan
    # `created_at` akan menyesatkan karena labelnya "Updated").
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)

class SampleRecord(Base):
    __tablename__ = "sample_records"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    article_code = Column(String(80), nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True, index=True)
    status = Column(String(32), default="PROCESS", nullable=False)
    customer_approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    customer_decision_at = Column(DateTime, nullable=True)
    customer_decision_reason = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    requested_date = Column(Date, nullable=True)
    completed_date = Column(Date, nullable=True)
    # ── SMP-F-005 / SMP-F-006: versi sample eksplisit ─────────────────────────
    # Sebelumnya "versi" hanya turunan urutan `id`, sehingga rantai revisi tidak
    # bisa dibaca apa adanya. Semua kolom nullable kecuali sample_version/current_stage
    # (default 1/OPEN) supaya baris lama tetap valid tanpa menebak alasan revisi.
    sample_version = Column(Integer, default=1, nullable=False)
    previous_version_id = Column(Integer, ForeignKey("sample_records.id"), nullable=True)
    revision_reason = Column(Text, nullable=True)
    current_stage = Column(String(20), default="OPEN", nullable=False, index=True)
    work_started_at = Column(DateTime, nullable=True)
    work_submitted_at = Column(DateTime, nullable=True)
    submitted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    evidence = relationship("SampleEvidence", back_populates="sample", cascade="all, delete-orphan")

class SampleEvidence(Base):
    __tablename__ = "sample_evidence"
    id = Column(Integer, primary_key=True)
    sample_fk = Column(Integer, ForeignKey("sample_records.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    file_mime = Column(String(120), nullable=False)
    file_data = Column(LargeBinary, nullable=False)
    note = Column(Text, nullable=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # Jenis bukti (PROGRESS/INSPECTION/RESULT) tidak lagi ditebak dari substring
    # nama file; `sample_version` mengikat bukti ke versi sample (#34).
    evidence_kind = Column(String(24), nullable=True, index=True)
    sample_version = Column(Integer, default=1, nullable=False)
    uploaded_stage = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sample = relationship("SampleRecord", back_populates="evidence")

class PrintingEvidence(Base):
    """Bukti hasil kerja Printing/Bordir milik satu movement (revisi #45).

    Pola sama dengan SampleEvidence (byte disimpan di DB) tetapi terikat ke
    `production_movements`, bukan ke sample.

    Kolom `handoff_id`/`disposition_id`/`kind` ditambahkan sesuai spesifikasi
    `REQUESTS/printing_schema.md` supaya bukti bisa diikat ke handoff atau
    disposition tertentu, bukan hanya ke movement.
    """
    __tablename__ = "printing_evidence"
    id = Column(Integer, primary_key=True)
    movement_id = Column(Integer, ForeignKey("production_movements.id", ondelete="CASCADE"), nullable=False, index=True)
    handoff_id = Column(Integer, ForeignKey("printing_handoffs.id", ondelete="SET NULL"), nullable=True)
    disposition_id = Column(Integer, ForeignKey("printing_defect_dispositions.id", ondelete="SET NULL"), nullable=True)
    # RESULT / INSPECTION / HANDOFF / REWORK — null berarti belum diklasifikasi.
    kind = Column(String(32), nullable=True)
    file_name = Column(String(255), nullable=False)
    file_mime = Column(String(120), nullable=False)
    file_data = Column(LargeBinary, nullable=False)
    # Alternatif kalau bukti disimpan di luar DB.
    file_path = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PrintingDailyTarget(Base):
    """Target harian Printing/Bordir yang TERSIMPAN (revisi #47).

    Sebelumnya target hanya diturunkan dari `production_movements.target_date`,
    sehingga "menetapkan target" tidak bisa dibedakan dari "mengubah movement"
    dan riwayat perubahannya hilang. Baris terbaru per (process, target_date)
    dengan `version` terbesar adalah target resmi hari itu; `previous_qty`
    menyimpan nilai sebelumnya untuk jejak revisi.
    """
    __tablename__ = "printing_daily_targets"
    id = Column(Integer, primary_key=True)
    process = Column(String(80), nullable=False)            # PRINTING / BORDIR
    target_date = Column(Date, nullable=False, index=True)
    target_qty = Column(Integer, default=0, nullable=False)
    unit = Column(String(20), nullable=True, default="PCS")
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="SET NULL"), nullable=True)
    set_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    set_at = Column(DateTime, nullable=True, default=datetime.utcnow)
    reason = Column(Text, nullable=True)
    version = Column(Integer, default=1, nullable=False)
    previous_qty = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PrintingHandoff(Base):
    """Partial handoff antar proses dengan qty kirim vs terima (revisi #44).

    `production_movements` hanya menyimpan agregat per proses, sehingga selisih
    kirim/terima tidak punya tempat. Baris di sini mencatat selisih itu apa
    adanya; tabel ini **tidak** mengubah `production_movements.qty_done` —
    angka WIP tetap milik COO.
    """
    __tablename__ = "printing_handoffs"
    id = Column(Integer, primary_key=True)
    handoff_no = Column(String(80), unique=True, nullable=False, index=True)
    job_id = Column(String(120), nullable=False, index=True)
    movement_id = Column(Integer, ForeignKey("production_movements.id", ondelete="SET NULL"), nullable=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, index=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    process = Column(String(80), nullable=False)            # PRINTING / BORDIR
    stage = Column(String(80), nullable=True)               # = process (dipakai UI job card)
    next_stage = Column(String(80), nullable=False)
    lot_no = Column(String(80), nullable=True)
    batch_no = Column(String(120), nullable=True)           # Batch ID (revisi #41)
    # `qty_sent` tidak boleh di-overwrite setelah baris dibuat.
    qty_sent = Column(Integer, default=0, nullable=False)
    qty_received = Column(Integer, nullable=True)
    remaining = Column(Integer, nullable=True)              # qty_sent - qty_received
    exception = Column(String(255), nullable=True)          # catatan selisih
    shift = Column(String(64), nullable=True)
    location = Column(String(120), nullable=True)
    evidence_ref = Column(Text, nullable=True)
    sender = Column(String(120), nullable=True)
    receiver = Column(String(120), nullable=True)
    sent_at = Column(DateTime, nullable=True, default=datetime.utcnow)
    received_at = Column(DateTime, nullable=True)
    # SENT / RECEIVED / DISCREPANCY / EXCEPTION
    status = Column(String(32), default="SENT", nullable=False, index=True)
    exception_id = Column(Integer, ForeignKey("exceptions.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PrintingDefectDisposition(Base):
    """Keputusan defect Printing/Bordir: kategori, severity, disposition (revisi #45).

    Sebelumnya kategori/severity hanya diturunkan dari teks
    `qc_records.reject_reason`, sehingga "defect sudah diputuskan" tidak bisa
    dibedakan dari "ada catatan teks". `REWORK`/`REMAKE` menuntut retest sebelum
    handoff berikutnya boleh jalan (ditegakkan router, bukan UI).
    """
    __tablename__ = "printing_defect_dispositions"
    id = Column(Integer, primary_key=True)
    qc_id = Column(Integer, ForeignKey("qc_records.id", ondelete="SET NULL"), nullable=True, index=True)
    job_id = Column(String(120), nullable=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, index=True)
    process = Column(String(80), nullable=True)
    defect_category = Column(String(80), nullable=False)
    defect_detail = Column(Text, nullable=True)
    qty = Column(Integer, default=0, nullable=False)
    origin = Column(String(32), nullable=True)              # PRINTING/BORDIR/SUPPLIER
    severity = Column(String(20), default="MINOR", nullable=False)  # MINOR/MAJOR/CRITICAL
    # REWORK / REMAKE / REJECT / ACCEPT_DEVIATION
    disposition = Column(String(40), nullable=False, index=True)
    rework_owner = Column(String(120), nullable=True)
    rework_due = Column(Date, nullable=True)
    rework_qc_id = Column(Integer, ForeignKey("qc_records.id", ondelete="SET NULL"), nullable=True)
    # REQUIRED / PENDING / PASSED / FAILED
    retest = Column(String(32), nullable=True)
    evidence_ref = Column(Text, nullable=True)
    resolution_evidence_ref = Column(Text, nullable=True)
    reason = Column(Text, nullable=False)                   # wajib diisi
    closed_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class CEOOverride(Base):
    """Registry override CEO yang terkontrol (revisi #74).

    Sebelumnya override hanya "izin lisan": tidak ada jejak siapa meminta, apa
    nilai asal vs usulannya, dan bagaimana membatalkannya. Baris di sini adalah
    satu permintaan override lengkap dengan keputusan CEO, pengakuan penerima,
    dan alasan rollback — bukan sekadar status.

    Nilai `original_value`/`proposed_value` disimpan sebagai teks apa adanya
    supaya bisa menampung tipe berbeda (angka, tanggal, string) tanpa menebak;
    pembacanya yang menafsirkan sesuai `override_type`.
    """
    __tablename__ = "ceo_overrides"
    id = Column(Integer, primary_key=True)
    override_no = Column(String(40), unique=True, nullable=True)
    # PRODUCTION_PRIORITY | PRICING_EXCEPTION | SHIPMENT_OUTSTANDING | PURCHASING_EXCEPTION
    override_type = Column(String(40), nullable=False, index=True)
    # REQUESTED | APPROVED | REJECTED | ROLLED_BACK
    status = Column(String(24), default="REQUESTED", nullable=False, index=True)
    source_module = Column(String(80), nullable=False)
    source_entity = Column(String(80), nullable=False)
    source_entity_id = Column(Integer, nullable=True, index=True)
    affected_entity = Column(String(160), nullable=False)
    original_value = Column(Text, nullable=False)
    proposed_value = Column(Text, nullable=False)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reason = Column(Text, nullable=False)
    impact = Column(Text, nullable=False)
    evidence_ref = Column(Text, nullable=True)
    scope = Column(String(300), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    ceo_decision = Column(String(24), nullable=True)          # APPROVED | REJECTED
    ceo_decision_reason = Column(Text, nullable=True)
    ceo_decided_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ceo_decided_at = Column(DateTime, nullable=True)
    acknowledged_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)
    rollback_reason = Column(Text, nullable=True)
    correction_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


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
    # ── Revisi #20: AP Register supplier vs makloon vs logistik ───────────────
    vendor_type = Column(String(24), nullable=True, index=True)
    vendor_invoice_no = Column(String(120), nullable=True)
    invoice_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True, index=True)
    currency = Column(String(8), nullable=True, default="IDR", server_default="IDR")
    tax_amount = Column(Numeric(18,2), nullable=True, default=0)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approval_status = Column(String(32), nullable=True, default="PENDING")
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
    due_date = Column(Date, nullable=True, index=True)
    # Revisi #17: aging/collection memakai promised date & mata uang invoice;
    # keduanya nullable supaya invoice lama tidak berpindah status apa pun.
    currency = Column(String(8), nullable=True, default="IDR", server_default="IDR")
    promised_date = Column(Date, nullable=True)
    next_action = Column(String(40), nullable=True)
    collection_owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(32), default="UNPAID", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    invoice_no = Column(String(80), nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True, index=True)
    # INT-ORDER-001 poin 3/4: setiap transaksi wajib bisa ditelusuri ke Order ID
    # yang sama. Sebelumnya payment hanya menaut lewat invoice_no (string bebas,
    # bukan FK), sehingga pembayaran bisa yatim dan tidak bisa di-query per order.
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=True, index=True)
    amount = Column(Numeric(18,2), nullable=False)
    payment_date = Column(Date, nullable=True)
    method = Column(String(80), nullable=True)
    notes = Column(Text, nullable=True)
    # ── Revisi #17: PAYMENT_REPORTED → CFO VERIFY/REJECT, dengan bukti ─────────
    # Status lama dibiarkan NULL: modul memperlakukannya sebagai VERIFIED (sama
    # seperti perilaku sebelumnya), jadi tidak ada baris lama yang berubah arti.
    evidence_ref = Column(String(500), nullable=True)
    reported_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reported_at = Column(DateTime, nullable=True)
    verified_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=True, default="REPORTED", index=True)
    rejection_reason = Column(Text, nullable=True)
    currency = Column(String(8), nullable=True, default="IDR", server_default="IDR")
    allocated_invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class APPayment(Base):
    """Ledger pembayaran AP per Purchase Order (revisi #20).

    Sebelumnya tidak ada ledger AP sama sekali; modul mencocokkan pembayaran ke
    PO lewat teks `payments.notes`. Nilai PO yang sudah dibayar harus dihitung
    dari baris nyata di sini, bukan dari tebakan.
    """
    __tablename__ = "ap_payments"
    id = Column(Integer, primary_key=True)
    po_fk = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(18,2), nullable=False)
    payment_date = Column(Date, nullable=True)
    method = Column(String(80), nullable=True)
    evidence_ref = Column(String(500), nullable=True)
    approval_status = Column(String(32), nullable=True, default="PENDING")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class OperationalCostEntry(Base):
    """Register biaya operasional formal (revisi #24).

    `purchase_orders` adalah komitmen pembelian, bukan biaya operasional
    terakui, jadi register ini mulai kosong — tidak ada backfill yang jujur.
    """
    __tablename__ = "operational_cost_entries"
    id = Column(Integer, primary_key=True)
    cost_id = Column(String(40), unique=True, nullable=False)
    category = Column(String(60), nullable=False, index=True)
    classification = Column(String(20), nullable=False, default="NON_HPP")
    department = Column(String(80), nullable=True)
    cost_center = Column(String(80), nullable=True)
    vendor_or_employee = Column(String(180), nullable=True)
    description = Column(Text, nullable=True)
    amount = Column(Numeric(18,2), nullable=False)
    currency = Column(String(8), nullable=False, default="IDR", server_default="IDR")
    fx_rate = Column(Numeric(18,6), nullable=True)
    evidence_ref = Column(Text, nullable=True)
    approval_status = Column(String(32), nullable=False, default="PENDING", server_default="PENDING")
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    payment_status = Column(String(32), nullable=False, default="UNPAID", server_default="UNPAID")
    accounting_period = Column(String(20), nullable=True, index=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True)
    incurred_at = Column(DateTime, nullable=False, index=True)
    reversal_of_id = Column(Integer, ForeignKey("operational_cost_entries.id"), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

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

class ShipmentException(Base):
    """CEO shipment outstanding exception (revisi #75).

    Terikat pada satu Shipment ID, bukan pada order secara umum: persetujuan
    melepas SATU pengiriman tertentu, lalu kedaluwarsa. Persetujuan tidak
    mengubah invoice/paid/outstanding — uangnya tetap tercatat sebagai piutang.
    """
    __tablename__ = "shipment_exceptions"
    id = Column(Integer, primary_key=True)
    exception_no = Column(String(40), nullable=True)
    shipment_fk = Column(Integer, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    buyer = Column(String(160), nullable=True)
    goods_ready = Column(Boolean, default=False, nullable=False)
    lines_json = Column(Text, default="[]", nullable=False)
    shipment_value = Column(Numeric(18, 2), nullable=True)
    invoice_total = Column(Numeric(18, 2), nullable=True)
    invoice_paid = Column(Numeric(18, 2), nullable=True)
    outstanding = Column(Numeric(18, 2), nullable=True)
    payment_terms = Column(String(255), nullable=True)
    payment_due = Column(Date, nullable=True)
    cfo_assessment = Column(Text, nullable=True)
    cfo_status = Column(String(32), nullable=True)
    cfo_assessed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    cfo_assessed_at = Column(DateTime, nullable=True)
    cmo_customer_confirmation = Column(Text, nullable=True)
    cmo_confirmed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    cmo_confirmed_at = Column(DateTime, nullable=True)
    reason = Column(Text, nullable=False)
    risk = Column(Text, nullable=True)
    evidence_ref = Column(Text, nullable=True)
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ceo_decision = Column(String(32), nullable=True)
    ceo_decision_reason = Column(Text, nullable=True)
    ceo_decided_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ceo_decided_at = Column(DateTime, nullable=True)
    valid_until = Column(Date, nullable=True)
    single_release = Column(Boolean, default=True, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


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
    # ── Revisi #62: Employee Master sebagai sumber resmi data SDM ──────────────
    # Semua kolom nullable: baris lama tetap sah dan statusnya "belum diisi",
    # bukan tanggal/status yang dikarang.
    join_date = Column(Date, nullable=True, index=True)
    exit_date = Column(Date, nullable=True)
    contract_type = Column(String(40), nullable=True)
    contract_start_date = Column(Date, nullable=True)
    contract_end_date = Column(Date, nullable=True, index=True)
    manager_name = Column(String(120), nullable=True)
    manager_employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    email = Column(String(180), nullable=True)
    phone = Column(String(40), nullable=True)
    document_ref = Column(String(255), nullable=True)
    # Asal data: baris lama yang belum jelas sumbernya ditandai LEGACY_UNKNOWN,
    # bukan dianggap berasal dari migrasi Lutfi.
    migration_source = Column(String(80), nullable=True)
    migrated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class EmployeeStatusHistory(Base):
    """Riwayat status/divisi/posisi kepegawaian (revisi #62).

    Tanpa tabel ini router HR hanya bisa MENURUNKAN timeline dari created_at,
    training, performance, dan issue — dan itu dilaporkan sebagai turunan.
    Baris di sini adalah riwayat apa adanya: perubahan status, divisi, posisi
    beserta aktor, alasan, dan bukti.
    """
    __tablename__ = "employee_status_history"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    effective_date = Column(Date, nullable=True, index=True)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=True)
    reason = Column(Text, nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_name = Column(String(120), nullable=True)
    source = Column(String(80), nullable=True)
    evidence_ref = Column(String(255), nullable=True)
    version = Column(Integer, default=1, nullable=False)
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
    # Revisi #72: keputusan harus bisa ditelusuri asalnya dan dijalankan.
    # `decision_type`/`action_status`/`owner_name` tetap ada untuk kompatibilitas,
    # tapi sekarang divalidasi terhadap daftar bertipe dan owner diambil dari user.
    source_module = Column(String(80), nullable=True)
    source_entity = Column(String(80), nullable=True)
    source_entity_id = Column(Integer, nullable=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    context = Column(Text, nullable=True)
    evidence_ref = Column(Text, nullable=True)
    options_json = Column(Text, default="[]", nullable=False)
    recommendation = Column(Text, nullable=True)
    impact_financial = Column(Text, nullable=True)
    impact_operational = Column(Text, nullable=True)
    impact_customer = Column(Text, nullable=True)
    impact_people = Column(Text, nullable=True)
    decision_owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decision_action = Column(String(32), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    version = Column(Integer, default=1, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CEOActionItem(Base):
    """Action Tracker (revisi #72).

    Keputusan yang butuh pelaksanaan membuat Action ID tersendiri. Penyelesaian
    ditentukan bukti pelaksanaan (`completion_note` + `verified_by`), bukan
    sekadar mengganti dropdown status.
    """
    __tablename__ = "ceo_action_items"
    id = Column(Integer, primary_key=True)
    action_no = Column(String(40), nullable=True)
    decision_fk = Column(Integer, ForeignKey("ceo_decisions.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    authorized_owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    due_date = Column(Date, nullable=True)
    status = Column(String(32), default="OPEN", nullable=False)
    next_follow_up = Column(Date, nullable=True)
    completion_note = Column(Text, nullable=True)
    evidence_ref = Column(Text, nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    overdue_escalated = Column(Boolean, default=False, nullable=False)
    verified_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class SystemConfig(Base):
    __tablename__ = "system_config"
    id = Column(Integer, primary_key=True)
    key = Column(String(120), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, onupdate=datetime.utcnow, nullable=False)


class BusinessPolicyVersion(Base):
    """Riwayat kebijakan bisnis (revisi #76).

    Policy sebelumnya hanya satu baris JSON yang ditimpa, sehingga versi lama,
    tanggal berlaku, alasan perubahan, dan nilai sebelumnya hilang. Tabel ini
    menyimpan tiap versi sebagai baris tersendiri; policy yang berlaku adalah
    versi dengan effective_from <= hari ini dan nonaktif_at masih NULL.
    """
    __tablename__ = "business_policy_versions"
    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)
    policy_json = Column(Text, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    change_reason = Column(Text, nullable=False)
    previous_json = Column(Text, nullable=True)
    proposed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

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


# ═══════════════════════ BATCH 2 — CMO/SAMPLE (#31-#37) ═══════════════════════
class SampleVersion(Base):
    """Versi sample + keputusan buyer PER versi (SMP-F-006 / revisi #32/#36).

    Sebelumnya keputusan buyer melekat pada `sample_records`, sehingga revisi
    sample baru menimpa keputusan lama dan "approved = immutable" tidak bisa
    dibuktikan per versi.
    """
    __tablename__ = "sample_versions"
    __table_args__ = (UniqueConstraint("sample_fk", "version", name="uq_sample_version_per_sample"),)
    id = Column(Integer, primary_key=True)
    sample_fk = Column(Integer, ForeignKey("sample_records.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    ppm_version = Column(Integer, nullable=True)
    ppm_reference = Column(String(120), nullable=True)
    submitted = Column(Boolean, default=False, nullable=False)
    submitted_at = Column(DateTime, nullable=True)
    submitted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    required_evidence_json = Column(Text, default="[]", nullable=False)
    decision = Column(String(16), nullable=True)
    decided_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SampleTask(Base):
    """Task sample eksplisit + lifecycle (SMP-F-005 / revisi #35).

    Sebelumnya lifecycle sample DISIMPULKAN dari kelengkapan bukti dan catatan
    bebas, sehingga START/INSPECTION/SUBMIT_RESULT tidak punya jejak waktu dan
    SLA per task tidak bisa disimpan.
    """
    __tablename__ = "sample_tasks"
    id = Column(Integer, primary_key=True)
    task_no = Column(String(40), unique=True, nullable=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=True, index=True)
    sample_fk = Column(Integer, ForeignKey("sample_records.id", ondelete="SET NULL"), nullable=True, index=True)
    sample_version = Column(Integer, default=1, nullable=False)
    stage = Column(String(20), default="OPEN", nullable=False, index=True)
    status = Column(String(32), default="OPEN", nullable=False)
    priority = Column(String(16), default="NORMAL", nullable=False)
    required_action = Column(String(40), nullable=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    due_date = Column(Date, nullable=True)
    sla_source = Column(String(40), nullable=True)
    bottleneck_reason = Column(Text, nullable=True)
    blocker_owner = Column(String(40), nullable=True)
    next_action = Column(Text, nullable=True)
    handoff = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    done_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SampleTaskPrerequisite(Base):
    """Prasyarat task sample — jejak kapan & bukti apa yang memenuhinya (#35)."""
    __tablename__ = "sample_task_prerequisites"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("sample_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_key = Column(String(60), nullable=False)
    label = Column(String(200), nullable=True)
    satisfied = Column(Boolean, default=False, nullable=False)
    satisfied_at = Column(DateTime, nullable=True)
    evidence_fk = Column(Integer, ForeignKey("sample_evidence.id", ondelete="SET NULL"), nullable=True)


# ══════════════════════ BATCH 2 — HR (#62-#66) ══════════════════════
class ManpowerRequest(Base):
    """Permintaan tenaga kerja (Revisi #63 HR-Y-003)."""
    __tablename__ = "manpower_requests"
    id = Column(Integer, primary_key=True)
    request_no = Column(String(40), unique=True, nullable=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    division = Column(String(120), nullable=True, index=True)
    position = Column(String(120), nullable=True)
    qty = Column(Integer, default=1, nullable=False)
    reason = Column(Text, nullable=True)
    requirement = Column(Text, nullable=True)
    priority = Column(String(20), default="NORMAL", nullable=False)
    target_start_date = Column(Date, nullable=True)
    budget_ref = Column(String(120), nullable=True)
    payroll_ref = Column(String(120), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    due_date = Column(Date, nullable=True, index=True)
    status = Column(String(32), default="SUBMITTED", nullable=False, index=True)
    decision = Column(String(32), nullable=True, index=True)
    decision_reason = Column(Text, nullable=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class RecruitmentVacancy(Base):
    __tablename__ = "recruitment_vacancies"
    id = Column(Integer, primary_key=True)
    manpower_request_fk = Column(Integer, ForeignKey("manpower_requests.id", ondelete="SET NULL"), nullable=True, index=True)
    vacancy_no = Column(String(40), unique=True, nullable=True)
    source = Column(String(80), nullable=True)
    status = Column(String(32), default="OPEN", nullable=False, index=True)
    opened_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class RecruitmentCandidate(Base):
    """Kandidat rekrutmen (Revisi #63 HR-Y-003).

    `employee_fk` hanya terisi setelah keputusan hire yang sah, jadi tidak ada
    kandidat yang diam-diam dihitung sebagai karyawan.
    """
    __tablename__ = "recruitment_candidates"
    id = Column(Integer, primary_key=True)
    candidate_no = Column(String(40), unique=True, nullable=True)
    vacancy_fk = Column(Integer, ForeignKey("recruitment_vacancies.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(160), nullable=True)
    source = Column(String(80), nullable=True)
    contact = Column(String(160), nullable=True)
    cv_evidence_ref = Column(Text, nullable=True)
    screening_result = Column(String(32), nullable=True)
    screening_notes = Column(Text, nullable=True)
    interview_scheduled_at = Column(DateTime, nullable=True)
    interviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    interview_result = Column(String(32), nullable=True)
    interview_score = Column(Float, nullable=True)
    manager_assessment = Column(Text, nullable=True)
    decision = Column(String(32), nullable=True, index=True)
    offer_amount = Column(Float, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    rejected_reason = Column(Text, nullable=True)
    next_action = Column(String(200), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(32), default="NEW", nullable=False, index=True)
    employee_fk = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PayrollHandoff(Base):
    """HR → Payroll handoff (Revisi #62/#64).

    HR hanya MEMBUAT handoff; CFO yang mem-posting nilai finansialnya. HR tidak
    pernah mengubah transaksi payroll.
    """
    __tablename__ = "payroll_handoffs"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    employee_fk = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    onboarding_fk = Column(Integer, ForeignKey("onboarding_programs.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(32), nullable=True)
    effective_date = Column(Date, nullable=True, index=True)
    status_code = Column(String(32), nullable=True)
    salary_reference = Column(String(120), nullable=True)
    division_salary_ref = Column(String(120), nullable=True)
    reason = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    requested_at = Column(DateTime, nullable=True)
    cfo_status = Column(String(32), default="PENDING", nullable=False, index=True)
    cfo_acted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    cfo_acted_at = Column(DateTime, nullable=True)
    read_by_cfo_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    read_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class OnboardingProgram(Base):
    """Onboarding & training pasca-hire (Revisi #64 HR-Y-004).

    PASS → aktivasi `employment_status` + buat payroll handoff; EXTEND wajib
    menyertakan `extend_days` dan alasan.
    """
    __tablename__ = "onboarding_programs"
    id = Column(Integer, primary_key=True)
    candidate_fk = Column(Integer, ForeignKey("recruitment_candidates.id", ondelete="SET NULL"), nullable=True, index=True)
    employee_fk = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    position = Column(String(120), nullable=True)
    training_start = Column(Date, nullable=True)
    training_end = Column(Date, nullable=True)
    mentor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    manager_evaluator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    checklist_json = Column(Text, default="[]", nullable=False)
    attendance_ref = Column(String(120), nullable=True)
    skill_evidence_ref = Column(Text, nullable=True)
    issue_blocker = Column(Text, nullable=True)
    progress_pct = Column(Integer, default=0, nullable=False)
    due_date = Column(Date, nullable=True)
    salary_category = Column(String(80), nullable=True)
    salary_rate = Column(Float, nullable=True)
    decision = Column(String(16), nullable=True, index=True)
    decision_reason = Column(Text, nullable=True)
    extend_days = Column(Integer, nullable=True)
    effective_date = Column(Date, nullable=True)
    payroll_handoff_fk = Column(Integer, ForeignKey("payroll_handoffs.id", ondelete="SET NULL"), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PerformanceReviewCycle(Base):
    """Siklus penilaian kinerja (Revisi #65 HR-Y-005)."""
    __tablename__ = "performance_review_cycles"
    id = Column(Integer, primary_key=True)
    period = Column(String(60), nullable=True, index=True)
    cycle_name = Column(String(160), nullable=True)
    weight_config_json = Column(Text, default="{}", nullable=False)
    scoring_rule_json = Column(Text, default="{}", nullable=False)
    status = Column(String(32), default="DRAFT", nullable=False, index=True)
    opened_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PerformanceReviewDetail(Base):
    """Detail review per karyawan (Revisi #65).

    Review final tidak ditimpa: koreksi lewat `version` baru + `correction_reason`.
    """
    __tablename__ = "performance_review_details"
    __table_args__ = (UniqueConstraint("cycle_fk", "performance_record_fk", name="uq_review_detail_cycle_record"),)
    id = Column(Integer, primary_key=True)
    cycle_fk = Column(Integer, ForeignKey("performance_review_cycles.id", ondelete="CASCADE"), nullable=False, index=True)
    performance_record_fk = Column(Integer, ForeignKey("performance_records.id", ondelete="SET NULL"), nullable=True, index=True)
    employee_fk = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    evaluator_manager_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    evaluator_is_manager = Column(Boolean, default=False, nullable=False)
    evidence_ref = Column(Text, nullable=True)
    strengths = Column(Text, nullable=True)
    gaps = Column(Text, nullable=True)
    improvement_action = Column(Text, nullable=True)
    action_owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action_due = Column(Date, nullable=True)
    employee_acknowledged_at = Column(DateTime, nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="DRAFT", nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    correction_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class EmployeeCaseDetail(Base):
    """Kasus kepegawaian (Revisi #66 HR-Y-006).

    `confidential = true` → hanya owner role HR + CEO yang boleh membaca
    detailnya. Eskalasi ke CEO hanya untuk kasus RED dan wajib tercatat.
    """
    __tablename__ = "employee_case_details"
    id = Column(Integer, primary_key=True)
    issue_fk = Column(Integer, ForeignKey("employee_issues.id", ondelete="SET NULL"), nullable=True, index=True)
    case_no = Column(String(40), unique=True, nullable=True)
    category = Column(String(80), nullable=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    occurred_date = Column(Date, nullable=True)
    reported_date = Column(Date, nullable=True)
    confidential = Column(Boolean, default=False, nullable=False, index=True)
    investigator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    due_date = Column(Date, nullable=True)
    sla_hours = Column(Integer, nullable=True)
    investigation_finding = Column(Text, nullable=True)
    action_plan = Column(Text, nullable=True)
    employee_response = Column(Text, nullable=True)
    manager_response = Column(Text, nullable=True)
    decision = Column(String(32), nullable=True)
    decision_reason = Column(Text, nullable=True)
    follow_up_date = Column(Date, nullable=True)
    resolution_evidence_ref = Column(Text, nullable=True)
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    closed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    escalated_to_ceo = Column(Boolean, default=False, nullable=False, index=True)
    escalated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    escalation_reason = Column(Text, nullable=True)
    ceo_decision_fk = Column(Integer, ForeignKey("ceo_decisions.id", ondelete="SET NULL"), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class EmployeeCaseEvidence(Base):
    """Bukti kasus kepegawaian dengan tingkat akses eksplisit (Revisi #66)."""
    __tablename__ = "employee_case_evidence"
    id = Column(Integer, primary_key=True)
    case_fk = Column(Integer, ForeignKey("employee_case_details.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_ref = Column(Text, nullable=True)
    access_level = Column(String(32), nullable=True, index=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class EmployeeCaseAccessLog(Base):
    """Jejak setiap pembukaan bukti kasus confidential (Revisi #66)."""
    __tablename__ = "employee_case_access_log"
    id = Column(Integer, primary_key=True)
    case_fk = Column(Integer, ForeignKey("employee_case_details.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(32), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class EmployeeIssueEscalation(Base):
    """Jejak eskalasi issue ke CEO (Revisi #66) — tanpa ini eskalasi dilarang.

    `reason` NOT NULL `server_default=''`: baris lama (kalau ada) tetap sah, tapi
    setiap eskalasi baru wajib mengisi alasannya di lapisan aplikasi.
    """
    __tablename__ = "employee_issue_escalations"
    id = Column(Integer, primary_key=True)
    issue_fk = Column(Integer, ForeignKey("employee_issues.id", ondelete="CASCADE"), nullable=False, index=True)
    escalated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    escalated_at = Column(DateTime, nullable=True)
    reason = Column(Text, nullable=False, server_default="")
    ceo_decision_fk = Column(Integer, ForeignKey("ceo_decisions.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ═══════════════════════ BATCH 2 — COO (#53-#57) ═══════════════════════
class ProductionHandoff(Base):
    """Handoff antar proses produksi (revisi #54).

    Qty Sent tidak boleh ditimpa; `qty_received` dicatat terpisah sehingga
    selisihnya (discrepancy) bisa diaudit, bukan disimpulkan ulang dari agregat
    `production_movements`.
    """
    __tablename__ = "production_handoffs"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=True, index=True)
    handoff_no = Column(String(64), unique=True, nullable=True)
    from_process = Column(String(80), nullable=True)
    to_process = Column(String(80), nullable=True)
    batch_no = Column(String(64), nullable=True)
    qty_sent = Column(Integer, default=0, nullable=False)
    qty_received = Column(Integer, default=0, nullable=False)
    discrepancy = Column(Integer, default=0, nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sent_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=True)
    evidence_ref = Column(Text, nullable=True)
    shift = Column(String(32), nullable=True)
    location = Column(String(80), nullable=True)
    status = Column(String(32), default="PENDING_RECEIPT", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
