from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, model_validator
from typing import Optional
from datetime import date
from decimal import Decimal
import json
from datetime import datetime
from pydantic import Field
from ..database import get_db
from ..auth import get_current_user, require_roles
from .. import models
from ..workflow import commit_changes, get, require, invoices_total, invoices_reconciled, quotation_ready, shipment_ready, role
from .. import workflow
from ..business_policy import BusinessPolicy, get_policy
from ..audit import log_audit
from ..spk_document import build_spk_pdf, snapshot_spk

class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def normalize_blank_dates(cls, value):
        if isinstance(value, dict):
            return {k: None if v == "" and (k.endswith("date") or k == "valid_until") else v for k, v in value.items()}
        return value

router = APIRouter(tags=["modules"])


@router.get("/config/business-policy")
def read_business_policy(db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO, models.Role.CFO_MANAGER, models.Role.CMO_MANAGER))):
    return get_policy(db)


@router.put("/config/business-policy")
def update_business_policy(data:BusinessPolicy, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO))):
    record = db.query(models.SystemConfig).filter_by(key="business_policy").with_for_update().first()
    if record is None:
        record = models.SystemConfig(key="business_policy", updated_at=datetime.utcnow())
        db.add(record)
    record.value = data.model_dump_json()
    record.updated_at = datetime.utcnow()
    from ..audit import log_audit
    db.flush()
    log_audit(db, user, "UPDATE", "BusinessPolicy", record.id, record.value)
    db.commit()
    return data

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ HELPERS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def get_or_404(db, model, id, label="Not found"):
    x = db.query(model).filter(model.id == id).first()
    if not x: raise HTTPException(404, label)
    return x

def apply_update(obj, data, db, user=None, entity_name=None):
    changes = []
    for k,v in data.model_dump(exclude_unset=True).items():
        old = getattr(obj, k, None)
        setattr(obj, k, v)
        if old != v: changes.append(f"{k}={v}")
    commit_changes(db, user); db.refresh(obj)
    return obj

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CMO: CUSTOMERS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class CustomerIn(BaseModel):
    name:str; country:Optional[str]=None; contact_name:Optional[str]=None; contact_info:Optional[str]=None; notes:Optional[str]=None

@router.get("/cmo/customers")
def customers(db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","CMO_MANAGER","CMO_SUPPORT","CFO_MANAGER")
    return db.query(models.Customer).order_by(models.Customer.name).all()

@router.post("/cmo/customers")
def create_customer(data:CustomerIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER,models.Role.CMO_SUPPORT))):
    x=models.Customer(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

class CustomerUpdate(BaseModel):
    name:Optional[str]=None; country:Optional[str]=None; contact_name:Optional[str]=None; contact_info:Optional[str]=None; notes:Optional[str]=None

@router.patch("/cmo/customers/{customer_id}")
def update_customer(customer_id:int, data:CustomerUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER,models.Role.CMO_SUPPORT))):
    return apply_update(get_or_404(db,models.Customer,customer_id,"Customer not found"), data, db, user)

@router.delete("/cmo/customers/{customer_id}")
def delete_customer(customer_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER))):
    x=get_or_404(db,models.Customer,customer_id,"Customer not found"); name=x.name; db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CMO: QUOTATIONS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class PricingLineIn(BaseModel):
    article_id: int
    unit_price: Decimal = Field(gt=0)
    unit_hpp: Decimal = Field(ge=0)


class QuotationIn(BaseModel):
    quotation_no:str; order_fk:int; amount:float=0; status:str="DRAFT"; valid_until:Optional[date]=None; notes:Optional[str]=None
    pricing_lines:Optional[list[PricingLineIn]]=None; payment_plan:Optional[str]=None

class QuotationUpdate(BaseModel):
    status:Optional[str]=None; valid_until:Optional[date]=None; notes:Optional[str]=None
    pricing_lines:Optional[list[PricingLineIn]]=None; payment_plan:Optional[str]=None; approval_reason:Optional[str]=None

@router.get("/cmo/quotations")
def list_quotations(limit:int=Query(500,ge=1,le=500), offset:int=Query(0,ge=0), db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","CMO_MANAGER","CMO_SUPPORT","CFO_MANAGER")
    return db.query(models.Quotation).order_by(desc(models.Quotation.id)).offset(offset).limit(limit).all()

@router.post("/cmo/quotations")
def create_quotation(data:QuotationIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER,models.Role.CMO_SUPPORT))):
    values = data.model_dump(exclude={"pricing_lines"})
    x=models.Quotation(**values)
    if data.pricing_lines is not None:
        x.pricing_breakdown = json.dumps([line.model_dump(mode="json") for line in data.pricing_lines])
    db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/cmo/quotations/{q_id}")
def update_quotation(q_id:int, data:QuotationUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER,models.Role.CFO_MANAGER))):
    x = get_or_404(db,models.Quotation,q_id,"Quotation not found")
    values = data.model_dump(exclude_unset=True, exclude={"pricing_lines"})
    if role(user) == "CFO_MANAGER" and (data.pricing_lines is not None or set(values) - {"status", "approval_reason"}):
        raise HTTPException(403, "CFO may only record a pricing decision")
    if role(user) == "CMO_MANAGER" and ("approval_reason" in values or values.get("status") == "APPROVED"):
        raise HTTPException(403, "Only CFO may approve quotation")
    for key, value in values.items():
        setattr(x, key, value)
    if data.pricing_lines is not None:
        x.pricing_breakdown = json.dumps([line.model_dump(mode="json") for line in data.pricing_lines])
    commit_changes(db, user); db.refresh(x); return x


class QuotationCEOApprovalIn(BaseModel):
    reason: str


@router.post("/ceo/quotations/{q_id}/approve-limit")
def approve_quotation_limit(q_id:int, data:QuotationCEOApprovalIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO))):
    quote = db.query(models.Quotation).filter_by(id=q_id).with_for_update().first()
    if not quote:
        raise HTTPException(404, "Quotation not found")
    if quote.status not in ("DRAFT", "SENT") or not data.reason.strip():
        raise HTTPException(400, "A draft quotation and documented CEO reason are required")
    workflow.price_quotation(db, quote)
    policy = get_policy(db)
    if quote.margin_percent < policy.minimum_margin_percent:
        raise HTTPException(400, "Quotation margin is below configured minimum")
    if quote.amount <= policy.cfo_quotation_limit:
        raise HTTPException(400, "Quotation is within CFO approval limit")
    quote.ceo_approved_by_id = user.id
    quote.ceo_approval_reason = data.reason.strip()
    from ..audit import log_audit
    log_audit(db, user, "CEO_QUOTATION_LIMIT_APPROVED", "Quotation", quote.id, data.reason.strip())
    db.commit()
    db.refresh(quote)
    return quote

@router.delete("/cmo/quotations/{q_id}")
def delete_quotation(q_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER))):
    x=get_or_404(db,models.Quotation,q_id); db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CMO: SAMPLE RECORDS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class SampleIn(BaseModel):
    order_fk:int; article_code:str; status:str="PROCESS"; notes:Optional[str]=None; requested_date:Optional[date]=None; completed_date:Optional[date]=None

class SampleUpdate(BaseModel):
    status:Optional[str]=None; notes:Optional[str]=None; completed_date:Optional[date]=None

@router.get("/cmo/samples")
def list_samples(db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","CMO_MANAGER","CMO_SUPPORT","COO_MANAGER","SAMPLE_PIC")
    return db.query(models.SampleRecord).order_by(desc(models.SampleRecord.id)).all()

@router.post("/cmo/samples")
def create_sample(data:SampleIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER,models.Role.SAMPLE_PIC))):
    x=models.SampleRecord(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/cmo/samples/{s_id}")
def update_sample(s_id:int, data:SampleUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER,models.Role.SAMPLE_PIC))):
    return apply_update(get_or_404(db,models.SampleRecord,s_id,"Sample not found"), data, db, user)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CMO: SPK â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class SPKIn(BaseModel):
    order_fk:int; spk_no:str; status:str="DRAFT"; notes:Optional[str]=None

class SPKUpdate(BaseModel):
    status:Optional[str]=None; notes:Optional[str]=None


def spk_deny(db, user, action, spk_id=None):
    log_audit(db, user, "DENIED_SPK_ACTION", "SPK", spk_id, action)
    db.commit()
    raise HTTPException(403, "Role or route not allowed for this SPK action")


def spk_require(db, user, action, allowed, spk_id=None):
    if role(user) not in allowed:
        spk_deny(db, user, action, spk_id)


def spk_document_response(spk):
    try:
        pdf = build_spk_pdf(spk)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(409, "SPK document is unavailable")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="spk-{spk.id}-v{spk.version}.pdf"'})

@router.get("/cmo/spk")
def list_spk(db:Session=Depends(get_db), user=Depends(get_current_user)):
    spk_require(db,user,"LIST",{"CEO","CMO_MANAGER","CMO_SUPPORT","COO_MANAGER","PRODUCTION_PIC"})
    return db.query(models.SPK).order_by(desc(models.SPK.id)).all()

@router.post("/cmo/spk")
def create_spk(data:SPKIn, db:Session=Depends(get_db), user=Depends(get_current_user)):
    spk_require(db,user,"CREATE_DRAFT",{"CMO_MANAGER","CMO_SUPPORT"})
    if data.status != "DRAFT": spk_deny(db,user,"CREATE_WITH_STATUS")
    x=models.SPK(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/cmo/spk/{spk_id}")
def update_spk(spk_id:int, data:SPKUpdate, db:Session=Depends(get_db), user=Depends(get_current_user)):
    spk_require(db,user,"EDIT_DRAFT",{"CMO_MANAGER","CMO_SUPPORT"},spk_id)
    if "status" in data.model_fields_set: spk_deny(db,user,"DIRECT_STATUS_CHANGE",spk_id)
    x=get_or_404(db,models.SPK,spk_id,"SPK not found")
    if x.status != "DRAFT":
        raise HTTPException(409,"Only draft SPK may be edited")
    return apply_update(x, data, db, user)


@router.post("/cmo/spk/{spk_id}/generate")
def generate_spk(spk_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    spk_require(db,user,"GENERATE",{"CMO_MANAGER","CMO_SUPPORT"},spk_id)
    x=db.query(models.SPK).filter_by(id=spk_id).with_for_update().first()
    if not x: raise HTTPException(404,"SPK not found")
    if x.status != "DRAFT": raise HTTPException(409,"Only a draft SPK can be generated")
    order=get_or_404(db,models.Order,x.order_fk,"Order not found")
    try: x.snapshot=json.dumps(snapshot_spk(x,order),ensure_ascii=False)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    x.status="GENERATED"
    db.info["spk_action"]="GENERATE"
    try: commit_changes(db,user)
    finally: db.info.pop("spk_action",None)
    db.refresh(x)
    return x


@router.get("/cmo/spk/{spk_id}/pdf")
def preview_spk_pdf(spk_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    spk_require(db,user,"PREVIEW_PDF",{"CMO_MANAGER","CMO_SUPPORT"},spk_id)
    x=get_or_404(db,models.SPK,spk_id,"SPK not found")
    if x.status not in ("GENERATED","PRINTED","RELEASED"):
        raise HTTPException(409,"Generate the SPK before previewing")
    return spk_document_response(x)


@router.post("/cmo/spk/{spk_id}/print")
def print_spk(spk_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    spk_require(db,user,"PRINT",{"CMO_MANAGER","CMO_SUPPORT"},spk_id)
    x=db.query(models.SPK).filter_by(id=spk_id).with_for_update().first()
    if not x: raise HTTPException(404,"SPK not found")
    if x.status not in ("GENERATED","PRINTED"):
        raise HTTPException(409,"Only a generated SPK can be printed")
    response=spk_document_response(x)
    if x.status == "GENERATED":
        x.status="PRINTED"
        db.info["spk_action"]="PRINT"
        try: commit_changes(db,user)
        finally: db.info.pop("spk_action",None)
    else:
        log_audit(db,user,"PRINT","SPK",x.id,"Reprint locked version")
        db.commit()
    return response


class SPKReleaseIn(BaseModel):
    version_id:int
    reason:str=Field(min_length=1,max_length=2000)
    correction_reason:Optional[str]=Field(default=None,max_length=2000)


@router.get("/cmo/spk/{spk_id}/release-readiness")
def spk_release_readiness(spk_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    spk_require(db,user,"RELEASE_READINESS",{"CMO_MANAGER"},spk_id)
    x=get_or_404(db,models.SPK,spk_id,"SPK not found")
    return workflow.spk_release_readiness(db,x)


@router.post("/cmo/spk/{spk_id}/release")
def release_spk(spk_id:int, data:SPKReleaseIn, db:Session=Depends(get_db), user=Depends(get_current_user)):
    spk_require(db,user,"RELEASE",{"CMO_MANAGER"},spk_id)
    x=db.query(models.SPK).filter_by(id=spk_id).with_for_update().first()
    if not x: raise HTTPException(404,"SPK not found")
    if data.version_id != x.id: raise HTTPException(409,"SPK version_id does not match the locked version")
    if x.status != "PRINTED": raise HTTPException(409,"Only a printed SPK can be released")
    reason=data.reason.strip()
    correction=(data.correction_reason or "").strip() or None
    if not reason: raise HTTPException(422,"Release reason is required")
    if x.version > 1 and not correction:
        raise HTTPException(422,"Correction reason is required for a revised SPK version")
    readiness=workflow.spk_release_readiness(db,x)
    if not readiness["ready"]:
        failed=[check["label"] for check in readiness["checks"].values() if not check["ok"]]
        log_audit(db,user,"SPK_RELEASE_BLOCKED","SPK",x.id,", ".join(failed))
        db.commit()
        raise HTTPException(400,"SPK release prerequisites failed: " + ", ".join(failed))
    now=datetime.utcnow()
    x.released_by=user.id
    x.released_at=now
    x.released_version=x.version
    x.release_reason=reason
    x.correction_reason=correction
    x.release_prerequisites=json.dumps({**readiness,"checked_at":now.isoformat(timespec="seconds")+"Z"},ensure_ascii=False)
    x.status="RELEASED"
    log_audit(db,user,"SPK_RELEASE","SPK",x.id,
              json.dumps({"version_id":x.id,"version":x.version,"reason":reason,
                          "correction_reason":correction,"prerequisites":readiness["checks"]},ensure_ascii=False))
    db.info["spk_action"]="RELEASE"
    try: commit_changes(db,user)
    finally: db.info.pop("spk_action",None)
    db.refresh(x)
    return x


@router.post("/cmo/spk/{spk_id}/void")
def void_spk(spk_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    spk_require(db,user,"VOID",{"CMO_MANAGER"},spk_id)
    x=db.query(models.SPK).filter_by(id=spk_id).with_for_update().first()
    if not x: raise HTTPException(404,"SPK not found")
    if x.status not in ("DRAFT","GENERATED","PRINTED"):
        raise HTTPException(409,"Only an unreleased SPK can be voided")
    x.status="VOID"
    db.info["spk_action"]="VOID"
    try: commit_changes(db,user)
    finally: db.info.pop("spk_action",None)
    db.refresh(x)
    return x

@router.delete("/cmo/spk/{spk_id}")
def delete_spk(spk_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    spk_require(db,user,"DELETE_DRAFT",{"CMO_MANAGER"},spk_id)
    x=get_or_404(db,models.SPK,spk_id)
    if x.status != "DRAFT": raise HTTPException(409,"Only draft SPK can be deleted")
    db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CFO: INVOICES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class InvoiceIn(BaseModel):
    invoice_no:str; order_fk:int; amount:float; paid_amount:float=0; due_date:Optional[date]=None; status:str="UNPAID"

class InvoiceUpdate(BaseModel):
    amount:Optional[float]=None; paid_amount:Optional[float]=None; due_date:Optional[date]=None; status:Optional[str]=None

@router.get("/cfo/invoices")
def invoices(limit:int=Query(500,ge=1,le=500), offset:int=Query(0,ge=0), db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER,models.Role.FINANCE_SUPPORT,models.Role.CEO))):
    return db.query(models.Invoice).order_by(desc(models.Invoice.id)).offset(offset).limit(limit).all()

@router.post("/cfo/invoices")
def create_invoice(data:InvoiceIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER,models.Role.FINANCE_SUPPORT))):
    x=models.Invoice(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/cfo/invoices/{inv_id}")
def update_invoice(inv_id:int, data:InvoiceUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER))):
    return apply_update(get_or_404(db, models.Invoice, inv_id, "Invoice not found"), data, db, user)

@router.delete("/cfo/invoices/{inv_id}")
def delete_invoice(inv_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER))):
    x=get_or_404(db,models.Invoice,inv_id); info=x.invoice_no; db.delete(x); commit_changes(db, user); return {"ok":True}


class InvoiceReconcileIn(BaseModel):
    opening_paid_amount: float
    evidence_ref: str


@router.post("/cfo/invoices/{inv_id}/reconcile")
def reconcile_invoice(inv_id:int, data:InvoiceReconcileIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER))):
    invoice = db.query(models.Invoice).filter_by(id=inv_id).with_for_update().first()
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if not data.evidence_ref.strip():
        raise HTTPException(400, "Reconciliation requires an evidence reference")
    opening = Decimal(str(data.opening_paid_amount))
    if not opening.is_finite() or opening < 0:
        raise HTTPException(400, "Opening paid amount must be finite and non-negative")
    ledger = sum((Decimal(p.amount) for p in db.query(models.Payment).filter(
        (models.Payment.invoice_id == invoice.id) |
        ((models.Payment.invoice_id.is_(None)) & (models.Payment.invoice_no == invoice.invoice_no))
    ).all()), Decimal(0))
    expected = opening + ledger
    if expected > Decimal(invoice.amount):
        raise HTTPException(400, "Reconciled total exceeds invoice amount")
    invoice.opening_paid_amount = opening
    invoice.paid_amount = expected
    invoice.status = "PAID" if expected >= Decimal(invoice.amount) else "PARTIAL" if expected > 0 else "UNPAID"
    invoice.reconciliation_status = "VERIFIED"
    invoice.reconciliation_evidence = data.evidence_ref.strip()
    invoice.reconciled_by_id = user.id
    from ..audit import log_audit
    log_audit(db, user, "INVOICE_RECONCILED", "Invoice", invoice.id,
              f"opening={opening}; ledger={ledger}; evidence={data.evidence_ref.strip()}")
    db.flush()
    workflow.sync_order(db, invoice.order_fk)
    db.commit()
    db.refresh(invoice)
    return invoice

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CFO: PURCHASE ORDERS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class POIn(BaseModel):
    po_no:str; order_fk:Optional[int]=None; item:str; qty:float; unit:Optional[str]=None; supplier:Optional[str]=None; amount:Optional[float]=0; status:str="PENDING"; arrival_date:Optional[date]=None; material_status:str="WAITING"

class POUpdate(BaseModel):
    item:Optional[str]=None; qty:Optional[float]=None; unit:Optional[str]=None; supplier:Optional[str]=None; amount:Optional[float]=None; status:Optional[str]=None; arrival_date:Optional[date]=None; material_status:Optional[str]=None

@router.get("/cfo/purchase-orders")
def list_pos(db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER,models.Role.FINANCE_SUPPORT,models.Role.CEO))):
    return db.query(models.PurchaseOrder).order_by(desc(models.PurchaseOrder.id)).all()

@router.post("/cfo/purchase-orders")
def create_po(data:POIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER,models.Role.FINANCE_SUPPORT))):
    x=models.PurchaseOrder(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/cfo/purchase-orders/{po_id}")
def update_po(po_id:int, data:POUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER))):
    return apply_update(get_or_404(db,models.PurchaseOrder,po_id,"PO not found"), data, db, user)

@router.delete("/cfo/purchase-orders/{po_id}")
def delete_po(po_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER))):
    x=get_or_404(db,models.PurchaseOrder,po_id); info=x.po_no; db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CFO: PAYMENTS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class PaymentIn(BaseModel):
    invoice_no:str; amount:float; payment_date:Optional[date]=None; method:Optional[str]=None; notes:Optional[str]=None

@router.get("/cfo/payments")
def list_payments(limit:int=Query(500,ge=1,le=500), offset:int=Query(0,ge=0), db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER,models.Role.FINANCE_SUPPORT,models.Role.CEO))):
    return db.query(models.Payment).order_by(desc(models.Payment.id)).offset(offset).limit(limit).all()

@router.post("/cfo/payments")
def create_payment(data:PaymentIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER,models.Role.FINANCE_SUPPORT))):
    x=models.Payment(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ COO: MATERIAL REQUESTS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class BOMIn(BaseModel):
    article_id: int
    material_name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=40)
    qty_per_unit: Decimal = Field(gt=0)
    planned_unit_cost: Decimal = Field(ge=0)


class ConsumptionIn(BaseModel):
    bom_item_id: int
    qty: Decimal = Field(gt=0)
    actual_unit_cost: Decimal = Field(ge=0)
    evidence_ref: str = Field(min_length=1)


class ProductionCostIn(BaseModel):
    article_id: int
    category: str
    amount: Decimal = Field(gt=0)
    evidence_ref: str = Field(min_length=1)


class CostReviewIn(BaseModel):
    evidence_ref: str = Field(min_length=1)


@router.get("/coo/bom")
def list_bom(order_fk:Optional[int]=None, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO,models.Role.COO_MANAGER,models.Role.PRODUCTION_PIC,models.Role.CFO_MANAGER))):
    query = db.query(models.BOMItem)
    if order_fk is not None:
        query = query.join(models.Article).filter(models.Article.order_fk == order_fk)
    return query.order_by(models.BOMItem.id).all()


@router.post("/coo/bom")
def create_bom(data:BOMIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER))):
    x=models.BOMItem(**data.model_dump()); db.add(x); commit_changes(db,user); db.refresh(x); return x


@router.get("/coo/material-consumptions")
def list_consumptions(order_fk:Optional[int]=None, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO,models.Role.COO_MANAGER,models.Role.PRODUCTION_PIC,models.Role.CFO_MANAGER))):
    query = db.query(models.MaterialConsumption)
    if order_fk is not None:
        query = query.join(models.BOMItem).join(models.Article).filter(models.Article.order_fk == order_fk)
    return query.order_by(models.MaterialConsumption.id).all()


@router.post("/coo/material-consumptions")
def create_consumption(data:ConsumptionIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER,models.Role.PRODUCTION_PIC))):
    x=models.MaterialConsumption(**data.model_dump(),recorded_by_id=user.id); db.add(x); commit_changes(db,user); db.refresh(x); return x


@router.get("/coo/production-costs")
def list_production_costs(order_fk:Optional[int]=None, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO,models.Role.COO_MANAGER,models.Role.CFO_MANAGER))):
    query=db.query(models.ProductionCostEntry)
    if order_fk is not None:
        query=query.join(models.Article).filter(models.Article.order_fk == order_fk)
    return query.order_by(models.ProductionCostEntry.id).all()


@router.post("/coo/production-costs")
def create_production_cost(data:ProductionCostIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER,models.Role.CFO_MANAGER))):
    x=models.ProductionCostEntry(**data.model_dump(),recorded_by_id=user.id); db.add(x); commit_changes(db,user); db.refresh(x); return x


def cost_report(db, order):
    rows=[]; total_planned=Decimal(0); total_actual=Decimal(0)
    for article in order.articles:
        planned=Decimal(0); material=Decimal(0); other=Decimal(0)
        items=db.query(models.BOMItem).filter_by(article_id=article.id).all()
        complete=bool(items)
        for item in items:
            planned += Decimal(article.qty) * Decimal(item.qty_per_unit) * Decimal(item.planned_unit_cost)
            consumed=Decimal(0)
            for usage in db.query(models.MaterialConsumption).filter_by(bom_item_id=item.id).all():
                consumed += Decimal(usage.qty)
                material += Decimal(usage.qty) * Decimal(usage.actual_unit_cost)
            complete = complete and consumed >= Decimal(article.qty) * Decimal(item.qty_per_unit)
        for entry in db.query(models.ProductionCostEntry).filter_by(article_id=article.id).all():
            other += Decimal(entry.amount)
        total_planned += planned; total_actual += material + other
        rows.append({"article_id":article.id,"article_code":article.article_code,"planned_material_cost":planned,
                     "actual_material_cost":material,"labor_overhead_cost":other,"actual_total_cost":material+other,"cost_complete":complete})
    complete=bool(rows) and all(row["cost_complete"] for row in rows)
    review=db.query(models.CostReview).filter_by(order_fk=order.id).first()
    verified=bool(complete and review and Decimal(review.reviewed_total)==total_actual)
    quote=db.query(models.Quotation).filter_by(order_fk=order.id,status="APPROVED").order_by(models.Quotation.id.desc()).first()
    revenue=Decimal(quote.amount) if quote else None
    return {"order_id":order.order_id,"articles":rows,"planned_material_cost":total_planned,
            "actual_material_cost":sum((r["actual_material_cost"] for r in rows),Decimal(0)),
            "labor_overhead_cost":sum((r["labor_overhead_cost"] for r in rows),Decimal(0)),
            "actual_total_cost":total_actual,"cost_complete":complete,"cost_verified":verified,
            "reviewed_by_id":review.reviewed_by_id if verified else None,
            "revenue":revenue,"actual_margin":revenue-total_actual if verified and revenue is not None else None,
            "actual_margin_percent":((revenue-total_actual)/revenue*100).quantize(Decimal("0.01")) if verified and revenue and revenue>0 else None}


@router.get("/coo/actual-cost/{order_id}")
def actual_cost(order_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO,models.Role.COO_MANAGER,models.Role.CFO_MANAGER))):
    order = get_or_404(db,models.Order,order_id,"Order not found")
    return cost_report(db,order)


@router.post("/cfo/orders/{order_id}/cost-review")
def review_cost(order_id:int, data:CostReviewIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER))):
    order=db.query(models.Order).filter_by(id=order_id).with_for_update().first()
    if not order:
        raise HTTPException(404,"Order not found")
    report=cost_report(db,order)
    if not report["cost_complete"] or report["revenue"] is None:
        raise HTTPException(400,"Complete BOM consumption and approved quotation required")
    review=db.query(models.CostReview).filter_by(order_fk=order_id).first()
    if review is None:
        review=models.CostReview(order_fk=order_id)
        db.add(review)
    review.reviewed_total=report["actual_total_cost"]
    review.evidence_ref=data.evidence_ref
    review.reviewed_by_id=user.id
    review.reviewed_at=datetime.utcnow()
    from ..audit import log_audit
    db.flush()
    log_audit(db,user,"VERIFY","CostReview",review.id,f"total={review.reviewed_total}; evidence={data.evidence_ref}")
    db.commit()
    return cost_report(db,order)

class MaterialIn(BaseModel):
    order_fk:int; item_name:str; qty:float; unit:Optional[str]=None; required_date:Optional[date]=None

@router.get("/coo/material-requests")
def material_requests(db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","COO_MANAGER","PRODUCTION_PIC","CFO_MANAGER")
    return db.query(models.MaterialRequest).order_by(desc(models.MaterialRequest.id)).all()

@router.post("/coo/material-requests")
def create_material_request(data:MaterialIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER,models.Role.PRODUCTION_PIC))):
    x=models.MaterialRequest(**data.model_dump(),requested_by=user.name); db.add(x); commit_changes(db, user); db.refresh(x); return x

class MaterialRequestUpdate(BaseModel):
    item_name:Optional[str]=None; qty:Optional[float]=None; unit:Optional[str]=None; status:Optional[str]=None; required_date:Optional[date]=None

@router.patch("/coo/material-requests/{mr_id}")
def update_material_request(mr_id:int, data:MaterialRequestUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER,models.Role.PRODUCTION_PIC))):
    return apply_update(get_or_404(db,models.MaterialRequest,mr_id,"Material request not found"), data, db, user)

@router.delete("/coo/material-requests/{mr_id}")
def delete_material_request(mr_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER))):
    x=get_or_404(db,models.MaterialRequest,mr_id); db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ COO: PRODUCTION MOVEMENTS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class MovementIn(BaseModel):
    article_id:int; process:str; qty_in:int=0; qty_done:int=0; qty_reject:int=0; status:str="IN_PROCESS"; pic_name:Optional[str]=None; target_date:Optional[date]=None; reject_reason:Optional[str]=None

class MovementUpdate(BaseModel):
    qty_in:Optional[int]=None; qty_done:Optional[int]=None; qty_reject:Optional[int]=None; status:Optional[str]=None; pic_name:Optional[str]=None; reject_reason:Optional[str]=None; target_date:Optional[date]=None

@router.post("/coo/movements")
def create_movement(data:MovementIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER,models.Role.PRODUCTION_PIC,models.Role.PRINTING_PIC,models.Role.SAMPLE_PIC))):
    if data.qty_done > data.qty_in: raise HTTPException(400,"qty_done cannot exceed qty_in")
    x=models.ProductionMovement(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.get("/coo/movements")
def list_movements(limit:int=Query(500,ge=1,le=500), offset:int=Query(0,ge=0), db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","COO_MANAGER","PRODUCTION_PIC","PRINTING_PIC","SAMPLE_PIC","CMO_MANAGER")
    return db.query(models.ProductionMovement).order_by(desc(models.ProductionMovement.id)).offset(offset).limit(limit).all()

@router.patch("/coo/movements/{mov_id}")
def update_movement(mov_id:int, data:MovementUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER,models.Role.PRODUCTION_PIC))):
    return apply_update(get_or_404(db,models.ProductionMovement,mov_id,"Movement not found"), data, db, user)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ COO: PRODUCTION PLANS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class PlanIn(BaseModel):
    order_fk:int; plan_date:Optional[date]=None; status:str="PLANNING"; notes:Optional[str]=None

class PlanUpdate(BaseModel):
    order_fk:Optional[int]=None; plan_date:Optional[date]=None; status:Optional[str]=None; notes:Optional[str]=None

@router.get("/coo/production-plans")
def list_plans(db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","COO_MANAGER","PRODUCTION_PIC","PRINTING_PIC","CFO_MANAGER","CMO_MANAGER")
    return db.query(models.ProductionPlan).order_by(desc(models.ProductionPlan.id)).all()

@router.post("/coo/production-plans")
def create_plan(data:PlanIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER))):
    x=models.ProductionPlan(**data.model_dump(), created_by_id=user.id); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/coo/production-plans/{plan_id}")
def update_plan(plan_id:int, data:PlanUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER))):
    return apply_update(get_or_404(db,models.ProductionPlan,plan_id,"Plan not found"), data, db, user, "ProductionPlan")

@router.delete("/coo/production-plans/{plan_id}")
def delete_plan(plan_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER))):
    x=get_or_404(db,models.ProductionPlan,plan_id,"Plan not found"); db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ COO: WIP SUMMARY â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.get("/coo/wip-summary")
def wip_summary(db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","COO_MANAGER","PRODUCTION_PIC","PRINTING_PIC","SAMPLE_PIC","CMO_MANAGER")
    from sqlalchemy import func
    rows=db.query(models.ProductionMovement.process,
        func.sum(models.ProductionMovement.qty_in).label("qty_in"),
        func.sum(models.ProductionMovement.qty_done).label("qty_done"),
        func.sum(models.ProductionMovement.qty_reject).label("qty_reject")
    ).group_by(models.ProductionMovement.process).all()
    return [{"process":r.process,"qty_in":int(r.qty_in or 0),"qty_done":int(r.qty_done or 0),"qty_reject":int(r.qty_reject or 0),"wip":int((r.qty_in or 0)-(r.qty_done or 0)-(r.qty_reject or 0))} for r in rows]

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ COO: QC RECORDS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class QCIn(BaseModel):
    order_fk:int; article_code:str; process:str; total_checked:int=0; total_pass:int=0; total_reject:int=0; reject_reason:Optional[str]=None; inspector:Optional[str]=None; status:str="PASS"; rework_parent_id:Optional[int]=None

class QCUpdate(BaseModel):
    total_checked:Optional[int]=None; total_pass:Optional[int]=None; total_reject:Optional[int]=None; reject_reason:Optional[str]=None; inspector:Optional[str]=None; status:Optional[str]=None

@router.get("/coo/qc-records")
def list_qc(limit:int=Query(500,ge=1,le=500), offset:int=Query(0,ge=0), db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","COO_MANAGER","PRODUCTION_PIC","PRINTING_PIC","CMO_MANAGER")
    return db.query(models.QCRecord).order_by(desc(models.QCRecord.id)).offset(offset).limit(limit).all()

@router.post("/coo/qc-records")
def create_qc(data:QCIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER,models.Role.PRODUCTION_PIC))):
    x=models.QCRecord(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/coo/qc-records/{qc_id}")
def update_qc(qc_id:int, data:QCUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER))):
    return apply_update(get_or_404(db,models.QCRecord,qc_id,"QC Record not found"), data, db, user)

@router.delete("/coo/qc-records/{qc_id}")
def delete_qc(qc_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER))):
    x=get_or_404(db,models.QCRecord,qc_id); db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ COO: SHIPMENTS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class ShipmentLineIn(BaseModel):
    article_id:int
    qty:int=Field(gt=0)

class ShipmentIn(BaseModel):
    order_fk:int; shipment_no:str; status:str="PREPARING"; finance_gate:str="PENDING"; ceo_approval:str="NOT_REQUIRED"; notes:Optional[str]=None; tracking_no:Optional[str]=None; shipped_date:Optional[date]=None; delivery_date:Optional[date]=None; packing_status:str="PENDING"
    lines:list[ShipmentLineIn]=Field(default_factory=list)

class ShipmentUpdate(BaseModel):
    status:Optional[str]=None; finance_gate:Optional[str]=None; ceo_approval:Optional[str]=None; notes:Optional[str]=None; tracking_no:Optional[str]=None; shipped_date:Optional[date]=None; delivery_date:Optional[date]=None; packing_status:Optional[str]=None
    lines:Optional[list[ShipmentLineIn]]=None

def shipment_out(shipment):
    fields = ("id", "order_fk", "shipment_no", "status", "finance_gate", "packing_status",
              "finance_assessed_by_id", "approved_outstanding", "ceo_approval", "notes",
              "delivery_date", "shipped_date", "tracking_no", "created_at",
              "line_reconciliation_required")
    lines = [{"id": line.id, "article_id": line.article_id,
              "article_code": line.article.article_code if line.article else None, "qty": line.qty}
             for line in shipment.lines]
    return {**{field: getattr(shipment, field) for field in fields}, "lines": lines,
            "line_total_qty": sum(line["qty"] for line in lines)}

def replace_shipment_lines(shipment, lines):
    article_ids = [line.article_id for line in lines]
    if len(article_ids) != len(set(article_ids)):
        raise HTTPException(400, "Each article may appear only once in a shipment")
    shipment.lines[:] = [models.ShipmentLine(article_id=line.article_id, qty=line.qty) for line in lines]
    shipment.line_reconciliation_required = True

@router.get("/coo/shipments")
def list_shipments(db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","COO_MANAGER","SHIPMENT_ADMIN","CFO_MANAGER","CMO_MANAGER","CMO_SUPPORT")
    return [shipment_out(x) for x in db.query(models.Shipment).order_by(desc(models.Shipment.id)).all()]

@router.get("/coo/shipments/{sh_id}/lines")
def shipment_lines(sh_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","COO_MANAGER","SHIPMENT_ADMIN","CFO_MANAGER","CMO_MANAGER","CMO_SUPPORT")
    return shipment_out(get_or_404(db, models.Shipment, sh_id, "Shipment not found"))["lines"]

@router.post("/coo/shipments")
def create_shipment(data:ShipmentIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER,models.Role.SHIPMENT_ADMIN))):
    x=models.Shipment(**data.model_dump(exclude={"lines"}), line_reconciliation_required=True)
    replace_shipment_lines(x, data.lines)
    db.add(x); commit_changes(db, user); db.refresh(x); return shipment_out(x)

@router.patch("/coo/shipments/{sh_id}")
def update_shipment(sh_id:int, data:ShipmentUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER,models.Role.SHIPMENT_ADMIN))):
    if {"finance_gate", "ceo_approval"}.intersection(data.model_fields_set):
        raise HTTPException(403, "Use CFO and CEO approval endpoints")
    if role(user) != "COO_MANAGER" and (data.status == "DELIVERED" or "delivery_date" in data.model_fields_set):
        raise HTTPException(403, "Only COO Manager may record physical handover")
    x = get_or_404(db, models.Shipment, sh_id, "Shipment not found")
    if data.lines is not None:
        if x.status in ("SHIPPED", "DELIVERED"):
            raise HTTPException(400, "Dispatched shipment lines cannot be changed")
        replace_shipment_lines(x, data.lines)
    for key, value in data.model_dump(exclude_unset=True, exclude={"lines"}).items():
        setattr(x, key, value)
    # Historical headers stay readable as legacy data.  The moment an operator
    # re-packs or dispatches one, its quantities must be explicitly reconciled.
    if data.packing_status == "PACKED" or data.status in ("SHIPPED", "DELIVERED"):
        x.line_reconciliation_required = True
    commit_changes(db, user); db.refresh(x)
    return shipment_out(x)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CFO: SHIPMENT GATE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class ShipmentFinanceGateIn(BaseModel):
    action:str
    reason:Optional[str]=None

@router.post("/cfo/shipments/{shipment_id}/gate")
def cfo_shipment_gate(shipment_id:int, data:ShipmentFinanceGateIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER))):
    if data.action not in ("APPROVE", "REJECT"):
        raise HTTPException(400, "action must be APPROVE or REJECT")
    x = db.query(models.Shipment).filter_by(id=shipment_id).with_for_update().first()
    if not x:
        raise HTTPException(404, "Shipment not found")
    if x.status in ("SHIPPED", "DELIVERED"):
        raise HTTPException(400, "Cannot reassess a dispatched shipment")
    total, paid = invoices_total(db, x.order_fk)
    if data.action == "APPROVE" and total <= 0:
        raise HTTPException(400, "An invoice is required for finance assessment")
    x.finance_assessed_by_id = user.id
    x.approved_outstanding = None
    x.ceo_approval = "PENDING" if total > paid and data.action == "APPROVE" else "NOT_REQUIRED"
    x.finance_gate = "CLEAR" if data.action == "APPROVE" and total <= paid else "HOLD"
    if data.action == "REJECT":
        x.ceo_approval = "NOT_REQUIRED"
    db.info["shipment_approval"] = True
    commit_changes(db, user)
    db.refresh(x)
    return x
class ShipmentGateIn(BaseModel):
    finance_gate:str
    ceo_approval:Optional[str]=None

@router.patch("/cfo/shipments/{shipment_id}/gate")
def shipment_gate(shipment_id:int, data:ShipmentGateIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER))):
    if data.ceo_approval is not None:
        raise HTTPException(403, "Only CEO may record CEO approval")
    if data.finance_gate not in ("CLEAR", "HOLD"):
        raise HTTPException(400, "finance_gate must be CLEAR or HOLD")
    return cfo_shipment_gate(shipment_id, ShipmentFinanceGateIn(action="APPROVE" if data.finance_gate == "CLEAR" else "REJECT"), db, user)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CHRO: EMPLOYEES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class EmployeeIn(BaseModel):
    employee_no:str; name:str; division:Optional[str]=None; position:Optional[str]=None; employment_status:str="ACTIVE"

@router.get("/chro/employees")
def employees(db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER,models.Role.HR_SUPPORT,models.Role.CEO))):
    return db.query(models.Employee).order_by(models.Employee.name).all()

@router.post("/chro/employees")
def create_employee(data:EmployeeIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER,models.Role.HR_SUPPORT))):
    x=models.Employee(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/chro/employees/{emp_id}")
def update_employee(emp_id:int, data:EmployeeIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER))):
    return apply_update(get_or_404(db,models.Employee,emp_id,"Employee not found"), data, db, user)

@router.delete("/chro/employees/{emp_id}")
def delete_employee(emp_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER))):
    x=get_or_404(db,models.Employee,emp_id); db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CHRO: TRAININGS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class TrainingIn(BaseModel):
    employee_id:int; title:str; start_date:Optional[date]=None; end_date:Optional[date]=None; result:Optional[str]=None; evaluator:Optional[str]=None

class TrainingUpdate(BaseModel):
    title:Optional[str]=None; start_date:Optional[date]=None; end_date:Optional[date]=None; result:Optional[str]=None; evaluator:Optional[str]=None

@router.get("/chro/trainings")
def trainings(db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER,models.Role.HR_SUPPORT,models.Role.CEO))):
    return db.query(models.TrainingRecord).order_by(desc(models.TrainingRecord.id)).all()

@router.post("/chro/trainings")
def create_training(data:TrainingIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER,models.Role.HR_SUPPORT))):
    x=models.TrainingRecord(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/chro/trainings/{tr_id}")
def update_training(tr_id:int, data:TrainingUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER))):
    return apply_update(get_or_404(db,models.TrainingRecord,tr_id,"Training not found"), data, db, user)

@router.delete("/chro/trainings/{tr_id}")
def delete_training(tr_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER))):
    x=get_or_404(db,models.TrainingRecord,tr_id); db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CHRO: PERFORMANCES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class PerformanceIn(BaseModel):
    employee_id:int; period:str; quality:Optional[float]=None; responsibility:Optional[float]=None; discipline:Optional[float]=None; spiritual:Optional[float]=None; attitude:Optional[float]=None; skill:Optional[float]=None; notes:Optional[str]=None

@router.get("/chro/performances")
def performances(db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER,models.Role.HR_SUPPORT,models.Role.CEO))):
    return db.query(models.PerformanceRecord).order_by(desc(models.PerformanceRecord.id)).all()

@router.post("/chro/performances")
def create_performance(data:PerformanceIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER))):
    scores=[v for v in [data.quality,data.responsibility,data.discipline,data.spiritual,data.attitude,data.skill] if v is not None]
    total=round(sum(scores)/len(scores),2) if scores else 0
    x=models.PerformanceRecord(**data.model_dump(),total_score=total); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/chro/performances/{pr_id}")
def update_performance(pr_id:int, data:PerformanceIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER))):
    x=get_or_404(db,models.PerformanceRecord,pr_id,"Performance not found")
    for k,v in data.model_dump(exclude_unset=True).items(): setattr(x,k,v)
    scores=[v for v in [x.quality,x.responsibility,x.discipline,x.spiritual,x.attitude,x.skill] if v is not None]
    x.total_score=round(sum(scores)/len(scores),2) if scores else 0
    commit_changes(db, user); db.refresh(x); return x

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CHRO: EMPLOYEE ISSUES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class IssueIn(BaseModel):
    employee_id:int; issue_type:str; description:str; severity:str="YELLOW"; status:str="OPEN"; reported_by:Optional[str]=None

class IssueUpdate(BaseModel):
    issue_type:Optional[str]=None; description:Optional[str]=None; severity:Optional[str]=None; status:Optional[str]=None; reported_by:Optional[str]=None

@router.get("/chro/issues")
def list_issues(db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER,models.Role.HR_SUPPORT,models.Role.CEO))):
    return db.query(models.EmployeeIssue).order_by(desc(models.EmployeeIssue.id)).all()

@router.post("/chro/issues")
def create_issue(data:IssueIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER,models.Role.HR_SUPPORT))):
    x=models.EmployeeIssue(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/chro/issues/{iss_id}")
def update_issue(iss_id:int, data:IssueUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER))):
    return apply_update(get_or_404(db,models.EmployeeIssue,iss_id,"Issue not found"), data, db, user)

@router.delete("/chro/issues/{iss_id}")
def delete_issue(iss_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CHRO_MANAGER))):
    x=get_or_404(db,models.EmployeeIssue,iss_id); info=x.issue_type; db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CEO: DECISIONS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class DecisionIn(BaseModel):
    order_fk:Optional[int]=None; decision_type:str; subject:str; decision:Optional[str]=None; reason:Optional[str]=None; owner_name:Optional[str]=None; due_date:Optional[date]=None

class DecisionUpdate(BaseModel):
    decision_type:Optional[str]=None; subject:Optional[str]=None; decision:Optional[str]=None; reason:Optional[str]=None; owner_name:Optional[str]=None; due_date:Optional[date]=None; action_status:Optional[str]=None

@router.get("/ceo/decisions")
def decisions(db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO))):
    return db.query(models.CEODecision).order_by(desc(models.CEODecision.id)).all()

@router.post("/ceo/decisions")
def create_decision(data:DecisionIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO))):
    x=models.CEODecision(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/ceo/decisions/{dec_id}")
def update_decision(dec_id:int, data:DecisionUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO))):
    return apply_update(get_or_404(db,models.CEODecision,dec_id,"Decision not found"), data, db, user)

@router.delete("/ceo/decisions/{dec_id}")
def delete_decision(dec_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO))):
    x=get_or_404(db,models.CEODecision,dec_id); info=x.subject; db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ EXCEPTIONS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class ExceptionIn(BaseModel):
    order_fk:Optional[int]=None; severity:str="YELLOW"; category:str; title:str; owner_role:Optional[str]=None; owner_name:Optional[str]=None; due_date:Optional[date]=None; next_action:Optional[str]=None

class ExceptionUpdate(BaseModel):
    severity:Optional[str]=None; category:Optional[str]=None; title:Optional[str]=None; owner_role:Optional[str]=None; owner_name:Optional[str]=None; due_date:Optional[date]=None; next_action:Optional[str]=None; status:Optional[str]=None

@router.get("/exceptions")
def list_exceptions(db:Session=Depends(get_db), user=Depends(get_current_user)):
    query = db.query(models.ExceptionItem)
    if role(user) != "CEO":
        from sqlalchemy import or_
        query = query.filter(models.ExceptionItem.owner_role == role(user), or_(models.ExceptionItem.owner_name == user.name, models.ExceptionItem.owner_name.is_(None)))
    return query.order_by(desc(models.ExceptionItem.id)).all()

@router.post("/exceptions")
def create_exception(data:ExceptionIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER,models.Role.COO_MANAGER,models.Role.CEO,models.Role.CMO_SUPPORT))):
    x=models.ExceptionItem(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/exceptions/{exc_id}")
def update_exception(exc_id:int, data:ExceptionUpdate, db:Session=Depends(get_db), user=Depends(get_current_user)):
    return apply_update(get_or_404(db,models.ExceptionItem,exc_id,"Exception not found"), data, db, user)

@router.delete("/exceptions/{exc_id}")
def delete_exception(exc_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO))):
    x=get_or_404(db,models.ExceptionItem,exc_id); info=x.title; db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ TASKS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class TaskIn(BaseModel):
    title:str; assigned_to_id:Optional[int]=None; order_fk:Optional[int]=None; due_date:Optional[date]=None

class TaskUpdate(BaseModel):
    title:Optional[str]=None; assigned_to_id:Optional[int]=None; order_fk:Optional[int]=None; due_date:Optional[date]=None; status:Optional[str]=None

@router.get("/tasks")
def list_tasks(db:Session=Depends(get_db), user=Depends(get_current_user)):
    query = db.query(models.Task)
    if role(user) != "CEO":
        query = query.filter(models.Task.assigned_to_id == user.id)
    return query.order_by(desc(models.Task.id)).all()

@router.post("/tasks")
def create_task(data:TaskIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER,models.Role.COO_MANAGER,models.Role.CEO,models.Role.CMO_SUPPORT))):
    x=models.Task(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/tasks/{task_id}")
def update_task(task_id:int, data:TaskUpdate, db:Session=Depends(get_db), user=Depends(get_current_user)):
    return apply_update(get_or_404(db,models.Task,task_id,"Task not found"), data, db, user)

@router.delete("/tasks/{task_id}")
def delete_task(task_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO))):
    x=get_or_404(db,models.Task,task_id); info=x.title; db.delete(x); commit_changes(db, user); return {"ok":True}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ USERS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.get("/users")
def list_users(db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO,models.Role.CMO_MANAGER,models.Role.COO_MANAGER,models.Role.CMO_SUPPORT,models.Role.CHRO_MANAGER))):
    # Directory is limited to roles that assign work (task assignee pickers) or
    # manage staff; other roles only ever see their own tasks and do not need it.
    return [{"id":u.id,"name":u.name,"role":u.role.value} for u in db.query(models.User).filter(models.User.is_active==True).order_by(models.User.name).all()]

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ AUDIT LOG â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.get("/audit-log")
def list_audit_log(limit:int=Query(100,ge=1,le=500), offset:int=Query(0,ge=0), db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO))):
    logs = db.query(models.AuditLog).order_by(desc(models.AuditLog.id)).offset(offset).limit(limit).all()
    result = []
    for l in logs:
        u = db.query(models.User).get(l.user_id) if l.user_id else None
        result.append({
            "id": l.id, "user": u.name if u else "-", "action": l.action,
            "entity": l.entity, "entity_id": l.entity_id, "detail": l.detail,
            "created_at": l.created_at,
        })
    return result


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CEO: SHIPMENT APPROVAL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class ShipmentApprovalIn(BaseModel):
    action:str
    reason:Optional[str]=None

@router.post("/ceo/shipments/{shipment_id}/approve-shipment")
def ceo_approve_shipment(shipment_id:int, data:ShipmentApprovalIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CEO))):
    if data.action not in ("APPROVE", "REJECT"):
        raise HTTPException(400, "action must be APPROVE or REJECT")
    x = db.query(models.Shipment).filter_by(id=shipment_id).with_for_update().first()
    if not x:
        raise HTTPException(404, "Shipment not found")
    if x.status in ("SHIPPED", "DELIVERED"):
        raise HTTPException(400, "Cannot approve a dispatched shipment")
    if not x.finance_assessed_by_id or x.ceo_approval != "PENDING":
        raise HTTPException(400, "CEO approval requires a pending request from CFO assessment")
    if not data.reason or not data.reason.strip():
        raise HTTPException(400, "CEO decision reason is required")
    total, paid = invoices_total(db, x.order_fk)
    x.ceo_approval = "APPROVED" if data.action == "APPROVE" else "REJECTED"
    x.finance_gate = "CLEAR" if data.action == "APPROVE" else "HOLD"
    x.approved_outstanding = max(total - paid, 0) if data.action == "APPROVE" else None
    db.info["shipment_approval"] = True
    from ..audit import log_audit
    log_audit(db, user, "CEO_SHIPMENT_" + data.action, "Shipment", x.id, data.reason)
    commit_changes(db, user)
    db.refresh(x)
    return x

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ COO: DELIVERY CONFIRMATIONS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class DeliveryConfirmIn(BaseModel):
    shipment_fk:int; confirmed_by_customer:Optional[str]=None; confirmation_date:Optional[date]=None; feedback:Optional[str]=None; status:str="PENDING"

class DeliveryConfirmUpdate(BaseModel):
    confirmed_by_customer:Optional[str]=None; confirmation_date:Optional[date]=None; feedback:Optional[str]=None; status:Optional[str]=None

@router.get("/coo/deliveries")
def list_deliveries(db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","CMO_MANAGER","CMO_SUPPORT","CFO_MANAGER","COO_MANAGER","SHIPMENT_ADMIN")
    return db.query(models.DeliveryConfirmation).order_by(desc(models.DeliveryConfirmation.id)).all()

@router.post("/cmo/delivery-confirmations")
def create_delivery_confirmation(data:DeliveryConfirmIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER))):
    x=models.DeliveryConfirmation(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x); return x

@router.patch("/cmo/delivery-confirmations/{del_id}")
def update_delivery_confirmation(del_id:int, data:DeliveryConfirmUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER))):
    return apply_update(get_or_404(db,models.DeliveryConfirmation,del_id,"Delivery not found"), data, db, user, "DeliveryConfirmation")

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ COO: ORDER CLOSING â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class OrderClosingIn(BaseModel):
    order_fk:int; customer_close_status:str="OPEN"; operational_close_status:str="OPEN"; financial_close_status:str="OPEN"; notes:Optional[str]=None

class OrderClosingUpdate(BaseModel):
    customer_close_status:Optional[str]=None; operational_close_status:Optional[str]=None; financial_close_status:Optional[str]=None; notes:Optional[str]=None

def require_closing_scope(data, user, creating=False):
    owned_field = {"CMO_MANAGER": "customer_close_status", "COO_MANAGER": "operational_close_status", "CFO_MANAGER": "financial_close_status"}[role(user)]
    allowed = {owned_field, "notes"} | ({"order_fk"} if creating else set())
    if data.model_fields_set - allowed:
        raise HTTPException(403, "Closing fields belong to their respective owners")

@router.get("/coo/order-closing/{order_id}")
def get_order_closing(order_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    require(user,"CEO","CMO_MANAGER","CFO_MANAGER","COO_MANAGER")
    rec = db.query(models.OrderClosing).filter(models.OrderClosing.order_fk==order_id).order_by(desc(models.OrderClosing.id)).first()
    if not rec: raise HTTPException(404,"No closing record for this order")
    return rec

@router.post("/coo/order-closing/{order_id}")
def create_order_closing(order_id:int, data:OrderClosingIn, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER,models.Role.COO_MANAGER,models.Role.CFO_MANAGER))):
    require_closing_scope(data, user, creating=True)
    if data.order_fk != order_id:
        raise HTTPException(400, "Closing order does not match URL")
    x=models.OrderClosing(**data.model_dump()); db.add(x); commit_changes(db, user); db.refresh(x)

    return x

@router.patch("/coo/order-closing/{order_id}")
def update_order_closing(order_id:int, data:OrderClosingUpdate, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER,models.Role.COO_MANAGER,models.Role.CFO_MANAGER))):
    require_closing_scope(data, user)
    rec = db.query(models.OrderClosing).filter(models.OrderClosing.order_fk==order_id).order_by(desc(models.OrderClosing.id)).first()
    if not rec: raise HTTPException(404,"No closing record for this order")
    return apply_update(rec, data, db, user, "OrderClosing")

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ COO: RELEASE TO PURCHASING â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post("/coo/release-to-purchasing/{material_request_id}")
def release_to_purchasing(material_request_id:int, db:Session=Depends(get_db), user=Depends(require_roles(models.Role.COO_MANAGER))):
    mr = get_or_404(db,models.MaterialRequest,material_request_id,"Material request not found")
    if mr.status not in ("REQUESTED","APPROVED"):
        raise HTTPException(400,"Material request must be REQUESTED or APPROVED")
    po_no = f"PO-{mr.id:05d}"
    po = models.PurchaseOrder(
        po_no=po_no, order_fk=mr.order_fk, item=mr.item_name,
        qty=mr.qty, unit=mr.unit, amount=0, status="PENDING"
    )
    db.add(po)
    mr.status = "ORDERED"
    commit_changes(db, user); db.refresh(po)

    return {"ok":True, "po_id":po.id, "po_no":po_no}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CFO: OUTSTANDING CALCULATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.get("/cfo/outstanding-summary")
def outstanding_summary(db:Session=Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER,models.Role.CEO))):
    from sqlalchemy import func
    rows = db.query(
        models.Invoice.order_fk,
        func.sum(models.Invoice.amount).label("total_amount"),
        func.sum(models.Invoice.paid_amount).label("total_paid"),
    ).group_by(models.Invoice.order_fk).all()
    result = []
    for r in rows:
        order = db.query(models.Order).get(r.order_fk) if r.order_fk else None
        outstanding = float(r.total_amount or 0) - float(r.total_paid or 0)
        result.append({
            "order_id": order.order_id if order else "-",
            "buyer": order.buyer if order else "-",
            "total_amount": float(r.total_amount or 0),
            "total_paid": float(r.total_paid or 0),
            "outstanding": outstanding,
        })
    return result

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ FLOW ENGINE ENDPOINTS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from ..flow_engine import FlowEngine

@router.get("/orders/{order_id}/flow")
def get_order_flow(order_id: str, db: Session = Depends(get_db), user = Depends(get_current_user)):
    require(user,"CEO","CMO_MANAGER","CMO_SUPPORT","CFO_MANAGER","FINANCE_SUPPORT","COO_MANAGER","PRODUCTION_PIC","PRINTING_PIC","SAMPLE_PIC","SHIPMENT_ADMIN")
    """Returns flow definition + current step + progress + validation for next steps."""
    order = db.query(models.Order).filter(models.Order.order_id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    order_type_val = order.order_type.value if hasattr(order.order_type, "value") else order.order_type
    current_step = order.flow_step or "ORDER"
    progress = FlowEngine.get_flow_progress(order_type_val, current_step)
    # Validate which steps can be advanced to
    next_steps = []
    for step_info in progress["steps"]:
        if step_info["key"] == current_step:
            continue
        ok, reason = FlowEngine.can_transition(order, step_info["key"])
        next_steps.append({"step": step_info["key"], "label": step_info["label"], "can_advance": ok, "reason": reason})
    return {
        "order_id": order.order_id,
        "order_type": order_type_val,
        "current_step": current_step,
        "current_label": FlowEngine.VALID_STEPS.get(order_type_val, []),
        "progress": progress,
        "next_steps": next_steps,
    }

class FlowAdvanceIn(BaseModel):
    target_step: str

@router.post("/orders/{order_id}/flow/advance")
def advance_order_flow(order_id: str, data: FlowAdvanceIn, db: Session = Depends(get_db), user = Depends(get_current_user)):
    """Advance order to target_step with validation."""
    order = db.query(models.Order).filter(models.Order.order_id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    result = FlowEngine.advance(order, data.target_step, user=user)
    return result

@router.get("/flow-definitions")
def flow_definitions(user = Depends(get_current_user)):
    """Returns all three flow definitions with step labels (for frontend)."""
    return FlowEngine.get_all_definitions()


@router.delete("/cmo/samples/{s_id}")
def delete_sample(s_id: int, db: Session = Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER))):
    obj = get_or_404(db, models.SampleRecord, s_id, "Sample not found")
    db.delete(obj)
    commit_changes(db, user)
    return {"ok": True}


@router.get("/coo/order-closing")
def list_order_closings(db: Session = Depends(get_db), user=Depends(require_roles(models.Role.CMO_MANAGER, models.Role.CFO_MANAGER, models.Role.COO_MANAGER, models.Role.CEO))):
    return db.query(models.OrderClosing).order_by(desc(models.OrderClosing.id)).all()


class FinanceAssessmentIn(BaseModel):
    action: str
    reason: str
    term_kind: Optional[str] = None
    required_dp_amount: Optional[Decimal] = None
    evidence_ref: Optional[str] = None
    credit_due_date: Optional[date] = None


@router.post("/cfo/orders/{order_id}/finance-gate")
def assess_order_finance(order_id: int, data: FinanceAssessmentIn, db: Session = Depends(get_db), user=Depends(require_roles(models.Role.CFO_MANAGER))):
    if data.action not in ("APPROVE", "REJECT") or not data.reason.strip():
        raise HTTPException(400, "Valid action and documented payment terms/DP assessment required")
    order = get_or_404(db, models.Order, order_id, "Order not found")
    if order.overall_status == "CLOSED":
        raise HTTPException(400, "Closed order is immutable")
    total, _ = invoices_total(db, order.id)
    if data.action == "APPROVE" and (total <= 0 or not quotation_ready(db, order) or not invoices_reconciled(db, order.id)):
        raise HTTPException(400, "Approved quotation and reconciled invoices are required")
    if data.action == "APPROVE":
        policy = get_policy(db)
        _, paid = invoices_total(db, order.id)
        if data.term_kind not in ("FULL", "DP", "CREDIT") or not data.evidence_ref or not data.evidence_ref.strip():
            raise HTTPException(400, "Payment term type and evidence reference are required")
        required = data.required_dp_amount
        if data.term_kind == "FULL" and paid < total:
            raise HTTPException(400, "Full-payment terms require cleared payment")
        if data.term_kind == "DP":
            if required is None or not required.is_finite() or required <= 0 or required > total:
                raise HTTPException(400, "Valid required DP amount is needed")
            if required * 100 < total * policy.minimum_dp_percent or paid < required:
                raise HTTPException(400, "Recorded payment does not satisfy configured DP policy")
        if data.term_kind == "CREDIT" and (not policy.allow_credit_terms or not data.credit_due_date):
            raise HTTPException(400, "Credit terms are disabled or missing a due date")
        order.finance_term_kind = data.term_kind
        order.required_dp_amount = required if data.term_kind == "DP" else None
        order.payment_evidence_ref = data.evidence_ref.strip()
        order.credit_due_date = data.credit_due_date if data.term_kind == "CREDIT" else None
    order.finance_gate_status = "APPROVED" if data.action == "APPROVE" else "HOLD"
    order.finance_gate_notes = data.reason.strip()
    order.finance_verified_by_id = user.id
    commit_changes(db, user)
    return {"order_fk": order.id, "finance_gate_status": order.finance_gate_status, "finance_gate_notes": order.finance_gate_notes}
