"""Batch 2 schema: tabel & kolom yang diminta anak batch 1 (revisi #13-#67).

Satu migrasi untuk seluruh kebutuhan tabel/kolom yang dititipkan lewat
REQUESTS/*.md, KECUALI tabel Printing (handoff/target/makloon) yang menjadi
milik agent printing di grup yang sama — lihat REQUESTS/schema_to_routers.md.

Prinsip yang dipegang:

* **Idempoten.** Tabel dibuat hanya kalau belum ada, kolom ditambahkan hanya
  kalau belum ada, index dibuat hanya kalau belum ada. Menjalankan ulang
  migration ini di DB yang sudah sebagian bermigrasi tidak boleh gagal.
* **Tidak merusak data produksi.** Tidak ada satu pun `DROP`, `DELETE`, atau
  penulisan ulang nilai lama. Kolom baru yang `nullable=False` diberi
  `server_default` supaya baris lama tetap valid tanpa disentuh; kolom baru
  yang tidak punya default jujur dibiarkan NULL ("belum diisi").
* **Backfill hanya kalau nilainya memang sudah ada** di DB — kalau tidak, kolom
  dibiarkan NULL dan itu dilaporkan, bukan dikarang:
  - `employees.join_date` ← `created_at` (TANGGAL DIBUAT, bukan tanggal masuk
    sebenarnya) dan WAJIB ditandai `migration_source='LEGACY_JOIN_DATE_ESTIMATE'`.
  - `sample_versions` v1 untuk tiap `sample_records`, keputusan buyer disalin
    dari `customer_*` yang sudah ada.
  - `exceptions.sample_fk` ← `source_entity='SampleRecord'` + `source_entity_id`.
  - `employees.migration_source` = `'LEGACY_UNKNOWN'` selama masih NULL,
    artinya "asalnya belum jelas" — bukan klaim hasil migrasi Lutfi.
* **Portabel SQLite ↔ PostgreSQL.** Hanya `sa.text` dengan operator yang sama di
  keduanya; tidak ada `sa.func`, tidak ada dialek khusus, tidak ada bind angka
  untuk kolom boolean.
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_batch2_schema"
down_revision = "0022_payment_order_link"
branch_labels = None
depends_on = None


# ───────────────────────────────── helpers ─────────────────────────────────
def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return _inspector().has_table(name)


def _columns(table):
    if not _has_table(table):
        return set()
    return {c["name"] for c in _inspector().get_columns(table)}


def _indexes(table):
    if not _has_table(table):
        return set()
    return {i["name"] for i in _inspector().get_indexes(table)}


def _add_column(table, column):
    """Tambah kolom kalau belum ada; lewati kalau tabelnya belum ada."""
    if not _has_table(table):
        print(f"[0023] SKIP {table}.{column.name}: tabel belum ada")
        return False
    if column.name in _columns(table):
        return False
    with op.batch_alter_table(table) as batch:
        batch.add_column(column)
    return True


def _create_index(name, table, columns, unique=False):
    if not _has_table(table) or name in _indexes(table):
        return False
    op.create_index(name, table, columns, unique=unique)
    return True


def _create_table(name, *columns, **kwargs):
    """Buat tabel hanya kalau belum ada (idempoten, tidak pernah drop)."""
    if _has_table(name):
        print(f"[0023] SKIP {name}: tabel sudah ada")
        return False
    op.create_table(name, *columns, **kwargs)
    return True


def _scalar(sql_text, **params):
    return op.get_bind().execute(sa.text(sql_text), params).scalar()


def _execute(sql_text, **params):
    return op.get_bind().execute(sa.text(sql_text), params)


NOW_DEFAULT = sa.text("CURRENT_TIMESTAMP")


def upgrade():
    _upgrade_employees()
    _upgrade_sample()
    _upgrade_finance()
    _upgrade_production()
    _hr_recruitment_tables()
    _hr_lifecycle_tables()
    _hr_case_tables()
    _coo_tables()


# ═══════════════════════════ 1. employees & HR (#62) ═══════════════════════════
def _upgrade_employees():
    employee_columns = (
        sa.Column("join_date", sa.Date(), nullable=True),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("contract_type", sa.String(length=40), nullable=True),
        sa.Column("contract_start_date", sa.Date(), nullable=True),
        sa.Column("contract_end_date", sa.Date(), nullable=True),
        sa.Column("manager_name", sa.String(length=120), nullable=True),
        sa.Column("manager_employee_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=180), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("document_ref", sa.String(length=255), nullable=True),
        sa.Column("migration_source", sa.String(length=80), nullable=True),
        sa.Column("migrated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    added = [c.name for c in employee_columns if _add_column("employees", c)]
    if added:
        print(f"[0023] employees: kolom ditambahkan: {', '.join(added)}")
    _create_index("ix_employees_join_date", "employees", ["join_date"])
    _create_index("ix_employees_contract_end_date", "employees", ["contract_end_date"])
    _create_index("ix_employees_manager_employee_id", "employees", ["manager_employee_id"])
    if not _has_table("employees"):
        return

    # Backfill jujur: created_at hanyalah PERKIRAAN, jadi ditandai.
    #
    # CATATAN PORTABILITAS (bug produksi nyata): `CAST(created_at AS DATE)` tidak
    # portabel karena di SQLite hasilnya integer tahun ("2026"), bukan tanggal.
    # Tetapi `SUBSTR(created_at, 1, 10)` JUSTRU GAGAL di PostgreSQL —
    # `substr(timestamp, int, int)` tidak ada:
    #   ProgrammingError: function substr(timestamp without time zone, integer,
    #   integer) does not exist
    # SQLite menerima keduanya (kolomnya bertipe longgar), jadi bug ini lolos
    # seluruh tes lokal dan baru muncul saat deploy.
    #
    # Solusinya: SUBSTR dipakai HANYA bila kolomnya benar-benar teks (SQLite),
    # dan CAST(... AS DATE) dipakai di PostgreSQL. `created_at` di SQLite
    # tersimpan sebagai TEXT sehingga SUBSTR aman di sana.
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        join_date_sql = "CAST(created_at AS DATE)"
    else:
        join_date_sql = "SUBSTR(CAST(created_at AS TEXT), 1, 10)"
    estimated = _execute(
        "UPDATE employees SET join_date = " + join_date_sql + " "
        "WHERE join_date IS NULL AND created_at IS NOT NULL"
    ).rowcount
    flagged = _execute(
        "UPDATE employees SET migration_source = 'LEGACY_JOIN_DATE_ESTIMATE' "
        "WHERE migration_source IS NULL AND join_date IS NOT NULL"
    ).rowcount
    unknown = _execute(
        "UPDATE employees SET migration_source = 'LEGACY_UNKNOWN' "
        "WHERE migration_source IS NULL"
    ).rowcount
    print(f"[0023] employees.join_date ditaksir dari created_at: {estimated}; "
          f"ditandai LEGACY_JOIN_DATE_ESTIMATE: {flagged}; "
          f"asal belum jelas (LEGACY_UNKNOWN): {unknown}")

    _create_table(
        "employee_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_name", sa.String(length=120), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("evidence_ref", sa.String(length=255), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    _create_index("ix_employee_status_history_employee_id", "employee_status_history", ["employee_id"])
    _create_index("ix_employee_status_history_effective_date", "employee_status_history", ["effective_date"])


# ═══════════════════════ 2. Sample: versi, task, evidence (#31-#37) ═══════════════════════
def _upgrade_sample():
    for column in (
        sa.Column("sample_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("previous_version_id", sa.Integer(), nullable=True),
        sa.Column("revision_reason", sa.Text(), nullable=True),
        sa.Column("current_stage", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("work_started_at", sa.DateTime(), nullable=True),
        sa.Column("work_submitted_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_by_id", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
    ):
        _add_column("sample_records", column)
    _create_index("ix_sample_records_current_stage", "sample_records", ["current_stage"])

    for column in (
        sa.Column("evidence_kind", sa.String(length=24), nullable=True),
        sa.Column("sample_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("uploaded_stage", sa.String(length=20), nullable=True),
    ):
        _add_column("sample_evidence", column)
    _create_index("ix_sample_evidence_evidence_kind", "sample_evidence", ["evidence_kind"])

    _create_table(
        "sample_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sample_fk", sa.Integer(), sa.ForeignKey("sample_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ppm_version", sa.Integer(), nullable=True),
        sa.Column("ppm_reference", sa.String(length=120), nullable=True),
        sa.Column("submitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("required_evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("decided_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.UniqueConstraint("sample_fk", "version", name="uq_sample_version_per_sample"),
    )
    _create_index("ix_sample_versions_sample_fk", "sample_versions", ["sample_fk"])

    _create_table(
        "sample_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_no", sa.String(length=40), unique=True, nullable=True),
        sa.Column("order_fk", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=True),
        sa.Column("sample_fk", sa.Integer(), sa.ForeignKey("sample_records.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sample_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("stage", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OPEN"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="NORMAL"),
        sa.Column("required_action", sa.String(length=40), nullable=True),
        sa.Column("assigned_to_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("sla_source", sa.String(length=40), nullable=True),
        sa.Column("bottleneck_reason", sa.Text(), nullable=True),
        sa.Column("blocker_owner", sa.String(length=40), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("handoff", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("order_fk", "article_id", "sample_fk", "assigned_to_id", "stage"):
        _create_index(f"ix_sample_tasks_{name}", "sample_tasks", [name])

    _create_table(
        "sample_task_prerequisites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("sample_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requirement_key", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("satisfied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("satisfied_at", sa.DateTime(), nullable=True),
        sa.Column("evidence_fk", sa.Integer(), sa.ForeignKey("sample_evidence.id", ondelete="SET NULL"), nullable=True),
    )
    _create_index("ix_sample_task_prerequisites_task_id", "sample_task_prerequisites", ["task_id"])

    # Exceptions ↔ sample (#37): kolom dulu, baru backfill dari string lama.
    for column in (
        sa.Column("sample_fk", sa.Integer(), nullable=True),
        sa.Column("sample_version", sa.Integer(), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=True),
    ):
        _add_column("exceptions", column)
    _create_index("ix_exceptions_sample_fk", "exceptions", ["sample_fk"])

    _backfill_sample_versions()
    _backfill_sample_evidence_kinds()
    _backfill_exception_sample_links()


def _backfill_sample_versions():
    """Bikin versi v1 untuk tiap sample lama — hanya kalau belum ada barisnya.

    Keputusan buyer disalin dari kolom `sample_records` yang SUDAH ada
    (`customer_approved_by_id`/`customer_decision_at`/`status`), jadi tidak ada
    keputusan yang dikarang; `sample_version` diisi dari kolom eksplisit kalau
    sudah terisi, kalau belum dipakai default 1 dan itu bukan klaim versi lama.
    """
    if not (_has_table("sample_versions") and _has_table("sample_records")):
        return
    missing = _scalar(
        "SELECT count(*) FROM sample_records r "
        "WHERE NOT EXISTS (SELECT 1 FROM sample_versions v WHERE v.sample_fk = r.id)"
    ) or 0
    if not missing:
        print("[0023] sample_versions: tidak ada sample lama yang belum punya versi")
        return
    # PORTABILITAS BOOLEAN (bug produksi nyata): `CASE WHEN ... THEN 0 ELSE 1 END`
    # diterima SQLite (boolean = integer), tetapi PostgreSQL menolaknya dengan
    #   DatatypeMismatch: column "submitted" is of type boolean but expression
    #   is of type integer
    # Jadi literal TRUE/FALSE yang dipakai — sah di kedua database.
    _execute(
        "INSERT INTO sample_versions "
        "(sample_fk, version, ppm_version, ppm_reference, submitted, submitted_at, "
        " submitted_by_id, required_evidence_json, decision, decided_by_id, decided_at, "
        " decision_reason, created_at) "
        "SELECT r.id, "
        "       CASE WHEN r.sample_version IS NULL OR r.sample_version < 1 THEN 1 ELSE r.sample_version END, "
        "       NULL, NULL, "
        "       CASE WHEN r.submitted_at IS NULL THEN FALSE ELSE TRUE END, "
        "       r.submitted_at, r.submitted_by_id, '[]', "
        "       CASE WHEN r.status = 'APPROVED' THEN 'APPROVED' "
        "            WHEN r.status = 'REJECTED' THEN 'REJECTED' ELSE NULL END, "
        "       r.customer_approved_by_id, r.customer_decision_at, r.customer_decision_reason, "
        "       CURRENT_TIMESTAMP "
        "FROM sample_records r "
        "WHERE NOT EXISTS (SELECT 1 FROM sample_versions v WHERE v.sample_fk = r.id)"
    )
    created = _scalar("SELECT count(*) FROM sample_versions") or 0
    with_decision = _scalar("SELECT count(*) FROM sample_versions WHERE decision IS NOT NULL") or 0
    print(f"[0023] sample_versions dibuat dari sample lama: {missing}; "
          f"total baris: {created}; membawa keputusan buyer lama: {with_decision}")


def _backfill_sample_evidence_kinds():
    """Bukti lama tidak punya jenis; 'PROGRESS' adalah label konservatif.

    Bukti lama dibuat sebelum jenis bukti ada, jadi tidak ada informasi untuk
    mengklasifikasikannya. Menandainya PROGRESS lebih aman daripada menebak
    INSPECTION/RESULT — aturan "DONE butuh seluruh required evidence" tidak boleh
    melepas task karena tebakan.
    """
    if not (_has_table("sample_evidence") and "evidence_kind" in _columns("sample_evidence")):
        return
    updated = _execute(
        "UPDATE sample_evidence SET evidence_kind = 'PROGRESS' WHERE evidence_kind IS NULL"
    ).rowcount
    print(f"[0023] sample_evidence.evidence_kind diisi PROGRESS untuk bukti lama: {updated}")


def _backfill_exception_sample_links():
    """Exception sample lama diikat lewat `source_entity`, bukan dikarang."""
    if not (_has_table("exceptions") and "sample_fk" in _columns("exceptions")):
        return
    linked = _execute(
        "UPDATE exceptions SET sample_fk = source_entity_id, scope = 'SAMPLE' "
        "WHERE sample_fk IS NULL AND source_entity = 'SampleRecord' "
        "AND source_entity_id IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM sample_records r WHERE r.id = exceptions.source_entity_id)"
    ).rowcount
    orphan = _scalar(
        "SELECT count(*) FROM exceptions WHERE sample_fk IS NULL "
        "AND source_entity = 'SampleRecord' AND source_entity_id IS NOT NULL"
    ) or 0
    print(f"[0023] exceptions.sample_fk terisi dari source_entity: {linked}; "
          f"masih NULL (sample-nya tidak ada): {orphan}")


# ═══════════════════════ 3. CFO: operational cost & AP (#17/#20/#24) ═══════════════════════
def _upgrade_finance():
    for column in (
        sa.Column("vendor_type", sa.String(length=24), nullable=True),
        sa.Column("vendor_invoice_no", sa.String(length=120), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True, server_default="IDR"),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=True, server_default="0"),
        sa.Column("approved_by_id", sa.Integer(), nullable=True),
        sa.Column("approval_status", sa.String(length=32), nullable=True, server_default="PENDING"),
    ):
        _add_column("purchase_orders", column)
    for name in ("vendor_type", "due_date"):
        _create_index(f"ix_purchase_orders_{name}", "purchase_orders", [name])

    for column in (
        sa.Column("currency", sa.String(length=8), nullable=True, server_default="IDR"),
        sa.Column("promised_date", sa.Date(), nullable=True),
        sa.Column("next_action", sa.String(length=40), nullable=True),
        sa.Column("collection_owner_id", sa.Integer(), nullable=True),
    ):
        _add_column("invoices", column)
    _create_index("ix_invoices_due_date", "invoices", ["due_date"])

    # Status pembayaran lama dibiarkan NULL: modul memperlakukannya sebagai
    # VERIFIED (perilaku sebelumnya), jadi tidak ada baris lama yang berubah arti.
    for column in (
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("reported_by_id", sa.Integer(), nullable=True),
        sa.Column("reported_at", sa.DateTime(), nullable=True),
        sa.Column("verified_by_id", sa.Integer(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True, server_default="REPORTED"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True, server_default="IDR"),
        sa.Column("allocated_invoice_id", sa.Integer(), nullable=True),
    ):
        _add_column("payments", column)
    _create_index("ix_payments_status", "payments", ["status"])

    _create_table(
        "ap_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("po_fk", sa.Integer(), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("method", sa.String(length=80), nullable=True),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("approval_status", sa.String(length=32), nullable=True, server_default="PENDING"),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    _create_index("ix_ap_payments_po_fk", "ap_payments", ["po_fk"])

    _create_table(
        "operational_cost_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cost_id", sa.String(length=40), unique=True, nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("classification", sa.String(length=20), nullable=False, server_default="NON_HPP"),
        sa.Column("department", sa.String(length=80), nullable=True),
        sa.Column("cost_center", sa.String(length=80), nullable=True),
        sa.Column("vendor_or_employee", sa.String(length=180), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="IDR"),
        sa.Column("fx_rate", sa.Numeric(18, 6), nullable=True),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("payment_status", sa.String(length=32), nullable=False, server_default="UNPAID"),
        sa.Column("accounting_period", sa.String(length=20), nullable=True),
        sa.Column("order_fk", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=True),
        sa.Column("incurred_at", sa.DateTime(), nullable=False),
        sa.Column("reversal_of_id", sa.Integer(), sa.ForeignKey("operational_cost_entries.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("category", "accounting_period", "incurred_at", "order_fk"):
        _create_index(f"ix_operational_cost_entries_{name}", "operational_cost_entries", [name])


# ═══════════════════════ 4. Produksi: movement, handoff, printing evidence ═══════════════════════
def _upgrade_production():
    for column in (
        sa.Column("job_notes", sa.Text(), nullable=True),
        sa.Column("colors", sa.String(length=255), nullable=True),
        sa.Column("placement", sa.String(length=255), nullable=True),
        sa.Column("size_spec", sa.Text(), nullable=True),
        sa.Column("technique", sa.String(length=120), nullable=True),
        sa.Column("vendor_type", sa.String(length=32), nullable=True),
        sa.Column("machine", sa.String(length=120), nullable=True),
        sa.Column("team", sa.String(length=80), nullable=True),
        sa.Column("shift", sa.String(length=64), nullable=True),
        sa.Column("requirement_version", sa.String(length=120), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column("route_version", sa.String(length=40), nullable=True),
        sa.Column("approved_artwork_version", sa.String(length=60), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("sla_due_date", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    ):
        _add_column("production_movements", column)
    for name in ("requirement_version", "batch_id"):
        _create_index(f"ix_production_movements_{name}", "production_movements", [name])

    _create_table(
        "production_handoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_fk", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=True),
        sa.Column("handoff_no", sa.String(length=64), unique=True, nullable=True),
        sa.Column("from_process", sa.String(length=80), nullable=True),
        sa.Column("to_process", sa.String(length=80), nullable=True),
        sa.Column("batch_no", sa.String(length=64), nullable=True),
        sa.Column("qty_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qty_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discrepancy", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("receiver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("shift", sa.String(length=32), nullable=True),
        sa.Column("location", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING_RECEIPT"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("order_fk", "article_id"):
        _create_index(f"ix_production_handoffs_{name}", "production_handoffs", [name])

    # Kolom penghubung movement → handoff (revisi #54). FK-nya dibuat lewat
    # batch_alter_table: di SQLite FK hanya bisa dipasang saat tabel di-recreate,
    # dan Alembic yang melakukannya — bukan saya yang menulis DDL manual.
    if _has_table("production_movements") and "handoff_id" not in _columns("production_movements"):
        if _has_table("production_handoffs"):
            with op.batch_alter_table("production_movements", recreate="auto") as batch:
                batch.add_column(sa.Column("handoff_id", sa.Integer(), nullable=True))
        else:
            with op.batch_alter_table("production_movements") as batch:
                batch.add_column(sa.Column("handoff_id", sa.Integer(), nullable=True))
    _create_index("ix_production_movements_handoff_id", "production_movements", ["handoff_id"])

    _create_table(
        "printing_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("movement_id", sa.Integer(), sa.ForeignKey("production_movements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_mime", sa.String(length=120), nullable=False),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    _create_index("ix_printing_evidence_movement_id", "printing_evidence", ["movement_id"])


# ═══════════════════════ 5. HR: recruitment (#63) ═══════════════════════
def _hr_recruitment_tables():
    _create_table(
        "manpower_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_no", sa.String(length=40), unique=True, nullable=True),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("division", sa.String(length=120), nullable=True),
        sa.Column("position", sa.String(length=120), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requirement", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="NORMAL"),
        sa.Column("target_start_date", sa.Date(), nullable=True),
        sa.Column("budget_ref", sa.String(length=120), nullable=True),
        sa.Column("payroll_ref", sa.String(length=120), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="SUBMITTED"),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("division", "due_date", "status"):
        _create_index(f"ix_manpower_requests_{name}", "manpower_requests", [name])

    _create_table(
        "recruitment_vacancies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("manpower_request_fk", sa.Integer(), sa.ForeignKey("manpower_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vacancy_no", sa.String(length=40), unique=True, nullable=True),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OPEN"),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    _create_index("ix_recruitment_vacancies_manpower_request_fk", "recruitment_vacancies", ["manpower_request_fk"])
    _create_index("ix_recruitment_vacancies_status", "recruitment_vacancies", ["status"])

    _create_table(
        "recruitment_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_no", sa.String(length=40), unique=True, nullable=True),
        sa.Column("vacancy_fk", sa.Integer(), sa.ForeignKey("recruitment_vacancies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("contact", sa.String(length=160), nullable=True),
        sa.Column("cv_evidence_ref", sa.Text(), nullable=True),
        sa.Column("screening_result", sa.String(length=32), nullable=True),
        sa.Column("screening_notes", sa.Text(), nullable=True),
        sa.Column("interview_scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("interviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("interview_result", sa.String(length=32), nullable=True),
        sa.Column("interview_score", sa.Float(), nullable=True),
        sa.Column("manager_assessment", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("offer_amount", sa.Float(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("next_action", sa.String(length=200), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="NEW"),
        sa.Column("employee_fk", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("vacancy_fk", "status", "employee_fk", "decision"):
        _create_index(f"ix_recruitment_candidates_{name}", "recruitment_candidates", [name])


# ═══════════════════════ 6. HR: onboarding, payroll, performance (#64/#65) ═══════════════════════
def _hr_lifecycle_tables():
    # URUTAN & FK (bug produksi nyata — PostgreSQL, bukan SQLite):
    # `payroll_handoffs.onboarding_fk` dan `onboarding_programs.payroll_handoff_fk`
    # saling menunjuk. Di PostgreSQL `CREATE TABLE` dengan FK ke tabel yang BELUM
    # ada langsung gagal:
    #   UndefinedTable: relation "onboarding_programs" does not exist
    # Rujukan silang begini tidak bisa diselesaikan dengan mengubah urutan saja.
    # Karena `payroll_handoff_fk` yang menyimpan hasil akhir (ditulis setelah
    # onboarding selesai), rujukan itulah yang dipertahankan sebagai FK, dan
    # `payroll_handoffs.onboarding_fk` cukup disimpan sebagai INTEGER biasa —
    # nilainya tetap diisi router, tapi tidak memasung urutan pembuatan tabel.
    _create_table(
        "payroll_handoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_fk", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        # Tanpa ForeignKey: lihat catatan urutan di atas (rujukan silang).
        sa.Column("onboarding_fk", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("status_code", sa.String(length=32), nullable=True),
        sa.Column("salary_reference", sa.String(length=120), nullable=True),
        sa.Column("division_salary_ref", sa.String(length=120), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=True),
        sa.Column("cfo_status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("cfo_acted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cfo_acted_at", sa.DateTime(), nullable=True),
        sa.Column("read_by_cfo_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("employee_id", "effective_date", "read_by_cfo_id", "cfo_status"):
        _create_index(f"ix_payroll_handoffs_{name}", "payroll_handoffs", [name])

    _create_table(
        "onboarding_programs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_fk", sa.Integer(), sa.ForeignKey("recruitment_candidates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_fk", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("position", sa.String(length=120), nullable=True),
        sa.Column("training_start", sa.Date(), nullable=True),
        sa.Column("training_end", sa.Date(), nullable=True),
        sa.Column("mentor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("manager_evaluator_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("checklist_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("attendance_ref", sa.String(length=120), nullable=True),
        sa.Column("skill_evidence_ref", sa.Text(), nullable=True),
        sa.Column("issue_blocker", sa.Text(), nullable=True),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("salary_category", sa.String(length=80), nullable=True),
        sa.Column("salary_rate", sa.Float(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("extend_days", sa.Integer(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("payroll_handoff_fk", sa.Integer(), sa.ForeignKey("payroll_handoffs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("employee_fk", "candidate_fk", "decision"):
        _create_index(f"ix_onboarding_programs_{name}", "onboarding_programs", [name])

    _create_table(
        "performance_review_cycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period", sa.String(length=60), nullable=True),
        sa.Column("cycle_name", sa.String(length=160), nullable=True),
        sa.Column("weight_config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("scoring_rule_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("period", "status"):
        _create_index(f"ix_performance_review_cycles_{name}", "performance_review_cycles", [name])

    _create_table(
        "performance_review_details",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_fk", sa.Integer(), sa.ForeignKey("performance_review_cycles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("performance_record_fk", sa.Integer(), sa.ForeignKey("performance_records.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_fk", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("evaluator_manager_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("evaluator_is_manager", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("strengths", sa.Text(), nullable=True),
        sa.Column("gaps", sa.Text(), nullable=True),
        sa.Column("improvement_action", sa.Text(), nullable=True),
        sa.Column("action_owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action_due", sa.Date(), nullable=True),
        sa.Column("employee_acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.UniqueConstraint("cycle_fk", "performance_record_fk", name="uq_review_detail_cycle_record"),
    )
    for name in ("cycle_fk", "performance_record_fk", "evaluator_manager_id", "status"):
        _create_index(f"ix_performance_review_details_{name}", "performance_review_details", [name])


# ═══════════════════════ 7. HR: kasus & eskalasi (#66) ═══════════════════════
def _hr_case_tables():
    _create_table(
        "employee_case_details",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issue_fk", sa.Integer(), sa.ForeignKey("employee_issues.id", ondelete="SET NULL"), nullable=True),
        sa.Column("case_no", sa.String(length=40), unique=True, nullable=True),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("occurred_date", sa.Date(), nullable=True),
        sa.Column("reported_date", sa.Date(), nullable=True),
        sa.Column("confidential", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("investigator_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column("investigation_finding", sa.Text(), nullable=True),
        sa.Column("action_plan", sa.Text(), nullable=True),
        sa.Column("employee_response", sa.Text(), nullable=True),
        sa.Column("manager_response", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("follow_up_date", sa.Date(), nullable=True),
        sa.Column("resolution_evidence_ref", sa.Text(), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("escalated_to_ceo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("escalated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("escalated_at", sa.DateTime(), nullable=True),
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column("ceo_decision_fk", sa.Integer(), sa.ForeignKey("ceo_decisions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("issue_fk", "confidential", "escalated_to_ceo"):
        _create_index(f"ix_employee_case_details_{name}", "employee_case_details", [name])

    _create_table(
        "employee_case_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_fk", sa.Integer(), sa.ForeignKey("employee_case_details.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("access_level", sa.String(length=32), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("case_fk", "access_level"):
        _create_index(f"ix_employee_case_evidence_{name}", "employee_case_evidence", [name])

    _create_table(
        "employee_case_access_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_fk", sa.Integer(), sa.ForeignKey("employee_case_details.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("case_fk", "user_id"):
        _create_index(f"ix_employee_case_access_log_{name}", "employee_case_access_log", [name])

    _create_table(
        "employee_issue_escalations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issue_fk", sa.Integer(), sa.ForeignKey("employee_issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("escalated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("escalated_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("ceo_decision_fk", sa.Integer(), sa.ForeignKey("ceo_decisions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW_DEFAULT),
    )
    for name in ("issue_fk", "escalated_by_id"):
        _create_index(f"ix_employee_issue_escalations_{name}", "employee_issue_escalations", [name])


# ═══════════════════════ 8. COO: schedule (handoff ada di bagian 4) ═══════════════════════
def _coo_tables():
    # `production_handoffs` sudah dibuat di _upgrade_production (dibutuhkan lebih
    # dulu oleh kolom `production_movements.handoff_id`). Tidak ada tabel COO lain
    # yang diminta; sisanya sengaja milik agent printing.
    return


def downgrade():
    raise RuntimeError(
        "Batch 2 schema is forward-only: it adds nullable/defaulted columns and new "
        "tables over existing production data, so a downgrade would silently discard "
        "recorded business facts. Restore a verified backup into a separate database."
    )
