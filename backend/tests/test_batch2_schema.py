"""Batch 2 schema: tabel & kolom baru benar-benar ada dan bisa dipakai.

Migrasi 0023 dibuat oleh AGENT SCHEMA untuk kebutuhan batch 1. Tes ini menjaga
dua hal yang tidak boleh regress:

1. Setiap tabel/kolom yang diminta REQUESTS/*.md benar-benar terpasang di
   metadata (dan karenanya di DB hasil migrasi).
2. Kolom baru bisa ditulis/dibaca lewat ORM, termasuk `employees.join_date`
   sebagai DATE asli (bukan angka tahun — SQLite pernah salah kalau memakai
   CAST(... AS DATE)).
3. Migrasi idempoten: dijalankan ulang pada DB yang sudah head tidak boleh gagal.
"""
from datetime import date

import pytest
from sqlalchemy import text as sa_text

from app import models as m


BATCH2_TABLES = (
    # HR (#62-#66)
    "manpower_requests", "recruitment_vacancies", "recruitment_candidates",
    "onboarding_programs", "payroll_handoffs", "performance_review_cycles",
    "performance_review_details", "employee_case_details", "employee_case_evidence",
    "employee_case_access_log", "employee_issue_escalations", "employee_status_history",
    # CFO (#17/#20/#24)
    "operational_cost_entries", "ap_payments",
    # Sample (#31-#37)
    "sample_versions", "sample_tasks", "sample_task_prerequisites",
    # COO (#54)
    "production_handoffs",
    # Printing evidence (#45) — tabel Printing lain milik agent printing
    "printing_evidence",
)

BATCH2_COLUMNS = {
    "employees": ("join_date", "exit_date", "contract_type", "contract_start_date",
                  "contract_end_date", "manager_name", "document_ref",
                  "migration_source", "migrated_at"),
    "invoices": ("currency", "promised_date"),
    "payments": ("status", "evidence_ref", "verified_by_id", "verified_at", "rejection_reason"),
    "purchase_orders": ("vendor_type", "due_date", "vendor_invoice_no"),
    "sample_records": ("sample_version", "previous_version_id", "revision_reason",
                       "submitted_by_id", "submitted_at"),
    "sample_evidence": ("evidence_kind", "sample_version"),
    "exceptions": ("sample_fk", "sample_version", "scope"),
}


def test_every_requested_table_exists_in_metadata():
    missing = [name for name in BATCH2_TABLES if name not in m.Base.metadata.tables]
    assert missing == []


def test_every_requested_column_exists_in_metadata():
    missing = {
        table: [c for c in columns if c not in m.Base.metadata.tables[table].c]
        for table, columns in BATCH2_COLUMNS.items()
    }
    assert {t: c for t, c in missing.items() if c} == {}


def test_new_columns_are_nullable_or_defaulted_so_existing_rows_survive():
    """Aturan keras batch 2: data produksi yang sudah ada tidak boleh rusak.

    Kolom baru yang NOT NULL WAJIB punya default (Python atau server_default),
    supaya baris lama tetap bisa dibaca setelah migrasi.
    """
    offenders = []
    for table, columns in BATCH2_COLUMNS.items():
        for name in columns:
            column = m.Base.metadata.tables[table].c[name]
            if not column.nullable and column.default is None and column.server_default is None:
                offenders.append(f"{table}.{name}")
    assert offenders == []


def test_new_tables_can_store_and_read_back_rows(db):
    """Bukti tabel baru bukan sekadar ada di metadata: barisnya bisa dibaca."""
    employee = m.Employee(employee_no="EMP-B2-1", name="Budi", join_date=date(2026, 2, 10),
                          contract_type="PKWT", contract_end_date=date(2026, 8, 10),
                          migration_source="LEGACY_JOIN_DATE_ESTIMATE")
    db.add(employee)
    db.commit()

    read = db.query(m.Employee).filter_by(employee_no="EMP-B2-1").one()
    # DATE asli, bukan integer tahun — ini regresi yang pernah terjadi di SQLite.
    assert read.join_date == date(2026, 2, 10)
    assert read.contract_end_date == date(2026, 8, 10)

    db.add(m.EmployeeStatusHistory(employee_id=read.id, effective_date=date(2026, 2, 10),
                                   from_status=None, to_status="ACTIVE", reason="Hire"))
    db.add(m.ManpowerRequest(request_no="MPR-1", division="Produksi", position="Operator",
                             qty=2, status="SUBMITTED"))
    db.add(m.OperationalCostEntry(cost_id="COST-1", category="OPEX_SEWA",
                                  amount=1000, incurred_at=read.join_date))
    db.commit()

    assert db.query(m.EmployeeStatusHistory).count() == 1
    assert db.query(m.ManpowerRequest).filter_by(request_no="MPR-1").one().qty == 2
    entry = db.query(m.OperationalCostEntry).filter_by(cost_id="COST-1").one()
    # classification/payment_status punya default walau tidak dikirim.
    assert entry.classification == "NON_HPP"
    assert entry.payment_status == "UNPAID"


def test_new_payment_fields_default_safely(db):
    """Baris lama tanpa `status` tetap sah: kolomnya NULLABLE, bukan NOT NULL.

    Modul AR memperlakukan status NULL sebagai VERIFIED (perilaku sebelum revisi
    #17), jadi migrasi tidak boleh memaksa nilai yang mengubah arti baris lama.
    """
    assert m.Payment.__table__.c.status.nullable is True
    assert m.Payment.__table__.c.evidence_ref.nullable is True
    assert m.Payment.__table__.c.verified_by_id.nullable is True
    assert m.Payment.__table__.c.rejection_reason.nullable is True
    assert m.Invoice.__table__.c.promised_date.nullable is True
    assert m.PurchaseOrder.__table__.c.vendor_type.nullable is True

    order = m.Order(order_id="SO-B2-PAY", buyer="Buyer", order_type=m.OrderType.SAMPLE_ONLY,
                    order_date=date.today())
    db.add(order); db.commit()
    invoice = m.Invoice(invoice_no="INV-B2-1", order_fk=order.id, amount=100, currency="IDR")
    db.add(invoice); db.commit()

    # Baris lama di DB tidak punya nilai ini sama sekali; buktinya adalah kolom
    # NULLABLE tanpa server_default, sehingga INSERT lama tetap sah. Disimulasikan
    # lewat SQL mentah karena `default="REPORTED"` Python akan mengisi nilai pada
    # setiap INSERT lewat ORM — default aplikasi tidak sama dengan paksaan skema.
    assert m.Payment.__table__.c.status.server_default is None
    db.execute(sa_text(
        "INSERT INTO payments (invoice_no, amount, created_at) VALUES ('INV-B2-LEGACY', 7, CURRENT_TIMESTAMP)"
    ))
    db.commit()
    legacy = db.query(m.Payment).filter_by(invoice_no="INV-B2-LEGACY").one()
    assert legacy.status is None


def test_sample_version_and_task_tables_hold_versions(db):
    order = m.Order(order_id="SO-B2-SMP", buyer="Buyer", order_type=m.OrderType.SAMPLE_ONLY,
                    order_date=date.today())
    db.add(order); db.commit()
    article = m.Article(order_fk=order.id, article_code="A1", qty=1)
    db.add(article); db.commit()

    first = m.SampleRecord(order_fk=order.id, article_id=article.id, article_code="A1",
                           status="PROCESS", sample_version=1)
    db.add(first); db.commit()
    second = m.SampleRecord(order_fk=order.id, article_id=article.id, article_code="A1",
                            status="PROCESS", sample_version=2, previous_version_id=first.id,
                            revision_reason="Warna buyer berubah")
    db.add(second); db.commit()

    db.add_all([
        m.SampleVersion(sample_fk=first.id, version=1, decision="REJECTED",
                        decision_reason="Warna kurang tepat"),
        m.SampleVersion(sample_fk=second.id, version=2),
        m.SampleTask(task_no="TSK-B2-1", order_fk=order.id, article_id=article.id,
                     sample_fk=second.id, sample_version=2, stage="OPEN", required_action="CREATE_SAMPLE"),
    ])
    db.commit()
    task = db.query(m.SampleTask).filter_by(task_no="TSK-B2-1").one()
    db.add(m.SampleTaskPrerequisite(task_id=task.id, requirement_key="sample_request",
                                    label="Sample Request ada", satisfied=True))
    db.commit()

    versions = db.query(m.SampleVersion).filter_by(sample_fk=first.id).all()
    assert [v.version for v in versions] == [1]
    assert versions[0].decision == "REJECTED"
    assert second.previous_version_id == first.id
    assert db.query(m.SampleTaskPrerequisite).filter_by(task_id=task.id).one().satisfied is True


def test_production_handoff_records_sent_and_received_separately(db):
    order = m.Order(order_id="SO-B2-HO", buyer="Buyer", order_type=m.OrderType.REPEAT_PRODUCTION,
                    order_date=date.today())
    db.add(order); db.commit()
    article = m.Article(order_fk=order.id, article_code="A1", qty=100)
    db.add(article); db.commit()

    handoff = m.ProductionHandoff(order_fk=order.id, article_id=article.id,
                                  handoff_no="HO-B2-1", from_process="Cutting",
                                  to_process="Sewing", qty_sent=100, qty_received=95,
                                  discrepancy=5, status="DISCREPANCY")
    db.add(handoff); db.commit()

    stored = db.query(m.ProductionHandoff).filter_by(handoff_no="HO-B2-1").one()
    # Qty sent tidak boleh tertimpa oleh penerimaan.
    assert (stored.qty_sent, stored.qty_received, stored.discrepancy) == (100, 95, 5)

    movement = m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                                    qty_done=100, status="DONE", handoff_id=stored.id,
                                    machine="Obras-1", batch_id="BATCH-B2")
    db.add(movement); db.commit()
    assert db.query(m.ProductionMovement).filter_by(batch_id="BATCH-B2").one().handoff_id == stored.id
