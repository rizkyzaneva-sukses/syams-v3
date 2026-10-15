"""Modul HR — Absensi (Attendance) dan Cuti/Izin (Leave).

Menambahkan sumber resmi dua hal yang sebelumnya hanya dititipkan ke modul lain:

- ``Attendance``: kehadiran harian per karyawan. Satu baris = satu karyawan pada
  satu tanggal (``UNIQUE(employee_id, work_date)``) supaya tidak pernah ada
  kehadiran ganda untuk hari yang sama — input kedua memperbarui baris yang ada
  (upsert), bukan menumpuk.
- ``LeaveRequest``: pengajuan cuti/izin dengan alur status eksplisit
  (DRAFT → SUBMITTED → APPROVED/REJECTED/CANCELLED). Keputusan hanya sah bila
  saldo cuti mencukupi (ditegakkan di router, bukan di UI).
- ``LeaveBalance``: saldo cuti per karyawan per tahun per jenis
  (``UNIQUE(employee_id, year, leave_type)``) agar jatah tidak pernah bisa
  tergandakan oleh dua baris yang saling bertentangan.

Pemisahan modul (bukan menempel ke ``models.py``) mengikuti pola
``accounting_models.py``: tabel domain mandiri yang ikut terdaftar ke
``Base.metadata`` lewat import. Router ``hr_time`` selalu diimpor oleh
``main.py`` sehingga tabel di sini otomatis ikut ``create_all``.

Catatan enum: nilai status/tipe disimpan sebagai ``String`` (bukan ``Enum``
PostgreSQL) supaya penambahan nilai baru tidak menuntut migrasi tipe — konsisten
dengan tabel HR lain yang sudah ada (mis. ``manpower_requests.status``).
"""
from datetime import datetime

from sqlalchemy import (Column, Integer, String, Text, Date, DateTime,
                        Numeric, ForeignKey, UniqueConstraint)
from .database import Base


# Status absensi harian yang sah. Di luar daftar ini ditolak di router.
ATTENDANCE_STATUSES = ("HADIR", "TERLAMBAT", "IZIN", "SAKIT", "ALPHA", "CUTI", "LIBUR")

# Jenis cuti/izin yang sah.
LEAVE_TYPES = ("TAHUNAN", "SAKIT", "IZIN", "MELAHIRKAN", "LAINNYA")

# Alur status pengajuan cuti.
LEAVE_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CANCELLED")


class Attendance(Base):
    """Kehadiran harian karyawan.

    ``recorded_by_id`` mencatat siapa yang menginput (bukan siapa yang hadir),
    sehingga jejak "siapa mencatat apa" bisa ditelusuri saat koreksi data.
    ``overtime_hours`` default 0 agar penjumlahan lembur tidak pernah None.
    """
    __tablename__ = "attendance"
    __table_args__ = (
        # Kunci anti-duplikat: satu karyawan hanya boleh punya satu baris per hari.
        UniqueConstraint("employee_id", "work_date", name="uq_attendance_employee_date"),
    )
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    work_date = Column(Date, nullable=False, index=True)
    status = Column(String(16), nullable=False, index=True)
    check_in = Column(String(8), nullable=True)   # "HH:MM" apa adanya, bukan tipe TIME
    check_out = Column(String(8), nullable=True)
    overtime_hours = Column(Numeric(6, 2), default=0, nullable=False)
    shift = Column(String(24), nullable=True)
    notes = Column(Text, nullable=True)
    recorded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class LeaveRequest(Base):
    """Pengajuan cuti/izin dengan alur persetujuan.

    ``days`` disimpan hasil hitungan inklusif (start..end), bukan dihitung ulang
    saat baca — supaya keputusan yang sudah diambil tetap konsisten walaupun
    tanggal diubah di sistem lain.
    """
    __tablename__ = "leave_requests"
    id = Column(Integer, primary_key=True)
    request_no = Column(String(40), unique=True, nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    leave_type = Column(String(24), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    days = Column(Numeric(6, 1), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String(16), default="DRAFT", nullable=False, index=True)
    submitted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class LeaveBalance(Base):
    """Saldo cuti per karyawan / tahun / jenis.

    ``used_days`` hanya bertambah lewat approve (di router) dan tidak boleh
    melewati ``entitled_days`` — karena itu keduanya disatukan dalam satu baris
    unik supaya tidak ada dua sumber kebenaran.
    """
    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint("employee_id", "year", "leave_type", name="uq_leave_balance_emp_year_type"),
    )
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    leave_type = Column(String(24), nullable=False)
    entitled_days = Column(Numeric(6, 1), default=0, nullable=False)
    used_days = Column(Numeric(6, 1), default=0, nullable=False)
