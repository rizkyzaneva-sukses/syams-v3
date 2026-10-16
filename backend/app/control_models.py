"""Tabel Control System: master data, SLA berversi, status tahap order, blok masalah.

Mengikuti sistem lama (Google Sheet "simulasi master control"): 15 tahap per order,
SLA per tahap, daftar jenis pakaian dan PIC. Status tahap TIDAK disimpan sebagai
teks bebas: yang disimpan hanya fakta (selesai / dilewati / masalah), sedangkan
PROGRES / PERHATIAN / URGENT diturunkan oleh `control_service` dari SLA.
"""
from datetime import datetime

from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)

from .database import Base


class GarmentType(Base):
    """Daftar jenis pakaian (Master Engine di sheet)."""
    __tablename__ = "garment_types"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PicMaster(Base):
    """Daftar PIC beserta bagian kerjanya (Master Engine di sheet)."""
    __tablename__ = "pic_masters"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    role_label = Column(String(120), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class StageSlaVersion(Base):
    """Satu versi standar SLA. Versi lama tidak pernah diubah atau dihapus.

    Order memakai versi yang berlaku saat order dibuat, jadi mengubah SLA tidak
    menggeser deadline order yang sedang berjalan.
    """
    __tablename__ = "stage_sla_versions"
    id = Column(Integer, primary_key=True)
    version = Column(Integer, unique=True, nullable=False)
    change_reason = Column(Text, nullable=False)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class StageSlaItem(Base):
    __tablename__ = "stage_sla_items"
    __table_args__ = (UniqueConstraint("version_fk", "stage_code", name="uq_sla_item_stage"),)
    id = Column(Integer, primary_key=True)
    version_fk = Column(Integer, ForeignKey("stage_sla_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_code = Column(String(24), nullable=False)
    sort_order = Column(Integer, nullable=False)
    duration_days = Column(Integer, nullable=False)
    primary_pic = Column(String(80), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    daily_capacity = Column(Integer, default=0, nullable=False)
    capacity_unit = Column(String(16), default="PCS", nullable=False)
    warning_pct = Column(Float, default=0.8, nullable=False)
    note = Column(String(200), nullable=True)


class OrderStage(Base):
    """Fakta per tahap per order. Baris hanya ada bila tahap pernah disentuh."""
    __tablename__ = "order_stages"
    __table_args__ = (UniqueConstraint("order_fk", "stage_code", name="uq_order_stage"),)
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_code = Column(String(24), nullable=False)
    # DONE | SKIPPED | ENABLED (ENABLED = tahap yang default-nya mati, mis. REVISI, dinyalakan)
    state = Column(String(12), nullable=False)
    done_at = Column(DateTime, nullable=True)
    done_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    pic_name = Column(String(80), nullable=True)
    note = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class OrderBlock(Base):
    """Problem / block + next action yang wajib ditulis PIC (kolom AG/AH di sheet)."""
    __tablename__ = "order_blocks"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_code = Column(String(24), nullable=True)
    problem = Column(Text, nullable=False)
    next_action = Column(Text, nullable=False)
    pic_name = Column(String(80), nullable=True)
    opened_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    opened_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_note = Column(Text, nullable=True)


class OrderSequence(Base):
    """Penomoran Order ID per bulan: SYM-YYMM-NNN. Baris dikunci saat menaikkan nomor."""
    __tablename__ = "order_sequences"
    period = Column(String(4), primary_key=True)
    last_no = Column(Integer, default=0, nullable=False)
