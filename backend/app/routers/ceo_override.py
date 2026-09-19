"""CEO Override Governance — registry override terkontrol (revisi #74).

Blueprint CEO-I-005 meminta empat batas override yang tepat:

======================  ==========================  ==============================
Tipe                    Pemutus                     Catatan
======================  ==========================  ==============================
``PRODUCTION_PRIORITY`` CEO                         satu-satunya override yang boleh
                                                    diputus CEO sendiri
``PRICING_EXCEPTION``   CFO (final), CEO informed   CEO hanya diberi tahu
``SHIPMENT_OUTSTANDING`` CEO                        wajib persetujuan CEO
``PURCHASING_EXCEPTION`` CFO / Riadi (kasus khusus) CEO hanya melihat
======================  ==========================  ==============================

Setiap override menyimpan Override ID/tipe, sumber, entitas terdampak, nilai
asal, nilai/usulan, requester, alasan, dampak, bukti, scope, berlaku/kedaluwarsa,
keputusan CEO, acknowledgement owner, rollback/koreksi, dan audit — persis
daftar yang diminta revisi #74.

Router ini **tidak** menyediakan endpoint pembuatan/ubah PO, invoice, delivery,
closing, atau BOM. Override hanya mengubah DIRI SENDIRI (registry), bukan
transaksi operasional — dan hanya pada scope yang dideklarasikan.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..auth import require_roles
from ..database import get_db
from ..models import Role, User
from ..workflow import commit_changes

router = APIRouter(prefix="/ceo", tags=["ceo-overrides"])

OverrideType = Literal[
    "PRODUCTION_PRIORITY",
    "PRICING_EXCEPTION",
    "SHIPMENT_OUTSTANDING",
    "PURCHASING_EXCEPTION",
]

# Siapa yang boleh MEMUTUS tiap tipe. `informed` = hanya diberi tahu.
OVERRIDE_GOVERNANCE = {
    "PRODUCTION_PRIORITY": {"decider": "CEO", "informed": [], "ceo_decides": True},
    "PRICING_EXCEPTION": {"decider": "CFO_MANAGER", "informed": ["CEO"], "ceo_decides": False},
    "SHIPMENT_OUTSTANDING": {"decider": "CEO", "informed": ["CFO_MANAGER", "COO_MANAGER"], "ceo_decides": True},
    "PURCHASING_EXCEPTION": {"decider": "CFO_MANAGER", "informed": ["CEO"], "ceo_decides": False},
}

OVERRIDE_TABLE = "ceo_overrides"


def _has_table(db: Session, name: str) -> bool:
    from sqlalchemy import inspect
    try:
        return name in inspect(db.get_bind()).get_table_names()
    except Exception:
        return False


def _table_missing() -> HTTPException:
    return HTTPException(
        503,
        "Tabel ceo_overrides belum ada — override tidak boleh berjalan tanpa jejak "
        "audit/rollback. Spesifikasi ada di REQUESTS/ceo_override.md.",
    )


class OverrideIn(PydanticBaseModel):
    """Permintaan override.

    ``extra="forbid"`` memastikan payload tidak bisa menyelundupkan kolom
    transaksi operasional (mis. ``invoice_id``, ``po_id``) ke registry.
    """
    model_config = ConfigDict(extra="forbid")

    override_type: OverrideType
    source_module: str = Field(min_length=2, max_length=80)
    source_entity: str = Field(min_length=2, max_length=80)
    source_entity_id: Optional[int] = None
    affected_entity: str = Field(min_length=2, max_length=160)
    original_value: str = Field(min_length=1, max_length=2000)
    proposed_value: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=5, max_length=2000)
    impact: str = Field(min_length=2, max_length=2000)
    evidence_ref: Optional[str] = Field(default=None, max_length=500)
    scope: str = Field(min_length=2, max_length=300)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class OverrideDecision(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=5, max_length=2000)


class OverrideRollback(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=5, max_length=2000)
    correction_note: str = Field(min_length=5, max_length=2000)


def _serialise(row) -> dict:
    return {
        "id": row.id,
        "override_no": row.override_no,
        "override_type": row.override_type,
        "governance": OVERRIDE_GOVERNANCE.get(row.override_type),
        "status": row.status,
        "source_module": row.source_module,
        "source_entity": row.source_entity,
        "source_entity_id": row.source_entity_id,
        "affected_entity": row.affected_entity,
        "original_value": row.original_value,
        "proposed_value": row.proposed_value,
        "requester_id": row.requester_id,
        "reason": row.reason,
        "impact": row.impact,
        "evidence_ref": row.evidence_ref,
        "scope": row.scope,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "ceo_decision": row.ceo_decision,
        "ceo_decision_reason": row.ceo_decision_reason,
        "ceo_decided_by_id": row.ceo_decided_by_id,
        "ceo_decided_at": row.ceo_decided_at.isoformat() if row.ceo_decided_at else None,
        "acknowledged_by_id": row.acknowledged_by_id,
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        "rolled_back_at": row.rolled_back_at.isoformat() if row.rolled_back_at else None,
        "rollback_reason": row.rollback_reason,
        "correction_note": row.correction_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "is_active": bool(row.ceo_decision == "APPROVED" and not row.rolled_back_at
                          and (not row.effective_to or row.effective_to >= date.today())),
    }


@router.get("/overrides")
def list_overrides(override_type: Optional[OverrideType] = None,
                   active_only: bool = False,
                   db: Session = Depends(get_db),
                   user=Depends(require_roles(Role.CEO, Role.CFO_MANAGER, Role.COO_MANAGER))):
    """Daftar override. CEO melihat semua; CFO/COO hanya tipe diwilayahnya."""
    from .. import models
    if not _has_table(db, OVERRIDE_TABLE):
        # Belum ada tabel: kembalikan registry kosong + kontrak governance,
        # supaya halaman CEO tetap bisa menampilkan batas override yang sah.
        return {"items": [], "governance": OVERRIDE_GOVERNANCE,
                "migration_pending": True,
                "note": "Tabel ceo_overrides belum dimigrasi; lihat REQUESTS/ceo_override.md."}
    Override = getattr(models, "CEOOverride")
    query = db.query(Override)
    role = user.role.value
    if role != "CEO":
        allowed = [t for t, g in OVERRIDE_GOVERNANCE.items() if g["decider"] == role]
        query = query.filter(Override.override_type.in_(allowed))
    if override_type:
        query = query.filter(Override.override_type == override_type)
    rows = query.order_by(Override.id.desc()).all()
    if active_only:
        # Hanya override yang benar-benar BERLAKU: sudah disetujui, belum
        # di-rollback, dan masih dalam masa efektif. Baris REQUESTED belum
        # mengubah apa pun, jadi tidak boleh terhitung aktif.
        rows = [r for r in rows if r.ceo_decision == "APPROVED"
                and not r.rolled_back_at
                and (not r.effective_to or r.effective_to >= date.today())]
    return {"items": [_serialise(r) for r in rows], "governance": OVERRIDE_GOVERNANCE,
            "migration_pending": False}


@router.post("/overrides", status_code=201)
def request_override(data: OverrideIn, db: Session = Depends(get_db),
                     user=Depends(require_roles(Role.CEO, Role.CFO_MANAGER, Role.COO_MANAGER))):
    """Ajukan override. Pemutus tipe tertentu tetap dibatasi governance."""
    from .. import models
    if not _has_table(db, OVERRIDE_TABLE):
        raise _table_missing()
    Override = getattr(models, "CEOOverride")
    if data.effective_to and data.effective_from and data.effective_to < data.effective_from:
        raise HTTPException(400, "effective_to tidak boleh sebelum effective_from.")
    row = Override(
        override_type=data.override_type,
        source_module=data.source_module, source_entity=data.source_entity,
        source_entity_id=data.source_entity_id, affected_entity=data.affected_entity,
        original_value=data.original_value, proposed_value=data.proposed_value,
        requester_id=user.id, reason=data.reason, impact=data.impact,
        evidence_ref=data.evidence_ref, scope=data.scope,
        effective_from=data.effective_from or date.today(),
        effective_to=data.effective_to, status="REQUESTED",
    )
    db.add(row)
    db.flush()
    row.override_no = f"OVR-{row.id:05d}"
    log_audit(db, user, "OVERRIDE_REQUEST", "CEOOverride", row.id,
              f"{data.override_type}: {data.affected_entity} ({data.original_value} -> "
              f"{data.proposed_value}); scope={data.scope}",
              source_module="CEOOverride", previous_status=None, new_status="REQUESTED",
              reason=data.reason)
    commit_changes(db, user)
    db.refresh(row)
    return _serialise(row)


@router.post("/overrides/{override_id}/decide")
def decide_override(override_id: int, data: OverrideDecision, db: Session = Depends(get_db),
                    user=Depends(require_roles(Role.CEO, Role.CFO_MANAGER))):
    """Putuskan override — hanya pemutus yang ditetapkan governance #74."""
    from .. import models
    if not _has_table(db, OVERRIDE_TABLE):
        raise _table_missing()
    Override = getattr(models, "CEOOverride")
    row = db.query(Override).filter_by(id=override_id).with_for_update().first()
    if row is None:
        raise HTTPException(404, "Override not found")
    governance = OVERRIDE_GOVERNANCE.get(row.override_type, {})
    decider = governance.get("decider")
    if user.role.value != decider:
        raise HTTPException(
            403,
            f"{row.override_type} diputus oleh {decider}; "
            f"{user.role.value} tidak berwenang memutus override ini.")
    if row.ceo_decision:
        raise HTTPException(409, "Override ini sudah diputuskan.")
    if row.rolled_back_at:
        raise HTTPException(409, "Override sudah di-rollback.")
    previous = row.status
    row.ceo_decision = data.decision
    row.ceo_decision_reason = data.reason
    row.ceo_decided_by_id = user.id
    row.ceo_decided_at = datetime.utcnow()
    row.status = "APPROVED" if data.decision == "APPROVED" else "REJECTED"
    log_audit(db, user, "OVERRIDE_DECIDE", "CEOOverride", row.id,
              f"{row.override_type} {data.decision}: {row.reason}",
              source_module="CEOOverride", previous_status=previous,
              new_status=row.status, reason=data.reason)
    commit_changes(db, user)
    db.refresh(row)
    return _serialise(row)


@router.post("/overrides/{override_id}/acknowledge")
def acknowledge_override(override_id: int, db: Session = Depends(get_db),
                         user=Depends(require_roles(Role.CEO, Role.CFO_MANAGER, Role.COO_MANAGER))):
    """Owner menandai sudah menerima keputusan override (acknowledgement owner)."""
    from .. import models
    if not _has_table(db, OVERRIDE_TABLE):
        raise _table_missing()
    Override = getattr(models, "CEOOverride")
    row = db.query(Override).filter_by(id=override_id).with_for_update().first()
    if row is None:
        raise HTTPException(404, "Override not found")
    if row.status not in ("APPROVED", "REJECTED"):
        raise HTTPException(409, "Override belum diputuskan.")
    row.acknowledged_by_id = user.id
    row.acknowledged_at = datetime.utcnow()
    log_audit(db, user, "OVERRIDE_ACKNOWLEDGE", "CEOOverride", row.id,
              f"{row.override_type} acknowledged oleh {user.role.value}",
              source_module="CEOOverride", new_status=row.status)
    commit_changes(db, user)
    db.refresh(row)
    return _serialise(row)


@router.post("/overrides/{override_id}/rollback")
def rollback_override(override_id: int, data: OverrideRollback, db: Session = Depends(get_db),
                      user=Depends(require_roles(Role.CEO))):
    """Rollback/koreksi override yang sudah berjalan (tanpa hard delete)."""
    from .. import models
    if not _has_table(db, OVERRIDE_TABLE):
        raise _table_missing()
    Override = getattr(models, "CEOOverride")
    row = db.query(Override).filter_by(id=override_id).with_for_update().first()
    if row is None:
        raise HTTPException(404, "Override not found")
    if row.rolled_back_at:
        raise HTTPException(409, "Override sudah di-rollback.")
    row.rolled_back_at = datetime.utcnow()
    row.rollback_reason = data.reason
    row.correction_note = data.correction_note
    row.status = "ROLLED_BACK"
    log_audit(db, user, "OVERRIDE_ROLLBACK", "CEOOverride", row.id,
              f"{row.override_type} rollback: {data.correction_note}",
              source_module="CEOOverride", previous_status="APPROVED",
              new_status="ROLLED_BACK", reason=data.reason)
    commit_changes(db, user)
    db.refresh(row)
    return _serialise(row)
