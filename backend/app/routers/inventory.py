"""Router inventory/purchasing — workspace Riadi (BLUEPRINT §3.4 & PRD §6).

Aturan keras yang ditegakkan DI SINI (bukan cuma di UI):

- **Saldo stok adalah turunan.** Tidak ada endpoint yang menulis saldo langsung;
  semuanya lewat `stock_movements` dan saldo dihitung `sum(inbound) - sum(outbound)`.
- **Stok tidak boleh negatif.** Movement keluar yang melebihi saldo ditolak 400.
- **ADJUSTMENT wajib beralasan.** Tanpa `reason`, penyesuaian ditolak 400 — kalau
  tidak, siapa pun bisa menghapus selisih stok tanpa jejak.
- **Goods Receipt idempotent.** Posting yang sama dua kali ditolak 409 supaya stok
  tidak tergandakan.
- **Material Gate punya pelaku + waktu.** `release` hanya COO_MANAGER; keputusan
  gate selalu tercatat.

Hak akses:
- Baca  : semua user terautentikasi.
- Tulis master (supplier/location/material): COO_MANAGER + PRODUCTION_PIC.
- Approve PR & posting GR & keputusan gate: COO_MANAGER + CFO_MANAGER.
- Release gate: COO_MANAGER saja.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user, require_roles
from ..audit import log_audit
from .. import models
from ..inventory_models import (Supplier, InventoryLocation, Material, StockMovement,
                                PurchaseRequest, PurchaseRequestLine, GoodsReceipt,
                                GoodsReceiptLine, MaterialGate,
                                INBOUND_TYPES, OUTBOUND_TYPES, ALL_MOVEMENT_TYPES)

router = APIRouter(prefix="/inventory", tags=["inventory"])

# Master data (supplier/location/material) boleh ditulis Riadi & PIC produksi,
# karena merekalah yang mengurus data fisik gudang.
MASTER_WRITE_ROLES = (models.Role.COO_MANAGER, models.Role.PRODUCTION_PIC)
# Approve PR / posting GR / keputusan gate adalah keputusan lintas fungsi (belanja
# vs produksi), jadi butuh COO + CFO.
APPROVE_ROLES = (models.Role.COO_MANAGER, models.Role.CFO_MANAGER)


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")


def _dec(value) -> Decimal:
    return Decimal(str(value if value is not None else 0))


# ── Penomoran dokumen ─────────────────────────────────────────────────────────
def _next_no(db: Session, model, column, prefix: str) -> str:
    """Nomor dokumen berurut per tahun: PREFIX-YYYY-00001."""
    year = date.today().year
    full = f"{prefix}-{year}-"
    last = (db.query(column)
            .filter(column.like(full + "%"))
            .order_by(column.desc()).first())
    seq = int(last[0].split("-")[-1]) + 1 if last else 1
    return f"{full}{seq:05d}"


def next_pr_no(db: Session) -> str:
    return _next_no(db, PurchaseRequest, PurchaseRequest.pr_no, "PR")


def next_gr_no(db: Session) -> str:
    return _next_no(db, GoodsReceipt, GoodsReceipt.gr_no, "GR")


def next_po_no(db: Session) -> str:
    return _next_no(db, models.PurchaseOrder, models.PurchaseOrder.po_no, "PO")


# ── Perhitungan saldo (SATU-SATUNYA sumber kebenaran) ─────────────────────────
def balance_of(db: Session, material_id: int, location_id: int) -> Decimal:
    """Saldo = sum(inbound) - sum(outbound) untuk satu material di satu lokasi."""
    rows = db.query(StockMovement.movement_type, func.coalesce(func.sum(StockMovement.qty), 0)) \
        .filter(StockMovement.material_id == material_id,
                StockMovement.location_id == location_id) \
        .group_by(StockMovement.movement_type).all()
    total = Decimal(0)
    for mtype, qty in rows:
        if mtype in INBOUND_TYPES:
            total += _dec(qty)
        elif mtype in OUTBOUND_TYPES:
            total -= _dec(qty)
    return total


# ══════════════════════════════════════════════════════════════════════════════
# SUPPLIERS
# ══════════════════════════════════════════════════════════════════════════════
class SupplierIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=180)
    vendor_type: Literal["SUPPLIER", "MAKLOON", "LOGISTIK"] = "SUPPLIER"
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    payment_terms: Optional[str] = None
    lead_time_days: Optional[int] = None
    notes: Optional[str] = None


class SupplierUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=180)
    vendor_type: Optional[Literal["SUPPLIER", "MAKLOON", "LOGISTIK"]] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    payment_terms: Optional[str] = None
    lead_time_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


def _supplier_dict(s: Supplier) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "vendor_type": s.vendor_type,
            "contact_person": s.contact_person, "phone": s.phone, "email": s.email,
            "address": s.address, "payment_terms": s.payment_terms,
            "lead_time_days": s.lead_time_days, "is_active": s.is_active, "notes": s.notes}


@router.get("/suppliers")
def list_suppliers(active_only: bool = False, vendor_type: Optional[str] = None,
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(Supplier)
    if active_only:
        q = q.filter(Supplier.is_active.is_(True))
    if vendor_type:
        q = q.filter(Supplier.vendor_type == vendor_type)
    return [_supplier_dict(s) for s in q.order_by(Supplier.code).all()]


@router.post("/suppliers", status_code=201)
def create_supplier(data: SupplierIn, db: Session = Depends(get_db),
                    user=Depends(require_roles(*MASTER_WRITE_ROLES))):
    if db.query(Supplier).filter_by(code=data.code).first():
        raise HTTPException(409, f"Supplier dengan kode '{data.code}' sudah ada.")
    s = Supplier(**data.model_dump())
    db.add(s)
    log_audit(db, user, "CREATE", "Supplier", obj=s, detail=f"Supplier {data.code} - {data.name}",
              new_status="ACTIVE", reason="Registrasi supplier baru")
    db.commit()
    db.refresh(s)
    return _supplier_dict(s)


@router.patch("/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, data: SupplierUpdate, db: Session = Depends(get_db),
                    user=Depends(require_roles(*MASTER_WRITE_ROLES))):
    s = db.get(Supplier, supplier_id)
    if s is None:
        raise HTTPException(404, "Supplier tidak ditemukan.")
    for field, val in data.model_dump(exclude_unset=True).items():
        if val is not None:
            setattr(s, field, val)
    log_audit(db, user, "UPDATE", "Supplier", entity_id=s.id, obj=s, reason="Update supplier")
    db.commit()
    return _supplier_dict(s)


# ══════════════════════════════════════════════════════════════════════════════
# LOCATIONS
# ══════════════════════════════════════════════════════════════════════════════
class LocationIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=180)
    location_type: Literal["WAREHOUSE", "STAGING", "QUARANTINE", "PRODUCTION"] = "WAREHOUSE"


def _location_dict(l: InventoryLocation) -> dict:
    return {"id": l.id, "code": l.code, "name": l.name,
            "location_type": l.location_type, "is_active": l.is_active}


@router.get("/locations")
def list_locations(active_only: bool = False, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    q = db.query(InventoryLocation)
    if active_only:
        q = q.filter(InventoryLocation.is_active.is_(True))
    return [_location_dict(l) for l in q.order_by(InventoryLocation.code).all()]


@router.post("/locations", status_code=201)
def create_location(data: LocationIn, db: Session = Depends(get_db),
                    user=Depends(require_roles(*MASTER_WRITE_ROLES))):
    if db.query(InventoryLocation).filter_by(code=data.code).first():
        raise HTTPException(409, f"Lokasi dengan kode '{data.code}' sudah ada.")
    l = InventoryLocation(**data.model_dump())
    db.add(l)
    log_audit(db, user, "CREATE", "InventoryLocation", obj=l,
              detail=f"Lokasi {data.code} - {data.name}", new_status="ACTIVE",
              reason="Registrasi lokasi gudang")
    db.commit()
    db.refresh(l)
    return _location_dict(l)


# ══════════════════════════════════════════════════════════════════════════════
# MATERIALS
# ══════════════════════════════════════════════════════════════════════════════
class MaterialIn(BaseModel):
    code: str = Field(min_length=2, max_length=60)
    name: str = Field(min_length=2, max_length=200)
    category: Optional[str] = None
    unit: str = Field(default="pcs", min_length=1, max_length=40)
    min_stock: Decimal = Field(default=Decimal(0), ge=0)
    reorder_point: Decimal = Field(default=Decimal(0), ge=0)
    standard_cost: Decimal = Field(default=Decimal(0), ge=0)
    default_supplier_id: Optional[int] = None
    default_location_id: Optional[int] = None
    notes: Optional[str] = None


class MaterialUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    category: Optional[str] = None
    unit: Optional[str] = Field(default=None, min_length=1, max_length=40)
    min_stock: Optional[Decimal] = Field(default=None, ge=0)
    reorder_point: Optional[Decimal] = Field(default=None, ge=0)
    standard_cost: Optional[Decimal] = Field(default=None, ge=0)
    default_supplier_id: Optional[int] = None
    default_location_id: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


def _material_dict(m: Material) -> dict:
    return {"id": m.id, "code": m.code, "name": m.name, "category": m.category,
            "unit": m.unit, "min_stock": float(m.min_stock), "reorder_point": float(m.reorder_point),
            "standard_cost": float(m.standard_cost), "default_supplier_id": m.default_supplier_id,
            "default_location_id": m.default_location_id, "is_active": m.is_active, "notes": m.notes}


@router.get("/materials")
def list_materials(category: Optional[str] = None, active: Optional[bool] = None,
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(Material)
    if category:
        q = q.filter(Material.category == category)
    if active is not None:
        q = q.filter(Material.is_active.is_(active))
    return [_material_dict(m) for m in q.order_by(Material.code).all()]


@router.post("/materials", status_code=201)
def create_material(data: MaterialIn, db: Session = Depends(get_db),
                    user=Depends(require_roles(*MASTER_WRITE_ROLES))):
    if db.query(Material).filter_by(code=data.code).first():
        raise HTTPException(409, f"Material dengan kode '{data.code}' sudah ada.")
    if data.default_supplier_id and db.get(Supplier, data.default_supplier_id) is None:
        raise HTTPException(400, "default_supplier_id tidak ditemukan.")
    if data.default_location_id and db.get(InventoryLocation, data.default_location_id) is None:
        raise HTTPException(400, "default_location_id tidak ditemukan.")
    m = Material(**data.model_dump())
    db.add(m)
    log_audit(db, user, "CREATE", "Material", obj=m, detail=f"Material {data.code} - {data.name}",
              new_status="ACTIVE", reason="Registrasi material baru")
    db.commit()
    db.refresh(m)
    return _material_dict(m)


@router.patch("/materials/{material_id}")
def update_material(material_id: int, data: MaterialUpdate, db: Session = Depends(get_db),
                    user=Depends(require_roles(*MASTER_WRITE_ROLES))):
    m = db.get(Material, material_id)
    if m is None:
        raise HTTPException(404, "Material tidak ditemukan.")
    for field, val in data.model_dump(exclude_unset=True).items():
        if val is not None:
            setattr(m, field, val)
    log_audit(db, user, "UPDATE", "Material", entity_id=m.id, obj=m, reason="Update material")
    db.commit()
    return _material_dict(m)


# ══════════════════════════════════════════════════════════════════════════════
# STOCK & MOVEMENTS
# ══════════════════════════════════════════════════════════════════════════════
class MovementIn(BaseModel):
    material_id: int
    location_id: int
    movement_type: Literal["RECEIPT", "RETURN", "ADJUSTMENT_IN", "TRANSFER_IN", "PRODUCTION_RETURN",
                           "ISSUE", "ALLOCATION_ISSUE", "TRANSFER_OUT", "SCRAP", "ADJUSTMENT_OUT"]
    qty: Decimal = Field(gt=0)
    unit_cost: Optional[Decimal] = Field(default=None, ge=0)
    order_fk: Optional[int] = None
    article_id: Optional[int] = None
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    reference_no: Optional[str] = None
    reason: Optional[str] = None


def _stock_rows(db: Session, material_id: Optional[int] = None) -> list:
    """Saldo per material per lokasi dari stock_movements (satu query agregat)."""
    q = db.query(StockMovement.material_id, StockMovement.location_id,
                 StockMovement.movement_type,
                 func.coalesce(func.sum(StockMovement.qty), 0)) \
        .group_by(StockMovement.material_id, StockMovement.location_id, StockMovement.movement_type)
    if material_id is not None:
        q = q.filter(StockMovement.material_id == material_id)
    acc = {}
    for mid, lid, mtype, qty in q.all():
        key = (mid, lid)
        if key not in acc:
            acc[key] = {"material_id": mid, "location_id": lid, "qty": Decimal(0)}
        if mtype in INBOUND_TYPES:
            acc[key]["qty"] += _dec(qty)
        elif mtype in OUTBOUND_TYPES:
            acc[key]["qty"] -= _dec(qty)
    return list(acc.values())


@router.get("/stock")
def get_stock(material_id: Optional[int] = None, location_id: Optional[int] = None,
              db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = _stock_rows(db, material_id)
    if location_id is not None:
        rows = [r for r in rows if r["location_id"] == location_id]
    mmat = {m.id: m for m in db.query(Material).all()}
    mloc = {l.id: l for l in db.query(InventoryLocation).all()}
    out = []
    for r in rows:
        m = mmat.get(r["material_id"])
        l = mloc.get(r["location_id"])
        out.append({
            "material_id": r["material_id"],
            "material_code": m.code if m else None,
            "material_name": m.name if m else None,
            "category": m.category if m else None,
            "unit": m.unit if m else None,
            "location_id": r["location_id"],
            "location_code": l.code if l else None,
            "location_name": l.name if l else None,
            "qty": float(r["qty"]),
            "reorder_point": float(m.reorder_point) if m else 0,
            "min_stock": float(m.min_stock) if m else 0,
            "below_reorder": bool(m and r["qty"] < _dec(m.reorder_point)),
        })
    out.sort(key=lambda r: (r["material_code"] or "", r["location_code"] or ""))
    return out


@router.get("/stock/low")
def get_low_stock(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Material yang saldo totalnya di bawah reorder_point (agregat seluruh lokasi)."""
    rows = _stock_rows(db)
    mmat = {m.id: m for m in db.query(Material).all()}
    total = {}
    for r in rows:
        total[r["material_id"]] = total.get(r["material_id"], Decimal(0)) + r["qty"]
    out = []
    for mid, m in mmat.items():
        if not m.is_active:
            continue
        bal = total.get(mid, Decimal(0))
        if bal < _dec(m.reorder_point):
            out.append({
                "material_id": mid, "material_code": m.code, "material_name": m.name,
                "category": m.category, "unit": m.unit, "qty": float(bal),
                "reorder_point": float(m.reorder_point), "min_stock": float(m.min_stock),
                "shortage": float(_dec(m.reorder_point) - bal),
                "default_supplier_id": m.default_supplier_id,
            })
    out.sort(key=lambda r: r["shortage"], reverse=True)
    return out


@router.post("/movements", status_code=201)
def create_movement(data: MovementIn, db: Session = Depends(get_db),
                    user=Depends(require_roles(*(MASTER_WRITE_ROLES + APPROVE_ROLES)))):
    if data.movement_type not in ALL_MOVEMENT_TYPES:
        raise HTTPException(400, f"movement_type '{data.movement_type}' tidak dikenal.")
    if db.get(Material, data.material_id) is None:
        raise HTTPException(400, "Material tidak ditemukan.")
    if db.get(InventoryLocation, data.location_id) is None:
        raise HTTPException(400, "Lokasi tidak ditemukan.")
    # ADJUSTMENT adalah satu-satunya jalur yang bisa menyentuh stok tanpa dokumen
    # pendukung; karena itu wajib beralasan (PRD §2 — tak ada perubahan tanpa jejak).
    if data.movement_type.startswith("ADJUSTMENT") and not (data.reason or "").strip():
        raise HTTPException(400, "Movement ADJUSTMENT wajib menyertakan reason.")
    if data.movement_type in OUTBOUND_TYPES:
        bal = balance_of(db, data.material_id, data.location_id)
        if _dec(data.qty) > bal:
            raise HTTPException(
                400, f"Stok tidak cukup: saldo {bal} < qty keluar {data.qty} "
                     f"(material {data.material_id}, lokasi {data.location_id}).")
    mv = StockMovement(material_id=data.material_id, location_id=data.location_id,
                       movement_type=data.movement_type, qty=data.qty,
                       unit_cost=data.unit_cost, order_fk=data.order_fk,
                       article_id=data.article_id, reference_type=data.reference_type,
                       reference_id=data.reference_id, reference_no=data.reference_no,
                       reason=data.reason, actor_id=user.id)
    db.add(mv)
    db.flush()
    new_bal = balance_of(db, data.material_id, data.location_id)
    log_audit(db, user, "CREATE", "StockMovement", entity_id=mv.id, obj=mv,
              detail=f"{data.movement_type} qty {data.qty} (saldo kini {new_bal})",
              reason=data.reason or "Input movement stok")
    db.commit()
    db.refresh(mv)
    return {"id": mv.id, "movement_type": mv.movement_type, "qty": float(mv.qty),
            "balance_after": float(new_bal)}


# ══════════════════════════════════════════════════════════════════════════════
# PURCHASE REQUESTS
# ══════════════════════════════════════════════════════════════════════════════
class PRLineIn(BaseModel):
    material_id: int
    qty: Decimal = Field(gt=0)
    estimated_unit_cost: Optional[Decimal] = Field(default=None, ge=0)
    notes: Optional[str] = None


class PRIn(BaseModel):
    order_fk: Optional[int] = None
    required_date: Optional[date] = None
    priority: Literal["LOW", "NORMAL", "URGENT"] = "NORMAL"
    notes: Optional[str] = None
    lines: list[PRLineIn] = Field(min_length=1)


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


def _pr_dict(db: Session, pr: PurchaseRequest) -> dict:
    lines = db.query(PurchaseRequestLine).filter_by(request_id=pr.id).all()
    mmat = {m.id: m for m in db.query(Material).all()}
    return {
        "id": pr.id, "pr_no": pr.pr_no, "order_fk": pr.order_fk, "status": pr.status,
        "priority": pr.priority, "required_date": pr.required_date.isoformat() if pr.required_date else None,
        "notes": pr.notes, "approved_by_id": pr.approved_by_id,
        "approved_at": pr.approved_at.isoformat() if pr.approved_at else None,
        "rejection_reason": pr.rejection_reason, "converted_po_id": pr.converted_po_id,
        "requested_by_id": pr.requested_by_id,
        "created_at": pr.created_at.isoformat() if pr.created_at else None,
        "total_estimated": float(sum((_dec(l.qty) * _dec(l.estimated_unit_cost or 0) for l in lines), Decimal(0))),
        "lines": [{"id": l.id, "material_id": l.material_id,
                   "material_code": mmat[l.material_id].code if l.material_id in mmat else None,
                   "material_name": mmat[l.material_id].name if l.material_id in mmat else None,
                   "unit": mmat[l.material_id].unit if l.material_id in mmat else None,
                   "qty": float(l.qty), "estimated_unit_cost": float(l.estimated_unit_cost or 0),
                   "notes": l.notes} for l in lines],
    }


@router.get("/purchase-requests")
def list_purchase_requests(status: Optional[str] = None, db: Session = Depends(get_db),
                           user=Depends(get_current_user)):
    q = db.query(PurchaseRequest)
    if status:
        q = q.filter(PurchaseRequest.status == status)
    rows = q.order_by(PurchaseRequest.id.desc()).limit(300).all()
    return [_pr_dict(db, pr) for pr in rows]


@router.post("/purchase-requests", status_code=201)
def create_purchase_request(data: PRIn, db: Session = Depends(get_db),
                            user=Depends(require_roles(*(MASTER_WRITE_ROLES + APPROVE_ROLES)))):
    for line in data.lines:
        if db.get(Material, line.material_id) is None:
            raise HTTPException(400, f"Material {line.material_id} tidak ditemukan.")
    pr = PurchaseRequest(pr_no=next_pr_no(db), order_fk=data.order_fk,
                         requested_by_id=user.id, required_date=data.required_date,
                         status="DRAFT", priority=data.priority, notes=data.notes)
    db.add(pr)
    db.flush()
    for line in data.lines:
        db.add(PurchaseRequestLine(request_id=pr.id, material_id=line.material_id,
                                   qty=line.qty, estimated_unit_cost=line.estimated_unit_cost,
                                   notes=line.notes))
    log_audit(db, user, "CREATE", "PurchaseRequest", entity_id=pr.id, obj=pr,
              detail=f"PR {pr.pr_no} dengan {len(data.lines)} baris", new_status="DRAFT",
              reason="Pembuatan purchase request")
    db.commit()
    db.refresh(pr)
    return _pr_dict(db, pr)


def _get_pr(db: Session, pr_id: int) -> PurchaseRequest:
    pr = db.get(PurchaseRequest, pr_id)
    if pr is None:
        raise HTTPException(404, "Purchase request tidak ditemukan.")
    return pr


@router.post("/purchase-requests/{pr_id}/submit")
def submit_purchase_request(pr_id: int, db: Session = Depends(get_db),
                            user=Depends(require_roles(*(MASTER_WRITE_ROLES + APPROVE_ROLES)))):
    pr = _get_pr(db, pr_id)
    if pr.status != "DRAFT":
        raise HTTPException(409, f"PR berstatus {pr.status}; hanya DRAFT yang bisa disubmit.")
    pr.status = "SUBMITTED"
    log_audit(db, user, "SUBMIT", "PurchaseRequest", entity_id=pr.id, obj=pr,
              previous_status="DRAFT", new_status="SUBMITTED", reason="PR disubmit untuk approval")
    db.commit()
    return _pr_dict(db, pr)


@router.post("/purchase-requests/{pr_id}/approve")
def approve_purchase_request(pr_id: int, db: Session = Depends(get_db),
                             user=Depends(require_roles(*APPROVE_ROLES))):
    pr = _get_pr(db, pr_id)
    if pr.status != "SUBMITTED":
        raise HTTPException(409, f"PR berstatus {pr.status}; hanya SUBMITTED yang bisa disetujui.")
    pr.status = "APPROVED"
    pr.approved_by_id = user.id
    pr.approved_at = datetime.utcnow()
    log_audit(db, user, "APPROVE", "PurchaseRequest", entity_id=pr.id, obj=pr,
              previous_status="SUBMITTED", new_status="APPROVED", reason="PR disetujui")
    db.commit()
    return _pr_dict(db, pr)


@router.post("/purchase-requests/{pr_id}/reject")
def reject_purchase_request(pr_id: int, data: RejectIn, db: Session = Depends(get_db),
                            user=Depends(require_roles(*APPROVE_ROLES))):
    pr = _get_pr(db, pr_id)
    if pr.status not in ("SUBMITTED", "DRAFT"):
        raise HTTPException(409, f"PR berstatus {pr.status}; tidak bisa ditolak.")
    prev = pr.status
    pr.status = "REJECTED"
    pr.rejection_reason = data.reason
    log_audit(db, user, "REJECT", "PurchaseRequest", entity_id=pr.id, obj=pr,
              previous_status=prev, new_status="REJECTED", reason=data.reason)
    db.commit()
    return _pr_dict(db, pr)


@router.post("/purchase-requests/{pr_id}/convert-to-po")
def convert_pr_to_po(pr_id: int, db: Session = Depends(get_db),
                     user=Depends(require_roles(*APPROVE_ROLES))):
    """Ubah PR yang sudah APPROVED menjadi satu PurchaseOrder."""
    pr = _get_pr(db, pr_id)
    if pr.status != "APPROVED":
        raise HTTPException(409, f"PR berstatus {pr.status}; hanya APPROVED yang bisa dikonversi ke PO.")
    lines = db.query(PurchaseRequestLine).filter_by(request_id=pr.id).all()
    if not lines:
        raise HTTPException(400, "PR tidak punya baris; tidak bisa dikonversi.")
    mmat = {m.id: m for m in db.query(Material).all()}
    total_qty = sum((_dec(l.qty) for l in lines), Decimal(0))
    total_amount = sum((_dec(l.qty) * _dec(l.estimated_unit_cost or 0) for l in lines), Decimal(0))
    names = ", ".join((mmat[l.material_id].name if l.material_id in mmat else str(l.material_id)) for l in lines)
    first_mat = mmat.get(lines[0].material_id)
    supplier_name = None
    if first_mat and first_mat.default_supplier_id:
        sup = db.get(Supplier, first_mat.default_supplier_id)
        supplier_name = sup.name if sup else None
    po = models.PurchaseOrder(po_no=next_po_no(db), order_fk=pr.order_fk, item=names,
                              qty=total_qty, unit=(first_mat.unit if first_mat else None),
                              supplier=supplier_name, amount=total_amount, status="PENDING",
                              material_status="WAITING", vendor_type="SUPPLIER",
                              approval_status="APPROVED", approved_by_id=user.id)
    db.add(po)
    db.flush()
    pr.status = "CONVERTED_TO_PO"
    pr.converted_po_id = po.id
    log_audit(db, user, "CONVERT", "PurchaseRequest", entity_id=pr.id, obj=pr,
              previous_status="APPROVED", new_status="CONVERTED_TO_PO",
              detail=f"PR {pr.pr_no} -> PO {po.po_no}", reason="Konversi PR ke PO")
    db.commit()
    return {"pr_id": pr.id, "pr_no": pr.pr_no, "po_id": po.id, "po_no": po.po_no,
            "amount": float(total_amount)}


# ══════════════════════════════════════════════════════════════════════════════
# GOODS RECEIPTS
# ══════════════════════════════════════════════════════════════════════════════
class GRLineIn(BaseModel):
    material_id: int
    location_id: int
    qty_ordered: Decimal = Field(default=Decimal(0), ge=0)
    qty_received: Decimal = Field(default=Decimal(0), ge=0)
    qty_rejected: Decimal = Field(default=Decimal(0), ge=0)
    unit_cost: Optional[Decimal] = Field(default=None, ge=0)
    notes: Optional[str] = None


class GRIn(BaseModel):
    po_fk: Optional[int] = None
    supplier_id: Optional[int] = None
    received_date: Optional[date] = None
    evidence_ref: Optional[str] = None
    notes: Optional[str] = None
    lines: list[GRLineIn] = Field(min_length=1)


def _gr_dict(db: Session, gr: GoodsReceipt) -> dict:
    lines = db.query(GoodsReceiptLine).filter_by(receipt_id=gr.id).all()
    mmat = {m.id: m for m in db.query(Material).all()}
    mloc = {l.id: l for l in db.query(InventoryLocation).all()}
    return {
        "id": gr.id, "gr_no": gr.gr_no, "po_fk": gr.po_fk, "supplier_id": gr.supplier_id,
        "received_date": gr.received_date.isoformat() if gr.received_date else None,
        "status": gr.status, "received_by_id": gr.received_by_id,
        "posted_by_id": gr.posted_by_id,
        "posted_at": gr.posted_at.isoformat() if gr.posted_at else None,
        "evidence_ref": gr.evidence_ref, "notes": gr.notes,
        "created_at": gr.created_at.isoformat() if gr.created_at else None,
        "lines": [{"id": l.id, "material_id": l.material_id,
                   "material_code": mmat[l.material_id].code if l.material_id in mmat else None,
                   "material_name": mmat[l.material_id].name if l.material_id in mmat else None,
                   "unit": mmat[l.material_id].unit if l.material_id in mmat else None,
                   "location_id": l.location_id,
                   "location_code": mloc[l.location_id].code if l.location_id in mloc else None,
                   "qty_ordered": float(l.qty_ordered), "qty_received": float(l.qty_received),
                   "qty_rejected": float(l.qty_rejected), "unit_cost": float(l.unit_cost or 0),
                   "notes": l.notes} for l in lines],
    }


@router.get("/goods-receipts")
def list_goods_receipts(status: Optional[str] = None, db: Session = Depends(get_db),
                        user=Depends(get_current_user)):
    q = db.query(GoodsReceipt)
    if status:
        q = q.filter(GoodsReceipt.status == status)
    rows = q.order_by(GoodsReceipt.id.desc()).limit(300).all()
    return [_gr_dict(db, gr) for gr in rows]


@router.post("/goods-receipts", status_code=201)
def create_goods_receipt(data: GRIn, db: Session = Depends(get_db),
                         user=Depends(require_roles(*(MASTER_WRITE_ROLES + APPROVE_ROLES)))):
    for line in data.lines:
        if db.get(Material, line.material_id) is None:
            raise HTTPException(400, f"Material {line.material_id} tidak ditemukan.")
        if db.get(InventoryLocation, line.location_id) is None:
            raise HTTPException(400, f"Lokasi {line.location_id} tidak ditemukan.")
    gr = GoodsReceipt(gr_no=next_gr_no(db), po_fk=data.po_fk, supplier_id=data.supplier_id,
                      received_date=data.received_date, status="DRAFT",
                      received_by_id=user.id, evidence_ref=data.evidence_ref, notes=data.notes)
    db.add(gr)
    db.flush()
    for line in data.lines:
        db.add(GoodsReceiptLine(receipt_id=gr.id, material_id=line.material_id,
                                location_id=line.location_id, qty_ordered=line.qty_ordered,
                                qty_received=line.qty_received, qty_rejected=line.qty_rejected,
                                unit_cost=line.unit_cost, notes=line.notes))
    log_audit(db, user, "CREATE", "GoodsReceipt", entity_id=gr.id, obj=gr,
              detail=f"GR {gr.gr_no} dengan {len(data.lines)} baris", new_status="DRAFT",
              reason="Pembuatan goods receipt")
    db.commit()
    db.refresh(gr)
    return _gr_dict(db, gr)


@router.post("/goods-receipts/{gr_id}/post")
def post_goods_receipt(gr_id: int, db: Session = Depends(get_db),
                       user=Depends(require_roles(*APPROVE_ROLES))):
    """Posting GR = buat stock_movements RECEIPT untuk setiap qty_received.

    Idempotent: GR yang sudah POSTED ditolak 409 supaya stok tidak tergandakan.
    """
    gr = db.get(GoodsReceipt, gr_id)
    if gr is None:
        raise HTTPException(404, "Goods receipt tidak ditemukan.")
    if gr.status == "POSTED":
        raise HTTPException(409, "Goods receipt ini sudah POSTED; stok tidak boleh ditambah dua kali.")
    if gr.status != "DRAFT":
        raise HTTPException(409, f"GR berstatus {gr.status}; hanya DRAFT yang bisa diposting.")
    lines = db.query(GoodsReceiptLine).filter_by(receipt_id=gr.id).all()
    if not lines:
        raise HTTPException(400, "GR tidak punya baris untuk diposting.")
    # Order diturunkan dari PO (kalau GR menunjuk PO), supaya movement bisa
    # ditelusuri balik ke order produksinya.
    order_fk = None
    if gr.po_fk:
        po = db.get(models.PurchaseOrder, gr.po_fk)
        order_fk = po.order_fk if po else None
    posted = []
    for l in lines:
        qty = _dec(l.qty_received)
        if qty <= 0:
            continue  # baris dengan penerimaan nol tidak menghasilkan movement
        db.add(StockMovement(material_id=l.material_id, location_id=l.location_id,
                             movement_type="RECEIPT", qty=qty, unit_cost=l.unit_cost,
                             order_fk=order_fk, reference_type="GOODS_RECEIPT",
                             reference_id=gr.id, reference_no=gr.gr_no,
                             reason=f"Penerimaan GR {gr.gr_no}", actor_id=user.id))
        posted.append({"material_id": l.material_id, "qty": float(qty)})
    if not posted:
        raise HTTPException(400, "Tidak ada qty_received > 0; tidak ada stok yang ditambah.")
    gr.status = "POSTED"
    gr.posted_by_id = user.id
    gr.posted_at = datetime.utcnow()
    log_audit(db, user, "POST", "GoodsReceipt", entity_id=gr.id, obj=gr,
              previous_status="DRAFT", new_status="POSTED",
              detail=f"Posting GR {gr.gr_no}: {len(posted)} movement", reason="Posting penerimaan barang")
    db.commit()
    return {"id": gr.id, "gr_no": gr.gr_no, "status": gr.status,
            "posted_at": gr.posted_at.isoformat(), "movements_created": len(posted),
            "posted_lines": posted}


# ══════════════════════════════════════════════════════════════════════════════
# MATERIAL GATE
# ══════════════════════════════════════════════════════════════════════════════
class GateBlockIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class GateEvaluateIn(BaseModel):
    order_fk: int


def _gate_dict(db: Session, g: MaterialGate) -> dict:
    art = db.get(models.Article, g.article_id)
    order = db.get(models.Order, g.order_fk)
    return {
        "id": g.id, "order_fk": g.order_fk,
        "order_id": order.order_id if order else None,
        "article_id": g.article_id,
        "article_code": art.article_code if art else None,
        "article_qty": art.qty if art else None,
        "status": g.status, "required_qty": float(g.required_qty),
        "allocated_qty": float(g.allocated_qty), "shortage_qty": float(g.shortage_qty),
        "block_reason": g.block_reason,
        "evaluated_by_id": g.evaluated_by_id,
        "evaluated_at": g.evaluated_at.isoformat() if g.evaluated_at else None,
        "released_by_id": g.released_by_id,
        "released_at": g.released_at.isoformat() if g.released_at else None,
    }


def _allocated_for_article(db: Session, article_id: int) -> Decimal:
    """Material yang sudah di-issue/dialokasikan ke artikel ini (per satuan kuantitas)."""
    total = (db.query(func.coalesce(func.sum(StockMovement.qty), 0))
             .filter(StockMovement.article_id == article_id,
                     StockMovement.movement_type.in_(("ISSUE", "ALLOCATION_ISSUE")))
             .scalar())
    return _dec(total)


def _required_for_article(db: Session, article_id: int) -> Decimal:
    """Kebutuhan material = Σ (qty_per_unit BOM × qty artikel)."""
    art = db.get(models.Article, article_id)
    article_qty = _dec(art.qty if art else 0)
    items = db.query(models.BOMItem).filter_by(article_id=article_id).all()
    return sum((_dec(i.qty_per_unit) * article_qty for i in items), Decimal(0))


@router.get("/material-gates")
def list_material_gates(status: Optional[str] = None, order_fk: Optional[int] = None,
                        db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(MaterialGate)
    if status:
        q = q.filter(MaterialGate.status == status)
    if order_fk:
        q = q.filter(MaterialGate.order_fk == order_fk)
    return [_gate_dict(db, g) for g in q.order_by(MaterialGate.id.desc()).all()]


@router.post("/material-gates/evaluate")
def evaluate_material_gates(data: GateEvaluateIn, db: Session = Depends(get_db),
                            user=Depends(require_roles(*APPROVE_ROLES))):
    """Evaluasi kesiapan material untuk semua artikel dalam satu order.

    `required_qty` = kebutuhan BOM × qty artikel; `allocated_qty` = material yang
    sudah di-issue/dialokasikan. Status: READY (cukup) / PARTIAL (sebagian) /
    NOT_REQUESTED (belum ada alokasi).
    """
    order = db.get(models.Order, data.order_fk)
    if order is None:
        raise HTTPException(404, "Order tidak ditemukan.")
    articles = db.query(models.Article).filter_by(order_fk=order.id).all()
    if not articles:
        raise HTTPException(400, "Order ini tidak punya artikel untuk dievaluasi.")
    results = []
    for art in articles:
        required = _required_for_article(db, art.id)
        allocated = _allocated_for_article(db, art.id)
        gate = db.query(MaterialGate).filter_by(article_id=art.id).first()
        # Kalau gate sedang BLOCKED, evaluasi tidak boleh diam-diam membukanya;
        # blokir hanya boleh dicabut lewat alur eksplisit.
        if gate is None:
            gate = MaterialGate(order_fk=order.id, article_id=art.id)
            db.add(gate)
        elif gate.status == "BLOCKED":
            results.append(_gate_dict(db, gate))
            continue
        gate.required_qty = required
        gate.allocated_qty = allocated
        gate.shortage_qty = max(Decimal(0), required - allocated)
        if allocated <= 0:
            gate.status = "NOT_REQUESTED"
        elif allocated >= required:
            gate.status = "READY"
        else:
            gate.status = "PARTIAL"
        gate.evaluated_by_id = user.id
        gate.evaluated_at = datetime.utcnow()
        db.flush()
        results.append(_gate_dict(db, gate))
    log_audit(db, user, "EVALUATE", "MaterialGate", detail=f"Evaluasi gate order {order.order_id}",
              reason="Evaluasi kesiapan material")
    db.commit()
    return results


@router.post("/material-gates/{gate_id}/release")
def release_material_gate(gate_id: int, db: Session = Depends(get_db),
                          user=Depends(require_roles(models.Role.COO_MANAGER))):
    """Release gate — COO_MANAGER saja (keputusan operasional)."""
    gate = db.get(MaterialGate, gate_id)
    if gate is None:
        raise HTTPException(404, "Material gate tidak ditemukan.")
    if gate.status == "BLOCKED":
        raise HTTPException(409, "Gate sedang BLOCKED; cabut blokir dulu sebelum release.")
    if gate.status != "READY":
        raise HTTPException(409, f"Gate berstatus {gate.status}; hanya READY yang bisa di-release.")
    prev = gate.status
    gate.status = "RELEASED"
    gate.released_by_id = user.id
    gate.released_at = datetime.utcnow()
    log_audit(db, user, "RELEASE", "MaterialGate", entity_id=gate.id, obj=gate,
              previous_status=prev, new_status="RELEASED", reason="Material dinyatakan siap produksi")
    db.commit()
    return _gate_dict(db, gate)


@router.post("/material-gates/{gate_id}/block")
def block_material_gate(gate_id: int, data: GateBlockIn, db: Session = Depends(get_db),
                        user=Depends(require_roles(*APPROVE_ROLES))):
    gate = db.get(MaterialGate, gate_id)
    if gate is None:
        raise HTTPException(404, "Material gate tidak ditemukan.")
    prev = gate.status
    gate.status = "BLOCKED"
    gate.block_reason = data.reason
    log_audit(db, user, "BLOCK", "MaterialGate", entity_id=gate.id, obj=gate,
              previous_status=prev, new_status="BLOCKED", reason=data.reason)
    db.commit()
    return _gate_dict(db, gate)


# ══════════════════════════════════════════════════════════════════════════════
# SEED
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/seed")
def seed_inventory(db: Session = Depends(get_db),
                   user=Depends(require_roles(models.Role.COO_MANAGER, models.Role.CFO_MANAGER))):
    """Isi master lokasi/supplier/material awal (idempotent)."""
    from ..inventory_seed import seed_inventory as _seed
    created = _seed(db)
    log_audit(db, user, "SEED", "Material",
              detail=f"Seed inventory: {created}", reason="Inisialisasi data inventory")
    db.commit()
    return {"created": created, "suppliers": db.query(Supplier).count(),
            "locations": db.query(InventoryLocation).count(),
            "materials": db.query(Material).count()}
