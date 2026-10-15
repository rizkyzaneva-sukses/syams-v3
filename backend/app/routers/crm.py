"""Router CRM — Lead / Opportunity / Sales Target (workspace Cecep & Deby).

Menutup gap BLUEPRINT §3.1 (lead source) dan §3.2 (pipeline dari PROSPEK +
sales target). Sebelumnya pipeline (``/cmo/sales-pipeline``) dihitung dari order
yang sudah ada; di sini pipeline dimulai dari lead/prospek dan bergerak lewat
stage komersial sendiri, terlepas dari progres order.

Aturan yang ditegakkan DI SINI (bukan cuma di UI):
1. **Win butuh nilai.** Opportunity dengan ``estimated_value <= 0`` ditolak (400)
   untuk ditandai WON — tidak ada "menang" tanpa angka.
2. **Lose butuh alasan.** ``lost_reason`` wajib; LOST tanpa alasan ditolak (400).
3. **Convert-to-order sekali saja.** Opportunity yang sudah CONVERTED
   (``order_fk`` terisi) atau sudah WON ditolak (409) untuk convert ulang; ini
   mencegah satu peluang menghasilkan dua order.
4. **Satu target per (periode, PIC).** POST sales-target = UPSERT; menulis
   periode+PIC yang sama memperbarui baris, tidak menggandakan.

Hak tulis:
* CMO_MANAGER (Cecep) + CMO_SUPPORT (Deby): lead & opportunity.
* CFO_MANAGER: sales target (anggaran penjualan milik Finance).
Read: CMO_MANAGER, CMO_SUPPORT, CEO, CFO_MANAGER.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user, require_roles
from ..audit import log_audit
from .. import models
from ..crm_models import (Lead, Opportunity, SalesTarget,
                          LEAD_SOURCES, LEAD_STATUSES, OPPORTUNITY_STAGES)

router = APIRouter(prefix="/crm", tags=["crm"])

# Peran yang boleh menulis lead/opportunity (pemilik customer truth).
CRM_WRITE_ROLES = (models.Role.CMO_MANAGER, models.Role.CMO_SUPPORT)
# Target penjualan adalah artefak Finance; hanya CFO_MANAGER yang menulis.
TARGET_WRITE_ROLES = (models.Role.CFO_MANAGER,)
# Pembaca: CMO + CEO (read-only) + CFO (target & aktual).
READ_ROLES = (models.Role.CEO, models.Role.CMO_MANAGER, models.Role.CMO_SUPPORT,
              models.Role.CFO_MANAGER)

ZERO = Decimal("0.00")

# Probabilitas default per stage supaya weighted pipeline tidak nol semua saat
# PIC belum mengisi probabilitas manual.
DEFAULT_PROBABILITY = {
    "PROSPECT": 10, "QUALIFICATION": 25, "PROPOSAL": 50,
    "NEGOTIATION": 75, "WON": 100, "LOST": 0,
}

# Probabilitas tidak pernah menang/kalah secara paksa — hanya stage terbuka.
OPEN_STAGES = ("PROSPECT", "QUALIFICATION", "PROPOSAL", "NEGOTIATION")


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# ── Skema input ──────────────────────────────────────────────────────────────
class LeadIn(BaseModel):
    source: str = Field(default="LAINNYA", max_length=20)
    company_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=1, max_length=40)
    email: str = Field(min_length=3, max_length=180)
    city: Optional[str] = Field(default=None, max_length=120)
    interested_product: Optional[str] = Field(default=None, max_length=200)
    estimated_value: Decimal = Field(default=ZERO, ge=0)
    status: str = Field(default="NEW", max_length=20)
    owner_id: Optional[int] = None
    next_followup_date: Optional[date] = None
    notes: Optional[str] = None


class LeadUpdate(BaseModel):
    source: Optional[str] = Field(default=None, max_length=20)
    company_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    contact_name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    phone: Optional[str] = Field(default=None, min_length=1, max_length=40)
    email: Optional[str] = Field(default=None, min_length=3, max_length=180)
    city: Optional[str] = Field(default=None, max_length=120)
    interested_product: Optional[str] = Field(default=None, max_length=200)
    estimated_value: Optional[Decimal] = Field(default=None, ge=0)
    status: Optional[str] = Field(default=None, max_length=20)
    owner_id: Optional[int] = None
    next_followup_date: Optional[date] = None
    notes: Optional[str] = None


class LeadConvertIn(BaseModel):
    """Opsi saat lead dikonversi menjadi opportunity."""
    estimated_value: Optional[Decimal] = Field(default=None, ge=0)
    probability_percent: Optional[int] = Field(default=None, ge=0, le=100)
    expected_close_date: Optional[date] = None
    owner_id: Optional[int] = None
    buyer_name: Optional[str] = Field(default=None, max_length=200)


class OpportunityIn(BaseModel):
    lead_id: Optional[int] = None
    buyer_name: str = Field(min_length=1, max_length=200)
    stage: str = Field(default="PROSPECT", max_length=20)
    estimated_value: Decimal = Field(default=ZERO, ge=0)
    probability_percent: Optional[int] = Field(default=None, ge=0, le=100)
    expected_close_date: Optional[date] = None
    owner_id: Optional[int] = None


class OpportunityUpdate(BaseModel):
    buyer_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    stage: Optional[str] = Field(default=None, max_length=20)
    estimated_value: Optional[Decimal] = Field(default=None, ge=0)
    probability_percent: Optional[int] = Field(default=None, ge=0, le=100)
    expected_close_date: Optional[date] = None
    owner_id: Optional[int] = None


class LoseIn(BaseModel):
    lost_reason: str = Field(min_length=1)


class ConvertToOrderIn(BaseModel):
    order_id: int


class SalesTargetIn(BaseModel):
    period: str = Field(min_length=7, max_length=7)
    owner_id: Optional[int] = None
    owner_name: Optional[str] = Field(default=None, max_length=160)
    target_amount: Decimal = Field(default=ZERO, ge=0)
    target_orders: int = Field(default=0, ge=0)
    notes: Optional[str] = None


# ── Helper ───────────────────────────────────────────────────────────────────
def _num(value):
    return None if value is None else float(value)


def _iso(value):
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _period_of(value: Optional[date], fallback: Optional[date] = None) -> str:
    day = value or fallback or date.today()
    return day.strftime("%Y-%m")


def _owner_name(db: Session, owner_id: Optional[int]) -> Optional[str]:
    if owner_id is None:
        return None
    user = db.get(models.User, owner_id)
    return user.name if user else None


def _next_lead_no(db: Session) -> str:
    """Nomor lead otomatis LD-YYYY-NNNNN, urut per tahun."""
    year = datetime.utcnow().strftime("%Y")
    prefix = f"LD-{year}-"
    last = (db.query(Lead.lead_no)
            .filter(Lead.lead_no.like(prefix + "%"))
            .order_by(Lead.lead_no.desc()).first())
    seq = int(last[0].rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:05d}"


def _next_opportunity_no(db: Session) -> str:
    """Nomor opportunity otomatis OPP-YYYY-NNNNN, urut per tahun."""
    year = datetime.utcnow().strftime("%Y")
    prefix = f"OPP-{year}-"
    last = (db.query(Opportunity.opportunity_no)
            .filter(Opportunity.opportunity_no.like(prefix + "%"))
            .order_by(Opportunity.opportunity_no.desc()).first())
    seq = int(last[0].rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:05d}"


def _validate_source(source: str) -> str:
    value = (source or "").upper()
    if value not in LEAD_SOURCES:
        raise HTTPException(400, f"source harus salah satu dari {', '.join(LEAD_SOURCES)}.")
    return value


def _validate_lead_status(status: str) -> str:
    value = (status or "").upper()
    if value not in LEAD_STATUSES:
        raise HTTPException(400, f"status lead harus salah satu dari {', '.join(LEAD_STATUSES)}.")
    return value


def _validate_stage(stage: str) -> str:
    value = (stage or "").upper()
    if value not in OPPORTUNITY_STAGES:
        raise HTTPException(400, f"stage harus salah satu dari {', '.join(OPPORTUNITY_STAGES)}.")
    return value


def _get_lead(db: Session, lead_id: int) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "Lead tidak ditemukan.")
    return lead


def _get_opportunity(db: Session, opp_id: int) -> Opportunity:
    opp = db.get(Opportunity, opp_id)
    if opp is None:
        raise HTTPException(404, "Opportunity tidak ditemukan.")
    return opp


def _lead_row(db: Session, lead: Lead) -> dict:
    return {
        "id": lead.id, "lead_no": lead.lead_no, "source": lead.source,
        "company_name": lead.company_name, "contact_name": lead.contact_name,
        "phone": lead.phone, "email": lead.email, "city": lead.city,
        "interested_product": lead.interested_product,
        "estimated_value": _num(lead.estimated_value), "status": lead.status,
        "owner_id": lead.owner_id, "owner_name": _owner_name(db, lead.owner_id),
        "next_followup_date": _iso(lead.next_followup_date), "notes": lead.notes,
        "created_at": _iso(lead.created_at), "updated_at": _iso(lead.updated_at),
    }


def _opportunity_row(db: Session, opp: Opportunity) -> dict:
    value = opp.estimated_value or ZERO
    probability = opp.probability_percent or 0
    return {
        "id": opp.id, "opportunity_no": opp.opportunity_no, "lead_id": opp.lead_id,
        "buyer_name": opp.buyer_name, "stage": opp.stage,
        "estimated_value": _num(value), "probability_percent": probability,
        "weighted_value": _num(value * Decimal(probability) / Decimal(100)),
        "expected_close_date": _iso(opp.expected_close_date),
        "owner_id": opp.owner_id, "owner_name": _owner_name(db, opp.owner_id),
        "order_fk": opp.order_fk,
        "order_id": (db.get(models.Order, opp.order_fk).order_id if opp.order_fk else None),
        "converted": opp.order_fk is not None,
        "lost_reason": opp.lost_reason,
        "created_at": _iso(opp.created_at), "updated_at": _iso(opp.updated_at),
    }


def _target_row(db: Session, target: SalesTarget) -> dict:
    return {
        "id": target.id, "period": target.period, "owner_id": target.owner_id,
        "owner_name": target.owner_name or _owner_name(db, target.owner_id),
        "target_amount": _num(target.target_amount),
        "target_orders": target.target_orders, "notes": target.notes,
        "created_at": _iso(target.created_at), "updated_at": _iso(target.updated_at),
    }


def _order_value(db: Session, order: models.Order) -> Decimal:
    """Nilai order = amount quotation APPROVED terakhir (basis revenue CMO)."""
    quote = (db.query(models.Quotation)
             .filter(models.Quotation.order_fk == order.id,
                     models.Quotation.status == "APPROVED")
             .order_by(models.Quotation.id.desc()).first())
    return Decimal(str(quote.amount or 0)) if quote else ZERO


# ── Leads ────────────────────────────────────────────────────────────────────
@router.get("/leads")
def list_leads(status: Optional[str] = None, source: Optional[str] = None,
               owner_id: Optional[int] = None, search: Optional[str] = None,
               limit: int = Query(default=500, le=2000),
               db: Session = Depends(get_db), user=Depends(require_roles(*READ_ROLES))):
    """Daftar lead dengan filter status/source/owner (BLUEPRINT §3.1)."""
    q = db.query(Lead)
    if status:
        q = q.filter(Lead.status == _validate_lead_status(status))
    if source:
        q = q.filter(Lead.source == _validate_source(source))
    if owner_id is not None:
        q = q.filter(Lead.owner_id == owner_id)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(func.lower(Lead.company_name).like(term.lower())
                     | func.lower(Lead.contact_name).like(term.lower()))
    rows = q.order_by(Lead.id.desc()).limit(limit).all()
    return {"total": len(rows), "rows": [_lead_row(db, lead) for lead in rows]}


@router.post("/leads", status_code=201)
def create_lead(data: LeadIn, db: Session = Depends(get_db),
                user=Depends(require_roles(*CRM_WRITE_ROLES))):
    """Catat lead baru; nomor lead digenerate otomatis (LD-YYYY-NNNNN)."""
    source = _validate_source(data.source)
    status = _validate_lead_status(data.status)
    if data.owner_id is not None and db.get(models.User, data.owner_id) is None:
        raise HTTPException(400, "owner_id tidak ditemukan.")
    lead = Lead(lead_no=_next_lead_no(db), source=source,
                company_name=data.company_name.strip(), contact_name=data.contact_name.strip(),
                phone=data.phone.strip(), email=data.email.strip(), city=data.city,
                interested_product=data.interested_product, estimated_value=data.estimated_value,
                status=status, owner_id=data.owner_id,
                next_followup_date=data.next_followup_date, notes=data.notes)
    db.add(lead)
    db.flush()
    log_audit(db, user, "CREATE", "Lead", entity_id=lead.id, obj=lead,
              detail=f"Lead {lead.lead_no} ({lead.company_name}, source={source})",
              new_status=status, reason="Pencatatan lead baru")
    db.commit()
    db.refresh(lead)
    return _lead_row(db, lead)


@router.patch("/leads/{lead_id}")
def update_lead(lead_id: int, data: LeadUpdate, db: Session = Depends(get_db),
                user=Depends(require_roles(*CRM_WRITE_ROLES))):
    lead = _get_lead(db, lead_id)
    previous = lead.status
    payload = data.model_dump(exclude_unset=True)
    if "source" in payload and payload["source"] is not None:
        payload["source"] = _validate_source(payload["source"])
    if "status" in payload and payload["status"] is not None:
        payload["status"] = _validate_lead_status(payload["status"])
    if payload.get("owner_id") is not None and db.get(models.User, payload["owner_id"]) is None:
        raise HTTPException(400, "owner_id tidak ditemukan.")
    for field, value in payload.items():
        setattr(lead, field, value)
    log_audit(db, user, "UPDATE", "Lead", entity_id=lead.id, obj=lead,
              previous_status=previous, new_status=lead.status, reason="Update lead")
    db.commit()
    db.refresh(lead)
    return _lead_row(db, lead)


@router.post("/leads/{lead_id}/convert", status_code=201)
def convert_lead(lead_id: int, data: LeadConvertIn, db: Session = Depends(get_db),
                 user=Depends(require_roles(*CRM_WRITE_ROLES))):
    """Jadikan lead sebuah Opportunity dan tandai lead CONVERTED.

    Guardrail: lead yang sudah CONVERTED tidak boleh dikonversi ulang (409) —
    satu lead menghasilkan tepat satu opportunity.
    """
    lead = _get_lead(db, lead_id)
    if lead.status == "CONVERTED":
        raise HTTPException(409, "Lead ini sudah CONVERTED menjadi opportunity.")
    previous_status = lead.status
    owner_id = data.owner_id if data.owner_id is not None else lead.owner_id
    if owner_id is not None and db.get(models.User, owner_id) is None:
        raise HTTPException(400, "owner_id tidak ditemukan.")
    value = data.estimated_value if data.estimated_value is not None else (lead.estimated_value or ZERO)
    probability = data.probability_percent
    if probability is None:
        probability = DEFAULT_PROBABILITY["PROSPECT"]
    opp = Opportunity(
        opportunity_no=_next_opportunity_no(db), lead_id=lead.id,
        buyer_name=(data.buyer_name or lead.company_name),
        stage="PROSPECT", estimated_value=value, probability_percent=probability,
        expected_close_date=data.expected_close_date, owner_id=owner_id,
    )
    db.add(opp)
    lead.status = "CONVERTED"
    db.flush()
    log_audit(db, user, "CONVERT", "Lead", entity_id=lead.id, obj=lead,
              detail=f"Lead {lead.lead_no} -> Opportunity {opp.opportunity_no}",
              previous_status=previous_status, new_status="CONVERTED",
              reason="Konversi lead menjadi opportunity")
    db.commit()
    db.refresh(opp)
    return {"lead": _lead_row(db, lead), "opportunity": _opportunity_row(db, opp)}


# ── Opportunities ────────────────────────────────────────────────────────────
@router.get("/opportunities")
def list_opportunities(stage: Optional[str] = None, owner_id: Optional[int] = None,
                       lead_id: Optional[int] = None,
                       include_closed: bool = True,
                       limit: int = Query(default=500, le=2000),
                       db: Session = Depends(get_db),
                       user=Depends(require_roles(*READ_ROLES))):
    """Daftar opportunity dengan filter stage (BLUEPRINT §3.2)."""
    q = db.query(Opportunity)
    if stage:
        q = q.filter(Opportunity.stage == _validate_stage(stage))
    elif not include_closed:
        q = q.filter(Opportunity.stage.in_(OPEN_STAGES))
    if owner_id is not None:
        q = q.filter(Opportunity.owner_id == owner_id)
    if lead_id is not None:
        q = q.filter(Opportunity.lead_id == lead_id)
    rows = q.order_by(Opportunity.id.desc()).limit(limit).all()
    return {"total": len(rows), "rows": [_opportunity_row(db, opp) for opp in rows]}


@router.post("/opportunities", status_code=201)
def create_opportunity(data: OpportunityIn, db: Session = Depends(get_db),
                       user=Depends(require_roles(*CRM_WRITE_ROLES))):
    stage = _validate_stage(data.stage)
    if data.lead_id is not None and db.get(Lead, data.lead_id) is None:
        raise HTTPException(400, "lead_id tidak ditemukan.")
    if data.owner_id is not None and db.get(models.User, data.owner_id) is None:
        raise HTTPException(400, "owner_id tidak ditemukan.")
    probability = data.probability_percent
    if probability is None:
        probability = DEFAULT_PROBABILITY.get(stage, 0)
    opp = Opportunity(opportunity_no=_next_opportunity_no(db), lead_id=data.lead_id,
                      buyer_name=data.buyer_name.strip(), stage=stage,
                      estimated_value=data.estimated_value, probability_percent=probability,
                      expected_close_date=data.expected_close_date, owner_id=data.owner_id)
    db.add(opp)
    db.flush()
    log_audit(db, user, "CREATE", "Opportunity", entity_id=opp.id, obj=opp,
              detail=f"Opportunity {opp.opportunity_no} ({opp.buyer_name}, stage={stage})",
              new_status=stage, reason="Pencatatan opportunity baru")
    db.commit()
    db.refresh(opp)
    return _opportunity_row(db, opp)


@router.patch("/opportunities/{opp_id}")
def update_opportunity(opp_id: int, data: OpportunityUpdate, db: Session = Depends(get_db),
                       user=Depends(require_roles(*CRM_WRITE_ROLES))):
    opp = _get_opportunity(db, opp_id)
    if opp.order_fk is not None:
        raise HTTPException(409, "Opportunity yang sudah dikonversi ke order tidak boleh diubah.")
    previous = opp.stage
    payload = data.model_dump(exclude_unset=True)
    if "stage" in payload and payload["stage"] is not None:
        payload["stage"] = _validate_stage(payload["stage"])
    if payload.get("owner_id") is not None and db.get(models.User, payload["owner_id"]) is None:
        raise HTTPException(400, "owner_id tidak ditemukan.")
    for field, value in payload.items():
        setattr(opp, field, value)
    log_audit(db, user, "UPDATE", "Opportunity", entity_id=opp.id, obj=opp,
              previous_status=previous, new_status=opp.stage, reason="Update opportunity")
    db.commit()
    db.refresh(opp)
    return _opportunity_row(db, opp)


@router.post("/opportunities/{opp_id}/win")
def win_opportunity(opp_id: int, db: Session = Depends(get_db),
                    user=Depends(require_roles(*CRM_WRITE_ROLES))):
    """Tandai opportunity WON. Guardrail: nilai harus > 0 (400 kalau tidak)."""
    opp = _get_opportunity(db, opp_id)
    if opp.order_fk is not None:
        raise HTTPException(409, "Opportunity ini sudah dikonversi ke order.")
    if opp.stage == "WON":
        raise HTTPException(409, "Opportunity ini sudah berstatus WON.")
    value = opp.estimated_value or ZERO
    if value <= 0:
        raise HTTPException(400, "Opportunity tidak bisa WON: estimated_value harus > 0.")
    previous = opp.stage
    opp.stage = "WON"
    opp.probability_percent = 100
    log_audit(db, user, "WIN", "Opportunity", entity_id=opp.id, obj=opp,
              detail=f"Opportunity {opp.opportunity_no} won (nilai {value})",
              previous_status=previous, new_status="WON", reason="Opportunity dimenangkan")
    db.commit()
    db.refresh(opp)
    return _opportunity_row(db, opp)


@router.post("/opportunities/{opp_id}/lose")
def lose_opportunity(opp_id: int, data: LoseIn, db: Session = Depends(get_db),
                     user=Depends(require_roles(*CRM_WRITE_ROLES))):
    """Tandai opportunity LOST. Guardrail: lost_reason wajib (400 kalau kosong)."""
    opp = _get_opportunity(db, opp_id)
    if opp.order_fk is not None:
        raise HTTPException(409, "Opportunity ini sudah dikonversi ke order.")
    reason = (data.lost_reason or "").strip()
    if not reason:
        raise HTTPException(400, "lost_reason wajib diisi saat opportunity ditandai LOST.")
    previous = opp.stage
    opp.stage = "LOST"
    opp.probability_percent = 0
    opp.lost_reason = reason
    log_audit(db, user, "LOSE", "Opportunity", entity_id=opp.id, obj=opp,
              detail=f"Opportunity {opp.opportunity_no} lost: {reason}",
              previous_status=previous, new_status="LOST", reason=reason)
    db.commit()
    db.refresh(opp)
    return _opportunity_row(db, opp)


@router.post("/opportunities/{opp_id}/convert-to-order")
def convert_to_order(opp_id: int, data: ConvertToOrderIn, db: Session = Depends(get_db),
                     user=Depends(require_roles(*CRM_WRITE_ROLES))):
    """Tautkan opportunity ke Order nyata dan tandai ``order_fk``.

    Guardrail: opportunity yang sudah CONVERTED (``order_fk`` terisi) atau sudah
    WON ditolak (409) — satu peluang hanya boleh menghasilkan satu order.
    """
    opp = _get_opportunity(db, opp_id)
    if opp.order_fk is not None:
        raise HTTPException(409, "Opportunity ini sudah dikonversi ke order.")
    if opp.stage == "WON":
        raise HTTPException(409, "Opportunity berstatus WON. Gunakan order_fk lewat WON flow, bukan convert ulang.")
    order = db.get(models.Order, data.order_id)
    if order is None:
        raise HTTPException(400, "order_id tidak ditemukan.")
    # Satu order tidak boleh mewakili dua opportunity.
    existing = db.query(Opportunity).filter(Opportunity.order_fk == order.id).first()
    if existing is not None:
        raise HTTPException(409, f"Order {order.order_id} sudah tertaut ke opportunity {existing.opportunity_no}.")
    previous = opp.stage
    opp.order_fk = order.id
    opp.stage = "WON"
    opp.probability_percent = 100
    log_audit(db, user, "CONVERT_TO_ORDER", "Opportunity", entity_id=opp.id, obj=opp,
              detail=f"Opportunity {opp.opportunity_no} -> Order {order.order_id}",
              previous_status=previous, new_status="WON", reason="Konversi opportunity menjadi order")
    db.commit()
    db.refresh(opp)
    return _opportunity_row(db, opp)


# ── Sales Target ─────────────────────────────────────────────────────────────
@router.get("/sales-targets")
def list_sales_targets(period: Optional[str] = None, owner_id: Optional[int] = None,
                       db: Session = Depends(get_db),
                       user=Depends(require_roles(*READ_ROLES))):
    """Daftar sales target; filter periode (YYYY-MM) dan PIC."""
    q = db.query(SalesTarget)
    if period:
        q = q.filter(SalesTarget.period == period)
    if owner_id is not None:
        q = q.filter(SalesTarget.owner_id == owner_id)
    rows = q.order_by(SalesTarget.period.desc(), SalesTarget.id.desc()).all()
    return {"total": len(rows), "rows": [_target_row(db, t) for t in rows]}


@router.post("/sales-targets", status_code=201)
def upsert_sales_target(data: SalesTargetIn, db: Session = Depends(get_db),
                        user=Depends(require_roles(*TARGET_WRITE_ROLES))):
    """Upsert target per (period, owner_id) — satu target per periode per PIC.

    Menulis periode+PIC yang sudah ada berarti MEMBARUI baris itu (mengembalikan
    status 201 dengan ``updated=True``), bukan membuat baris kedua.
    """
    period = (data.period or "").strip()
    # Validasi bentuk YYYY-MM supaya periode tidak bocor sebagai teks bebas.
    try:
        datetime.strptime(period, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "period harus berformat YYYY-MM.")
    if data.owner_id is not None and db.get(models.User, data.owner_id) is None:
        raise HTTPException(400, "owner_id tidak ditemukan.")
    owner_name = data.owner_name or _owner_name(db, data.owner_id)

    target = (db.query(SalesTarget)
              .filter(SalesTarget.period == period, SalesTarget.owner_id == data.owner_id)
              .first())
    updated = target is not None
    if target is None:
        target = SalesTarget(period=period, owner_id=data.owner_id)
        db.add(target)
    target.owner_name = owner_name
    target.target_amount = data.target_amount
    target.target_orders = data.target_orders
    target.notes = data.notes
    db.flush()
    log_audit(db, user, "UPSERT", "SalesTarget", entity_id=target.id, obj=target,
              detail=f"Target {period} ({owner_name or 'tanpa PIC'}) = {data.target_amount}",
              reason="Update target penjualan" if updated else "Set target penjualan")
    db.commit()
    db.refresh(target)
    row = _target_row(db, target)
    row["updated"] = updated
    return row


# ── Dashboard: pipeline summary ──────────────────────────────────────────────
@router.get("/pipeline-summary")
def pipeline_summary(period: Optional[str] = None, db: Session = Depends(get_db),
                     user=Depends(require_roles(*READ_ROLES))):
    """Ringkasan pipeline dari LEAD/PROSPEK (BLUEPRINT §3.2).

    Mengembalikan: total & weighted value per stage, jumlah lead baru, konversi
    lead -> opportunity -> WON, serta target vs aktual (dari order yang sudah ada)
    per periode. Aktual dihitung dari quotation APPROVED order pada periode itu.
    """
    period = period or date.today().strftime("%Y-%m")

    leads = db.query(Lead).all()
    opps = db.query(Opportunity).all()

    # 1. Agregasi per stage: jumlah, total nilai, weighted value.
    stages = []
    for stage in OPPORTUNITY_STAGES:
        rows = [o for o in opps if o.stage == stage]
        total_value = sum((o.estimated_value or ZERO) for o in rows)
        weighted = sum((o.estimated_value or ZERO) * Decimal(o.probability_percent or 0) / Decimal(100)
                       for o in rows)
        stages.append({
            "stage": stage, "count": len(rows),
            "total_value": _num(total_value), "weighted_value": _num(weighted),
        })
    open_value = sum((o.estimated_value or ZERO) for o in opps if o.stage in OPEN_STAGES)
    open_weighted = sum((o.estimated_value or ZERO) * Decimal(o.probability_percent or 0) / Decimal(100)
                        for o in opps if o.stage in OPEN_STAGES)

    # 2. Funnel konversi lead -> opportunity -> WON.
    converted_leads = sum(1 for lead in leads if lead.status == "CONVERTED")
    won_opps = sum(1 for o in opps if o.stage == "WON")
    lead_to_opp = round(converted_leads / len(leads) * 100, 1) if leads else None
    opp_to_won = round(won_opps / len(opps) * 100, 1) if opps else None

    # Lead baru = dibuat pada periode terpilih (kontribusi kanal bulan ini).
    new_leads = [lead for lead in leads if lead.created_at and _period_of(None, lead.created_at.date()) == period]

    # 3. Target vs aktual dari order yang sudah ada pada periode terpilih.
    targets = db.query(SalesTarget).filter(SalesTarget.period == period).all()
    orders = db.query(models.Order).all()
    actual_amount = ZERO
    actual_orders = 0
    for order in orders:
        order_date = order.order_date
        if order_date is None or _period_of(order_date) != period:
            continue
        actual_orders += 1
        actual_amount += _order_value(db, order)
    target_amount = sum((t.target_amount or ZERO) for t in targets)
    attainment = (float(actual_amount) / float(target_amount) * 100) if target_amount else None
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "leads": {
            "total": len(leads), "new_in_period": len(new_leads),
            "converted": converted_leads, "lead_to_opportunity_percent": lead_to_opp,
        },
        "opportunities": {
            "total": len(opps), "won": won_opps,
            "opportunity_to_won_percent": opp_to_won,
            "open_value": _num(open_value), "open_weighted_value": _num(open_weighted),
            "stages": stages,
        },
        "sales_target": {
            "period": period,
            "target_amount": _num(target_amount),
            "target_orders": sum(t.target_orders or 0 for t in targets),
            "target_count": len(targets),
            "actual_amount": _num(actual_amount),
            "actual_orders": actual_orders,
            "attainment_percent": round(attainment, 1) if attainment is not None else None,
            "note": "Aktual dihitung dari quotation APPROVED atas order pada periode tersebut.",
        },
    }
