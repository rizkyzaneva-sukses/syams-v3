"""HR — Absensi (Attendance) & Cuti/Izin (Leave).

Router ini adalah jalur TULIS resmi untuk dua hal yang sebelumnya tidak punya
rumah di HR: kehadiran harian dan pengajuan cuti/izin. Aturan bisnis ditegakkan
di server, bukan diserahkan ke UI, mengikuti pola ``hr_recruitment.py``:

- Absensi satu karyawan satu tanggal bersifat unik. POST kedua di tanggal yang
  sama TIDAK membuat baris baru dan TIDAK gagal — ia memperbarui baris yang ada
  (upsert). Ini menutup celah "input ganda" tanpa memaksa UI mengirim id.
- Pengajuan cuti baru selalu DRAFT/SUBMITTED dengan ``days`` dihitung inklusif;
  klien tidak boleh mengarang jumlah hari.
- Approve cuti TAHUNAN wajib punya saldo cukup; kalau kurang → 400 dan
  ``used_days`` tidak berkurang/ditambah. Approve juga hanya untuk
  CHRO_MANAGER/HR_SUPPORT — CEO read-only.
- Reject WAJIB menyertakan alasan.

Semua endpoint tulis mencatat audit lewat ``log_audit`` (satu transaksi dengan
perubahan datanya). Baca = semua pengguna terautentikasi.
"""
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..auth import get_current_user, require_roles
from ..database import get_db
from .. import models
from ..hr_time_models import (Attendance, LeaveRequest, LeaveBalance,
                              ATTENDANCE_STATUSES, LEAVE_TYPES,
                              LEAVE_STATUSES)

router = APIRouter(prefix="/hr", tags=["hr"])

# Penulis HR (absensi & pengajuan cuti). CEO sengaja TIDAK di sini: CEO hanya
# membaca laporan, tidak mengubah absensi maupun memutuskan cuti.
HR_WRITE_ROLES = (models.Role.CHRO_MANAGER, models.Role.HR_SUPPORT)
# Pemutus cuti. Dipisah dari penulis supaya perubahan di masa depan tidak
# diam-diam memberi hak approve ke peran lain.
HR_DECIDER_ROLES = (models.Role.CHRO_MANAGER, models.Role.HR_SUPPORT)

_D0 = Decimal("0")


def _role(user) -> str:
    return getattr(user.role, "value", user.role)


def _actor(user) -> str:
    name = getattr(user, "name", None)
    return f"{name} ({_role(user)}#{getattr(user, 'id', None)})" if name else f"{_role(user)}#{getattr(user, 'id', None)}"


def _parse_date(value, field: str) -> date | None:
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


def _require_write(user):
    if _role(user) not in {r.value for r in HR_WRITE_ROLES}:
        raise HTTPException(403, "Hanya CHRO_MANAGER/HR_SUPPORT yang boleh menulis data absensi & cuti.")


def _serial(obj) -> dict:
    """Kolom objek → dict JSON-able (Date/DateTime jadi ISO)."""
    out = {}
    for col in obj.__table__.columns:
        value = getattr(obj, col.name, None)
        out[col.name] = value.isoformat() if isinstance(value, (date, datetime)) else value
    return out


def _seq_no(db: Session, prefix: str, width: int = 5) -> str:
    """Nomor pengajuan cuti berurutan; aman di DB kosong maupun berisi."""
    count = db.query(LeaveRequest).count()
    seq = count + 1
    for _ in range(50):
        candidate = f"{prefix}{seq:0{width}d}"
        if not db.query(LeaveRequest).filter(LeaveRequest.request_no == candidate).first():
            return candidate
        seq += 1
    raise HTTPException(409, f"Tidak bisa mengalokasikan nomor {prefix} baru.")


def _days_between(start: date, end: date) -> Decimal:
    """Jumlah hari cuti inklusif (tanggal mulai DAN tanggal akhir dihitung)."""
    return Decimal((end - start).days + 1)


# ═══════════════════════════════════ ABSENSI ═══════════════════════════════════

@router.get("/attendance")
def list_attendance(
    employee_id: int = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    status: str = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Daftar absensi dengan filter karyawan / rentang tanggal / status. Read-only."""
    q = db.query(Attendance)
    if employee_id:
        q = q.filter(Attendance.employee_id == employee_id)
    d_from = _parse_date(date_from, "date_from")
    d_to = _parse_date(date_to, "date_to")
    if d_from:
        q = q.filter(Attendance.work_date >= d_from)
    if d_to:
        q = q.filter(Attendance.work_date <= d_to)
    if status:
        st = status.upper()
        if st not in ATTENDANCE_STATUSES:
            raise HTTPException(422, f"status harus salah satu dari {list(ATTENDANCE_STATUSES)}.")
        q = q.filter(Attendance.status == st)
    rows = q.order_by(Attendance.work_date.desc(), Attendance.employee_id).limit(limit).all()
    return {"count": len(rows), "rows": [_serial(r) for r in rows]}


@router.post("/attendance", status_code=201)
def upsert_attendance(
    employee_id: int = Query(..., description="FK employees.id"),
    work_date: str = Query(..., description="Tanggal kerja ISO (YYYY-MM-DD)"),
    status: str = Query(..., description="HADIR/TERLAMBAT/IZIN/SAKIT/ALPHA/CUTI/LIBUR"),
    check_in: str = Query(None),
    check_out: str = Query(None),
    overtime_hours: float = Query(0, ge=0),
    shift: str = Query(None),
    notes: str = Query(None),
    db: Session = Depends(get_db),
    user=Depends(require_roles(*HR_WRITE_ROLES)),
):
    """Input absensi satu karyawan pada satu tanggal (upsert).

    Bila baris (employee_id, work_date) sudah ada, ia DIPERBARUI — bukan dibuat
    kedua. Ini mencegah absensi ganda untuk hari yang sama tanpa menuntut klien
    menyertakan id.
    """
    _require_write(user)
    wd = _parse_date(work_date, "work_date")
    if wd is None:
        raise HTTPException(422, "work_date wajib diisi.")
    st = (status or "").upper()
    if st not in ATTENDANCE_STATUSES:
        raise HTTPException(422, f"status harus salah satu dari {list(ATTENDANCE_STATUSES)}.")
    if not db.get(models.Employee, employee_id):
        raise HTTPException(404, f"Employee {employee_id} tidak ditemukan.")

    row = db.query(Attendance).filter(
        Attendance.employee_id == employee_id, Attendance.work_date == wd).first()
    created = row is None
    if created:
        row = Attendance(employee_id=employee_id, work_date=wd)
        db.add(row)
    row.status = st
    row.check_in = check_in or None
    row.check_out = check_out or None
    row.overtime_hours = Decimal(str(overtime_hours or 0))
    row.shift = shift or None
    row.notes = notes
    row.recorded_by_id = user.id
    db.flush()
    log_audit(db, user,
              "HR_ATTENDANCE_CREATE" if created else "HR_ATTENDANCE_UPDATE",
              "Attendance", row.id,
              f"employee={employee_id} date={wd} status={st} overtime={row.overtime_hours}",
              obj=row, source_module="HRTime",
              previous_status=None if created else "EXISTING", new_status=st)
    db.commit()
    return {**_serial(row), "created": created, "upserted": True, "audit_logged": True}


@router.get("/attendance/summary")
def attendance_summary(
    date_from: str = Query(None),
    date_to: str = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Rekap absensi per karyawan: hadir/terlambat/izin/sakit/alpha + total lembur.

    Dihitung langsung dari tabel ``attendance`` (bukan dari data turunan), jadi
    angka yang ditampilkan HR persis sama dengan yang tersimpan.
    """
    q = db.query(
        Attendance.employee_id,
        Attendance.status,
        func.count(Attendance.id),
        func.coalesce(func.sum(Attendance.overtime_hours), 0),
    )
    d_from = _parse_date(date_from, "date_from")
    d_to = _parse_date(date_to, "date_to")
    if d_from:
        q = q.filter(Attendance.work_date >= d_from)
    if d_to:
        q = q.filter(Attendance.work_date <= d_to)
    bucket = q.group_by(Attendance.employee_id, Attendance.status).all()

    per_emp: dict[int, dict] = {}
    for emp_id, st, count, ot in bucket:
        row = per_emp.setdefault(emp_id, {
            "employee_id": emp_id, "HADIR": 0, "TERLAMBAT": 0, "IZIN": 0,
            "SAKIT": 0, "ALPHA": 0, "CUTI": 0, "LIBUR": 0, "overtime_hours": 0.0,
        })
        key = (st or "").upper()
        if key in row:
            row[key] += int(count)
        row["overtime_hours"] += float(ot or 0)

    employees = {e.id: e for e in db.query(models.Employee).filter(
        models.Employee.id.in_(list(per_emp.keys()) or [0])).all()}
    rows = []
    for emp_id, row in per_emp.items():
        emp = employees.get(emp_id)
        rows.append({
            **row,
            "employee_no": emp.employee_no if emp else None,
            "name": emp.name if emp else None,
            "division": emp.division if emp else None,
        })
    rows.sort(key=lambda r: (r["name"] or "", r["employee_id"]))
    return {
        "date_from": d_from, "date_to": d_to,
        "count": len(rows),
        "totals": {
            "HADIR": sum(r["HADIR"] for r in rows),
            "TERLAMBAT": sum(r["TERLAMBAT"] for r in rows),
            "IZIN": sum(r["IZIN"] for r in rows),
            "SAKIT": sum(r["SAKIT"] for r in rows),
            "ALPHA": sum(r["ALPHA"] for r in rows),
            "CUTI": sum(r["CUTI"] for r in rows),
            "LIBUR": sum(r["LIBUR"] for r in rows),
            "overtime_hours": round(sum(r["overtime_hours"] for r in rows), 2),
        },
        "rows": rows,
    }


# ═══════════════════════════════════ CUTI / IZIN ═══════════════════════════════

@router.get("/leave/balances")
def list_leave_balances(
    year: int = Query(None),
    employee_id: int = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Saldo cuti per karyawan/tahun/jenis. ``remaining`` = entitled - used."""
    q = db.query(LeaveBalance)
    if year:
        q = q.filter(LeaveBalance.year == year)
    if employee_id:
        q = q.filter(LeaveBalance.employee_id == employee_id)
    rows = q.order_by(LeaveBalance.year.desc(), LeaveBalance.employee_id).all()
    employees = {e.id: e for e in db.query(models.Employee).filter(
        models.Employee.id.in_([r.employee_id for r in rows] or [0])).all()}
    out = []
    for r in rows:
        entitled = Decimal(r.entitled_days or 0)
        used = Decimal(r.used_days or 0)
        emp = employees.get(r.employee_id)
        out.append({
            **_serial(r),
            "remaining": float(entitled - used),
            "employee_no": emp.employee_no if emp else None,
            "name": emp.name if emp else None,
        })
    return {"count": len(out), "rows": out}


@router.get("/leave")
def list_leave(
    employee_id: int = Query(None),
    status: str = Query(None),
    leave_type: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Daftar pengajuan cuti dengan filter. Read-only untuk semua peran."""
    q = db.query(LeaveRequest)
    if employee_id:
        q = q.filter(LeaveRequest.employee_id == employee_id)
    if status:
        st = status.upper()
        if st not in LEAVE_STATUSES:
            raise HTTPException(422, f"status harus salah satu dari {list(LEAVE_STATUSES)}.")
        q = q.filter(LeaveRequest.status == st)
    if leave_type:
        lt = leave_type.upper()
        if lt not in LEAVE_TYPES:
            raise HTTPException(422, f"leave_type harus salah satu dari {list(LEAVE_TYPES)}.")
        q = q.filter(LeaveRequest.leave_type == lt)
    d_from = _parse_date(date_from, "date_from")
    d_to = _parse_date(date_to, "date_to")
    if d_from:
        q = q.filter(LeaveRequest.end_date >= d_from)
    if d_to:
        q = q.filter(LeaveRequest.start_date <= d_to)
    rows = q.order_by(LeaveRequest.created_at.desc()).limit(limit).all()
    employees = {e.id: e for e in db.query(models.Employee).filter(
        models.Employee.id.in_([r.employee_id for r in rows] or [0])).all()}
    out = []
    for r in rows:
        emp = employees.get(r.employee_id)
        out.append({
            **_serial(r),
            "employee_no": emp.employee_no if emp else None,
            "name": emp.name if emp else None,
            "division": emp.division if emp else None,
        })
    return {"count": len(out), "rows": out}


@router.post("/leave", status_code=201)
def create_leave(
    employee_id: int = Query(...),
    leave_type: str = Query(..., description="TAHUNAN/SAKIT/IZIN/MELAHIRKAN/LAINNYA"),
    start_date: str = Query(...),
    end_date: str = Query(...),
    reason: str = Query(None),
    db: Session = Depends(get_db),
    user=Depends(require_roles(*HR_WRITE_ROLES)),
):
    """Buat pengajuan cuti baru (status awal SUBMITTED).

    ``days`` dihitung server-side secara inklusif — klien tidak boleh mengirim
    jumlah hari. Check-in validasi tanggal agar end tidak mendahului start.
    """
    _require_write(user)
    lt = (leave_type or "").upper()
    if lt not in LEAVE_TYPES:
        raise HTTPException(422, f"leave_type harus salah satu dari {list(LEAVE_TYPES)}.")
    sd = _parse_date(start_date, "start_date")
    ed = _parse_date(end_date, "end_date")
    if not sd or not ed:
        raise HTTPException(422, "start_date dan end_date wajib diisi.")
    if ed < sd:
        raise HTTPException(422, "end_date tidak boleh mendahului start_date.")
    if not db.get(models.Employee, employee_id):
        raise HTTPException(404, f"Employee {employee_id} tidak ditemukan.")

    row = LeaveRequest(
        request_no=_seq_no(db, "LV-"),
        employee_id=employee_id, leave_type=lt,
        start_date=sd, end_date=ed, days=_days_between(sd, ed),
        reason=reason, status="SUBMITTED", submitted_by_id=user.id)
    db.add(row)
    db.flush()
    log_audit(db, user, "HR_LEAVE_CREATE", "LeaveRequest", row.id,
              f"{row.request_no} {lt} {sd}..{ed} days={row.days}",
              obj=row, source_module="HRTime", previous_status=None, new_status="SUBMITTED")
    db.commit()
    return {**_serial(row), "audit_logged": True}


@router.post("/leave/{leave_id}/submit")
def submit_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_roles(*HR_WRITE_ROLES)),
):
    """Ajukan cuti dari DRAFT → SUBMITTED (idempotent bila sudah SUBMITTED)."""
    _require_write(user)
    row = db.get(LeaveRequest, leave_id)
    if row is None:
        raise HTTPException(404, "Pengajuan cuti tidak ditemukan.")
    current = (row.status or "").upper()
    if current == "SUBMITTED":
        return {**_serial(row), "previous_status": current, "audit_logged": False}
    if current != "DRAFT":
        raise HTTPException(409, f"Hanya pengajuan DRAFT yang bisa diajukan; status kini {current}.")
    row.status = "SUBMITTED"
    db.flush()
    log_audit(db, user, "HR_LEAVE_SUBMIT", "LeaveRequest", row.id,
              f"{row.request_no} DRAFT -> SUBMITTED", obj=row, source_module="HRTime",
              previous_status="DRAFT", new_status="SUBMITTED")
    db.commit()
    return {**_serial(row), "previous_status": "DRAFT", "audit_logged": True}


@router.post("/leave/{leave_id}/approve")
def approve_leave(
    leave_id: int,
    note: str = Query(None),
    db: Session = Depends(get_db),
    user=Depends(require_roles(*HR_DECIDER_ROLES)),
):
    """Setujui pengajuan cuti. Wajib saldo cukup untuk cuti TAHUNAN.

    Guardrail nyata: bila jenis TAHUNAN dan sisa saldo (entitled - used) kurang
    dari ``days`` → 400 dan ``used_days`` TIDAK berubah. Saldo yang belum
    tersedia (tidak ada baris) dianggap 0 → ditolak, bukan disetujui diam-diam.
    """
    row = db.get(LeaveRequest, leave_id)
    if row is None:
        raise HTTPException(404, "Pengajuan cuti tidak ditemukan.")
    current = (row.status or "").upper()
    if current != "SUBMITTED":
        raise HTTPException(409, f"Hanya pengajuan SUBMITTED yang bisa disetujui; status kini {current}.")

    used_balance = None
    if (row.leave_type or "").upper() == "TAHUNAN":
        year = row.start_date.year
        bal = db.query(LeaveBalance).filter(
            LeaveBalance.employee_id == row.employee_id,
            LeaveBalance.year == year,
            LeaveBalance.leave_type == "TAHUNAN").first()
        entitled = Decimal(bal.entitled_days or 0) if bal else _D0
        used = Decimal(bal.used_days or 0) if bal else _D0
        remaining = entitled - used
        if remaining < Decimal(row.days or 0):
            raise HTTPException(
                400,
                f"Saldo cuti TAHUNAN tidak cukup: sisa {remaining} hari, "
                f"diajukan {row.days} hari (tahun {year}).")
        bal.used_days = used + Decimal(row.days or 0)
        used_balance = bal

    row.status = "APPROVED"
    row.decided_by_id = user.id
    row.decided_at = datetime.utcnow()
    row.decision_note = note
    db.flush()
    log_audit(db, user, "HR_LEAVE_APPROVE", "LeaveRequest", row.id,
              f"{row.request_no} SUBMITTED -> APPROVED"
              + (f" (saldo {row.leave_type} dipakai {row.days} hari)" if used_balance else ""),
              obj=row, source_module="HRTime", previous_status="SUBMITTED",
              new_status="APPROVED", reason=note)
    db.commit()
    return {**_serial(row), "balance_updated": used_balance is not None,
            "previous_status": "SUBMITTED", "audit_logged": True}


@router.post("/leave/{leave_id}/reject")
def reject_leave(
    leave_id: int,
    reason: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user=Depends(require_roles(*HR_DECIDER_ROLES)),
):
    """Tolak pengajuan cuti — alasan WAJIB diisi."""
    if not (reason or "").strip():
        raise HTTPException(400, "Penolakan cuti wajib menyertakan alasan.")
    row = db.get(LeaveRequest, leave_id)
    if row is None:
        raise HTTPException(404, "Pengajuan cuti tidak ditemukan.")
    current = (row.status or "").upper()
    if current != "SUBMITTED":
        raise HTTPException(409, f"Hanya pengajuan SUBMITTED yang bisa ditolak; status kini {current}.")
    row.status = "REJECTED"
    row.decided_by_id = user.id
    row.decided_at = datetime.utcnow()
    row.decision_note = reason
    db.flush()
    log_audit(db, user, "HR_LEAVE_REJECT", "LeaveRequest", row.id,
              f"{row.request_no} SUBMITTED -> REJECTED", obj=row, source_module="HRTime",
              previous_status="SUBMITTED", new_status="REJECTED", reason=reason)
    db.commit()
    return {**_serial(row), "previous_status": "SUBMITTED", "audit_logged": True}
