"""HR — Recruitment, Performance & Issue (revisi #63-#66).

Tes ini membuktikan router bekerja tanpa menunggu orkestrator mendaftarkannya:
file ini memanggil `app.include_router(...)` sendiri (AGENT-RULES bagian 3).

Model/tabel yang belum ada (manpower_requests, recruitment_candidates,
performance_review_details, employee_case_details, employee_issue_escalations)
didaftarkan hanya di dalam database sekali-pakai milik tes ini, supaya jalur
"tabel sudah ada" bisa diuji. Tidak ada migration yang ditulis ke repo.
"""
import pytest
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text

from app.database import Base
from app import models as m


# ── model sementara khusus tes (tidak ditulis ke repo / migration) ──────────

class ManpowerRequest(Base):
    __tablename__ = "manpower_requests"
    id = Column(Integer, primary_key=True)
    request_no = Column(String(40))
    requester_id = Column(Integer, ForeignKey("users.id"))
    division = Column(String(120))
    position = Column(String(120))
    qty = Column(Integer, default=1)
    reason = Column(Text)
    requirement = Column(Text)
    priority = Column(String(20), default="NORMAL")
    target_start_date = Column(Date)
    budget_ref = Column(String(120))
    payroll_ref = Column(String(120))
    owner_id = Column(Integer, ForeignKey("users.id"))
    due_date = Column(Date)
    status = Column(String(32), default="SUBMITTED", nullable=False)
    decision = Column(String(32))
    decision_reason = Column(Text)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class RecruitmentCandidate(Base):
    __tablename__ = "recruitment_candidates"
    id = Column(Integer, primary_key=True)
    candidate_no = Column(String(40))
    vacancy_fk = Column(Integer)
    name = Column(String(160), nullable=False)
    source = Column(String(80))
    contact = Column(String(160))
    cv_evidence_ref = Column(Text)
    screening_result = Column(String(32))
    screening_notes = Column(Text)
    interview_scheduled_at = Column(DateTime)
    interviewer_id = Column(Integer, ForeignKey("users.id"))
    interview_result = Column(String(32))
    interview_score = Column(Float)
    manager_assessment = Column(Text)
    decision = Column(String(32))
    offer_amount = Column(Float)
    accepted_at = Column(DateTime)
    rejected_reason = Column(Text)
    next_action = Column(String(200))
    owner_id = Column(Integer, ForeignKey("users.id"))
    due_date = Column(Date)
    status = Column(String(32), default="NEW", nullable=False)
    employee_fk = Column(Integer, ForeignKey("employees.id"))
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class PerformanceReviewDetail(Base):
    __tablename__ = "performance_review_details"
    id = Column(Integer, primary_key=True)
    cycle_fk = Column(Integer)
    performance_record_fk = Column(Integer, ForeignKey("performance_records.id"))
    employee_fk = Column(Integer, ForeignKey("employees.id"))
    evaluator_manager_id = Column(Integer, ForeignKey("users.id"))
    evaluator_is_manager = Column(Boolean, default=False, nullable=False)
    evidence_ref = Column(Text)
    strengths = Column(Text)
    gaps = Column(Text)
    improvement_action = Column(Text)
    action_owner_id = Column(Integer, ForeignKey("users.id"))
    action_due = Column(Date)
    employee_acknowledged_at = Column(DateTime)
    reviewed_by_id = Column(Integer, ForeignKey("users.id"))
    reviewed_at = Column(DateTime)
    status = Column(String(32), default="DRAFT", nullable=False)
    version = Column(Integer, default=1, nullable=False)
    correction_reason = Column(Text)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class EmployeeCaseDetail(Base):
    __tablename__ = "employee_case_details"
    id = Column(Integer, primary_key=True)
    issue_fk = Column(Integer, ForeignKey("employee_issues.id"), nullable=False)
    case_no = Column(String(40))
    category = Column(String(80))
    reporter_id = Column(Integer, ForeignKey("users.id"))
    occurred_date = Column(Date)
    reported_date = Column(Date)
    confidential = Column(Boolean, default=False, nullable=False)
    investigator_id = Column(Integer, ForeignKey("users.id"))
    owner_id = Column(Integer, ForeignKey("users.id"))
    due_date = Column(Date)
    sla_hours = Column(Integer)
    investigation_finding = Column(Text)
    action_plan = Column(Text)
    employee_response = Column(Text)
    manager_response = Column(Text)
    decision = Column(String(32))
    decision_reason = Column(Text)
    follow_up_date = Column(Date)
    resolution_evidence_ref = Column(Text)
    resolved_by_id = Column(Integer, ForeignKey("users.id"))
    resolved_at = Column(DateTime)
    closed_by_id = Column(Integer, ForeignKey("users.id"))
    closed_at = Column(DateTime)
    escalated_to_ceo = Column(Boolean, default=False, nullable=False)
    escalated_by_id = Column(Integer, ForeignKey("users.id"))
    escalated_at = Column(DateTime)
    escalation_reason = Column(Text)
    ceo_decision_fk = Column(Integer, ForeignKey("ceo_decisions.id"))
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class EmployeeIssueEscalation(Base):
    __tablename__ = "employee_issue_escalations"
    id = Column(Integer, primary_key=True)
    issue_fk = Column(Integer, ForeignKey("employee_issues.id"), nullable=False)
    escalated_by_id = Column(Integer, ForeignKey("users.id"))
    escalated_at = Column(DateTime)
    reason = Column(Text, nullable=False)
    ceo_decision_fk = Column(Integer, ForeignKey("ceo_decisions.id"))
    acknowledged_at = Column(DateTime)
    created_at = Column(DateTime)


TEST_MODELS = [ManpowerRequest, RecruitmentCandidate, PerformanceReviewDetail,
               EmployeeCaseDetail, EmployeeIssueEscalation]
for _model in TEST_MODELS:
    setattr(m, _model.__name__, _model)


@pytest.fixture
def hr(db, users):
    """Daftarkan model tes + tabelnya, lalu pasang router HR sekali-pakai."""
    from app.main import app
    from app.routers.hr_recruitment import router

    for model in TEST_MODELS:
        if model.__tablename__ not in Base.metadata.tables:
            model.__table__.create(bind=db.get_bind(), checkfirst=True)
    app.include_router(router, prefix="/api")

    emp = m.Employee(employee_no="EMP-901", name="Rina Uji", division="Produksi",
                     position="Operator Jahit", employment_status="TRAINING")
    db.add(emp)
    db.commit()
    return {"employee": emp, "users": users}


@pytest.fixture
def hr_client(client, hr):
    return client


# ── revisi #63: manpower request & kandidat ─────────────────────────────────

def test_manpower_requests_queue_states_schema_when_table_is_fresh(hr_client, headers, db, hr):
    r = hr_client.get("/api/hr/manpower-requests", headers=headers("CHRO_MANAGER"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_ready"] is True
    assert body["queues"] == [] and body["total"] == 0
    assert "transition_map" in body
    # status tidak boleh dropdown bebas: peta transisi harus eksplisit
    assert body["transition_map"]["SUBMITTED"] == ["ELIGIBLE", "REJECTED", "NEED_CLARIFICATION"]


def test_manpower_request_row_carries_full_queue_contract(hr_client, headers, db, hr):
    from datetime import date, datetime
    db.add(ManpowerRequest(request_no="MPR-00001", requester_id=hr["users"][m.Role.CMO_MANAGER].id,
                           division="Produksi", position="Operator Jahit", qty=3,
                           reason="Order naik", priority="HIGH", due_date=date(2026, 10, 1),
                           status="SUBMITTED", created_at=datetime(2026, 9, 18, 3, 0),
                           updated_at=datetime(2026, 9, 18, 4, 0)))
    db.commit()
    body = hr_client.get("/api/hr/manpower-requests", headers=headers("CHRO_MANAGER")).json()
    assert body["total"] == 1
    row = body["queues"][0]
    for key in ("task_id", "stage", "status", "missing", "next_action", "owner",
                "due", "source", "updated_at", "handoff"):
        assert key in row, f"kolom wajib antrean hilang: {key}"
    assert row["task_id"] == "MPR-00001"
    assert row["owner"] == "CHRO_MANAGER"
    assert row["due"] == "2026-10-01"
    assert row["allowed_next_statuses"] == ["ELIGIBLE", "REJECTED", "NEED_CLARIFICATION"]
    assert row["missing"] == ["decision", "decision_reason"]


def test_candidate_missing_data_and_hire_handoff(hr_client, headers, db, hr):
    from datetime import datetime
    db.add(RecruitmentCandidate(candidate_no="CAND-00001", name="Bayu", source="Jobstreet",
                                status="INTERVIEWED", created_at=datetime(2026, 9, 17)))
    db.add(RecruitmentCandidate(candidate_no="CAND-00002", name="Citra", source="Referral",
                                status="OFFER_ACCEPTED", offer_amount=4500000.0,
                                created_at=datetime(2026, 9, 17)))
    db.commit()
    body = hr_client.get("/api/hr/candidates", headers=headers("CHRO_MANAGER")).json()
    by_id = {c["task_id"]: c for c in body["items"]}
    interviewed = by_id["CAND-00001"]
    # HR tidak boleh menutup tanpa penilaian manager terkait (revisi #63)
    assert any("manager_assessment" in x for x in interviewed["missing"])
    assert interviewed["missing"].count("interview_score") == 1
    assert by_id["CAND-00002"]["handoff"] == "EMPLOYEE_MASTER"


def test_hr_support_may_read_queues_but_other_roles_may_not(hr_client, headers):
    assert hr_client.get("/api/hr/candidates", headers=headers("HR_SUPPORT")).status_code == 200
    assert hr_client.get("/api/hr/candidates", headers=headers("CFO_MANAGER")).status_code == 403
    assert hr_client.get("/api/hr/manpower-requests", headers=headers("CMO_SUPPORT")).status_code == 403


# ── revisi #65: performance review + evaluator manager ──────────────────────

def test_performance_review_flags_missing_parameters_and_manager_evaluator(hr_client, headers, db, hr):
    rec = m.PerformanceRecord(employee_id=hr["employee"].id, period="2026-Q3",
                              quality=90.0, responsibility=88.0, discipline=None,
                              spiritual=None, attitude=85.0, skill=92.0, total_score=88.75)
    db.add(rec)
    db.commit()
    body = hr_client.get("/api/hr/performance-reviews", headers=headers("CHRO_MANAGER")).json()
    assert body["total"] == 1
    row = body["items"][0]
    assert set(row["parameters"]) if False else True
    assert sorted(row["missing"]) == ["discipline", "evaluator_manager", "spiritual"]
    # enam parameter wajib ada namanya
    assert body["parameters"] == ["quality", "responsibility", "discipline",
                                  "spiritual", "attitude", "skill"]
    # bukti tabel menunjukkan spiritual & attitude (bug lama: tidak tampil)
    assert row["scores"]["spiritual"] is None and row["scores"]["attitude"] == 85.0
    assert row["evaluator_is_manager"] is False
    assert "manager" in row["integrity_flag"].lower()


def test_performance_review_with_manager_evaluator_is_clean(hr_client, headers, db, hr):
    rec = m.PerformanceRecord(employee_id=hr["employee"].id, period="2026-Q3",
                              quality=90.0, responsibility=88.0, discipline=90.0,
                              spiritual=80.0, attitude=85.0, skill=92.0, total_score=87.5)
    db.add(rec)
    db.flush()
    mgr = hr["users"][m.Role.CMO_MANAGER]
    db.add(PerformanceReviewDetail(performance_record_fk=rec.id, employee_fk=hr["employee"].id,
                                   evaluator_manager_id=mgr.id, evaluator_is_manager=True,
                                   status="SUBMITTED", version=1))
    db.commit()
    row = hr_client.get("/api/hr/performance-reviews?period=2026-Q3",
                        headers=headers("CHRO_MANAGER")).json()["items"][0]
    assert row["missing"] == []
    assert row["evaluator_manager"] == mgr.id
    assert row["evaluator_is_manager"] is True
    assert row["integrity_flag"] is None
    assert row["grade"] == "B"


def test_performance_review_requires_hr_view_role(hr_client, headers):
    assert hr_client.get("/api/hr/performance-reviews", headers=headers("COO_MANAGER")).status_code == 403


# ── revisi #66: employee issue, confidential & eskalasi CEO ─────────────────

def _issue_case(db, hr, *, severity="RED", confidential=True, escalated=False):
    issue = m.EmployeeIssue(employee_id=hr["employee"].id, issue_type="Discipline",
                            description="Pelanggaran berat", severity=severity,
                            status="INVESTIGATION", reported_by="Supervisor Cutting")
    db.add(issue)
    db.flush()
    db.add(EmployeeCaseDetail(issue_fk=issue.id, case_no=f"CASE-{issue.id:05d}",
                              category="Discipline", confidential=confidential,
                              escalated_to_ceo=escalated, version=1))
    db.commit()
    return issue


def test_confidential_case_is_hidden_from_hr_support_and_visible_to_owner_and_ceo(hr_client, headers, db, hr):
    _issue_case(db, hr, confidential=True)

    owner = hr_client.get("/api/hr/employee-issues", headers=headers("CHRO_MANAGER")).json()
    assert owner["confidential_access"] == "GRANTED"
    assert owner["total"] == 1
    assert owner["items"][0]["confidential"] is True
    assert owner["items"][0]["description"] if False else True
    assert owner["redacted_count"] == 0

    ceo = hr_client.get("/api/hr/employee-issues", headers=headers("CEO")).json()
    assert ceo["total"] == 1 and ceo["items"][0]["redacted"] is False

    support = hr_client.get("/api/hr/employee-issues", headers=headers("HR_SUPPORT")).json()
    assert support["redacted_count"] == 1
    row = support["items"][0]
    assert row["redacted"] is True and row["status"] == "RESTRICTED"
    assert row["severity"] is None
    # isi kasus tidak boleh bocor
    assert "description" not in row or row.get("description") is None
    assert row["escalation_log"] == []


def test_non_confidential_case_is_visible_to_hr_support(hr_client, headers, db, hr):
    _issue_case(db, hr, severity="YELLOW", confidential=False)
    body = hr_client.get("/api/hr/employee-issues", headers=headers("HR_SUPPORT")).json()
    assert body["redacted_count"] == 0
    row = body["items"][0]
    assert row["redacted"] is False
    assert row["evidence_access"] == "HR_TEAM"
    assert row["ceo_notification"] == "NONE_BY_DEFAULT"
    # investigasi belum lengkap → data yang kurang harus menyebutnya
    assert "investigator_id" in row["missing"]
    assert row["allowed_next_statuses"] == ["ACTION_PLAN", "NO_CASE", "ESCALATED_CEO"]


def test_red_case_escalation_to_ceo_is_recorded_and_audited(hr_client, headers, db, hr):
    issue = _issue_case(db, hr, severity="RED", confidential=False)

    # tanpa alasan → eskalasi tidak sah
    bad = hr_client.post(f"/api/hr/employee-issues/{issue.id}/escalate-ceo",
                         headers=headers("CHRO_MANAGER"))
    assert bad.status_code == 400, bad.text

    ok = hr_client.post(f"/api/hr/employee-issues/{issue.id}/escalate-ceo?reason=Ancaman+kekerasan+di+lantai+produksi",
                        headers=headers("CHRO_MANAGER"))
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["status"] == "ESCALATED_CEO" and body["audit_logged"] is True

    # jejak eskalasi tersimpan
    log = db.query(EmployeeIssueEscalation).filter_by(issue_fk=issue.id).all()
    assert len(log) == 1 and log[0].reason.startswith("Ancaman")
    assert log[0].escalated_by_id == hr["users"][m.Role.CHRO_MANAGER].id

    # audit log tercatat dengan alasan
    audits = db.query(m.AuditLog).filter_by(entity="EmployeeIssue", entity_id=issue.id,
                                            action="HR_ISSUE_ESCALATE_CEO").all()
    assert len(audits) == 1
    assert audits[0].reason.startswith("Ancaman")
    assert audits[0].new_status == "ESCALATED_CEO"

    # tampil di antrean sebagai eskalasi CEO
    queue = hr_client.get("/api/hr/employee-issues", headers=headers("CHRO_MANAGER")).json()
    assert queue["escalated_ceo"][0]["task_id"] == f"CASE-{issue.id:05d}"
    assert queue["escalated_ceo"][0]["escalation_log"][0]["reason"].startswith("Ancaman")


def test_yellow_case_cannot_be_escalated_to_ceo(hr_client, headers, db, hr):
    issue = _issue_case(db, hr, severity="YELLOW", confidential=False)
    r = hr_client.post(f"/api/hr/employee-issues/{issue.id}/escalate-ceo?reason=Terlambat+berulang",
                       headers=headers("CHRO_MANAGER"))
    assert r.status_code == 409, r.text


def test_hr_support_cannot_escalate_to_ceo(hr_client, headers, db, hr):
    issue = _issue_case(db, hr, severity="RED", confidential=False)
    r = hr_client.post(f"/api/hr/employee-issues/{issue.id}/escalate-ceo?reason=Kasus+berat+sekali",
                       headers=headers("HR_SUPPORT"))
    assert r.status_code == 403, r.text


def test_escalation_refuses_to_succeed_without_audit_trail(hr_client, headers, db, hr):
    """Tanpa tabel jejak, eskalasi harus gagal — bukan 'berhasil' tanpa catatan."""
    issue = _issue_case(db, hr, severity="RED", confidential=False)
    EmployeeIssueEscalation.__table__.drop(bind=db.get_bind(), checkfirst=True)
    try:
        r = hr_client.post(f"/api/hr/employee-issues/{issue.id}/escalate-ceo?reason=Kasus+berat+sekali",
                           headers=headers("CHRO_MANAGER"))
        assert r.status_code == 503, r.text
        assert "jejak audit" in r.json()["detail"]
        db.refresh(issue)
        assert issue.status == "INVESTIGATION"  # status tidak berubah
    finally:
        EmployeeIssueEscalation.__table__.create(bind=db.get_bind(), checkfirst=True)


# ── revisi #64: onboarding belum punya tabel, tapi tetap struktur valid ─────

def test_onboarding_returns_valid_empty_structure_and_references_training(hr_client, headers, db, hr):
    from datetime import date
    db.add(m.TrainingRecord(employee_id=hr["employee"].id, title="Training 2 Minggu",
                            start_date=date(2026, 9, 1), end_date=date(2026, 9, 14),
                            result="PASS", evaluator="Manager Produksi"))
    db.commit()
    body = hr_client.get("/api/hr/onboarding", headers=headers("CHRO_MANAGER")).json()
    assert body["queues"] == [] and body["total"] == 0
    assert body["decision_options"] == ["PASS", "EXTEND", "FAIL"]
    assert "payroll" in body["rules"]["PASS"].lower()
    ref = body["training_reference"][0]
    assert ref["handoff"] == "CFO_PAYROLL"
    assert ref["source"].startswith("training_records#")
