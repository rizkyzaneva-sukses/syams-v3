"""Customer PO inbox: CMO Support prepares, CMO Manager reviews and activates."""
import json
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from ..audit import log_audit
from ..auth import require_roles
from ..database import get_db
from ..models import Customer, OrderType, POIntake, Role, User
from ..schemas import ArticleCreate, OrderCreate
from .orders import create_order_record

router = APIRouter(prefix="/cmo/po-intake", tags=["po-intake"])
READ_ROLES = (Role.CMO_SUPPORT, Role.CMO_MANAGER, Role.CEO)
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
EDITABLE = {"DRAFT", "NEEDS_INFO", "READY"}


class PODraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    po_number: str | None = Field(default=None, max_length=100)
    buyer: str | None = Field(default=None, max_length=160)
    customer_id: int | None = None
    order_type: OrderType | None = None
    buyer_deadline: date | None = None
    articles: list[ArticleCreate] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=5000)
    follow_up_note: str | None = Field(default=None, max_length=2000)


class POChange(PODraft):
    pass


class POReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["ACCEPT", "REJECT"]
    note: str = Field(default="", max_length=2000)


def po_out(po: POIntake) -> dict:
    return {
        "id": po.id, "po_number": po.po_number, "buyer": po.buyer,
        "customer_id": po.customer_id, "order_type": po.order_type,
        "buyer_deadline": po.buyer_deadline, "articles": json.loads(po.articles_json),
        "notes": po.notes, "has_document": bool(po.document_name),
        "document_name": po.document_name, "status": po.status,
        "missing_items": json.loads(po.missing_items_json),
        "follow_up_note": po.follow_up_note, "review_note": po.review_note,
        "created_by_id": po.created_by_id, "reviewed_by_id": po.reviewed_by_id,
        "reviewed_at": po.reviewed_at, "order_fk": po.order_fk,
        "order_id": po.order.order_id if po.order else None,
        "received_at": po.received_at, "created_at": po.created_at,
        "updated_at": po.updated_at,
    }


def missing_items(po: POIntake) -> list[str]:
    missing = []
    for field, label in (("po_number", "Nomor PO"), ("buyer", "Buyer"),
                         ("order_type", "Tipe order"), ("buyer_deadline", "Deadline buyer")):
        if not getattr(po, field):
            missing.append(label)
    articles = json.loads(po.articles_json)
    if not articles:
        missing.append("Minimal satu article")
    else:
        codes = [a["article_code"].strip() for a in articles]
        if any(not code for code in codes) or len(set(codes)) != len(codes):
            missing.append("Kode article unik dan tidak kosong")
        if po.order_type != OrderType.SAMPLE_ONLY.value and any(not (a.get("production_route") or "").strip() for a in articles):
            missing.append("Rute produksi setiap article")
    if not po.document_data:
        missing.append("Dokumen PO (PDF/JPG/PNG)")
    return missing


def load_po(db: Session, po_id: int, lock: bool = False) -> POIntake:
    query = db.query(POIntake).filter_by(id=po_id)
    if lock:
        query = query.with_for_update()
    po = query.first()
    if po is None:
        raise HTTPException(404, "PO intake not found")
    return po


def require_editable(po: POIntake):
    if po.status not in EDITABLE:
        raise HTTPException(409, "Submitted or reviewed PO cannot be edited")


def apply_draft(po: POIntake, payload: PODraft, db: Session):
    values = payload.model_dump(exclude_unset=True)
    if "customer_id" in values and values["customer_id"] is not None and db.get(Customer, values["customer_id"]) is None:
        raise HTTPException(404, "Customer not found")
    for field in ("po_number", "buyer", "notes", "follow_up_note"):
        if field in values:
            value = values[field]
            setattr(po, field, value.strip() or None if isinstance(value, str) else value)
    if "customer_id" in values:
        po.customer_id = values["customer_id"]
    if "order_type" in values:
        po.order_type = values["order_type"].value if values["order_type"] else None
    if "buyer_deadline" in values:
        po.buyer_deadline = values["buyer_deadline"]
    if "articles" in values:
        po.articles_json = json.dumps([a.model_dump(mode="json") for a in payload.articles])
    po.status = "DRAFT"
    po.missing_items_json = json.dumps(missing_items(po), ensure_ascii=False)


def commit_or_conflict(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This buyer and PO number are already registered") from exc


@router.get("")
def list_po_intake(limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
                   db: Session = Depends(get_db), user: User = Depends(require_roles(*READ_ROLES))):
    rows = (db.query(POIntake).options(defer(POIntake.document_data))
            .order_by(POIntake.id.desc()).offset(offset).limit(limit).all())
    return [po_out(row) for row in rows]


@router.get("/{po_id}")
def get_po_intake(po_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*READ_ROLES))):
    return po_out(load_po(db, po_id))


@router.post("", status_code=201)
def create_po_intake(payload: PODraft, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.CMO_SUPPORT))):
    po = POIntake(created_by_id=user.id, articles_json="[]", missing_items_json="[]")
    db.add(po)
    apply_draft(po, payload, db)
    db.flush()
    log_audit(db, user, "CREATE_DRAFT", "POIntake", po.id, po.po_number or "Incomplete PO")
    commit_or_conflict(db)
    db.refresh(po)
    return po_out(po)


@router.patch("/{po_id}")
def update_po_intake(po_id: int, payload: POChange, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.CMO_SUPPORT))):
    po = load_po(db, po_id, lock=True)
    require_editable(po)
    apply_draft(po, payload, db)
    log_audit(db, user, "UPDATE_DRAFT", "POIntake", po.id, ", ".join(sorted(payload.model_fields_set)))
    commit_or_conflict(db)
    db.refresh(po)
    return po_out(po)


@router.post("/{po_id}/document")
async def upload_po_document(po_id: int, document: UploadFile = File(...), db: Session = Depends(get_db),
                             user: User = Depends(require_roles(Role.CMO_SUPPORT))):
    po = load_po(db, po_id, lock=True)
    require_editable(po)
    data = await document.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "PO document exceeds 10 MB")
    mime = ("application/pdf" if data.startswith(b"%PDF-") else
            "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else
            "image/jpeg" if data.startswith(b"\xff\xd8\xff") else None)
    if mime is None:
        raise HTTPException(415, "Upload a PDF, PNG, or JPG PO document")
    name = (document.filename or "PO document").replace("\\", "/").split("/")[-1][:255]
    po.document_name = name
    po.document_mime = mime
    po.document_data = data
    po.status = "DRAFT"
    po.missing_items_json = json.dumps(missing_items(po), ensure_ascii=False)
    log_audit(db, user, "UPLOAD_DOCUMENT", "POIntake", po.id, name)
    db.commit()
    db.refresh(po)
    return po_out(po)


@router.get("/{po_id}/document")
def get_po_document(po_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*READ_ROLES))):
    po = load_po(db, po_id)
    if not po.document_data:
        raise HTTPException(404, "PO document not uploaded")
    return Response(content=po.document_data, media_type=po.document_mime,
                    headers={"Content-Disposition": 'attachment; filename="po-document"',
                             "X-Content-Type-Options": "nosniff"})


@router.post("/{po_id}/check")
def check_po_intake(po_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(Role.CMO_SUPPORT))):
    po = load_po(db, po_id, lock=True)
    require_editable(po)
    missing = missing_items(po)
    po.missing_items_json = json.dumps(missing, ensure_ascii=False)
    po.status = "NEEDS_INFO" if missing else "READY"
    log_audit(db, user, "CHECK_COMPLETENESS", "POIntake", po.id, ", ".join(missing) or "Complete")
    db.commit()
    db.refresh(po)
    return po_out(po)


@router.post("/{po_id}/submit")
def submit_po_intake(po_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.CMO_SUPPORT))):
    po = load_po(db, po_id, lock=True)
    if po.status != "READY":
        raise HTTPException(409, "Check completeness before submitting PO")
    missing = missing_items(po)
    if missing:
        raise HTTPException(409, "PO is incomplete: " + ", ".join(missing))
    po.status = "SUBMITTED"
    log_audit(db, user, "SUBMIT_REVIEW", "POIntake", po.id, po.po_number)
    db.commit()
    db.refresh(po)
    return po_out(po)


@router.post("/{po_id}/review")
def review_po_intake(po_id: int, payload: POReview, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.CMO_MANAGER))):
    po = load_po(db, po_id, lock=True)
    if po.status != "SUBMITTED":
        raise HTTPException(409, "Only a submitted PO can be reviewed")
    note = payload.note.strip()
    if payload.action == "REJECT" and not note:
        raise HTTPException(422, "A rejection reason is required")
    order = None
    if payload.action == "ACCEPT":
        missing = missing_items(po)
        if missing:
            raise HTTPException(409, "PO is incomplete: " + ", ".join(missing))
        order_payload = OrderCreate(
            buyer=po.buyer, customer_id=po.customer_id, order_type=po.order_type,
            buyer_deadline=po.buyer_deadline, notes=po.notes,
            articles=[ArticleCreate.model_validate(a) for a in json.loads(po.articles_json)],
        )
        order = create_order_record(order_payload, db, user)
        po.order_fk = order.id
        po.status = "ACCEPTED"
        log_audit(db, user, "CREATE_FROM_PO", "Order", order.id, f"POIntake {po.id}: {order.order_id}")
    else:
        po.status = "REJECTED"
    po.review_note = note or None
    po.reviewed_by_id = user.id
    po.reviewed_at = datetime.utcnow()
    log_audit(db, user, payload.action, "POIntake", po.id, note or (order.order_id if order else ""))
    commit_or_conflict(db)
    db.refresh(po)
    return po_out(po)
