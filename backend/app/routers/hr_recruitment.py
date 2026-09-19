"""HR — Manpower Request & Recruitment, Onboarding, Performance Review, Employee Issue.

Revisi #63 (HR-Y-003 Manpower Request, Recruitment & Candidate), #64 (HR-Y-004
Onboarding, Training 2 Minggu & Payroll Handoff), #65 (HR-Y-005 Performance Review
& Evaluator Manager), #66 (HR-Y-006 Employee Issue, Discipline & CEO Escalation).

Desain endpoint ini sengaja *read-only* dan *defensif*:

- Ia hanya menyajikan antrean kerja (work queue) dari tabel yang SUDAH ada
  (`performance_records`, `employee_issues`, `employees`, `training_records`).
- Tabel/kolom yang dibutuhkan lifecycle penuh (manpower_requests, candidates,
  investigations, dst.) BELUM ada; spesifikasinya ditulis di
  `REQUESTS/hr_recruitment.md` dan TIDAK dibuat migration sendiri sesuai
  AGENT-RULES bagian 1 & 4.
- Kalau tabel belum ada, endpoint mengembalikan daftar kosong yang tetap
  valid (bukan 500), dan menyebut kebutuhan kolomnya di `pending_schema`.

Aturan akses yang ditegakkan di sini:

- Kasus `confidential` (revisi #66) HANYA boleh dibaca owner role HR + CEO.
  Artinya bila `confidential=True`, baris hanya dikembalikan ke CHRO_MANAGER/CEO
  (dan user yang terlibat sebagai reporter/investigator). HR_SUPPORT tidak
  otomatis melihat detailnya.
- Eskalasi ke CEO harus tercatat: detail kasus menampilkan `escalated_to_ceo`
  beserta siapa/kapan, dan `ceo_action_tracker` yang tertaut (CEODecision /
  CEOActionItem) — bukan dropdown status bebas.
- Performance review punya `evaluator_manager`; sistem menandai review yang
  penilainya bukan manager (`evaluator_is_manager=False`) sebagai temuan, karena
  HR tidak boleh menilai dirinya sendiri (revisi #65).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..auth import get_current_user
from ..database import get_db
from .. import models as m

router = APIRouter(prefix="/hr", tags=["hr"])

# Owner role HR + CEO. HR_SUPPORT hanya melihat baris non-confidential.
HR_OWNER_ROLES = {"CHRO_MANAGER"}
HR_VIEW_ROLES = {"CHRO_MANAGER", "HR_SUPPORT", "CEO"}

# Transisi status yang sah (revisi #63/#64/#66): perubahan status lewat tindakan,
# bukan dropdown bebas. Dipakai untuk menghitung allowed_next_actions.
MANPOWER_TRANSITIONS = {
    "DRAFT": ["SUBMITTED", "CANCELLED"],
    "SUBMITTED": ["ELIGIBLE", "REJECTED", "NEED_CLARIFICATION"],
    "NEED_CLARIFICATION": ["SUBMITTED", "CANCELLED"],
    "ELIGIBLE": ["VACANCY_OPEN", "CANCELLED"],
    "VACANCY_OPEN": ["SCREENING", "ON_HOLD", "CANCELLED"],
    "SCREENING": ["INTERVIEW", "ON_HOLD", "CANCELLED"],
    "INTERVIEW": ["OFFER", "REJECTED", "ON_HOLD"],
    "OFFER": ["HIRED", "REJECTED"],
    "HIRED": ["CLOSED"],
    "CLOSED": [],
    "REJECTED": ["CLOSED"],
    "CANCELLED": [],
    "ON_HOLD": ["VACANCY_OPEN", "SCREENING", "CANCELLED"],
}

CANDIDATE_TRANSITIONS = {
    "NEW": ["SCREENING"],
    "SCREENING": ["SHORTLISTED", "SCREENED_OUT"],
    "SHORTLISTED": ["INTERVIEW_SCHEDULED", "REJECTED"],
    "INTERVIEW_SCHEDULED": ["INTERVIEWED", "NO_SHOW"],
    "INTERVIEWED": ["OFFERED", "REJECTED", "TALENT_POOL"],
    "OFFERED": ["OFFER_ACCEPTED", "OFFER_REJECTED", "OFFER_EXPIRED"],
    "OFFER_ACCEPTED": ["HIRED"],
    "HIRED": [],
    "SCREENED_OUT": [],
    "REJECTED": [],
    "NO_SHOW": ["INTERVIEW_SCHEDULED", "REJECTED"],
    "TALENT_POOL": ["SHORTLISTED"],
    "OFFER_REJECTED": ["TALENT_POOL", "REJECTED"],
    "OFFER_EXPIRED": ["TALENT_POOL", "REJECTED"],
}

ISSUE_TRANSITIONS = {
    "OPEN": ["INVESTIGATION", "CLOSED"],
    "INVESTIGATION": ["ACTION_PLAN", "NO_CASE", "ESCALATED_CEO"],
    "ACTION_PLAN": ["PENDING_RESPONSE", "ESCALATED_CEO", "RESOLVED"],
    "PENDING_RESPONSE": ["ACTION_PLAN", "ESCALATED_CEO", "RESOLVED"],
    "ESCALATED_CEO": ["ACTION_PLAN", "RESOLVED", "CLOSED"],
    "RESOLVED": ["CLOSED", "REOPENED"],
    "CLOSED": ["REOPENED"],
    "REOPENED": ["INVESTIGATION", "ACTION_PLAN", "CLOSED"],
    "NO_CASE": [],
}

PERFORMANCE_TRANSITIONS = {
    "DRAFT": ["SUBMITTED"],
    "SUBMITTED": ["ACKNOWLEDGED", "NEED_REVISION"],
    "ACKNOWLEDGED": ["FINALIZED"],
    "NEED_REVISION": ["DRAFT", "SUBMITTED"],
    "FINALIZED": ["CORRECTED"],
    "CORRECTED": ["ACKNOWLEDGED", "FINALIZED"],
}

# Kolom yang dibutuhkan tapi belum ada di schema — dipakai untuk `data_missing`
# dan untuk `pending_schema` saat tabel benar-benar belum ada.
PENDING_TABLES = {
    "manpower_requests": [
        "id", "request_no", "requester_id (FK users.id)", "division", "position",
        "qty", "reason", "requirement", "priority (LOW/NORMAL/HIGH/URGENT)",
        "target_start_date", "budget_ref", "payroll_ref", "owner_id", "due_date",
        "status", "decision", "decision_reason", "version", "created_at", "updated_at",
    ],
    "recruitment_vacancies": [
        "id", "manpower_request_fk", "vacancy_no", "source", "status",
        "opened_at", "closed_at", "created_at", "updated_at",
    ],
    "recruitment_candidates": [
        "id", "candidate_no", "vacancy_fk", "name", "source", "contact",
        "cv_evidence_ref", "screening_result", "screening_notes",
        "interview_scheduled_at", "interviewer_id", "interview_result",
        "interview_score", "manager_assessment", "decision", "offer_amount",
        "accepted_at", "rejected_reason", "next_action", "owner_id", "due_date",
        "status", "employee_fk (terisi hanya setelah hire sah)", "version",
        "created_at", "updated_at",
    ],
    "onboarding_programs": [
        "id", "employee_fk/candidate_fk", "position", "training_start",
        "training_end", "mentor_id", "manager_evaluator_id", "checklist_json",
        "attendance_ref (read-only dari CFO)", "skill_evidence_ref",
        "issue_blocker", "progress_pct", "due_date", "salary_category", "salary_rate",
        "decision (PASS/EXTEND/FAIL)", "decision_reason", "extend_days",
        "effective_date", "payroll_handoff_id", "version", "created_at", "updated_at",
    ],
    "payroll_handoffs": [
        "id", "onboarding_fk", "employee_fk", "division_salary_ref",
        "requested_by_id", "requested_at", "cfo_status", "cfo_acted_by_id",
        "cfo_acted_at", "note (HR tidak mem-posting payroll)", "created_at", "updated_at",
    ],
    "performance_review_cycles": [
        "id", "period", "cycle_name", "weight_config_json", "scoring_rule_json",
        "status", "opened_at", "closed_at", "created_by_id", "created_at", "updated_at",
    ],
    "performance_review_details": [
        "id", "cycle_fk", "performance_record_fk", "employee_fk",
        "evaluator_manager_id", "evaluator_is_manager", "evidence_ref",
        "strengths", "gaps", "improvement_action", "action_owner_id", "action_due",
        "employee_acknowledged_at", "reviewed_by_id", "reviewed_at", "status",
        "version", "correction_reason", "created_at", "updated_at",
    ],
    "employee_case_details": [
        "id", "issue_fk", "case_no", "category", "source/reporter_id",
        "occurred_date", "reported_date", "confidential (bool)", "investigator_id",
        "owner_id", "due_date", "sla_hours", "investigation_finding",
        "action_plan", "employee_response", "manager_response", "decision",
        "decision_reason", "follow_up_date", "resolution_evidence_ref",
        "resolved_by_id", "resolved_at", "closed_by_id", "closed_at",
        "escalated_to_ceo", "escalated_by_id", "escalated_at", "escalation_reason",
        "ceo_decision_fk", "version", "created_at", "updated_at",
    ],
    "employee_case_evidence": [
        "id", "case_fk", "evidence_ref", "access_level", "uploaded_by_id",
        "created_at", "updated_at",
    ],
    "employee_case_access_log": [
        "id", "case_fk", "user_id", "action", "reason", "created_at",
    ],
    "employee_issue_escalations": [
        "id", "issue_fk", "escalated_by_id", "escalated_at", "reason",
        "ceo_decision_fk", "acknowledged_at", "created_at",
    ],
}


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()
    return value.isoformat()


def _has_table(db: Session, name: str) -> bool:
    try:
        return sa_inspect(db.get_bind()).has_table(name)
    except Exception:
        return False


def _require_view(user):
    role = getattr(user.role, "value", user.role)
    if role not in HR_VIEW_ROLES:
        raise HTTPException(403, "Antrean HR tidak tersedia untuk peran ini.")


def _require_owner(user):
    """Owner role HR (revisi #66): hanya owner role HR + CEO yang melihat kasus confidential."""
    role = getattr(user.role, "value", user.role)
    if role not in (HR_OWNER_ROLES | {"CEO"}):
        raise HTTPException(403, "Hanya owner role HR dan CEO yang dapat mengakses data ini.")


def _allowed(transitions, current):
    return transitions.get((current or "").upper(), [])


def _queue_row(*, task_id, kind, stage, status, missing, action, owner, due,
               source, updated, handoff, ref=None, extra=None):
    """Kontrak kolom wajib antrean (revisi #63): ID, tahap proses, status saat ini,
    data yang kurang, next action, owner, due, source/evidence, updated_at, handoff."""
    row = {
        "task_id": task_id,
        "decision_type": kind,
        "ref": ref,
        "stage": stage,
        "status": status,
        "missing": missing,
        "next_action": action,
        "owner": owner,
        "due": _iso(due),
        "source": source,
        "updated_at": _iso(updated),
        "handoff": handoff,
    }
    if extra:
        row.update(extra)
    return row


# ─────────────────────────── manpower requests ───────────────────────────

@router.get("/manpower-requests")
def manpower_requests(db: Session = Depends(get_db), user=Depends(get_current_user),
                      status: str = Query(None)):
    """Antrean Manpower Request dari semua manager/divisi ke HR (revisi #63)."""
    _require_view(user)
    table_ready = _has_table(db, "manpower_requests")
    rows = []
    if table_ready:
        rows = db.query(m.ManpowerRequest).order_by(m.ManpowerRequest.id.desc()).all()
    items = []
    for r in rows:
        current = (r.status or "SUBMITTED").upper()
        items.append(_queue_row(
            task_id=r.request_no or f"MPR-{r.id:05d}",
            kind="MANPOWER_REQUEST",
            ref=r.id,
            stage="HR_ELIGIBILITY" if current == "SUBMITTED" else current,
            status=current,
            missing=[] if r.decision else ["decision", "decision_reason"],
            action=(f"HR review kelayakan; next sah: {', '.join(_allowed(MANPOWER_TRANSITIONS, current)) or '-'}"),
            owner="CHRO_MANAGER",
            due=getattr(r, "due_date", None),
            source=f"manpower_requests#{r.id}",
            updated=getattr(r, "updated_at", None) or getattr(r, "created_at", None),
            handoff="MANAGER_DIVISI" if current == "SUBMITTED" else "HR_RECRUITMENT",
            extra={
                "request_no": r.request_no,
                "division": r.division,
                "position": r.position,
                "qty": r.qty,
                "priority": r.priority,
                "target_start_date": _iso(getattr(r, "target_start_date", None)),
                "requester": getattr(r, "requester_id", None),
                "allowed_next_statuses": _allowed(MANPOWER_TRANSITIONS, current),
            },
        ))
    if status:
        items = [i for i in items if (i["status"] or "").upper() == status.upper()]
    return {
        "queues": [i for i in items if i["status"] in
                   ("SUBMITTED", "ELIGIBLE", "NEED_CLARIFICATION", "DRAFT", "VACANCY_OPEN")],
        "completed": [i for i in items if i["status"] in
                      ("HIRED", "CLOSED", "REJECTED", "CANCELLED")],
        "in_progress": [i for i in items if i["status"] in
                        ("SCREENING", "INTERVIEW", "OFFER", "ON_HOLD")],
        "total": len(items),
        "schema_ready": table_ready,
        "pending_schema": [] if table_ready else PENDING_TABLES["manpower_requests"],
        "pending_tables": [] if table_ready else ["manpower_requests", "recruitment_vacancies"],
        "note": None if table_ready else
                "Tabel manpower_requests belum ada. Kebutuhan ada di REQUESTS/hr_recruitment.md.",
        "transition_map": MANPOWER_TRANSITIONS,
    }


# ─────────────────────────── candidates ───────────────────────────

@router.get("/candidates")
def candidates(db: Session = Depends(get_db), user=Depends(get_current_user),
               status: str = Query(None)):
    """Antrean kandidat: screening → interview → keputusan → hire (revisi #63)."""
    _require_view(user)
    table_ready = _has_table(db, "recruitment_candidates")
    rows = []
    if table_ready:
        rows = db.query(m.RecruitmentCandidate).order_by(m.RecruitmentCandidate.id.desc()).all()
    items = []
    for c in rows:
        current = (c.status or "NEW").upper()
        missing = []
        if current in ("INTERVIEWED", "SHORTLISTED") and not getattr(c, "interview_score", None):
            missing.append("interview_score")
        if current == "INTERVIEWED" and not getattr(c, "manager_assessment", None):
            missing.append("manager_assessment (penilaian manager terkait)")
        if current == "OFFERED" and not getattr(c, "offer_amount", None):
            missing.append("offer_amount")
        if not getattr(c, "cv_evidence_ref", None):
            missing.append("cv_evidence_ref")
        items.append(_queue_row(
            task_id=c.candidate_no or f"CAND-{c.id:05d}",
            kind="RECRUITMENT_CANDIDATE",
            ref=c.id,
            stage=current,
            status=current,
            missing=missing,
            action=("Jadwalkan interview" if current in ("SHORTLISTED", "NEW")
                    else "Input hasil wawancara" if current == "INTERVIEW_SCHEDULED"
                    else "Rekam keputusan hire/reject" if current == "INTERVIEWED"
                    else f"Next sah: {', '.join(_allowed(CANDIDATE_TRANSITIONS, current)) or '-'}"),
            owner="CHRO_MANAGER",
            due=getattr(c, "due_date", None),
            source=f"recruitment_candidates#{c.id}",
            updated=getattr(c, "updated_at", None) or getattr(c, "created_at", None),
            handoff="EMPLOYEE_MASTER" if current == "OFFER_ACCEPTED" else "HR_ONBOARDING" if current == "HIRED" else "MANAGER_INTERVIEW",
            extra={
                "candidate_no": c.candidate_no,
                "name": c.name,
                "source_of_candidate": c.source,
                "vacancy_fk": getattr(c, "vacancy_fk", None),
                "interviewer": getattr(c, "interviewer_id", None),
                "interview_score": getattr(c, "interview_score", None),
                "decision": getattr(c, "decision", None),
                "accepted_rejected_reason": getattr(c, "rejected_reason", None),
                "next_action_detail": getattr(c, "next_action", None),
                "allowed_next_statuses": _allowed(CANDIDATE_TRANSITIONS, current),
            },
        ))
    if status:
        items = [i for i in items if (i["status"] or "").upper() == status.upper()]
    return {
        "queues": [i for i in items if i["status"] not in ("HIRED", "REJECTED", "SCREENED_OUT")],
        "completed": [i for i in items if i["status"] == "HIRED"],
        "rejected": [i for i in items if i["status"] in ("REJECTED", "SCREENED_OUT", "OFFER_REJECTED", "OFFER_EXPIRED")],
        "items": items,
        "total": len(items),
        "schema_ready": table_ready,
        "pending_schema": [] if table_ready else PENDING_TABLES["recruitment_candidates"],
        "pending_tables": [] if table_ready else ["recruitment_vacancies", "recruitment_candidates"],
        "note": None if table_ready else
                "Tabel recruitment_candidates belum ada. Kebutuhan ada di REQUESTS/hr_recruitment.md.",
        "transition_map": CANDIDATE_TRANSITIONS,
    }


# ─────────────────────────── performance reviews ───────────────────────────

@router.get("/performance-reviews")
def performance_reviews(db: Session = Depends(get_db), user=Depends(get_current_user),
                        period: str = Query(None), employee_id: int = Query(None)):
    """Performance review enam parameter dengan evaluator manager (revisi #65).

    Sumber: `performance_records` (sudah ada). Tabel detail (cycle/weight/evidence/
    acknowledgement/version) belum ada → `pending_schema`.
    """
    _require_view(user)
    query = db.query(m.PerformanceRecord)
    if period:
        query = query.filter(m.PerformanceRecord.period == period)
    if employee_id:
        query = query.filter(m.PerformanceRecord.employee_id == employee_id)
    records = query.order_by(m.PerformanceRecord.id.desc()).all()
    detail_ready = _has_table(db, "performance_review_details")
    details = {}
    if detail_ready:
        for d in db.query(m.PerformanceReviewDetail).all():
            details[d.performance_record_fk] = d

    employees = {e.id: e for e in db.query(m.Employee).all()}
    items = []
    for r in records:
        d = details.get(r.id)
        emp = employees.get(r.employee_id)
        score_cols = {
            "quality": r.quality, "responsibility": r.responsibility,
            "discipline": r.discipline, "spiritual": r.spiritual,
            "attitude": r.attitude, "skill": r.skill,
        }
        # Empat parameter wajib diisi sebelum HR mengelola hasil.
        missing = [k for k in ("quality", "responsibility", "discipline", "spiritual",
                               "attitude", "skill") if score_cols[k] is None]
        evaluator = getattr(d, "evaluator_manager_id", None) if d else None
        evaluator_is_manager = bool(getattr(d, "evaluator_is_manager", False)) if d else False
        current = (getattr(d, "status", None) or "DRAFT").upper()
        items.append(_queue_row(
            task_id=f"PR-{r.id:05d}",
            kind="PERFORMANCE_REVIEW",
            ref=r.id,
            stage=f"PERIOD {r.period}",
            status=current,
            missing=missing + ([] if evaluator else ["evaluator_manager"]),
            action=("Lengkapi enam parameter" if missing else
                    f"Next sah: {', '.join(_allowed(PERFORMANCE_TRANSITIONS, current)) or '-'}"),
            owner="CHRO_MANAGER",
            due=getattr(d, "action_due", None) if d else None,
            source=f"performance_records#{r.id}",
            updated=getattr(r, "updated_at", None) or r.created_at,
            handoff="MANAGER_EVALUATOR" if not missing else "HR_MONITOR",
            extra={
                "employee_id": r.employee_id,
                "employee_name": emp.name if emp else None,
                "division": emp.division if emp else None,
                "position": emp.position if emp else None,
                "period": r.period,
                "scores": score_cols,
                "total_score": r.total_score,
                "grade": _grade(r.total_score),
                "evaluator_manager": evaluator,
                "evaluator_is_manager": evaluator_is_manager,
                "evidence_ref": getattr(d, "evidence_ref", None) if d else None,
                "improvement_action": getattr(d, "improvement_action", None) if d else None,
                "version": getattr(d, "version", None) if d else None,
                "allowed_next_statuses": _allowed(PERFORMANCE_TRANSITIONS, current),
                "integrity_flag": None if evaluator_is_manager else
                                  "Evaluator bukan manager terkait — penilaian tidak sah tanpa manager.",
            },
        ))
    return {
        "queues": [i for i in items if i["missing"] or i["status"] in ("SUBMITTED", "NEED_REVISION")],
        "finalized": [i for i in items if i["status"] in ("FINALIZED", "ACKNOWLEDGED")],
        "items": items,
        "total": len(items),
        "parameters": ["quality", "responsibility", "discipline", "spiritual", "attitude", "skill"],
        "schema_ready": True,
        "detail_schema_ready": detail_ready,
        "pending_schema": [] if detail_ready else PENDING_TABLES["performance_review_cycles"] + PENDING_TABLES["performance_review_details"],
        "pending_tables": [] if detail_ready else ["performance_review_cycles", "performance_review_details"],
        "note": None if detail_ready else
                "performance_records ada; detail siklus/bobot/evidence/version belum ada. Lihat REQUESTS/hr_recruitment.md.",
        "transition_map": PERFORMANCE_TRANSITIONS,
    }


def _grade(total):
    if total is None:
        return None
    if total >= 90:
        return "A"
    if total >= 80:
        return "B"
    if total >= 70:
        return "C"
    if total >= 60:
        return "D"
    return "E"


# ─────────────────────────── employee issues ───────────────────────────

def _case_detail(db, issue_id):
    if not _has_table(db, "employee_case_details"):
        return None
    return (db.query(m.EmployeeCaseDetail)
            .filter(m.EmployeeCaseDetail.issue_fk == issue_id)
            .order_by(m.EmployeeCaseDetail.id.desc()).first())


def _escalations(db, issue_id):
    if not _has_table(db, "employee_issue_escalations"):
        return []
    rows = (db.query(m.EmployeeIssueEscalation)
            .filter(m.EmployeeIssueEscalation.issue_fk == issue_id)
            .order_by(m.EmployeeIssueEscalation.id).all())
    return [{
        "id": e.id, "escalated_by": e.escalated_by_id, "escalated_at": _iso(e.escalated_at),
        "reason": e.reason, "ceo_decision_fk": e.ceo_decision_fk,
        "acknowledged_at": _iso(e.acknowledged_at),
    } for e in rows]


def _ceo_action_tracker(db, decision_fk):
    if not decision_fk or not _has_table(db, "ceo_action_items"):
        return []
    rows = (db.query(m.CEOActionItem).filter(m.CEOActionItem.decision_fk == decision_fk)
            .order_by(m.CEOActionItem.id).all())
    return [{
        "action_no": a.action_no, "title": a.title, "status": a.status,
        "authorized_owner_id": a.authorized_owner_id, "due_date": _iso(a.due_date),
        "next_follow_up": _iso(a.next_follow_up), "completion_note": a.completion_note,
        "evidence_ref": a.evidence_ref, "completed_at": _iso(a.completed_at),
        "verified_at": _iso(a.verified_at),
    } for a in rows]


@router.get("/employee-issues")
def employee_issues(db: Session = Depends(get_db), user=Depends(get_current_user),
                    severity: str = Query(None), status: str = Query(None)):
    """Kasus karyawan + disiplin + eskalasi CEO (revisi #66).

    Confidential: baris `confidential=True` HANYA dikembalikan ke owner role HR
    (CHRO_MANAGER) dan CEO. HR_SUPPORT menerima versi tersamarkan (redacted),
    bukan 500 — supaya antrean tetap jalan tanpa membocorkan isi kasus.
    """
    _require_view(user)
    role = getattr(user.role, "value", user.role)
    is_owner = role in (HR_OWNER_ROLES | {"CEO"})
    detail_ready = _has_table(db, "employee_case_details")
    query = db.query(m.EmployeeIssue)
    if severity:
        query = query.filter(m.EmployeeIssue.severity == severity.upper())
    if status:
        query = query.filter(m.EmployeeIssue.status == status.upper())
    issues = query.order_by(m.EmployeeIssue.id.desc()).all()
    employees = {e.id: e for e in db.query(m.Employee).all()}

    items = []
    redacted_count = 0
    for i in issues:
        d = _case_detail(db, i.id)
        confidential = bool(getattr(d, "confidential", False)) if d else False
        if confidential and not is_owner:
            redacted_count += 1
            items.append(_queue_row(
                task_id=getattr(d, "case_no", None) or f"CASE-{i.id:05d}",
                kind="EMPLOYEE_ISSUE",
                ref=i.id,
                stage="CONFIDENTIAL",
                status="RESTRICTED",
                missing=["akses: hanya owner role HR + CEO"],
                action="Minta owner role HR/CEO membuka kasus ini",
                owner="CHRO_MANAGER",
                due=None,
                source=f"employee_issues#{i.id} (restricted)",
                updated=i.created_at,
                handoff="CEO_ESCALATION",
                extra={"confidential": True, "redacted": True, "category": None,
                       "severity": None, "description": None, "escalation_log": [],
                       "evidence_access": "HR_OWNER_AND_CEO_ONLY"},
            ))
            continue

        severity_v = (i.severity or "YELLOW").upper()
        current = (i.status or "OPEN").upper()
        escalated = bool(getattr(d, "escalated_to_ceo", False)) if d else False
        missing = []
        if not getattr(d, "investigator_id", None):
            missing.append("investigator_id")
        if current in ("ACTION_PLAN", "PENDING_RESPONSE", "ESCALATED_CEO") and not getattr(d, "action_plan", None):
            missing.append("action_plan")
        if current in ("RESOLVED", "CLOSED") and not getattr(d, "resolution_evidence_ref", None):
            missing.append("resolution_evidence_ref")
        if escalated and not _escalations(db, i.id):
            missing.append("employee_issue_escalations (jejak eskalasi ke CEO)")
        if escalated and not getattr(d, "ceo_decision_fk", None):
            missing.append("ceo_decision_fk (Action Tracker CEO)")
        emp = employees.get(i.employee_id)
        items.append(_queue_row(
            task_id=getattr(d, "case_no", None) or f"CASE-{i.id:05d}",
            kind="EMPLOYEE_ISSUE",
            ref=i.id,
            stage="INVESTIGATION" if current in ("OPEN", "INVESTIGATION") else current,
            status=current,
            missing=missing,
            action=_issue_action(current, escalated),
            owner="CHRO_MANAGER",
            due=getattr(d, "due_date", None) if d else None,
            source=f"employee_issues#{i.id}",
            updated=getattr(d, "updated_at", None) or i.created_at,
            handoff="CEO_ACTION_TRACKER" if escalated else "HR_MANAGER",
            extra={
                "case_no": getattr(d, "case_no", None),
                "category": getattr(d, "category", None) or i.issue_type,
                "employee_id": i.employee_id,
                "employee_name": emp.name if emp else None,
                "source_reporter": i.reported_by or getattr(d, "reporter_id", None),
                "occurred_date": _iso(getattr(d, "occurred_date", None)) if d else None,
                "reported_date": _iso(getattr(d, "reported_date", None)) if d else None,
                "severity": severity_v,
                "confidential": confidential,
                "redacted": False,
                "investigator": getattr(d, "investigator_id", None) if d else None,
                "investigation_finding": getattr(d, "investigation_finding", None) if d else None,
                "decision": getattr(d, "decision", None) if d else None,
                "escalated_to_ceo": escalated,
                "escalated_by": getattr(d, "escalated_by_id", None) if d else None,
                "escalated_at": _iso(getattr(d, "escalated_at", None)) if d else None,
                "escalation_log": _escalations(db, i.id) if is_owner else [],
                "ceo_decision_fk": getattr(d, "ceo_decision_fk", None) if d else None,
                "ceo_action_tracker": _ceo_action_tracker(db, getattr(d, "ceo_decision_fk", None)) if is_owner else [],
                "evidence_access": "HR_OWNER_AND_CEO_ONLY" if confidential else "HR_TEAM",
                "allowed_next_statuses": _allowed(ISSUE_TRANSITIONS, current),
                "ceo_notification": "RED" if severity_v == "RED" else "NONE_BY_DEFAULT",
            },
        ))

    return {
        "queues": [i for i in items if i["status"] not in ("CLOSED", "NO_CASE", "RESTRICTED")],
        "resolved": [i for i in items if i["status"] in ("RESOLVED", "CLOSED", "NO_CASE")],
        "escalated_ceo": [i for i in items if i.get("escalated_to_ceo")],
        "red_critical": [i for i in items if i.get("severity") == "RED"],
        "items": items,
        "total": len(items),
        "redacted_count": redacted_count,
        "viewer_role": role,
        "confidential_access": "OWNER_HR_AND_CEO_ONLY" if not is_owner else "GRANTED",
        "schema_ready": True,
        "detail_schema_ready": detail_ready,
        "pending_schema": [] if detail_ready else
                          (PENDING_TABLES["employee_case_details"]
                           + PENDING_TABLES["employee_case_evidence"]
                           + PENDING_TABLES["employee_case_access_log"]
                           + PENDING_TABLES["employee_issue_escalations"]),
        "pending_tables": [] if detail_ready else
                          ["employee_case_details", "employee_case_evidence",
                           "employee_case_access_log", "employee_issue_escalations"],
        "note": None if detail_ready else
                "employee_issues ada; investigasi/confidential/eskalasi belum ada tabelnya. Lihat REQUESTS/hr_recruitment.md.",
        "escalation_rule": {
            "light_case": "HR bersama manager menyelesaikan; status lewat tindakan sah.",
            "red_case": "Dapat dieskalasi ke CEO; wajib tercatat (employee_issue_escalations).",
            "ceo_notification": {"RED": "PUSH", "YELLOW": "VISIBLE_NO_PUSH"},
            "ceo_action_tracker": "Wajib bila eskalasi butuh tindakan wajib (owner, due, follow-up sampai Closed).",
        },
        "transition_map": ISSUE_TRANSITIONS,
    }


def _issue_action(current, escalated):
    if current in ("OPEN", "INVESTIGATION"):
        return "Rekam temuan investigasi + evidence"
    if current == "ACTION_PLAN":
        return "Jalankan action plan, kumpulkan respons karyawan/manager"
    if current == "PENDING_RESPONSE":
        return "Kejar respons; eskalasi bila SLA lewat"
    if current == "ESCALATED_CEO":
        return "Pantau CEO Action Tracker sampai Closed"
    if current == "RESOLVED":
        return "Verifikasi bukti penyelesaian lalu tutup"
    if current == "CLOSED":
        return "Arsipkan; buka kembali hanya bila ada temuan baru"
    return f"Next sah: {', '.join(_allowed(ISSUE_TRANSITIONS, current)) or '-'}"


# ─────────────────────────── eskalasi ke CEO (write, tercatat) ───────────────────────────

@router.post("/employee-issues/{issue_id}/escalate-ceo", status_code=201)
def escalate_issue_to_ceo(issue_id: int,
                          reason: str = Query(None, description="Alasan eskalasi (wajib, tercatat)"),
                          db: Session = Depends(get_db),
                          user=Depends(get_current_user)):
    """Eskalasi kasus ke CEO — WAJIB tercatat (revisi #66).

    Menolak eskalasi yang tidak punya akibat audit:
    - 400 bila alasan tidak diberikan (eskalasi tanpa alasan bukan catatan sah),
    - 503 bila tabel jejak eskalasi belum ada — supaya eskalasi tidak pernah
      "berhasil" tanpa jejak,
    - 409 bila kasusnya bukan RED/critical.
    Hanya owner role HR + CEO.
    """
    _require_owner(user)
    issue = db.get(m.EmployeeIssue, issue_id)
    if issue is None:
        raise HTTPException(404, "Issue not found")
    if reason is None or len(reason.strip()) < 5:
        raise HTTPException(400, "Alasan eskalasi wajib diisi (minimal 5 karakter) agar tercatat.")
    reason = reason.strip()
    if not _has_table(db, "employee_issue_escalations"):
        raise HTTPException(
            503,
            "employee_issue_escalations belum ada — eskalasi ke CEO tidak boleh tanpa jejak audit. "
            "Lihat REQUESTS/hr_recruitment.md.")
    detail = _case_detail(db, issue_id)
    severity = (issue.severity or "YELLOW").upper()
    if severity != "RED":
        raise HTTPException(409, "Hanya kasus RED/critical yang dieskalasi ke CEO.")
    previous_status = (issue.status or "OPEN").upper()
    row = m.EmployeeIssueEscalation(issue_fk=issue_id, escalated_by_id=user.id,
                                    reason=reason, escalated_at=datetime.utcnow())
    db.add(row)
    if detail is not None:
        detail.escalated_to_ceo = True
        detail.escalated_by_id = user.id
        detail.escalated_at = datetime.utcnow()
        detail.escalation_reason = reason
    issue.status = "ESCALATED_CEO"
    log_audit(db, user, "HR_ISSUE_ESCALATE_CEO", "EmployeeIssue", issue_id,
              f"severity={severity}; reason={reason}",
              obj=issue, source_module="HREmployeeIssue",
              previous_status=previous_status, new_status="ESCALATED_CEO", reason=reason)
    db.commit()
    return {"ok": True, "issue_id": issue_id, "status": "ESCALATED_CEO",
            "escalated_by": user.id, "reason": reason,
            "ceo_notification": "RED", "audit_logged": True}


# ─────────────────────────── onboarding (revisi #64) ───────────────────────────

@router.get("/onboarding")
def onboarding(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Onboarding & training 2 minggu + payroll handoff (revisi #64).

    Belum ada tabelnya → keluar struktur kosong yang valid + kebutuhan schema.
    Sebagai gantinya, training_records yang ada dirangkum read-only.
    """
    _require_view(user)
    table_ready = _has_table(db, "onboarding_programs")
    training_ref = []
    employees = {e.id: e for e in db.query(m.Employee).all()}
    for t in db.query(m.TrainingRecord).order_by(m.TrainingRecord.id.desc()).limit(200).all():
        emp = employees.get(t.employee_id)
        training_ref.append({
            "task_id": f"TRN-{t.id:05d}",
            "employee_id": t.employee_id,
            "employee_name": emp.name if emp else None,
            "title": t.title,
            "start_date": _iso(t.start_date),
            "end_date": _iso(t.end_date),
            "result": t.result,
            "evaluator": t.evaluator,
            "source": f"training_records#{t.id}",
            "updated_at": _iso(t.created_at),
            "handoff": "CFO_PAYROLL" if (t.result or "").upper() == "PASS" else "HR_MONITOR",
        })
    return {
        "queues": [],
        "training_reference": training_ref,
        "total": 0,
        "schema_ready": table_ready,
        "pending_schema": [] if table_ready else
                          PENDING_TABLES["onboarding_programs"] + PENDING_TABLES["payroll_handoffs"],
        "pending_tables": [] if table_ready else ["onboarding_programs", "payroll_handoffs"],
        "note": None if table_ready else
                "Tabel onboarding_programs/payroll_handoffs belum ada. Lihat REQUESTS/hr_recruitment.md.",
        "decision_options": ["PASS", "EXTEND", "FAIL"],
        "rules": {
            "PASS": "Aktifkan employment status + buat Payroll Handoff ke CFO (gaji standar divisi). HR tidak mem-posting payroll.",
            "EXTEND": "Wajib durasi + alasan.",
            "FAIL": "Menutup onboarding secara terkontrol.",
        },
    }
