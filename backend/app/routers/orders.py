from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..models import Order, Article, Role, User
from ..schemas import OrderCreate, OrderOut
from ..auth import get_current_user, require_roles

router = APIRouter(prefix="/orders", tags=["orders"])
ORDER_READ_ROLES = (Role.CEO, Role.CMO_MANAGER, Role.CMO_SUPPORT, Role.CFO_MANAGER,
                    Role.FINANCE_SUPPORT, Role.COO_MANAGER, Role.SAMPLE_PIC,
                    Role.PRINTING_PIC, Role.PRODUCTION_PIC, Role.SHIPMENT_ADMIN)

@router.get("", response_model=list[OrderOut])
def list_orders(limit:int=Query(500,ge=1,le=500), offset:int=Query(0,ge=0), db: Session = Depends(get_db), user: User = Depends(require_roles(*ORDER_READ_ROLES))):
    return db.query(Order).options(joinedload(Order.articles)).order_by(Order.buyer_deadline.asc().nullslast(), Order.id).offset(offset).limit(limit).all()

@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*ORDER_READ_ROLES))):
    order = db.query(Order).options(joinedload(Order.articles)).filter(Order.order_id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

def create_order_record(payload: OrderCreate, db: Session, user: User) -> Order:
    """Create an Order inside the accepting PO transaction; caller commits."""
    from uuid import uuid4
    from ..models import Customer
    # UUID-backed identifiers do not race or rely on lexical max ordering.
    customer = db.get(Customer, payload.customer_id) if payload.customer_id else db.query(Customer).filter_by(name=payload.buyer).first()
    if payload.customer_id and not customer:
        raise HTTPException(404, "Customer not found")
    if not customer:
        customer = Customer(name=payload.buyer)
        db.add(customer)
    db.flush()
    order = Order(order_id=f"SO-{uuid4().hex[:16].upper()}", buyer=customer.name,
        customer_id=customer.id, order_type=payload.order_type,
        buyer_deadline=payload.buyer_deadline, notes=payload.notes, created_by_id=user.id)
    for article in payload.articles:
        order.articles.append(Article(**article.model_dump(), sample_status="PROCESS" if article.sample_required else "NOT_REQUIRED"))
    db.add(order)
    db.flush()
    return order


@router.post("")
def create_order_directly(user: User = Depends(get_current_user)):
    raise HTTPException(403, "Create a PO intake draft and obtain CMO Manager acceptance to activate an Order")


def customer_safe_stage(order: Order) -> str:
    if order.overall_status == "CLOSED":
        return "Pesanan selesai"
    if order.shipment_status in ("SHIPPED", "DELIVERED"):
        return "Pesanan telah dikirim"
    if order.shipment_status in ("READY", "PACKED"):
        return "Pesanan siap dikirim"
    any_produced = any(a.production_status in ("DONE", "PRODUCED", "IN_PROCESS") for a in order.articles)
    if any_produced:
        return "Pesanan sedang diproduksi"
    if order.spk_status == "RELEASED":
        return "Pesanan siap diproduksi"
    if any(a.sample_required and a.sample_status == "PROCESS" for a in order.articles):
        return "Sampel sedang diproses"
    if order.finance_gate_status in ("PENDING", "HOLD", "UNPAID"):
        return "Menunggu proses pembayaran"
    return "Pesanan sedang diverifikasi"


@router.get("/{order_id}/customer-tracking")
@router.get("/{order_id}/customer-status")
def customer_tracking(order_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Customer-safe tracking bridge (INT-ORDER-001 poin 6, 7, 8).
    Accessible by customers and internal users. Excludes all sensitive internal
    financial and production details (no HPP, margin, supplier costs, employee notes).
    """
    order = db.query(Order).options(joinedload(Order.articles)).filter(Order.order_id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    finance_label = "Pembayaran lunas" if order.finance_status == "PAID" else (
        "Pembayaran sebagian diterima" if order.finance_status == "PARTIAL" else "Menunggu pembayaran"
    )
    shipment_label = "Pesanan telah dikirim" if order.shipment_status in ("SHIPPED", "DELIVERED") else (
        "Pesanan siap dikirim" if order.shipment_status in ("READY", "PACKED") else (
            "Pesanan sedang disiapkan" if order.shipment_status == "PREPARING" else "Belum siap dikirim"
        )
    )

    from ..models import AuditLog
    history_logs = db.query(AuditLog).filter(
        (AuditLog.order_id == order.order_id) |
        ((AuditLog.entity == "Order") & (AuditLog.entity_id == order.id))
    ).order_by(AuditLog.id.asc()).limit(10).all()

    history = [{
        "action": log.action,
        "timestamp": log.created_at.isoformat() + "Z" if log.created_at else None,
        "status": customer_safe_stage(order)
    } for log in history_logs]

    return {
        "order_id": order.order_id,
        "buyer": order.buyer,
        "articles": [{"code": a.article_code, "qty": a.qty} for a in order.articles],
        "tahap": customer_safe_stage(order),
        "status_customer": customer_safe_stage(order),
        "projected_shipment": order.projected_shipment.isoformat() if order.projected_shipment else None,
        "status_pembayaran_sederhana": finance_label,
        "shipment": shipment_label,
        "resi": getattr(order, "resi", None) or getattr(order, "tracking_no", None),
        "updated_at": (order.updated_at or order.created_at).isoformat() + "Z" if (order.updated_at or order.created_at) else None,
        "riwayat_status": history,
    }
