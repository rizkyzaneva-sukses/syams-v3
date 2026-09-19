"""HR — Manpower Request & Recruitment, Onboarding, Performance Review, Employee Issue.

Revisi #63 (HR-Y-003 Manpower Request, Recruitment & Candidate), #64 (HR-Y-004
Onboarding, Training 2 Minggu & Payroll Handoff), #65 (HR-Y-005 Performance Review
& Evaluator Manager), #66 (HR-Y-006 Employee Issue, Discipline & CEO Escalation).

Sejak tabel `manpower_requests`, `recruitment_vacancies`, `recruitment_candidates`,
`onboarding_programs`, `payroll_handoffs`, `performance_review_cycles`,
`performance_review_details`, `employee_case_details`, `employee_case_evidence`,
`employee_case_access_log`, dan `employee_issue_escalations` sudah ada, router ini
BUKAN lagi read-only: ia membuka jalur tulis yang sah (POST/PATCH) untuk antrean
tersebut, dengan aturan bisnis ditegakkan di server — bukan diserahkan ke UI.

Aturan bisnis yang ditegakkan di sini:

- #63 Perubahan status lewat *tindakan* (`/actions`), bukan dropdown bebas: setiap
  tindakan divalidasi terhadap `*_TRANSITIONS`. `employee_fk` pada kandidat hanya
  terisi setelah keputusan hire yang sah (`/hire`), dan hire menuntut status
  `OFFER_ACCEPTED` + penilaian manager.
- #64 Training onboarding 2 minggu (`TRAINING_DAYS = 14`). `PASS` → karyawan
  diaktifkan + Payroll Handoff dibuat untuk CFO; `EXTEND` WAJIB `extend_days` +
  alasan; `FAIL` menutup onboarding terkontrol. HR membuat handoff, CFO yang
  mem-posting — HR tidak pernah menulis transaksi payroll.
- #65 Evaluator performance HARUS manager terkait: detail review ditolak (422)
  kalau `evaluator_manager_id` bukan pengguna dengan peran manager. Review
  `FINALIZED` tidak boleh ditimpa — koreksi lewat `version` baru +
  `correction_reason`.
- #66 Eskalasi ke CEO hanya untuk kasus RED dan WAJIB meninggalkan jejak di
  `employee_issue_escalations`. Tanpa tabel itu endpoint mengembalikan **503**
  dan status issue TIDAK berubah — eskalasi tidak boleh "berhasil" tanpa audit.
  Kasus `confidential` hanya dibaca owner role HR + CEO, dan setiap pembukaan
  bukti confidential dicatat di `employee_case_access_log`.

Selama tabel belum ada (mis. DB lama), endpoint baca tetap mengembalikan struktur
kosong valid (`schema_ready: false` + `pending_schema`), bukan 500.
"""
import json
from datetime import date, datetime, timedelta, timezone

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

# Penulis antrean HR (revisi #63-#66). CEO ikut menulis jejak dampak/tindakannya.
HR_WRITE_ROLES = {"CHRO_MANAGER", "HR_SUPPORT", "CEO"}

# Peran yang sah sebagai manager terkait (revisi #65: evaluator = manager).
MANAGER_ROLES = {"CMO_MANAGER", "CFO_MANAGER", "COO_MANAGER", "CHRO_MANAGER"}

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

# Aturan bisnis #64: masa training onboarding adalah 2 minggu.
TRAINING_DAYS = 14

MANPOWER_PRIORITIES = {"LOW", "NORMAL", "HIGH", "URGENT"}
ONBOARDING_DECISIONS = {"PASS", "EXTEND", "FAIL"}
CASE_CATEGORIES = {
    "DISCIPLINE", "ATTENDANCE", "PERFORMANCE", "CONDUCT", "HARASSMENT",
    "SAFETY", "FRAUD", "OTHER",
}
EVIDENCE_ACCESS_LEVELS = {"HR_TEAM", "HR_OWNER_AND_CEO_ONLY"}
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


# ─────────────────────── helper jalur TULIS (revisi #63-#66) ───────────────────────
#
# Semua penulisan lewat helper di bawah supaya: (1) tabel yang belum ada ditolak
# 503 dengan alasan — bukan 500, dan bukan "berhasil" tanpa jejak; (2) peran
# penulis diperiksa di server; (3) setiap perubahan status meninggalkan audit log.

def _role(user) -> str:
    return getattr(user.role, "value", user.role)


def _actor_name(user) -> str:
    """Identitas aktor untuk pencatatan: peran + id (stabil, tidak menebak nama)."""
    name = getattr(user, "name", None)
    return f"{name} ({_role(user)}#{getattr(user, 'id', None)})" if name else f"{_role(user)}#{getattr(user, 'id', None)}"


def _require_write(user):
    if _role(user) not in HR_WRITE_ROLES:
        raise HTTPException(403, "Hanya CHRO_MANAGER/HR_SUPPORT/CEO yang boleh menulis antrean HR.")


def _need(db: Session, table: str):
    """Tabel yang belum ada → 503 dengan alasan; tidak pernah dilanjutkan sebagian."""
    if not _has_table(db, table):
        raise HTTPException(
            503,
            f"Tabel {table} belum ada — permintaan tulis HR ini tidak boleh "
            f"dilakukan sebagian. Lihat REQUESTS/hr_recruitment.md.")


def _serial(obj):
    """Kolom objek → dict JSON-able (Date/DateTime jadi ISO)."""
    out = {}
    for col in obj.__table__.columns:
        value = getattr(obj, col.name, None)
        out[col.name] = _iso(value) if isinstance(value, (date, datetime)) else value
    return out


def _parse_date(value, field: str):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise HTTPException(422, f"{field} harus berupa tanggal ISO (YYYY-MM-DD).")


def _parse_dt(value, field: str):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"{field} harus berupa timestamp ISO.")


def _parse_json(value, field: str, default):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{field} harus berupa JSON yang sah.")


def _seq_no(db: Session, model, column, prefix: str, width: int = 5) -> str:
    """Nomor dokumen berurutan; aman di DB kosong maupun berisi."""
    count = db.query(model).count() if _has_table(db, model.__tablename__) else 0
    seq = count + 1
    for _ in range(50):
        candidate = f"{prefix}{seq:0{width}d}"
        if not db.query(model).filter(column == candidate).first():
            return candidate
        seq += 1
    raise HTTPException(409, f"Tidak bisa mengalokasikan nomor {prefix} baru.")


def _require_transition(transitions, current: str, target: str, label: str = "status"):
    current = (current or "").upper()
    target = (target or "").upper()
    allowed = _allowed(transitions, current)
    if target not in allowed:
        raise HTTPException(
            409,
            f"Transisi {label} {current} → {target} tidak sah. "
            f"Yang sah: {', '.join(allowed) or '-'}.")
    return target


def _bump_version(obj, reason: str | None = None):
    """Revisi #63/#65: perubahan menaikkan `version`; koreksi disertai alasan."""
    obj.version = (getattr(obj, "version", None) or 1) + 1
    return obj.version


def _audit(db, user, action, entity, entity_id, detail, obj,
           previous_status=None, new_status=None, reason=None):
    log_audit(db, user, action, entity, entity_id, detail, obj=obj,
              source_module="HRRecruitment", previous_status=previous_status,
              new_status=new_status, reason=reason)


def _require_manager(user_id: int, db: Session, label: str):
    """Revisi #65: evaluator WAJIB manager terkait, bukan sembarang user."""
    target = db.get(m.User, user_id)
    if target is None:
        raise HTTPException(404, f"User {user_id} untuk {label} tidak ditemukan.")
    role = _role(target)
    if role not in MANAGER_ROLES:
        raise HTTPException(
            422, f"{label} harus manager terkait (peran {sorted(MANAGER_ROLES)}); "
                 f"user {user_id} berperan {role}.")
    return target


def _require_hr_owner(user):
    """Revisi #66: kasus confidential hanya untuk owner role HR + CEO."""
    if _role(user) not in (HR_OWNER_ROLES | {"CEO"}):
        raise HTTPException(403, "Hanya owner role HR dan CEO yang dapat mengakses data ini.")


# ══════════════ jalur TULIS: manpower, vacancy, kandidat (revisi #63) ══════════════


# ─────────────── WRITE: manpower request, vacancy & kandidat (revisi #63) ───────────────

@router.post("/manpower-requests", status_code=201)
def create_manpower_request(division: str = Query(..., min_length=1),
                            position: str = Query(..., min_length=1),
                            qty: int = Query(1, ge=1),
                            reason: str = Query(None),
                            requirement: str = Query(None),
                            priority: str = Query("NORMAL"),
                            target_start_date: str = Query(None),
                            budget_ref: str = Query(None),
                            payroll_ref: str = Query(None),
                            due_date: str = Query(None),
                            status: str = Query("SUBMITTED"),
                            db: Session = Depends(get_db),
                            user=Depends(get_current_user)):
    """Buat Manpower Request (revisi #63). Requester = user yang login (server-side)."""
    _require_write(user)
    _need(db, "manpower_requests")
    priority = (priority or "NORMAL").upper()
    if priority not in MANPOWER_PRIORITIES:
        raise HTTPException(422, f"priority harus salah satu dari {sorted(MANPOWER_PRIORITIES)}.")
    status = (status or "SUBMITTED").upper()
    if status not in ("DRAFT", "SUBMITTED"):
        raise HTTPException(409, "Manpower request baru hanya boleh DRAFT atau SUBMITTED; "
                                 "perubahan berikutnya lewat /actions.")
    row = m.ManpowerRequest(
        request_no=_seq_no(db, m.ManpowerRequest, m.ManpowerRequest.request_no, "MPR-"),
        requester_id=user.id,  # requester tidak boleh diklaim dari body
        division=division.strip(), position=position.strip(), qty=qty,
        reason=reason, requirement=requirement, priority=priority,
        target_start_date=_parse_date(target_start_date, "target_start_date"),
        budget_ref=budget_ref, payroll_ref=payroll_ref, owner_id=user.id,
        due_date=_parse_date(due_date, "due_date"), status=status, version=1)
    db.add(row)
    db.flush()
    _audit(db, user, "HR_MANPOWER_REQUEST_CREATE", "ManpowerRequest", row.id,
           f"{row.request_no} {division}/{position} qty={qty} priority={priority}",
           row, previous_status=None, new_status=status)
    db.commit()
    payload = _serial(row)
    payload.update({"allowed_next_statuses": _allowed(MANPOWER_TRANSITIONS, status),
                    "audit_logged": True})
    return payload


@router.patch("/manpower-requests/{request_id}")
def update_manpower_request(request_id: int,
                            reason: str = Query(None),
                            requirement: str = Query(None),
                            priority: str = Query(None),
                            qty: int = Query(None, ge=1),
                            target_start_date: str = Query(None),
                            budget_ref: str = Query(None),
                            payroll_ref: str = Query(None),
                            due_date: str = Query(None),
                            correction_reason: str = Query(None),
                            db: Session = Depends(get_db),
                            user=Depends(get_current_user)):
    """Perbaiki isi Manpower Request. Status hanya berubah lewat /actions."""
    _require_write(user)
    _need(db, "manpower_requests")
    row = db.get(m.ManpowerRequest, request_id)
    if row is None:
        raise HTTPException(404, "Manpower request not found")
    if (row.status or "").upper() in ("CLOSED", "CANCELLED", "HIRED", "REJECTED"):
        raise HTTPException(409, f"Manpower request {row.request_no} sudah terminal "
                                 f"({row.status}) dan tidak boleh diubah.")
    changed = []
    if priority is not None:
        priority = priority.upper()
        if priority not in MANPOWER_PRIORITIES:
            raise HTTPException(422, f"priority harus salah satu dari {sorted(MANPOWER_PRIORITIES)}.")
        changed.append(f"priority:{row.priority}->{priority}")
        row.priority = priority
    for field, value in (("reason", reason), ("requirement", requirement),
                         ("budget_ref", budget_ref), ("payroll_ref", payroll_ref)):
        if value is not None:
            changed.append(field)
            setattr(row, field, value)
    if qty is not None:
        changed.append(f"qty:{row.qty}->{qty}")
        row.qty = qty
    if target_start_date is not None:
        changed.append("target_start_date")
        row.target_start_date = _parse_date(target_start_date, "target_start_date")
    if due_date is not None:
        changed.append("due_date")
        row.due_date = _parse_date(due_date, "due_date")
    if not changed:
        raise HTTPException(422, "Tidak ada kolom yang diubah.")
    _bump_version(row, correction_reason)
    _audit(db, user, "HR_MANPOWER_REQUEST_UPDATE", "ManpowerRequest", row.id,
           f"{row.request_no}: {', '.join(changed)}", row,
           previous_status=row.status, new_status=row.status, reason=correction_reason)
    db.commit()
    return {**_serial(row), "changed": changed, "correction_reason": correction_reason,
            "audit_logged": True,
            "allowed_next_statuses": _allowed(MANPOWER_TRANSITIONS, row.status)}


@router.post("/manpower-requests/{request_id}/actions", status_code=201)
def act_on_manpower_request(request_id: int,
                            action: str = Query(..., description="Status tujuan yang sah"),
                            reason: str = Query(None),
                            decision: str = Query(None),
                            db: Session = Depends(get_db),
                            user=Depends(get_current_user)):
    """Ubah status Manpower Request lewat tindakan yang divalidasi (bukan dropdown bebas)."""
    _require_write(user)
    _need(db, "manpower_requests")
    row = db.get(m.ManpowerRequest, request_id)
    if row is None:
        raise HTTPException(404, "Manpower request not found")
    previous = (row.status or "SUBMITTED").upper()
    target = _require_transition(MANPOWER_TRANSITIONS, previous, action, "manpower")
    if target in ("REJECTED", "NEED_CLARIFICATION") and not (reason or "").strip():
        raise HTTPException(400, "Menolak/meminta klarifikasi wajib menyertakan alasan.")
    row.status = target
    if decision:
        row.decision = decision.upper()
    if reason:
        row.decision_reason = reason
    _bump_version(row, reason)
    _audit(db, user, "HR_MANPOWER_REQUEST_ACTION", "ManpowerRequest", row.id,
           f"{row.request_no} {previous} -> {target}", row,
           previous_status=previous, new_status=target, reason=reason)
    db.commit()
    return {**_serial(row), "previous_status": previous,
            "allowed_next_statuses": _allowed(MANPOWER_TRANSITIONS, target),
            "audit_logged": True}


@router.post("/manpower-requests/{request_id}/vacancies", status_code=201)
def create_vacancy(request_id: int,
                   source: str = Query(None),
                   db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    """Buka lowongan dari Manpower Request yang sudah ELIGIBLE (revisi #63).

    Menutup celah lama: status manpower harus benar-benar boleh membuka vacancy,
    dan membuka vacancy memindahkan manpower ke VACANCY_OPEN — bukan dua catatan
    yang saling tidak tahu. Jumlah vacancy OPEN tidak boleh melampaui qty yang
    diminta.
    """
    _require_write(user)
    _need(db, "manpower_requests")
    _need(db, "recruitment_vacancies")
    req = db.get(m.ManpowerRequest, request_id)
    if req is None:
        raise HTTPException(404, "Manpower request not found")
    previous = (req.status or "SUBMITTED").upper()
    if not (req.division or "").strip() or not (req.position or "").strip():
        raise HTTPException(422, "Manpower request tanpa divisi/posisi tidak boleh membuka vacancy.")
    # Kuota diperiksa LEBIH DAHULU daripada transisi: membuka vacancy ke-(n+1)
    # untuk qty=n harus ditolak sebagai kelebihan kuota, bukan sebagai
    # "transisi tidak sah" (request sudah VACANCY_OPEN karena yang pertama).
    prev_vacancies = db.query(m.RecruitmentVacancy).filter(
        m.RecruitmentVacancy.manpower_request_fk == request_id,
        m.RecruitmentVacancy.status == "OPEN").count()
    if prev_vacancies >= (req.qty or 1):
        raise HTTPException(409, f"Vacancy OPEN sudah {prev_vacancies} untuk qty={req.qty} "
                                 f"({req.request_no}): tidak boleh membuka lebih banyak dari kebutuhan.")
    _require_transition(MANPOWER_TRANSITIONS, previous, "VACANCY_OPEN", "manpower")
    vacancy = m.RecruitmentVacancy(
        manpower_request_fk=req.id,
        vacancy_no=_seq_no(db, m.RecruitmentVacancy, m.RecruitmentVacancy.vacancy_no, "VAC-"),
        source=source, status="OPEN", opened_at=datetime.utcnow())
    db.add(vacancy)
    req.status = "VACANCY_OPEN"
    _bump_version(req)
    db.flush()
    _audit(db, user, "HR_VACANCY_OPEN", "RecruitmentVacancy", vacancy.id,
           f"{vacancy.vacancy_no} dari {req.request_no} ({req.position} x{req.qty})",
           vacancy, previous_status=None, new_status="OPEN")
    db.commit()
    return {**_serial(vacancy), "manpower_request_no": req.request_no,
            "previous_manpower_status": previous, "audit_logged": True}


@router.post("/candidates", status_code=201)
def create_candidate(vacancy_fk: int = Query(...),
                     name: str = Query(..., min_length=1),
                     source: str = Query(None),
                     contact: str = Query(None),
                     cv_evidence_ref: str = Query(None),
                     owner_id: int = Query(None),
                     due_date: str = Query(None),
                     db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    """Tambah kandidat ke sebuah vacancy (revisi #63).

    `employee_fk` sengaja TIDAK bisa diisi di sini: kandidat baru bukan karyawan.
    """
    _require_write(user)
    _need(db, "recruitment_candidates")
    _need(db, "recruitment_vacancies")
    vacancy = db.get(m.RecruitmentVacancy, vacancy_fk)
    if vacancy is None:
        raise HTTPException(404, "Vacancy not found")
    if (vacancy.status or "").upper() != "OPEN":
        raise HTTPException(409, f"Vacancy {vacancy.vacancy_no} tidak OPEN ({vacancy.status}); "
                                 f"kandidat tidak boleh ditambahkan ke lowongan tertutup.")
    row = m.RecruitmentCandidate(
        candidate_no=_seq_no(db, m.RecruitmentCandidate, m.RecruitmentCandidate.candidate_no, "CAND-"),
        vacancy_fk=vacancy_fk, name=name.strip(), source=source, contact=contact,
        cv_evidence_ref=cv_evidence_ref, owner_id=owner_id or user.id,
        due_date=_parse_date(due_date, "due_date"), status="NEW", version=1)
    db.add(row)
    db.flush()
    _audit(db, user, "HR_CANDIDATE_ADD", "RecruitmentCandidate", row.id,
           f"{row.candidate_no} {row.name} untuk {vacancy.vacancy_no}",
           row, previous_status=None, new_status="NEW")
    db.commit()
    return {**_serial(row), "vacancy_no": vacancy.vacancy_no, "employee_fk": None,
            "employee_note": "employee_fk hanya terisi setelah keputusan hire yang sah (#63).",
            "allowed_next_statuses": _allowed(CANDIDATE_TRANSITIONS, "NEW"),
            "audit_logged": True}


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
    if detail is None:
        raise HTTPException(
            409,
            "Issue ini belum punya detail kasus (employee_case_details); eskalasi tanpa "
            "kasus tidak punya pemilik tindak lanjut. Buat kasusnya lebih dahulu.")
    previous_status = (issue.status or "OPEN").upper()
    # Jejak eskalasi ditulis lebih dulu; kalau tabelnya hilang endpoint sudah 503 di atas.
    row = m.EmployeeIssueEscalation(issue_fk=issue_id, escalated_by_id=user.id,
                                    reason=reason, escalated_at=datetime.utcnow())
    db.add(row)
    # Eskalasi yang butuh tindakan wajib punya Action Tracker CEO (revisi #66).
    decision = m.CEODecision(
        decision_type="HR_EMPLOYEE_CASE", subject=f"{detail.case_no or ('CASE-' + str(issue_id))}: "
                                                   f"{detail.category or issue.issue_type}",
        decision=None, reason=reason, owner_name=user.name, due_date=detail.due_date,
        action_status="OPEN", source_module="HRRecruitment",
        source_entity="EmployeeCaseDetail", source_entity_id=detail.id,
        requester_id=user.id, context=issue.description,
        options_json="[]", recommendation="HR mengeskalasi kasus RED; CEO memutuskan arah tindakan.")
    db.add(decision)
    db.commit()   # keputusan CEO durable sebelum FK jejak eskalasi diisi
    row.ceo_decision_fk = decision.id
    detail.escalated_to_ceo = True
    detail.escalated_by_id = user.id
    detail.escalated_at = datetime.utcnow()
    detail.escalation_reason = reason
    detail.ceo_decision_fk = decision.id
    issue.status = "ESCALATED_CEO"
    log_audit(db, user, "HR_ISSUE_ESCALATE_CEO", "EmployeeIssue", issue_id,
              f"severity={severity}; reason={reason}",
              obj=issue, source_module="HREmployeeIssue",
              previous_status=previous_status, new_status="ESCALATED_CEO", reason=reason)
    db.commit()
    return {"ok": True, "issue_id": issue_id, "status": "ESCALATED_CEO",
            "escalated_by": user.id, "reason": reason,
            "ceo_notification": "RED", "audit_logged": True,
            "escalation_id": row.id, "ceo_decision_fk": row.ceo_decision_fk,
            "action_tracker": "CEODecision dibuat sebagai penampung tindakan wajib CEO.",
            "case_no": detail.case_no}


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

# Owner role HR + CEO. HR_SUPPORT hanya melihat baris non-confidential.
@router.post("/candidates/{candidate_id}/actions", status_code=201)
def act_on_candidate(candidate_id: int,
                     action: str = Query(..., description="SCREENING/SHORTLISTED/INTERVIEW_SCHEDULED/INTERVIEWED/OFFERED/HIRED/... atau HIRE/REJECT"),
                     reason: str = Query(None),
                     screening_result: str = Query(None),
                     screening_notes: str = Query(None),
                     interview_scheduled_at: str = Query(None),
                     interviewer_id: int = Query(None),
                     interview_result: str = Query(None),
                     interview_score: float = Query(None),
                     manager_assessment: str = Query(None),
                     offer_amount: float = Query(None),
                     next_action: str = Query(None),
                     db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    """Jalankan tindakan atas kandidat (revisi #63).

    Dua gerbang yang tidak boleh dilewati UI:
    - `OFFERED` wajib sudah punya `offer_amount`,
    - `HIRED` (atau pintasan `HIRE`) hanya sah bila kandidat sudah
      `OFFER_ACCEPTED` DAN punya penilaian manager (`manager_assessment`) —
      keputusan hire sepihak tanpa penilaian manager ditolak 409.
    """
    _require_write(user)
    _need(db, "recruitment_candidates")
    row = db.get(m.RecruitmentCandidate, candidate_id)
    if row is None:
        raise HTTPException(404, "Candidate not found")
    previous = (row.status or "NEW").upper()

    # Pintasan eksplisit: HIRE wajib melewati gerbang keputusan sah.
    if (action or "").upper() == "HIRE":
        if previous != "OFFER_ACCEPTED":
            raise HTTPException(
                409, f"Kandidat {row.candidate_no} berstatus {previous}: hire hanya sah dari "
                     f"OFFER_ACCEPTED (butuh offer + penerimaan kandidat).")
        target = "HIRED"
    elif (action or "").upper() == "REJECT":
        target = "REJECTED"
    else:
        target = _require_transition(CANDIDATE_TRANSITIONS, previous, action, "kandidat")

    if target == "OFFERED" and offer_amount is None and row.offer_amount is None:
        raise HTTPException(409, "Kandidat tidak boleh masuk OFFERED tanpa offer_amount.")
    if target == "HIRED":
        if not (row.manager_assessment or manager_assessment or "").strip():
            raise HTTPException(
                409, "Hire tanpa penilaian manager terkait tidak sah: isi manager_assessment "
                     "lebih dahulu (revisi #63).")
        if target not in _allowed(CANDIDATE_TRANSITIONS, previous) and previous != "OFFER_ACCEPTED":
            raise HTTPException(409, f"Transisi kandidat {previous} → HIRED tidak sah.")

    for field, value in (("screening_result", screening_result),
                         ("screening_notes", screening_notes),
                         ("interview_result", interview_result),
                         ("manager_assessment", manager_assessment),
                         ("next_action", next_action)):
        if value is not None:
            setattr(row, field, value)
    if interview_score is not None:
        row.interview_score = interview_score
    if interviewer_id is not None:
        row.interviewer_id = interviewer_id
    if offer_amount is not None:
        row.offer_amount = offer_amount
    if interview_scheduled_at is not None:
        row.interview_scheduled_at = _parse_dt(interview_scheduled_at, "interview_scheduled_at")
    if target in ("REJECTED", "SCREENED_OUT", "OFFER_REJECTED") and (reason or "").strip():
        row.rejected_reason = reason
    if target == "OFFER_ACCEPTED":
        row.accepted_at = datetime.utcnow()
        row.decision = "ACCEPTED"
    if target == "OFFERED":
        row.decision = "OFFER"
    row.status = target
    _bump_version(row, reason)
    _audit(db, user, "HR_CANDIDATE_ACTION", "RecruitmentCandidate", row.id,
           f"{row.candidate_no} {previous} -> {target}", row,
           previous_status=previous, new_status=target, reason=reason)
    db.commit()
    return {**_serial(row), "previous_status": previous,
            "allowed_next_statuses": _allowed(CANDIDATE_TRANSITIONS, target),
            "hire_gate": ("employee_fk diisi melalui POST /hr/candidates/{id}/hire "
                          "yang membuat karyawan resmi." if target == "HIRED" else None),
            "audit_logged": True}


@router.post("/candidates/{candidate_id}/hire", status_code=201)
def hire_candidate(candidate_id: int,
                   employee_no: str = Query(None),
                   division: str = Query(None),
                   position: str = Query(None),
                   employment_status: str = Query("TRAINING"),
                   start_training: str = Query(None),
                   manager_evaluator_id: int = Query(None),
                   mentor_id: int = Query(None),
                   db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    """Keputusan hire yang sah (revisi #63) — satu transaksi:

    1. kandidat harus OFFER_ACCEPTED (bukan sekadar lulus interview),
    2. `employees` dibuat sebagai karyawan resmi (status TRAINING),
    3. `recruitment_candidates.employee_fk` diisi dari karyawan itu,
    4. onboarding 2 minggu dibuka otomatis (revisi #64).

    Kalau salah satu langkah tidak bisa dijalankan (mis. tabel onboarding belum
    ada), seluruh transaksi ditolak — tidak ada karyawan "setengah jadi".
    """
    _require_write(user)
    _need(db, "recruitment_candidates")
    _need(db, "onboarding_programs")
    row = db.get(m.RecruitmentCandidate, candidate_id)
    if row is None:
        raise HTTPException(404, "Candidate not found")
    if row.employee_fk:
        raise HTTPException(409, f"Kandidat {row.candidate_no} sudah di-hire (employee_fk={row.employee_fk}).")
    previous = (row.status or "NEW").upper()
    if previous != "OFFER_ACCEPTED":
        raise HTTPException(
            409, f"Kandidat {row.candidate_no} berstatus {previous}: hire hanya sah setelah "
                 f"OFFER_ACCEPTED (offer + penerimaan).")
    if not (row.manager_assessment or "").strip():
        raise HTTPException(409, "Hire tanpa penilaian manager terkait tidak sah (revisi #63).")

    vacancy = db.get(m.RecruitmentVacancy, row.vacancy_fk) if row.vacancy_fk else None
    request_row = (db.get(m.ManpowerRequest, vacancy.manpower_request_fk)
                   if vacancy is not None and vacancy.manpower_request_fk else None)
    division = division or (request_row.division if request_row else None)
    position = position or (request_row.position if request_row else None)
    if not division or not position:
        raise HTTPException(422, "Divisi/posisi karyawan baru tidak bisa ditentukan "
                                 "(vacancy tanpa manpower request); isi division & position eksplisit.")

    employee_no = (employee_no or "").strip() or _seq_no(
        db, m.Employee, m.Employee.employee_no, "EMP-", width=4)
    if db.query(m.Employee).filter(m.Employee.employee_no == employee_no).first():
        raise HTTPException(409, f"employee_no {employee_no} sudah dipakai.")

    emp = m.Employee(employee_no=employee_no, name=row.name, division=division,
                     position=position, employment_status=(employment_status or "TRAINING").upper())
    db.add(emp)
    db.commit()   # FK onboarding/employee harus melihat karyawan yang sudah durable

    row.employee_fk = emp.id
    row.status = "HIRED"
    row.decision = "HIRED"
    _bump_version(row)

    if vacancy is not None:
        vacancy.status = "FILLED"
        vacancy.closed_at = datetime.utcnow()

    training_start = (_parse_date(start_training, "start_training") or date.today())
    prog = m.OnboardingProgram(
        candidate_fk=row.id, employee_fk=emp.id, position=position,
        training_start=training_start,
        training_end=training_start + timedelta(days=TRAINING_DAYS),
        mentor_id=mentor_id, manager_evaluator_id=manager_evaluator_id or user.id,
        checklist_json=json.dumps([
            "Orientasi perusahaan (Hari 1)", "Aturan kerja & K3",
            "Pendampingan mentor", "Evaluasi skill akhir training",
            "Keputusan PASS/EXTEND/FAIL",
        ]),
        progress_pct=0, due_date=training_start + timedelta(days=TRAINING_DAYS),
        version=1)
    db.add(prog)
    db.flush()

    _audit(db, user, "HR_CANDIDATE_HIRE", "RecruitmentCandidate", row.id,
           f"{row.candidate_no} -> employee {employee_no} ({division}/{position}); "
           f"onboarding #{prog.id}", row, previous_status=previous, new_status="HIRED",
           reason="hire sah: OFFER_ACCEPTED + penilaian manager")
    db.commit()
    return {"ok": True, "candidate_no": row.candidate_no, "previous_status": previous,
            "status": "HIRED", "employee": _serial(emp),
            "vacancy_no": vacancy.vacancy_no if vacancy is not None else None,
            "vacancy_status": vacancy.status if vacancy is not None else None,
            "onboarding": {**_serial(prog), "training_days": TRAINING_DAYS,
                           "rule": "revisi #64: training onboarding 2 minggu."},
            "audit_logged": True}


# ─────────────── WRITE: onboarding 2 minggu & payroll handoff (revisi #64) ───────────────

ONBOARDING_TRANSITIONS = {
    "DRAFT": ["IN_PROGRESS", "CANCELLED"],
    "IN_PROGRESS": ["PASS", "EXTEND", "FAIL", "CANCELLED"],
    "EXTEND": ["IN_PROGRESS", "PASS", "FAIL"],
    "PASS": [],
    "FAIL": [],
    "CANCELLED": [],
}


@router.post("/onboarding", status_code=201)
def create_onboarding(candidate_fk: int = Query(None),
                      employee_fk: int = Query(None),
                      position: str = Query(None),
                      training_start: str = Query(None),
                      training_days: int = Query(TRAINING_DAYS, ge=1, le=90),
                      mentor_id: int = Query(None),
                      manager_evaluator_id: int = Query(None),
                      checklist: str = Query(None, description="JSON array (opsional)"),
                      db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    """Mulai onboarding manual (revisi #64). Durasi bawaan 2 minggu (14 hari)."""
    _require_write(user)
    _need(db, "onboarding_programs")
    if candidate_fk is None and employee_fk is None:
        raise HTTPException(422, "Onboarding butuh candidate_fk atau employee_fk.")
    candidate = None
    if candidate_fk is not None:
        candidate = db.get(m.RecruitmentCandidate, candidate_fk)
        if candidate is None:
            raise HTTPException(404, "Candidate not found")
        if candidate.employee_fk is None:
            raise HTTPException(
                409, f"Kandidat {candidate.candidate_no} belum di-hire; onboarding hanya untuk "
                     f"karyawan hasil hire yang sah (revisi #63/#64).")
        employee_fk = employee_fk or candidate.employee_fk
    emp = db.get(m.Employee, employee_fk)
    if emp is None:
        raise HTTPException(404, "Employee not found")
    if db.query(m.OnboardingProgram).filter(
            m.OnboardingProgram.employee_fk == employee_fk,
            m.OnboardingProgram.decision.is_(None)).first():
        raise HTTPException(409, f"Karyawan {emp.employee_no} sudah punya onboarding yang belum "
                                 f"diputuskan; selesaikan dulu (PASS/EXTEND/FAIL).")
    start = _parse_date(training_start, "training_start") or date.today()
    checklist_json = json.dumps(_parse_json(checklist, "checklist", None) or
                                ["Orientasi", "Aturan kerja & K3", "Pendampingan mentor",
                                 "Evaluasi skill", "Keputusan PASS/EXTEND/FAIL"])
    row = m.OnboardingProgram(
        candidate_fk=candidate_fk, employee_fk=employee_fk,
        position=position or emp.position or (candidate and None),
        training_start=start, training_end=start + timedelta(days=training_days),
        mentor_id=mentor_id, manager_evaluator_id=manager_evaluator_id or user.id,
        checklist_json=checklist_json, progress_pct=0,
        due_date=start + timedelta(days=training_days), version=1)
    db.add(row)
    db.flush()
    _audit(db, user, "HR_ONBOARDING_START", "OnboardingProgram", row.id,
           f"onboarding {emp.employee_no}: {start} → {row.training_end} ({training_days} hari)",
           row, previous_status=None, new_status="IN_PROGRESS",
           reason=f"training {training_days} hari")
    db.commit()
    return {**_serial(row), "employee_no": emp.employee_no, "training_days": training_days,
            "rule": "revisi #64: onboarding/training standar 2 minggu.",
            "decision_options": sorted(ONBOARDING_DECISIONS),
            "allowed_next_statuses": _allowed(ONBOARDING_TRANSITIONS, "IN_PROGRESS"),
            "audit_logged": True}


@router.patch("/onboarding/{program_id}")
def update_onboarding(program_id: int,
                      progress_pct: int = Query(None, ge=0, le=100),
                      checklist: str = Query(None),
                      skill_evidence_ref: str = Query(None),
                      issue_blocker: str = Query(None),
                      mentor_id: int = Query(None),
                      manager_evaluator_id: int = Query(None),
                      salary_category: str = Query(None),
                      salary_rate: float = Query(None),
                      correction_reason: str = Query(None),
                      db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    """Catat progres training onboarding. Keputusan PASS/EXTEND/FAIL punya endpoint sendiri."""
    _require_write(user)
    _need(db, "onboarding_programs")
    row = db.get(m.OnboardingProgram, program_id)
    if row is None:
        raise HTTPException(404, "Onboarding program not found")
    if (row.decision or "").upper() in ("PASS", "FAIL"):
        raise HTTPException(409, f"Onboarding #{row.id} sudah {row.decision} dan terkunci.")
    changed = []
    if progress_pct is not None:
        changed.append(f"progress_pct:{row.progress_pct}->{progress_pct}")
        row.progress_pct = progress_pct
    if checklist is not None:
        row.checklist_json = json.dumps(_parse_json(checklist, "checklist", []))
        changed.append("checklist")
    for field, value in (("skill_evidence_ref", skill_evidence_ref),
                         ("issue_blocker", issue_blocker),
                         ("salary_category", salary_category)):
        if value is not None:
            setattr(row, field, value)
            changed.append(field)
    for field, value in (("mentor_id", mentor_id), ("manager_evaluator_id", manager_evaluator_id)):
        if value is not None:
            setattr(row, field, value)
            changed.append(field)
    if salary_rate is not None:
        row.salary_rate = salary_rate
        changed.append("salary_rate")
    if not changed:
        raise HTTPException(422, "Tidak ada kolom yang diubah.")
    _bump_version(row, correction_reason)
    _audit(db, user, "HR_ONBOARDING_UPDATE", "OnboardingProgram", row.id,
           f"onboarding #{row.id}: {', '.join(changed)}", row,
           previous_status=None, new_status=row.decision or "IN_PROGRESS",
           reason=correction_reason)
    db.commit()
    return {**_serial(row), "changed": changed, "audit_logged": True,
            "decision_options": sorted(ONBOARDING_DECISIONS)}




@router.post("/onboarding/{program_id}/decision", status_code=201)
def decide_onboarding(program_id: int,
                      decision: str = Query(..., description="PASS/EXTEND/FAIL"),
                      reason: str = Query(None),
                      extend_days: int = Query(None, ge=1, le=90),
                      skill_evidence_ref: str = Query(None),
                      employee_acknowledged: bool = Query(False),
                      db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    """Keputusan akhir onboarding (revisi #64) — inilah satu-satunya pintu PASS.

    `PASS` mengaktifkan employment status karyawan DAN membuat Payroll Handoff
    untuk CFO dalam satu transaksi. `EXTEND` wajib `extend_days` + alasan (aturan
    #64). `FAIL` menutup onboarding secara terkontrol.
    """
    _need(db, "onboarding_programs")
    _need(db, "payroll_handoffs")
    _require_write(user)
    row = db.get(m.OnboardingProgram, program_id)
    if row is None:
        raise HTTPException(404, "Onboarding program not found")
    decision = (decision or "").upper()
    if decision not in ONBOARDING_DECISIONS:
        raise HTTPException(422, f"decision harus salah satu dari {sorted(ONBOARDING_DECISIONS)}.")
    previous = (row.decision or "IN_PROGRESS").upper()
    _require_transition(ONBOARDING_TRANSITIONS, previous, decision, "onboarding")

    if decision == "EXTEND":
        if extend_days is None:
            raise HTTPException(400, "EXTEND wajib menyertakan extend_days.")
        if not (reason or "").strip():
            raise HTTPException(400, "EXTEND wajib menyertakan alasan.")
        row.extend_days = extend_days
        row.decision = "EXTEND"
        row.decision_reason = reason
        if row.training_end:
            row.training_end = row.training_end + timedelta(days=extend_days)
            row.due_date = row.training_end
        _bump_version(row, reason)
        _audit(db, user, "HR_ONBOARDING_EXTEND", "OnboardingProgram", row.id,
               f"onboarding #{row.id} EXTEND {extend_days} hari: {reason}", row,
               previous_status=previous, new_status="EXTEND", reason=reason)
        db.commit()
        return {**_serial(row), "previous_decision": previous,
                "decision_options": sorted(ONBOARDING_DECISIONS), "audit_logged": True}

    emp = db.get(m.Employee, row.employee_fk) if row.employee_fk else None

    if decision == "FAIL":
        if not (reason or "").strip():
            raise HTTPException(400, "FAIL wajib menyertakan alasan penutupan.")
        row.decision = "FAIL"
        row.decision_reason = reason
        if emp is not None:
            emp.employment_status = "INACTIVE"
        _bump_version(row, reason)
        _audit(db, user, "HR_ONBOARDING_FAIL", "OnboardingProgram", row.id,
               f"onboarding #{row.id} FAIL: {reason}", row,
               previous_status=previous, new_status="FAIL", reason=reason)
        db.commit()
        return {**_serial(row), "previous_decision": previous, "employee_activated": False,
                "employment_status": emp.employment_status if emp else None,
                "payroll_handoff": None, "audit_logged": True}

    # PASS: aktifkan karyawan + serahkan ke CFO
    if emp is None:
        raise HTTPException(409, "Onboarding tanpa employee terdaftar tidak bisa PASS.")
    if not (reason or "").strip() and not (skill_evidence_ref or "").strip():
        raise HTTPException(400, "PASS wajib menyertakan alasan atau bukti skill.")
    effective = _parse_date(row.training_end, "training_end") or date.today()
    emp.employment_status = "ACTIVE"
    handoff = m.PayrollHandoff(
        employee_id=emp.id, employee_fk=emp.id, onboarding_fk=row.id,
        event_type="PASS", effective_date=effective,
        status_code="TRAINING_TO_STANDARD" if row.salary_category else "STANDARD_SALARY",
        salary_reference=row.salary_category, division_salary_ref=row.salary_category,
        reason=reason or f"Lulus onboarding: {skill_evidence_ref}",
        created_by_id=user.id, requested_by_id=user.id, requested_at=datetime.utcnow(),
        cfo_status="PENDING",
        note="HR hanya membuat handoff; CFO yang mem-posting nilai payroll.")
    db.add(handoff)
    db.flush()
    row.decision = "PASS"
    row.decision_reason = reason or skill_evidence_ref
    row.skill_evidence_ref = skill_evidence_ref or row.skill_evidence_ref
    row.progress_pct = 100
    row.effective_date = effective
    row.payroll_handoff_fk = handoff.id
    _bump_version(row, reason)
    _audit(db, user, "HR_ONBOARDING_PASS", "OnboardingProgram", row.id,
           f"onboarding #{row.id} PASS → {emp.employee_no} ACTIVE; handoff #{handoff.id} PENDING CFO",
           row, previous_status=previous, new_status="PASS", reason=reason)
    db.commit()
    return {**_serial(row), "previous_decision": previous, "employee_activated": True,
            "employment_status": emp.employment_status,
            "payroll_handoff": _serial(handoff),
            "payroll_rule": "HR MEMBUAT handoff; CFO mem-posting (revisi #64).",
            "audit_logged": True}


@router.get("/payroll-handoffs")
def payroll_handoffs(db: Session = Depends(get_db), user=Depends(get_current_user),
                     cfo_status: str = Query(None)):
    """Daftar handoff HR → CFO (read-only bagi HR: posting dilakukan CFO)."""
    _require_view(user)
    ready = _has_table(db, "payroll_handoffs")
    rows = []
    if ready:
        query = db.query(m.PayrollHandoff)
        if cfo_status:
            query = query.filter(m.PayrollHandoff.cfo_status == cfo_status.upper())
        rows = query.order_by(m.PayrollHandoff.id.desc()).all()
    return {
        "items": [_serial(r) for r in rows],
        "total": len(rows),
        "schema_ready": ready,
        "pending_schema": [] if ready else PENDING_TABLES["payroll_handoffs"],
        "note": "HR hanya membuat handoff; status POSTED/REJECTED ditentukan CFO.",
    }


@router.post("/payroll-handoffs/{handoff_id}/actions", status_code=201)
def act_on_payroll_handoff(handoff_id: int,
                           action: str = Query(..., description="POSTED/REJECTED (wewenang CFO)"),
                           note: str = Query(None),
                           db: Session = Depends(get_db),
                           user=Depends(get_current_user)):
    """Mem-posting payroll BUKAN wewenang HR (revisi #64/#67) — ditolak 403.

    Endpoint ini sengaja ada supaya batas kewenangannya terbukti lewat tes, bukan
    hanya lewat dokumen.
    """
    _need(db, "payroll_handoffs")
    if _role(user) not in ("CFO_MANAGER", "FINANCE_SUPPORT", "CEO"):
        raise HTTPException(
            403, "Mem-posting payroll adalah wewenang CFO; HR hanya membuat handoff (revisi #64).")
    row = db.get(m.PayrollHandoff, handoff_id)
    if row is None:
        raise HTTPException(404, "Payroll handoff not found")
    action = (action or "").upper()
    if action not in ("POSTED", "REJECTED"):
        raise HTTPException(422, "action harus POSTED atau REJECTED.")
    previous = row.cfo_status
    row.cfo_status = action
    row.cfo_acted_by_id = user.id
    row.cfo_acted_at = datetime.utcnow()
    if note:
        row.note = note
    _audit(db, user, "HR_PAYROLL_HANDOFF_ACTION", "PayrollHandoff", row.id,
           f"handoff #{row.id} {previous} -> {action}", row,
           previous_status=previous, new_status=action, reason=note)
    db.commit()
    return {**_serial(row), "previous_status": previous, "audit_logged": True}


# ─────────────── WRITE: performance review cycle & detail (revisi #65) ───────────────

@router.post("/performance-cycles", status_code=201)
def create_performance_cycle(period: str = Query(..., min_length=1),
                             cycle_name: str = Query(None),
                             weight_config: str = Query(None, description="JSON bobot parameter"),
                             scoring_rule: str = Query(None, description="JSON aturan skor"),
                             db: Session = Depends(get_db),
                             user=Depends(get_current_user)):
    """Buka siklus penilaian (revisi #65). Bobot & aturan skor disimpan apa adanya."""
    _require_write(user)
    _need(db, "performance_review_cycles")
    row = m.PerformanceReviewCycle(
        period=period.strip(), cycle_name=cycle_name or f"Review {period.strip()}",
        weight_config_json=json.dumps(_parse_json(weight_config, "weight_config", {})),
        scoring_rule_json=json.dumps(_parse_json(scoring_rule, "scoring_rule", {})),
        status="DRAFT", created_by_id=user.id)
    db.add(row)
    db.flush()
    _audit(db, user, "HR_PERFORMANCE_CYCLE_CREATE", "PerformanceReviewCycle", row.id,
           f"cycle {row.period} dibuat", row, previous_status=None, new_status="DRAFT")
    db.commit()
    return {**_serial(row), "details": [], "audit_logged": True,
            "next_statuses": _allowed({"DRAFT": ["OPEN"], "OPEN": ["CLOSED"]}, "DRAFT")}


@router.post("/performance-cycles/{cycle_id}/details", status_code=201)
def create_performance_detail(cycle_id: int,
                              performance_record_fk: int = Query(...),
                              evaluator_manager_id: int = Query(...),
                              evidence_ref: str = Query(None),
                              strengths: str = Query(None),
                              gaps: str = Query(None),
                              improvement_action: str = Query(None),
                              action_owner_id: int = Query(None),
                              action_due: str = Query(None),
                              db: Session = Depends(get_db),
                              user=Depends(get_current_user)):
    """Lampirkan record penilaian ke siklus dengan EVALUATOR = MANAGER (revisi #65).

    `evaluator_is_manager` dihitung server dari tabel `users` — bukan dikirim klien,
    supaya penilaian tidak bisa diklaim sah tanpa manager terkait.
    """
    _require_write(user)
    _need(db, "performance_review_cycles")
    _need(db, "performance_review_details")
    cycle = db.get(m.PerformanceReviewCycle, cycle_id)
    if cycle is None:
        raise HTTPException(404, "Performance review cycle not found")
    record = db.get(m.PerformanceRecord, performance_record_fk)
    if record is None:
        raise HTTPException(404, "Performance record not found")
    evaluator = _require_manager(evaluator_manager_id, db, "evaluator_manager_id")
    if db.query(m.PerformanceReviewDetail).filter_by(
            cycle_fk=cycle_id, performance_record_fk=performance_record_fk).first():
        raise HTTPException(409, "Record ini sudah punya detail di siklus tersebut.")
    row = m.PerformanceReviewDetail(
        cycle_fk=cycle_id, performance_record_fk=performance_record_fk,
        employee_fk=record.employee_id, evaluator_manager_id=evaluator.id,
        evaluator_is_manager=True,  # sudah dipastikan manager di atas
        evidence_ref=evidence_ref, strengths=strengths, gaps=gaps,
        improvement_action=improvement_action, action_owner_id=action_owner_id,
        action_due=_parse_date(action_due, "action_due"), status="DRAFT", version=1)
    db.add(row)
    db.flush()
    _audit(db, user, "HR_PERFORMANCE_DETAIL_CREATE", "PerformanceReviewDetail", row.id,
           f"record #{record.id} dinilai oleh manager {evaluator.id}", row,
           previous_status=None, new_status="DRAFT")
    db.commit()
    return {**_serial(row), "cycle_period": cycle.period,
            "evaluator_name": evaluator.name,
            "evaluator_is_manager": True,
            "allowed_next_statuses": _allowed(PERFORMANCE_TRANSITIONS, "DRAFT"),
            "audit_logged": True}


@router.post("/performance-details/{detail_id}/actions", status_code=201)
def act_on_performance_detail(detail_id: int,
                              action: str = Query(..., description="SUBMITTED/ACKNOWLEDGED/FINALIZED/NEED_REVISION/CORRECTED"),
                              correction_reason: str = Query(None),
                              evidence_ref: str = Query(None),
                              improvement_action: str = Query(None),
                              employee_acknowledged_at: str = Query(None),
                              action_owner_id: int = Query(None),
                              action_due: str = Query(None),
                              db: Session = Depends(get_db),
                              user=Depends(get_current_user)):
    """Jalankan transisi review yang sah. `FINALIZED` tidak bisa ditimpa tanpa
    koreksi beralasan (revisi #65)."""
    _require_write(user)
    _need(db, "performance_review_details")
    row = db.get(m.PerformanceReviewDetail, detail_id)
    if row is None:
        raise HTTPException(404, "Performance review detail not found")
    previous = (row.status or "DRAFT").upper()
    target = _require_transition(PERFORMANCE_TRANSITIONS, previous, action, "review")
    if target == "CORRECTED" and not (correction_reason or "").strip():
        raise HTTPException(
            409, "Review FINALIZED hanya boleh dikoreksi dengan correction_reason "
                 "(revisi #65: koreksi lewat versi baru + alasan).")
    if evidence_ref is not None:
        row.evidence_ref = evidence_ref
    if improvement_action is not None:
        row.improvement_action = improvement_action
    if employee_acknowledged_at is not None:
        row.employee_acknowledged_at = _parse_dt(employee_acknowledged_at, "employee_acknowledged_at")
    elif target == "ACKNOWLEDGED":
        row.employee_acknowledged_at = datetime.utcnow()
    if action_owner_id is not None:
        row.action_owner_id = action_owner_id
    if action_due is not None:
        row.action_due = _parse_date(action_due, "action_due")
    if target in ("FINALIZED", "CORRECTED"):
        row.reviewed_by_id = user.id
        row.reviewed_at = datetime.utcnow()
    if target == "CORRECTED":
        row.correction_reason = correction_reason
    row.status = target
    # Revisi #65: "koreksi lewat version baru" — versi naik pada KOREKSI, bukan
    # pada setiap langkah alur (DRAFT→SUBMITTED→ACKNOWLEDGED bukan revisi isi).
    if target == "CORRECTED":
        _bump_version(row, correction_reason)
    _audit(db, user,
           "HR_PERFORMANCE_REVIEW_CORRECT" if target == "CORRECTED" else "HR_PERFORMANCE_REVIEW_ACTION",
           "PerformanceReviewDetail", row.id,
           f"detail #{row.id} {previous} -> {target}", row,
           previous_status=previous, new_status=target, reason=correction_reason)
    db.commit()
    return {**_serial(row), "previous_status": previous,
            "allowed_next_statuses": _allowed(PERFORMANCE_TRANSITIONS, target),
            "audit_logged": True}


# ─────────────── WRITE: employee case + evidence + akses (revisi #66) ───────────────

def _case_of(db, case_id: int):
    case = db.get(m.EmployeeCaseDetail, case_id)
    if case is None:
        raise HTTPException(404, "Employee case not found")
    return case


@router.post("/employee-issues", status_code=201)
def create_employee_issue(employee_id: int = Query(...),
                          issue_type: str = Query(..., min_length=1),
                          description: str = Query(..., min_length=1),
                          severity: str = Query("YELLOW"),
                          category: str = Query(None),
                          confidential: bool = Query(False),
                          occurred_date: str = Query(None),
                          reported_date: str = Query(None),
                          investigator_id: int = Query(None),
                          sla_hours: int = Query(None, ge=1),
                          due_date: str = Query(None),
                          db: Session = Depends(get_db),
                          user=Depends(get_current_user)):
    """Catat kasus karyawan + detail investigasinya (revisi #66).

    Kategori wajib (kasus tanpa kategori tidak bisa dilaporkan/dianalisis), dan
    status issue mengikuti lifecycle yang sah: langsung INVESTIGATION.
    """
    _require_write(user)
    _need(db, "employee_issues")
    _need(db, "employee_case_details")
    emp = db.get(m.Employee, employee_id)
    if emp is None:
        raise HTTPException(404, "Employee not found")
    severity = (severity or "YELLOW").upper()
    if severity not in ("GREEN", "YELLOW", "RED"):
        raise HTTPException(422, "severity harus GREEN/YELLOW/RED.")
    category = (category or "").upper()
    if category not in CASE_CATEGORIES:
        raise HTTPException(422, f"category wajib salah satu dari {sorted(CASE_CATEGORIES)}.")
    issue = m.EmployeeIssue(employee_id=employee_id, issue_type=issue_type.strip(),
                            description=description.strip(), severity=severity,
                            status="INVESTIGATION", reported_by=_actor_name(user))
    db.add(issue)
    # Commit parent dulu: FK `employee_case_details.issue_fk` harus melihat baris
    # issue yang sudah durable — bukan bergantung pada urutan flush.
    db.commit()
    case = m.EmployeeCaseDetail(
        issue_fk=issue.id,
        case_no=_seq_no(db, m.EmployeeCaseDetail, m.EmployeeCaseDetail.case_no, "CASE-"),
        category=category, reporter_id=user.id,
        occurred_date=_parse_date(occurred_date, "occurred_date"),
        reported_date=_parse_date(reported_date, "reported_date") or date.today(),
        confidential=bool(confidential), investigator_id=investigator_id or user.id,
        owner_id=user.id, due_date=_parse_date(due_date, "due_date"),
        sla_hours=sla_hours, version=1)
    db.add(case)
    db.flush()
    _audit(db, user, "HR_EMPLOYEE_CASE_CREATE", "EmployeeCaseDetail", case.id,
           f"{case.case_no} {category} severity={severity} confidential={bool(confidential)}",
           case, previous_status=None, new_status="INVESTIGATION",
           reason=description.strip()[:200])
    db.commit()
    return {**_serial(case), "issue_id": issue.id, "severity": severity,
            "status": "INVESTIGATION", "employee_no": emp.employee_no,
            "evidence_access": "HR_OWNER_AND_CEO_ONLY" if confidential else "HR_TEAM",
            "escalation_rule": "Hanya kasus RED yang boleh dieskalasi ke CEO (revisi #66).",
            "allowed_next_statuses": _allowed(ISSUE_TRANSITIONS, "INVESTIGATION"),
            "audit_logged": True}


@router.post("/employee-cases/{case_id}/evidence", status_code=201)
def add_case_evidence(case_id: int,
                      evidence_ref: str = Query(..., min_length=1),
                      access_level: str = Query("HR_OWNER_AND_CEO_ONLY"),
                      db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    """Simpan bukti kasus dengan tingkat akses eksplisit (revisi #66)."""
    _require_write(user)
    _need(db, "employee_case_evidence")
    case = _case_of(db, case_id)
    access_level = (access_level or "").upper()
    if access_level not in EVIDENCE_ACCESS_LEVELS:
        raise HTTPException(422, f"access_level wajib salah satu dari {sorted(EVIDENCE_ACCESS_LEVELS)}.")
    if access_level == "HR_TEAM" and case.confidential:
        raise HTTPException(422, "Kasus confidential tidak boleh punya bukti berakses HR_TEAM.")
    if _role(user) not in (HR_OWNER_ROLES | {"CEO"}) and access_level == "HR_OWNER_AND_CEO_ONLY":
        raise HTTPException(403, "Hanya owner role HR + CEO yang boleh menyimpan bukti terbatas.")
    row = m.EmployeeCaseEvidence(case_fk=case.id, evidence_ref=evidence_ref.strip(),
                                 access_level=access_level, uploaded_by_id=user.id)
    db.add(row)
    db.flush()
    _audit(db, user, "HR_EMPLOYEE_CASE_EVIDENCE_ADD", "EmployeeCaseEvidence", row.id,
           f"{case.case_no}: {evidence_ref.strip()} ({access_level})", row,
           previous_status=None, new_status=access_level)
    db.commit()
    return {**_serial(row), "case_no": case.case_no, "audit_logged": True}


@router.get("/employee-cases/{case_id}/evidence/{evidence_ref}")
def open_case_evidence(case_id: int, evidence_ref: str,
                       reason: str = Query(..., min_length=3,
                                           description="Alasan membuka bukti (wajib dicatat)"),
                       action: str = Query("VIEW"),
                       db: Session = Depends(get_db),
                       user=Depends(get_current_user)):
    """Buka bukti kasus — setiap pembukaan bukti confidential DICATAT (revisi #66).

    HR_SUPPORT ditolak (403) untuk bukti `HR_OWNER_AND_CEO_ONLY`; pemanggilan yang
    gagal pun tidak mengubah apa pun. Akses yang berhasil meninggalkan satu baris
    di `employee_case_access_log`.
    """
    _need(db, "employee_case_evidence")
    _need(db, "employee_case_access_log")
    case = _case_of(db, case_id)
    action = (action or "VIEW").upper()
    if action not in ("VIEW", "DOWNLOAD"):
        raise HTTPException(422, "action harus VIEW atau DOWNLOAD.")
    ev = db.query(m.EmployeeCaseEvidence).filter_by(
        case_fk=case.id, evidence_ref=evidence_ref).first()
    if ev is None:
        raise HTTPException(404, "Evidence not found")
    restricted = (ev.access_level or "").upper() == "HR_OWNER_AND_CEO_ONLY" or bool(case.confidential)
    if restricted and _role(user) not in (HR_OWNER_ROLES | {"CEO"}):
        raise HTTPException(403, "Bukti kasus confidential hanya untuk owner role HR + CEO.")
    db.add(m.EmployeeCaseAccessLog(case_fk=case.id, user_id=user.id, action=action,
                                   reason=reason.strip()))
    _audit(db, user, "HR_EMPLOYEE_CASE_EVIDENCE_OPEN", "EmployeeCaseEvidence", ev.id,
           f"{case.case_no}/{evidence_ref} {action}: {reason.strip()}", ev,
           previous_status=None, new_status=action, reason=reason.strip())
    db.commit()
    return {"ok": True, "case_no": case.case_no, "evidence_ref": evidence_ref,
            "access_level": ev.access_level, "action": action, "reason": reason.strip(),
            "access_logged": True}
