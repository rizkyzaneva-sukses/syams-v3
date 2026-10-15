"""Modul Lead / Opportunity + Sales Target BOS SYAMS (workspace Cecep/Deby).

Menutup gap BLUEPRINT §3.1/§3.2: pipeline SEBELUM order. Selama ini pipeline
(``/cmo/sales-pipeline`` di cmo_pipeline.py) DIHITUNG dari order yang sudah ada,
sehingga prospek yang belum jadi order tidak pernah muncul dan lead source tidak
tercatat. Modul ini menambah tabel sumber (lead -> opportunity) supaya pipeline
punya titik awal dari PROSPEK, bukan dari order.

Prinsip yang ditegakkan di level model:
1. **Lead adalah sumber pertama.** Lead mencatat lead source (BLUEPRINT §3.1)
   sebelum ada opportunity. Satu lead bisa dikonversi menjadi satu opportunity.
2. **Opportunity punya stage komersial sendiri** (PROSPECT -> ... -> WON/LOST),
   tidak diturunkan dari progres order. ``probability_percent`` melekat pada
   opportunity supaya weighted pipeline bisa dihitung apa adanya.
3. **order_fk hanya diisi saat convert-to-order.** Opportunity yang belum menjadi
   order tetap punya nilai dan probabilitas — itulah pipeline riil.
4. **SalesTarget unik per (period, owner_id)** — satu PIC hanya boleh punya satu
   target per periode; menulis ulang berarti upsert, bukan membuat baris ganda.

Tabel tabel ini dibuat dengan ``Base.metadata.create_all`` (dev/test) atau lewat
migrasi (production). Modul ini sengaja terpisah dari ``models.py`` inti agar
tidak menyentuh model yang sudah stabil.
"""
from datetime import datetime

from sqlalchemy import (Column, Integer, String, Text, Date, DateTime, Numeric,
                        ForeignKey, UniqueConstraint, Index)

from .database import Base


# Nilai sah untuk lead source (BLUEPRINT §3.1) dan status lead.
LEAD_SOURCES = ("REFERRAL", "WEBSITE", "WHATSAPP", "EXHIBITION", "COLD_CALL",
                "REPEAT", "LAINNYA")
LEAD_STATUSES = ("NEW", "CONTACTED", "QUALIFIED", "UNQUALIFIED", "CONVERTED")

# Stage pipeline opportunity, berurutan dari prospek sampai hasil akhir.
OPPORTUNITY_STAGES = ("PROSPECT", "QUALIFICATION", "PROPOSAL", "NEGOTIATION",
                       "WON", "LOST")


class Lead(Base):
    """Prospek/calon buyer sebelum menjadi opportunity.

    Lead source wajib diisi karena BLUEPRINT §3.1 meminta attribusi asal lead
    (referral/website/whatsapp/exhibition/cold call/repeat/lainnya) untuk
    mengukur kanal mana yang menghasilkan pipeline. Nilai perkiraan
    (``estimated_value``) boleh 0 selama belum dikualifikasi.
    """
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True)
    lead_no = Column(String(40), unique=True, nullable=False, index=True)
    source = Column(String(20), nullable=False, default="LAINNYA", index=True)
    company_name = Column(String(200), nullable=False)
    contact_name = Column(String(160), nullable=False)
    phone = Column(String(40), nullable=False)
    email = Column(String(180), nullable=False)
    city = Column(String(120), nullable=True)
    interested_product = Column(String(200), nullable=True)
    estimated_value = Column(Numeric(18, 2), nullable=False, default=0)
    # NEW/CONTACTED/QUALIFIED/UNQUALIFIED/CONVERTED (dipakai untuk funnel §3.2).
    status = Column(String(20), nullable=False, default="NEW", index=True)
    # PIC lead (Deby/CMO_SUPPORT menyiapkan, Cecep/CMO_MANAGER memutuskan).
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    next_followup_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                        nullable=False)


class Opportunity(Base):
    """Peluang komersial dengan stage sendiri, terpisah dari progres order.

    ``lead_id`` boleh NULL supaya penawaran langsung (tanpa lead tercatat) tetap
    bisa dilacak. ``order_fk`` diisi HANYA saat convert-to-order; sampai saat itu
    opportunity hidup di pipeline sebagai nilai berbobot
    (``estimated_value`` x ``probability_percent`` / 100).
    """
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True)
    opportunity_no = Column(String(40), unique=True, nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True, index=True)
    buyer_name = Column(String(200), nullable=False)
    # PROSPECT/QUALIFICATION/PROPOSAL/NEGOTIATION/WON/LOST.
    stage = Column(String(20), nullable=False, default="PROSPECT", index=True)
    estimated_value = Column(Numeric(18, 2), nullable=False, default=0)
    probability_percent = Column(Integer, nullable=False, default=0)
    expected_close_date = Column(Date, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # Diisi saat opportunity ditautkan ke order nyata (convert-to-order).
    order_fk = Column(Integer, ForeignKey("orders.id"), nullable=True, index=True)
    lost_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                        nullable=False)
    # Query pipeline per stage adalah akses terpanas modul ini.
    __table_args__ = (Index("ix_opportunity_stage_owner", "stage", "owner_id"),)


class SalesTarget(Base):
    """Target penjualan per periode (YYYY-MM) per PIC.

    UNIQUE(period, owner_id) menegakkan aturan "satu target per periode per PIC":
    menulis target untuk periode+PIC yang sama berarti UPSERT, bukan menambah
    baris kedua yang saling bertentangan. ``owner_name`` disimpan sebagai label
    supaya target tetap terbaca walaupun owner_id belum/tidak terhubung ke user.
    """
    __tablename__ = "sales_targets"
    id = Column(Integer, primary_key=True)
    period = Column(String(7), nullable=False, index=True)  # 'YYYY-MM'
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    owner_name = Column(String(160), nullable=True)
    target_amount = Column(Numeric(18, 2), nullable=False, default=0)
    target_orders = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                        nullable=False)
    __table_args__ = (
        UniqueConstraint("period", "owner_id", name="uq_sales_target_period_owner"),
    )
