"""HR — Recruitment, Performance & Issue (revisi #63-#66) — BACA + TULIS.

Batch 1 menguji antrean baca dengan model sementara yang didaftarkan di dalam
file ini. Sejak `models.py` (agent SCHEMA) sudah memuat tabel batch 2 yang nyata,
model sementara itu justru bertabrakan (`Table 'manpower_requests' is already
defined`). Karena itu tes ini sekarang memakai model NYATA dari `app.models` —
yang juga berarti tes membuktikan endpoint tulis bekerja di atas schema asli,
bukan di atas tiruan.

Cakupan:
- antrean baca tetap utuh (kontrak kolom, RBAC, confidential, evaluator manager),
- jalur tulis baru: manpower → vacancy → kandidat → hire → onboarding → handoff
  payroll → siklus performance → kasus karyawan → eskalasi CEO,
- aturan yang HARUS ditolak: eskalasi tanpa tabel jejak (503), eskalasi non-RED
  (409), hire tanpa penilaian manager (409), EXTEND tanpa alasan/hari (400),
  evaluator bukan manager (422), koreksi review FINALIZED tanpa alasan (#65).
"""
import pytest
from datetime import date
from sqlalchemy import text

from app.database import Base
from app import models as m


@pytest.fixture
def hr(db, users):
    """Pasang router HR sekali-pakai di atas schema nyata (tanpa migration repo)."""
    from app.main import app
    from app.routers.hr_recruitment import router

    # Tabel batch 2 mendarat di DB tes; tabel yang belum ada boleh menyusul.
    Base.metadata.create_all(bind=db.get_bind())
    app.include_router(router, prefix="/api")

    emp = m.Employee(employee_no="EMP-901", name="Rina Uji", division="Produksi",
                     position="Operator Jahit", employment_status="TRAINING")
    db.add(emp)
    db.commit()
    return {"employee": emp, "users": users}


@pytest.fixture
def hr_client(client, hr):
    return client


def _new_manpower(client, headers, **overrides):
    params = {"division": "Produksi", "position": "Operator Jahit", "qty": 1,
              "priority": "HIGH", "reason": "Beban order naik"}
    params.update(overrides)
    r = client.post("/api/hr/manpower-requests", params=params, headers=headers("CHRO_MANAGER"))
    assert r.status_code == 201, r.text
    return r.json()


def _vacancy(client, headers, request_id, source="Jobstreet"):
    r = client.post(f"/api/hr/manpower-requests/{request_id}/vacancies",
                    params={"source": source}, headers=headers("CHRO_MANAGER"))
    assert r.status_code == 201, r.text
    return r.json()


def _candidate(client, headers, vacancy_fk, name="Bayu"):
    r = client.post("/api/hr/candidates", params={"vacancy_fk": vacancy_fk, "name": name},
                    headers=headers("CHRO_MANAGER"))
    assert r.status_code == 201, r.text
    return r.json()


# ── revisi #63: manpower request — baca ─────────────────────────────────────

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
    from datetime import datetime
    db.add(m.ManpowerRequest(request_no="MPR-00001", requester_id=hr["users"][m.Role.CMO_MANAGER].id,
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
    db.add(m.RecruitmentCandidate(candidate_no="CAND-00001", name="Bayu", source="Jobstreet",
                                  status="INTERVIEWED", created_at=datetime(2026, 9, 17)))
    db.add(m.RecruitmentCandidate(candidate_no="CAND-00002", name="Citra", source="Referral",
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


# ── revisi #63: manpower request — tulis ────────────────────────────────────

def test_create_manpower_request_records_requester_and_audit(hr_client, headers, db, hr):
    body = _new_manpower(hr_client, headers, qty=3)
    assert body["request_no"] == "MPR-00001"
    assert body["requester_id"] == hr["users"][m.Role.CHRO_MANAGER].id
    assert body["status"] == "SUBMITTED" and body["version"] == 1
    assert body["allowed_next_statuses"] == ["ELIGIBLE", "REJECTED", "NEED_CLARIFICATION"]
    assert body["audit_logged"] is True
    audits = db.query(m.AuditLog).filter_by(entity="ManpowerRequest",
                                            action="HR_MANPOWER_REQUEST_CREATE").all()
    assert len(audits) == 1 and audits[0].new_status == "SUBMITTED"

    # requester berasal dari sesi, bukan dari parameter klien
    other = hr_client.post("/api/hr/manpower-requests",
                           params={"division": "Gudang", "position": "Helper",
                                   "requester_id": 99999},
                           headers=headers("HR_SUPPORT"))
    assert other.status_code == 201, other.text
    assert other.json()["requester_id"] == hr["users"][m.Role.HR_SUPPORT].id


def test_manpower_status_only_changes_through_valid_actions(hr_client, headers, db, hr):
    created = _new_manpower(hr_client, headers)
    mid = created["id"]

    # lompat langsung ke VACANCY_OPEN dari SUBMITTED → ditolak
    bad = hr_client.post(f"/api/hr/manpower-requests/{mid}/actions",
                         params={"action": "VACANCY_OPEN"}, headers=headers("CHRO_MANAGER"))
    assert bad.status_code == 409, bad.text
    assert "tidak sah" in bad.json()["detail"]

    # menolak tanpa alasan → ditolak
    no_reason = hr_client.post(f"/api/hr/manpower-requests/{mid}/actions",
                               params={"action": "REJECTED"}, headers=headers("CHRO_MANAGER"))
    assert no_reason.status_code == 400, no_reason.text

    ok = hr_client.post(f"/api/hr/manpower-requests/{mid}/actions",
                        params={"action": "ELIGIBLE"}, headers=headers("CHRO_MANAGER"))
    assert ok.status_code == 201, ok.text
    assert ok.json()["previous_status"] == "SUBMITTED"
    assert ok.json()["status"] == "ELIGIBLE"

    audits = db.query(m.AuditLog).filter_by(entity="ManpowerRequest",
                                            action="HR_MANPOWER_REQUEST_ACTION").all()
    assert len(audits) == 1
    assert (audits[0].previous_status, audits[0].new_status) == ("SUBMITTED", "ELIGIBLE")


def test_vacancy_requires_eligible_manpower_and_cannot_exceed_qty(hr_client, headers, db, hr):
    created = _new_manpower(hr_client, headers, qty=1)   # SUBMITTED
    mid = created["id"]

    early = hr_client.post(f"/api/hr/manpower-requests/{mid}/vacancies",
                           headers=headers("CHRO_MANAGER"))
    assert early.status_code == 409, early.text          # belum ELIGIBLE

    hr_client.post(f"/api/hr/manpower-requests/{mid}/actions", params={"action": "ELIGIBLE"},
                   headers=headers("CHRO_MANAGER"))
    vac = _vacancy(hr_client, headers, mid)
    assert vac["vacancy_no"] == "VAC-00001" and vac["status"] == "OPEN"
    assert vac["previous_manpower_status"] == "ELIGIBLE"

    # qty=1 → vacancy OPEN kedua tidak boleh dibuka
    more = hr_client.post(f"/api/hr/manpower-requests/{mid}/vacancies",
                          headers=headers("CHRO_MANAGER"))
    assert more.status_code == 409, more.text
    assert "qty" in more.json()["detail"]

    req = db.get(m.ManpowerRequest, mid)
    assert req.status == "VACANCY_OPEN"


def test_candidate_hired_only_after_offer_accepted_and_manager_assessment(hr_client, headers, db, hr):
    created = _new_manpower(hr_client, headers)
    mid = created["id"]
    hr_client.post(f"/api/hr/manpower-requests/{mid}/actions", params={"action": "ELIGIBLE"},
                   headers=headers("CHRO_MANAGER"))
    vac = _vacancy(hr_client, headers, mid)
    cand = _candidate(hr_client, headers, vac["id"])
    cid = cand["id"]
    assert cand["employee_fk"] is None
    assert "hire" in cand["employee_note"].lower() or "keputusan hire" in cand["employee_note"]

    # lompat langsung HIRED dari NEW → ditolak
    jump = hr_client.post(f"/api/hr/candidates/{cid}/actions", params={"action": "HIRED"},
                          headers=headers("CHRO_MANAGER"))
    assert jump.status_code == 409, jump.text

    def act(action, **params):
        return hr_client.post(f"/api/hr/candidates/{cid}/actions",
                              params={"action": action, **params}, headers=headers("CHRO_MANAGER"))

    assert act("SCREENING", screening_result="LOLOS").status_code == 201
    assert act("SHORTLISTED").status_code == 201
    assert act("INTERVIEW_SCHEDULED", interview_scheduled_at="2026-09-20T09:00:00").status_code == 201
    assert act("INTERVIEWED").status_code == 201
    # OFFERED tanpa offer_amount → ditolak
    assert act("OFFERED").status_code == 409
    assert act("OFFERED", offer_amount=4500000.0).status_code == 201
    assert act("OFFER_ACCEPTED").status_code == 201

    # hire tanpa penilaian manager → ditolak (revisi #63)
    no_assess = hr_client.post(f"/api/hr/candidates/{cid}/hire", headers=headers("CHRO_MANAGER"))
    assert no_assess.status_code == 409, no_assess.text
    assert "manager" in no_assess.json()["detail"].lower()

    # Penilaian manager dicatat sebagai bagian dari keputusan (revisi #63).
    row = db.get(m.RecruitmentCandidate, cid)
    row.manager_assessment = "Siap kerja, disiplin"
    db.commit()

    hired = hr_client.post(f"/api/hr/candidates/{cid}/hire", headers=headers("CHRO_MANAGER"))
    assert hired.status_code == 201, hired.text
    payload = hired.json()
    assert payload["status"] == "HIRED"
    assert payload["employee"]["employee_no"] not in (None, "")
    assert payload["employee"]["division"] == "Produksi"
    assert payload["onboarding"]["training_days"] == 14          # revisi #64: 2 minggu
    assert (payload["onboarding"]["training_end"] > payload["onboarding"]["training_start"])

    db.refresh(row)
    assert row.employee_fk == payload["employee"]["id"]
    assert payload["vacancy_status"] == "FILLED"

    # hire dua kali → ditolak
    again = hr_client.post(f"/api/hr/candidates/{cid}/hire", headers=headers("CHRO_MANAGER"))
    assert again.status_code == 409, again.text


def test_write_endpoints_reject_roles_outside_hr_and_ceo(hr_client, headers):
    for role in ("CFO_MANAGER", "COO_MANAGER", "CMO_SUPPORT"):
        r = hr_client.post("/api/hr/manpower-requests",
                           params={"division": "Produksi", "position": "Operator"},
                           headers=headers(role))
        assert r.status_code == 403, (role, r.text)


# ── revisi #64: onboarding & payroll handoff ────────────────────────────────

def _hired_candidate(hr_client, headers, db):
    created = _new_manpower(hr_client, headers)
    hr_client.post(f"/api/hr/manpower-requests/{created['id']}/actions",
                   params={"action": "ELIGIBLE"}, headers=headers("CHRO_MANAGER"))
    vac = _vacancy(hr_client, headers, created["id"])
    cid = _candidate(hr_client, headers, vac["id"])["id"]
    row = db.get(m.RecruitmentCandidate, cid)
    row.status = "OFFER_ACCEPTED"
    row.manager_assessment = "Siap kerja"
    row.offer_amount = 4000000.0
    db.commit()
    hired = hr_client.post(f"/api/hr/candidates/{cid}/hire", headers=headers("CHRO_MANAGER"))
    assert hired.status_code == 201, hired.text
    return hired.json()


def test_onboarding_pass_activates_employee_and_creates_payroll_handoff(hr_client, headers, db, hr):
    hired = _hired_candidate(hr_client, headers, db)
    prog_id = hired["onboarding"]["id"]

    body = hr_client.get("/api/hr/onboarding", headers=headers("CHRO_MANAGER")).json()
    assert body["schema_ready"] is True and body["total"] == 0
    assert body["queues"] == []

    # EXTEND tanpa alasan & tanpa extend_days → ditolak
    bad = hr_client.post(f"/api/hr/onboarding/{prog_id}/decision",
                         params={"decision": "EXTEND"}, headers=headers("CHRO_MANAGER"))
    assert bad.status_code == 400, bad.text
    no_days = hr_client.post(f"/api/hr/onboarding/{prog_id}/decision",
                             params={"decision": "EXTEND", "reason": "Belum siap"},
                             headers=headers("CHRO_MANAGER"))
    assert no_days.status_code == 400, no_days.text

    ok_extend = hr_client.post(f"/api/hr/onboarding/{prog_id}/decision",
                               params={"decision": "EXTEND", "reason": "Skill belum cukup",
                                       "extend_days": 7}, headers=headers("CHRO_MANAGER"))
    assert ok_extend.status_code == 201, ok_extend.text
    assert ok_extend.json()["decision"] == "EXTEND"
    assert ok_extend.json()["training_end"] > hired["onboarding"]["training_end"]

    passed = hr_client.post(f"/api/hr/onboarding/{prog_id}/decision",
                            params={"decision": "PASS", "reason": "Lulus evaluasi mentor",
                                    "skill_evidence_ref": "SKILL-EVID-001"},
                            headers=headers("CHRO_MANAGER"))
    assert passed.status_code == 201, passed.text
    payload = passed.json()
    assert payload["decision"] == "PASS"
    assert payload["employee_activated"] is True
    assert payload["employment_status"] == "ACTIVE"
    assert payload["payroll_handoff"]["cfo_status"] == "PENDING"
    assert payload["payroll_handoff"]["employee_id"] == hired["employee"]["id"]

    # PASS kedua kali tidak sah (terminal)
    twice = hr_client.post(f"/api/hr/onboarding/{prog_id}/decision",
                           params={"decision": "PASS"}, headers=headers("CHRO_MANAGER"))
    assert twice.status_code == 409, twice.text

    emp = db.get(m.Employee, hired["employee"]["id"])
    assert emp.employment_status == "ACTIVE"
    handoff = db.query(m.PayrollHandoff).filter_by(employee_id=emp.id).one()
    assert handoff.event_type == "PASS" and handoff.onboarding_fk == prog_id
    # HR tidak mem-posting payroll: tidak ada penulisan cfo_status=POSTED dari HR
    assert handoff.cfo_acted_by_id is None and handoff.cfo_acted_at is None


def test_hr_cannot_post_payroll_only_request_handoff(hr_client, headers, db, hr):
    """Payroll milik CFO: HR boleh MEMBUAT handoff, tidak boleh mem-posting."""
    hired = _hired_candidate(hr_client, headers, db)
    r = hr_client.post(f"/api/hr/onboarding/{hired['onboarding']['id']}/decision",
                       params={"decision": "PASS", "reason": "Lulus"}, headers=headers("CHRO_MANAGER"))
    assert r.status_code == 201, r.text
    handoff_id = r.json()["payroll_handoff"]["id"]

    posted = hr_client.post(f"/api/hr/payroll-handoffs/{handoff_id}/actions",
                            params={"action": "POSTED"}, headers=headers("CHRO_MANAGER"))
    assert posted.status_code == 403, posted.text              # bukan wewenang HR
    row = db.get(m.PayrollHandoff, handoff_id)
    assert row.cfo_status == "PENDING"                          # tidak berubah


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
    assert sorted(row["missing"]) == ["discipline", "evaluator_manager", "spiritual"]
    assert body["parameters"] == ["quality", "responsibility", "discipline",
                                  "spiritual", "attitude", "skill"]
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
    cycle = m.PerformanceReviewCycle(period="2026-Q3", status="OPEN")
    db.add(cycle)
    db.commit()
    db.add(m.PerformanceReviewDetail(cycle_fk=cycle.id, performance_record_fk=rec.id,
                                     employee_fk=hr["employee"].id,
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


def test_create_cycle_record_detail_rejects_non_manager_evaluator(hr_client, headers, db, hr):
    cycle = hr_client.post("/api/hr/performance-cycles",
                           params={"period": "2026-Q3", "cycle_name": "Triwulan III"},
                           headers=headers("CHRO_MANAGER"))
    assert cycle.status_code == 201, cycle.text
    cycle_id = cycle.json()["id"]
    assert cycle.json()["status"] == "DRAFT"

    rec = m.PerformanceRecord(employee_id=hr["employee"].id, period="2026-Q3", quality=90.0)
    db.add(rec)
    db.commit()

    # evaluator HR_SUPPORT bukan manager terkait → harus ditolak (revisi #65)
    support = hr["users"][m.Role.HR_SUPPORT]
    bad = hr_client.post(f"/api/hr/performance-cycles/{cycle_id}/details",
                         params={"performance_record_fk": rec.id,
                                 "evaluator_manager_id": support.id},
                         headers=headers("CHRO_MANAGER"))
    assert bad.status_code == 422, bad.text
    assert "manager" in bad.json()["detail"].lower()

    mgr = hr["users"][m.Role.COO_MANAGER]
    ok = hr_client.post(f"/api/hr/performance-cycles/{cycle_id}/details",
                        params={"performance_record_fk": rec.id,
                                "evaluator_manager_id": mgr.id,
                                "strengths": "Disiplin", "gaps": "Skill teknis",
                                "improvement_action": "Pelatihan lanjutan"},
                        headers=headers("CHRO_MANAGER"))
    assert ok.status_code == 201, ok.text
    assert ok.json()["evaluator_is_manager"] is True
    assert ok.json()["employee_fk"] == hr["employee"].id

    # duplikat record dalam satu siklus → ditolak
    dup = hr_client.post(f"/api/hr/performance-cycles/{cycle_id}/details",
                         params={"performance_record_fk": rec.id,
                                 "evaluator_manager_id": mgr.id},
                         headers=headers("CHRO_MANAGER"))
    assert dup.status_code == 409, dup.text


def test_finalized_review_cannot_be_overwritten_without_correction_reason(hr_client, headers, db, hr):
    cycle_id = hr_client.post("/api/hr/performance-cycles",
                              params={"period": "2026-Q4"}, headers=headers("CHRO_MANAGER")).json()["id"]
    rec = m.PerformanceRecord(employee_id=hr["employee"].id, period="2026-Q4", quality=80.0)
    db.add(rec)
    db.commit()
    mgr = hr["users"][m.Role.CMO_MANAGER]
    detail_id = hr_client.post(f"/api/hr/performance-cycles/{cycle_id}/details",
                               params={"performance_record_fk": rec.id,
                                       "evaluator_manager_id": mgr.id},
                               headers=headers("CHRO_MANAGER")).json()["id"]

    def step(action, **params):
        return hr_client.post(f"/api/hr/performance-details/{detail_id}/actions",
                              params={"action": action, **params}, headers=headers("CHRO_MANAGER"))

    assert step("SUBMITTED").status_code == 201
    bad = step("FINALIZED")                       # belum ACKNOWLEDGED → transisi tidak sah
    assert bad.status_code == 409, bad.text
    assert step("ACKNOWLEDGED", employee_acknowledged_at="2026-10-01T08:00:00").status_code == 201
    assert step("FINALIZED", evidence_ref="EVID-REVIEW-1").status_code == 201

    # koreksi review FINALIZED tanpa correction_reason → ditolak (revisi #65)
    no_reason = step("CORRECTED")
    assert no_reason.status_code == 409 and "correction" in no_reason.json()["detail"].lower(), no_reason.text

    corrected = step("CORRECTED", correction_reason="Salah input bobot spiritual")
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["version"] == 2
    assert corrected.json()["correction_reason"] == "Salah input bobot spiritual"

    audits = db.query(m.AuditLog).filter_by(entity="PerformanceReviewDetail").all()
    assert any(a.action == "HR_PERFORMANCE_REVIEW_CORRECT" for a in audits)


# ── revisi #66: employee issue, confidential & eskalasi CEO ─────────────────

def _issue_case(db, hr, *, severity="RED", confidential=True, escalated=False):
    issue = m.EmployeeIssue(employee_id=hr["employee"].id, issue_type="Discipline",
                            description="Pelanggaran berat", severity=severity,
                            status="INVESTIGATION", reported_by="Supervisor Cutting")
    db.add(issue)
    db.flush()
    db.add(m.EmployeeCaseDetail(issue_fk=issue.id, case_no=f"CASE-{issue.id:05d}",
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
    assert owner["redacted_count"] == 0

    ceo = hr_client.get("/api/hr/employee-issues", headers=headers("CEO")).json()
    assert ceo["total"] == 1 and ceo["items"][0]["redacted"] is False

    support = hr_client.get("/api/hr/employee-issues", headers=headers("HR_SUPPORT")).json()
    assert support["redacted_count"] == 1
    row = support["items"][0]
    assert row["redacted"] is True and row["status"] == "RESTRICTED"
    assert row["severity"] is None
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
    assert "investigator_id" in row["missing"]
    assert row["allowed_next_statuses"] == ["ACTION_PLAN", "NO_CASE", "ESCALATED_CEO"]


def test_red_case_escalation_to_ceo_is_recorded_and_audited(hr_client, headers, db, hr):
    issue = _issue_case(db, hr, severity="RED", confidential=False)

    bad = hr_client.post(f"/api/hr/employee-issues/{issue.id}/escalate-ceo",
                         headers=headers("CHRO_MANAGER"))
    assert bad.status_code == 400, bad.text

    ok = hr_client.post(f"/api/hr/employee-issues/{issue.id}/escalate-ceo?reason=Ancaman+kekerasan+di+lantai+produksi",
                        headers=headers("CHRO_MANAGER"))
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["status"] == "ESCALATED_CEO" and body["audit_logged"] is True

    log = db.query(m.EmployeeIssueEscalation).filter_by(issue_fk=issue.id).all()
    assert len(log) == 1 and log[0].reason.startswith("Ancaman")
    assert log[0].escalated_by_id == hr["users"][m.Role.CHRO_MANAGER].id

    audits = db.query(m.AuditLog).filter_by(entity="EmployeeIssue", entity_id=issue.id,
                                            action="HR_ISSUE_ESCALATE_CEO").all()
    assert len(audits) == 1
    assert audits[0].reason.startswith("Ancaman")
    assert audits[0].new_status == "ESCALATED_CEO"

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
    db.commit()
    db.execute(text("ALTER TABLE employee_issue_escalations RENAME TO _esc_tmp"))
    db.commit()
    try:
        r = hr_client.post(f"/api/hr/employee-issues/{issue.id}/escalate-ceo?reason=Kasus+berat+sekali",
                           headers=headers("CHRO_MANAGER"))
        assert r.status_code == 503, r.text
        assert "jejak audit" in r.json()["detail"]
        db.refresh(issue)
        assert issue.status == "INVESTIGATION"          # status tidak berubah
    finally:
        db.execute(text("ALTER TABLE _esc_tmp RENAME TO employee_issue_escalations"))
        db.commit()


def test_case_creation_red_escalation_only_and_confidential_evidence_logged(hr_client, headers, db, hr):
    """Revisi #66: kategori wajib, bukti confidential hanya owner HR/CEO + dicatat."""
    created = hr_client.post("/api/hr/employee-issues",
                             params={"employee_id": hr["employee"].id,
                                     "issue_type": "Discipline",
                                     "description": "Pelanggaran berat",
                                     "severity": "RED", "category": "DISCIPLINE",
                                     "confidential": True, "sla_hours": 24},
                             headers=headers("CHRO_MANAGER"))
    assert created.status_code == 201, created.text
    case = created.json()
    assert case["case_no"] == "CASE-00001"
    assert case["confidential"] is True
    case_id = case["id"]

    # bukti access_level di luar daftar → ditolak
    bad_level = hr_client.post(f"/api/hr/employee-cases/{case_id}/evidence",
                               params={"evidence_ref": "FILE-1", "access_level": "PUBLIC"},
                               headers=headers("CHRO_MANAGER"))
    assert bad_level.status_code == 422, bad_level.text

    ev = hr_client.post(f"/api/hr/employee-cases/{case_id}/evidence",
                        params={"evidence_ref": "FILE-1",
                                "access_level": "HR_OWNER_AND_CEO_ONLY"},
                        headers=headers("CHRO_MANAGER"))
    assert ev.status_code == 201, ev.text

    # HR_SUPPORT tidak boleh membuka bukti kasus confidential
    denied = hr_client.get(f"/api/hr/employee-cases/{case_id}/evidence/FILE-1?reason=Mau+lihat",
                           headers=headers("HR_SUPPORT"))
    assert denied.status_code == 403, denied.text

    opened = hr_client.get(f"/api/hr/employee-cases/{case_id}/evidence/FILE-1?reason=Verifikasi+laporan",
                           headers=headers("CHRO_MANAGER"))
    assert opened.status_code == 200, opened.text
    logs = db.query(m.EmployeeCaseAccessLog).filter_by(case_fd if False else m.EmployeeCaseAccessLog.case_fk,
                                                       case_id).all() if False else \
        db.query(m.EmployeeCaseAccessLog).filter_by(case_fk=case_id).all()
    assert len(logs) == 1 and logs[0].action == "VIEW"
    assert logs[0].user_id == hr["users"][m.Role.CHRO_MANAGER].id
    assert "Verifikasi" in logs[0].reason

    # escalate ke CEO tercatat pada kasus RED
    esc = hr_client.post(f"/api/hr/employee-issues/{case_id if False else case['issue_fk']}/escalate-ceo",
                         params={"reason": "Kekerasan fisik di lantai produksi"},
                         headers=headers("CHRO_MANAGER"))
    assert esc.status_code == 201, esc.text
    db.refresh(db.get(m.EmployeeCaseDetail, case_id))
    assert db.get(m.EmployeeCaseDetail, case_id).ceo_decision_fk is not None
