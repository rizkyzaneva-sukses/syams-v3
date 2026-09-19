"""Employee Master & Lifecycle HR (revisi #62, #67) — READ-ONLY.

Revisi #62 meminta Employee Master menjadi sumber resmi data SDM: status
kepegawaian, tanggal masuk/keluar, kontrak, dan penanda data warisan yang perlu
dimigrasi. Revisi #67 meminta ringkasan attendance read-only dan handoff
employment/payroll. Attendance dan payroll adalah milik CFO: router ini HANYA
membaca, tidak menyediakan satu pun endpoint tulis (tidak ada POST/PATCH/DELETE).

Skema Supabase yang dipakai (lihat REQUESTS/hr_employees.md) hanya dibaca kalau
kolomnya sudah ada. Selama migrasi belum mendarat, semua derivasi memakai kolom
yang benar-benar ada hari ini (`employees.created_at`, status, divisi, posisi)
sehingga tidak ada angka yang dikarang, dan setiap baris yang tanggal masuknya
masih ditaksir diberi penanda utang migrasi.
"""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..database import get_db
from ..models import Employee, TrainingRecord, PerformanceRecord, EmployeeIssue, Role, User

router = APIRouter(prefix="/hr", tags=["hr"])
HR_ROLES = (Role.CHRO_MANAGER, Role.HR_SUPPORT, Role.CEO)

# Status yang dianggap masih memakai slot headcount dan/atau masih berhak
# dinilai. Status di luar daftar ini tidak dihitung sebagai karyawan aktif.
OPEN_STATUSES = {"ACTIVE", "PROBATION", "TRAINING", "CONTRACT", "EXTENDED"}
CLOSED_STATUSES = {"INACTIVE", "TERMINATED", "RESIGNED", "EXITED", "RETIRED"}

# NIP yang jelas berasal dari seed demo. Data seperti ini tidak boleh ikut ke
# produksi (revisi #62: "hapus seed/dummy dari data produksi").
SEED_PREFIXES = ("EMP-DEMO", "DEMO-", "DUMMY-")

# Kolom yang dibaca kalau orkestrator sudah menambahkannya lewat migrasi.
EMPLOYEE_COLUMNS = {
    "join_date", "exit_date", "contract_end_date", "contract_start_date",
    "contract_type", "manager_name", "manager_id", "email", "phone",
    "migration_source", "migrated_at", "document_ref",
}

ATTENDANCE_PENDING = {
    "mode": "READ_ONLY",
    "source": "CFO",
    "available": False,
    "reason": "Ringkasan attendance per Employee/period belum diekspos ke HR; lihat REQUESTS/hr_employees.md.",
}


def _columns(db: Session) -> set[str]:
    """Kolom `employees` yang benar-benar ada di DB saat ini."""
    try:
        return {c["name"] for c in sa_inspect(db.bind).get_columns("employees")}
    except Exception:  # pragma: no cover - DB belum siap
        return {c.name for c in Employee.__table__.columns}


def _has(cols: set[str], name: str) -> bool:
    return name in cols and name in EMPLOYEE_COLUMNS


def _get(emp: Employee, cols: set[str], name: str):
    return getattr(emp, name, None) if _has(cols, name) else None


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _status(emp: Employee) -> str:
    return (emp.employment_status or "UNKNOWN").upper()


def _is_seed_row(emp: Employee) -> bool:
    no = (emp.employee_no or "").upper()
    return any(no.startswith(p) for p in SEED_PREFIXES)


def _migration_flags(emp: Employee, cols: set[str]) -> list[str]:
    """Alasan sebuah baris ditandai perlu migrasi/kelengkapan data.

    Hanya fakta yang bisa dibuktikan dari baris itu sendiri — tidak menebak.
    """
    flags = []
    if _is_seed_row(emp):
        flags.append("SEED_DEMO_ROW")
    if not (emp.employee_no or "").strip():
        flags.append("MISSING_EMPLOYEE_NO")
    if _has(cols, "join_date"):
        if _get(emp, cols, "join_date") is None:
            flags.append("MISSING_JOIN_DATE")
    else:
        # Kolom join_date belum ada: tanggal masuk hanya bisa ditaksir dari
        # created_at, dan penaksiran itu sendiri adalah utang migrasi.
        flags.append("JOIN_DATE_NOT_MIGRATED")
    if not (emp.division or "").strip():
        flags.append("MISSING_DIVISION")
    if not (emp.position or "").strip():
        flags.append("MISSING_POSITION")
    if _has(cols, "manager_name"):
        manager = _get(emp, cols, "manager_name") or _get(emp, cols, "manager_id")
        if manager in (None, ""):
            flags.append("MISSING_MANAGER")
    if _has(cols, "contract_end_date"):
        end = _as_date(_get(emp, cols, "contract_end_date"))
        if end and end < date.today() and _status(emp) in OPEN_STATUSES:
            flags.append("CONTRACT_EXPIRED_BUT_OPEN")
    elif _status(emp) in {"CONTRACT", "PROBATION", "TRAINING"}:
        # Tanpa kolom kontrak, tidak ada cara membuktikan sisa masa kontrak.
        flags.append("CONTRACT_FIELDS_NOT_MIGRATED")
    if _has(cols, "exit_date") and _get(emp, cols, "exit_date") and _status(emp) in OPEN_STATUSES:
        flags.append("EXIT_DATE_BUT_OPEN")
    return flags


def _row(emp: Employee, cols: set[str], *, today: date, warnings_at: int) -> dict:
    status = _status(emp)
    join_date = _as_date(_get(emp, cols, "join_date")) or _as_date(emp.created_at)
    join_source = "JOIN_DATE" if _as_date(_get(emp, cols, "join_date")) else "CREATED_AT_PROXY"
    contract_end = _as_date(_get(emp, cols, "contract_end_date"))
    exit_date = _as_date(_get(emp, cols, "exit_date"))
    days_to_contract_end = (contract_end - today).days if contract_end else None
    contract_expiring = bool(contract_end and days_to_contract_end is not None
                             and 0 <= days_to_contract_end <= warnings_at
                             and status in OPEN_STATUSES)
    contract_expired = bool(contract_end and days_to_contract_end is not None
                            and days_to_contract_end < 0 and status in OPEN_STATUSES)
    manager = _get(emp, cols, "manager_name") or _get(emp, cols, "manager_id")
    flags = _migration_flags(emp, cols)
    return {
        "id": emp.id,
        "employee_no": emp.employee_no,
        "name": emp.name,
        "division": emp.division,
        "position": emp.position,
        "manager": manager,
        "employment_status": status,
        "status_group": "OPEN" if status in OPEN_STATUSES else "CLOSED" if status in CLOSED_STATUSES else "OTHER",
        "join_date": join_date,
        "join_date_source": join_source,
        "exit_date": exit_date,
        "contract_type": _get(emp, cols, "contract_type"),
        "contract_start_date": _as_date(_get(emp, cols, "contract_start_date")),
        "contract_end_date": contract_end,
        "days_to_contract_end": days_to_contract_end,
        "contract_expiring": contract_expiring,
        "contract_expired": contract_expired,
        "migration_source": _get(emp, cols, "migration_source"),
        "migrated_at": _get(emp, cols, "migrated_at"),
        "needs_migration": bool(flags),
        "migration_flags": flags,
    }


def _ids_with(db: Session, model, employee_ids: list[int]) -> set[int]:
    if not employee_ids:
        return set()
    return {row[0] for row in db.query(model.employee_id).filter(
        model.employee_id.in_(employee_ids)).distinct().all()}


@router.get("/employees-summary")
def employees_summary(
    warnings_within_days: int = Query(30, ge=0, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    """Ringkasan Employee Master: total, per employment status, kontrak akan habis.

    Tidak menyentuh tabel attendance/payroll — angka jejak HR dihitung dari data
    HR yang memang ada (training, performance, employee issue).
    """
    today = date.today()
    cols = _columns(db)
    employees = db.query(Employee).order_by(Employee.name).all()
    rows = [_row(e, cols, today=today, warnings_at=warnings_within_days) for e in employees]

    by_status: dict[str, int] = {}
    by_division: dict[str, int] = {}
    flags: dict[str, int] = {}
    for row in rows:
        by_status[row["employment_status"]] = by_status.get(row["employment_status"], 0) + 1
        division = row["division"] or "UNASSIGNED"
        by_division[division] = by_division.get(division, 0) + 1
        for flag in row["migration_flags"]:
            flags[flag] = flags.get(flag, 0) + 1

    open_rows = [r for r in rows if r["status_group"] == "OPEN"]
    expiring = sorted(
        [r for r in open_rows if r["contract_expiring"]],
        key=lambda r: (r["days_to_contract_end"], r["name"]),
    )

    employee_ids = [r["id"] for r in rows]
    with_training = _ids_with(db, TrainingRecord, employee_ids)
    with_performance = _ids_with(db, PerformanceRecord, employee_ids)
    trainings = performances = issues = open_issues = 0
    if employee_ids:
        trainings = db.query(func.count(TrainingRecord.id)).filter(
            TrainingRecord.employee_id.in_(employee_ids)).scalar() or 0
        performances = db.query(func.count(PerformanceRecord.id)).filter(
            PerformanceRecord.employee_id.in_(employee_ids)).scalar() or 0
        issues = db.query(func.count(EmployeeIssue.id)).filter(
            EmployeeIssue.employee_id.in_(employee_ids)).scalar() or 0
        open_issues = db.query(func.count(EmployeeIssue.id)).filter(
            EmployeeIssue.employee_id.in_(employee_ids),
            EmployeeIssue.status.notin_(["CLOSED", "RESOLVED"])).scalar() or 0

    return {
        "as_of": datetime.now(timezone.utc),
        "total": len(rows),
        "headcount_active": len(open_rows),
        "headcount_inactive": len(rows) - len(open_rows),
        "by_employment_status": [
            {"employment_status": k, "count": v} for k, v in sorted(by_status.items(), key=lambda i: (-i[1], i[0]))
        ],
        "by_division": [
            {"division": k, "count": v} for k, v in sorted(by_division.items(), key=lambda i: (-i[1], i[0]))
        ],
        "contract_watch": {
            "window_days": warnings_within_days,
            "count": len(expiring),
            "expired_count": sum(1 for r in open_rows if r["contract_expired"]),
            "employees": [{
                "id": r["id"], "employee_no": r["employee_no"], "name": r["name"],
                "division": r["division"], "position": r["position"],
                "employment_status": r["employment_status"],
                "contract_end_date": r["contract_end_date"],
                "days_to_contract_end": r["days_to_contract_end"],
            } for r in expiring[:20]],
        },
        "migration": {
            "needs_migration": sum(1 for r in rows if r["needs_migration"]),
            "by_flag": [{"flag": k, "count": v} for k, v in sorted(flags.items(), key=lambda i: (-i[1], i[0]))],
            "seed_rows": sum(1 for e in employees if _is_seed_row(e)),
            "contract_columns_present": _has(cols, "contract_end_date"),
            "join_date_column_present": _has(cols, "join_date"),
        },
        "hr_trace": {
            "training_records": int(trainings),
            "performance_records": int(performances),
            "employee_issues": int(issues),
            "open_issues": int(open_issues),
            "employees_without_training": sum(1 for r in rows if r["id"] not in with_training),
            "employees_without_performance": sum(1 for r in rows if r["id"] not in with_performance),
        },
        # Attendance & payroll: sumbernya CFO (revisi #67). Router ini read-only
        # dan tidak menulis/mengubah record attendance mana pun.
        "attendance": dict(ATTENDANCE_PENDING),
        "employees": rows,
    }


@router.get("/employees/{emp_id}/lifecycle")
def employee_lifecycle(
    emp_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    """Riwayat status kepegawaian yang bisa ditelusuri dari data yang ada."""
    today = date.today()
    cols = _columns(db)
    emp = db.get(Employee, emp_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    row = _row(emp, cols, today=today, warnings_at=30)

    trainings = db.query(TrainingRecord).filter(TrainingRecord.employee_id == emp_id).all()
    performances = db.query(PerformanceRecord).filter(PerformanceRecord.employee_id == emp_id).all()
    issues = db.query(EmployeeIssue).filter(EmployeeIssue.employee_id == emp_id).all()

    events = []
    if row["join_date"]:
        events.append({
            "date": row["join_date"], "type": "JOINED", "label": "Tanggal masuk",
            "detail": f"Tercatat dari {row['join_date_source']}",
            "source": row["join_date_source"], "status_after": _status(emp),
        })
    for t in trainings:
        events.append({
            "date": _as_date(t.start_date), "type": "TRAINING_START", "label": t.title,
            "detail": f"Evaluator: {t.evaluator or '-'}", "source": "training_records",
            "status_after": "TRAINING" if _status(emp) in OPEN_STATUSES else _status(emp),
        })
        events.append({
            "date": _as_date(t.end_date), "type": "TRAINING_END", "label": t.title,
            "detail": f"Hasil: {t.result or 'belum ada hasil'}", "source": "training_records",
            "status_after": _status(emp),
        })
    for p in performances:
        events.append({
            "date": _as_date(p.created_at), "type": "PERFORMANCE_REVIEW", "label": f"Periode {p.period}",
            "detail": f"Total skor: {p.total_score if p.total_score is not None else '-'}",
            "source": "performance_records", "status_after": _status(emp),
        })
    for i in issues:
        events.append({
            "date": _as_date(i.created_at), "type": "EMPLOYEE_ISSUE", "label": i.issue_type,
            "detail": f"Severity {i.severity} / status {i.status}",
            "source": "employee_issues", "status_after": _status(emp),
        })
    if row["contract_end_date"]:
        events.append({
            "date": row["contract_end_date"], "type": "CONTRACT_END",
            "label": f"Kontrak {row['contract_type'] or 'berakhir'}",
            "detail": f"{row['days_to_contract_end']} hari dari hari ini",
            "source": "employees.contract_end_date", "status_after": _status(emp),
        })
    if row["exit_date"]:
        events.append({
            "date": row["exit_date"], "type": "EXIT", "label": "Tanggal keluar",
            "detail": f"Status tercatat: {_status(emp)}",
            "source": "employees.exit_date", "status_after": _status(emp),
        })
    if row["migrated_at"]:
        events.append({
            "date": _as_date(row["migrated_at"]), "type": "MIGRATED",
            "label": f"Migrasi dari {row['migration_source'] or 'sumber lama'}",
            "detail": "Data warisan dimigrasikan", "source": "employees.migration_source",
            "status_after": _status(emp),
        })
    events.sort(key=lambda e: (e["date"] is None, e["date"] or date.min, e["type"]))

    return {
        "employee": row,
        "current_status": row["employment_status"],
        "timeline_source": "DERIVED_FROM_EXISTING_DATA",
        "events": events,
        "notes": [
            "Riwayat diturunkan dari kolom yang ada; belum ada tabel riwayat status tersendiri.",
            "Attendance & payroll tetap milik CFO dan read-only bagi HR.",
        ],
        "migration": {"needs_migration": row["needs_migration"], "flags": row["migration_flags"]},
        "related_counts": {
            "trainings": len(trainings),
            "performances": len(performances),
            "issues": len(issues),
        },
    }
