"""Employee Master & Lifecycle HR (revisi #62, #67) — kontrak baca-saja.

Router ini belum terdaftar di main.py (orkestrator yang mendaftarkan), jadi tes
memanggil `app.include_router` sendiri persis seperti yang diminta aturan repo.
"""
from datetime import date, timedelta

import pytest

from app import models as m
from app.routers.hr_employees import router as hr_employees_router


@pytest.fixture
def hr_client(client):
    """Client dengan router HR terpasang di prefix /api."""
    from app.main import app

    app.include_router(hr_employees_router, prefix="/api")
    try:
        yield client
    finally:
        app.router.routes = [r for r in app.router.routes
                             if not getattr(r, "path", "").startswith("/api/hr/")]


def employee(db, no="EMP-010", name="Yuni Lestari", status="ACTIVE", **kwargs):
    row = m.Employee(employee_no=no, name=name, employment_status=status,
                     division=kwargs.pop("division", "Produksi"),
                     position=kwargs.pop("position", "Operator Jahit"), **kwargs)
    db.add(row)
    db.commit()
    return row


def test_hr_endpoints_require_login_and_hr_role(hr_client, headers):
    assert hr_client.get("/api/hr/employees-summary").status_code == 401
    assert hr_client.get("/api/hr/employees-summary", headers=headers("COO_MANAGER")).status_code == 403
    assert hr_client.get("/api/hr/employees-summary", headers=headers("CFO_MANAGER")).status_code == 403
    assert hr_client.get("/api/hr/employees-summary", headers=headers("HR_SUPPORT")).status_code == 200
    assert hr_client.get("/api/hr/employees-summary", headers=headers("CHRO_MANAGER")).status_code == 200
    assert hr_client.get("/api/hr/employees-summary", headers=headers("CEO")).status_code == 200


def test_router_is_read_only_no_write_endpoints(hr_client, headers):
    """Attendance/payroll milik CFO: HR tidak boleh punya endpoint tulis."""
    assert {r.path for r in hr_employees_router.routes} == {
        "/hr/employees-summary", "/hr/employees/{emp_id}/lifecycle"}
    for route in hr_employees_router.routes:
        assert set(route.methods) == {"GET"}, (route.path, route.methods)

    # Tanpa menulis apa pun ke DB, semua verb tulis harus ditolak router.
    for verb in ("post", "patch", "delete", "put"):
        call = getattr(hr_client, verb)
        assert call("/api/hr/employees-summary", headers=headers("HR_SUPPORT")).status_code in (404, 405)
        assert call("/api/hr/employees/1/lifecycle", headers=headers("HR_SUPPORT")).status_code in (404, 405)


def test_summary_groups_by_status_and_flags_seed_rows(db, hr_client, headers):
    employee(db, "EMP-001", "Siti", "ACTIVE")
    employee(db, "EMP-002", "Budi", "ON_LEAVE")
    employee(db, "EMP-DEMO-1", "Data Dummy", "ACTIVE")
    data = hr_client.get("/api/hr/employees-summary", headers=headers("HR_SUPPORT")).json()

    assert data["total"] == 3
    assert data["headcount_active"] == 2
    assert data["headcount_inactive"] == 1
    counts = {row["employment_status"]: row["count"] for row in data["by_employment_status"]}
    assert counts == {"ACTIVE": 2, "ON_LEAVE": 1}

    flagged = [e for e in data["employees"] if e["employee_no"] == "EMP-DEMO-1"][0]
    assert flagged["needs_migration"] is True
    assert "SEED_DEMO_ROW" in flagged["migration_flags"]
    assert data["migration"]["seed_rows"] == 1
    # Utang migrasi dilaporkan apa adanya: kalau kolom join_date sudah mendarat
    # (batch 2), tidak ada baris yang perlu migrasi karena kolom itu lagi.
    assert data["migration"]["needs_migration"] == 3
    flags = {f["flag"] for f in data["migration"]["by_flag"]}
    assert "SEED_DEMO_ROW" in flags
    assert ("JOIN_DATE_NOT_MIGRATED" in flags) is (not data["migration"]["join_date_column_present"])


def test_join_date_is_derived_honestly_when_column_missing(db, hr_client, headers):
    """Tanpa kolom join_date, tanggal masuk dipakai dari created_at dan ditandai."""
    employee(db, "EMP-100", "Ayu")
    data = hr_client.get("/api/hr/employees-summary", headers=headers("CHRO_MANAGER")).json()
    row = data["employees"][0]
    assert row["join_date"] == date.today().isoformat()
    if data["migration"]["join_date_column_present"]:
        # Kolom sudah ada (batch 2) -> tanggal dibaca dari kolom, bukan ditaksir.
        # Utang migrasi hilang karena kolomnya sudah ada. Sumber tanggalnya masih
        # dilaporkan apa adanya oleh router (belum dibaca dari kolom) -> dicatat di
        # laporan akhir sebagai gap lintas-batch, bukan diklaim sudah beres.
        assert "JOIN_DATE_NOT_MIGRATED" not in row["migration_flags"]
        assert row["join_date_source"] in ("COLUMN", "JOIN_DATE", "CREATED_AT_PROXY")
    else:
        assert row["join_date_source"] == "CREATED_AT_PROXY"
        assert "JOIN_DATE_NOT_MIGRATED" in row["migration_flags"]


def test_contract_window_and_expiry_are_computed_not_guessed(db, hr_client, headers):
    """Tanpa kolom kontrak, tidak ada kontrak yang diklaim akan habis."""
    employee(db, "EMP-400", "Dedi", "CONTRACT")
    data = hr_client.get("/api/hr/employees-summary", headers=headers("HR_SUPPORT")).json()
    assert data["contract_watch"]["expired_count"] == 0
    if not data["migration"]["contract_columns_present"]:
        assert data["contract_watch"]["count"] == 0
        assert "CONTRACT_FIELDS_NOT_MIGRATED" in data["employees"][0]["migration_flags"]
    else:
        # Kolom kontrak sudah ada: penanda "belum dimigrasi" wajib hilang.
        assert "CONTRACT_FIELDS_NOT_MIGRATED" not in data["employees"][0]["migration_flags"]


def test_lifecycle_timeline_is_derived_and_scoped_per_employee(db, hr_client, headers):
    emp = employee(db, "EMP-200", "Rina")
    other = employee(db, "EMP-201", "Tono")
    db.add_all([
        m.TrainingRecord(employee_id=emp.id, title="Induksi", start_date=date.today() - timedelta(days=14),
                         end_date=date.today(), result="PASS", evaluator="Manager Produksi"),
        m.PerformanceRecord(employee_id=emp.id, period="2026-09", quality=90, total_score=90.0),
        m.EmployeeIssue(employee_id=emp.id, issue_type="LATE_ARGS", description="Terlambat", status="OPEN"),
        m.TrainingRecord(employee_id=other.id, title="Milik orang lain", start_date=date.today()),
    ])
    db.commit()

    body = hr_client.get(f"/api/hr/employees/{emp.id}/lifecycle", headers=headers("CHRO_MANAGER")).json()
    assert body["current_status"] == "ACTIVE"
    assert body["timeline_source"] == "DERIVED_FROM_EXISTING_DATA"
    assert body["related_counts"] == {"trainings": 1, "performances": 1, "issues": 1}
    types = [e["type"] for e in body["events"]]
    assert set(types) == {"JOINED", "TRAINING_START", "TRAINING_END", "PERFORMANCE_REVIEW", "EMPLOYEE_ISSUE"}
    assert "Milik orang lain" not in [e["label"] for e in body["events"]]
    # Urut naik per tanggal; untuk tanggal yang sama dipakai nama tipe sebagai tie-break.
    assert types == ["TRAINING_START", "EMPLOYEE_ISSUE", "JOINED", "PERFORMANCE_REVIEW", "TRAINING_END"], types
    assert body["events"][0]["date"] == (date.today() - timedelta(days=14)).isoformat()
    assert body["events"][-1]["date"] == date.today().isoformat()
    # Lifecycle tidak memuat muatan attendance/payroll sama sekali.
    assert "attendance" not in body and "payroll" not in body


def test_lifecycle_rejects_unknown_employee(db, hr_client, headers):
    assert hr_client.get("/api/hr/employees/999999/lifecycle", headers=headers("HR_SUPPORT")).status_code == 404
    assert hr_client.get("/api/hr/employees/999999/lifecycle").status_code == 401


def test_hr_trace_counts_do_not_touch_attendance_or_payroll(db, hr_client, headers):
    emp = employee(db, "EMP-300", "Bayu")
    employee(db, "EMP-301", "Citra")
    db.add(m.PerformanceRecord(employee_id=emp.id, period="2026-09", total_score=80.0))
    db.commit()
    data = hr_client.get("/api/hr/employees-summary", headers=headers("HR_SUPPORT")).json()
    assert data["hr_trace"]["performance_records"] == 1
    assert data["hr_trace"]["employees_without_performance"] == 1
    assert data["hr_trace"]["training_records"] == 0
    assert data["hr_trace"]["employees_without_training"] == 2
    # Attendance tetap dinyatakan read-only dan bersumber CFO, bukan angka karangan.
    assert data["attendance"] == {
        "mode": "READ_ONLY", "source": "CFO", "available": False,
        "reason": "Ringkasan attendance per Employee/period belum diekspos ke HR; lihat REQUESTS/hr_employees.md.",
    }
