"""Tabel baru untuk tugas CFO Manager (role Finance Support dihapus; semua tugas keuangan di CFO):
gambar tersimpan (logo, desain, size chart), kas kecil/besar, master karyawan harian, dan input hasil produksi.
"""
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, Boolean, Index

from .database import Base
from . import accounting_models  # noqa: F401 — cash_entries.journal_entry_id mereferensikan journal_entries


class StoredImage(Base):
    """Gambar yang diunggah pengguna: logo perusahaan, desain artikel, size chart. Disimpan di database
    (bukan link Drive) supaya selalu tersedia untuk dokumen SPK/Invoice. Tidak pernah ditimpa."""
    __tablename__ = "stored_images"
    id = Column(Integer, primary_key=True)
    kind = Column(String(16), nullable=False, index=True)   # LOGO | DESIGN | SIZE_CHART
    filename = Column(String(200), nullable=True)
    mime = Column(String(40), nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    data = Column(LargeBinary, nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CashEntry(Base):
    """Buku kas. PETTY = kas kecil harian; BIG = kas besar (otomatis diposting ke jurnal akuntansi)."""
    __tablename__ = "cash_entries"
    id = Column(Integer, primary_key=True)
    kind = Column(String(8), nullable=False, index=True)          # PETTY | BIG
    entry_date = Column(Date, nullable=False, index=True)
    direction = Column(String(4), nullable=False)                 # IN | OUT
    category = Column(String(80), nullable=True)
    description = Column(Text, nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    cash_account_code = Column(String(24), nullable=True)         # BIG: 1-1000 (Kas) / 1-1100 (Bank)
    counter_account_code = Column(String(24), nullable=True)      # BIG: akun lawan
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class DailyWorker(Base):
    """Master karyawan harian (borongan/harian) yang dipakai untuk input hasil produksi."""
    __tablename__ = "daily_workers"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    process = Column(String(40), nullable=True)                   # bagian utama: CUTTING, SEWING, dst.
    rate_per_pcs = Column(Numeric(18, 2), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ProductionResult(Base):
    """Hasil produksi per karyawan per hari. Upah = qty × tarif per pcs saat dicatat (tarif disalin)."""
    __tablename__ = "production_results"
    id = Column(Integer, primary_key=True)
    result_date = Column(Date, nullable=False, index=True)
    worker_fk = Column(Integer, ForeignKey("daily_workers.id"), nullable=False, index=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    process = Column(String(40), nullable=False)
    qty = Column(Integer, nullable=False)
    rate = Column(Numeric(18, 2), nullable=False, default=0)
    amount = Column(Numeric(18, 2), nullable=False, default=0)
    notes = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("ix_production_results_worker_date", "worker_fk", "result_date"),)
