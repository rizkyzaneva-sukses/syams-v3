"""Shared operational views; quantities come from transactions, not demo snapshots."""
from datetime import date, datetime, timezone, timedelta
from math import ceil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Order, ExceptionItem, CapacitySnapshot, ProductionMovement, ProductionPlan, Article, User, Role
from ..workflow import route_for
from ..auth import get_current_user, require_roles
from ..audit import log_audit

router = APIRouter(prefix="/master", tags=["master"])
MASTER_ROLES = (Role.CEO, Role.CMO_MANAGER, Role.CMO_SUPPORT, Role.CFO_MANAGER,
                Role.FINANCE_SUPPORT, Role.COO_MANAGER, Role.SAMPLE_PIC,
                Role.PRINTING_PIC, Role.PRODUCTION_PIC, Role.SHIPMENT_ADMIN)


def forecast_row(db, order):
    projection = order.projected_shipment
    source = "MANUAL" if projection else "NOT_SET"
    if not projection and order.articles:
        needs = {}
        for article in order.articles:
            for process in route_for(article):
                completed = db.query(func.coalesce(func.sum(ProductionMovement.qty_done), 0)).filter(
                    ProductionMovement.article_id == article.id,
                    func.upper(ProductionMovement.process) == process).scalar() or 0
                needs[process] = needs.get(process, 0) + max(article.qty - int(completed), 0)
        days = 0
        for process, remaining in needs.items():
            if remaining <= 0:
                continue
            snapshot = db.query(CapacitySnapshot).filter(CapacitySnapshot.process == process,
                CapacitySnapshot.snapshot_date == date.today(), CapacitySnapshot.capacity > 0).order_by(CapacitySnapshot.id.desc()).first()
            if not snapshot:
                break
            days += ceil(remaining / snapshot.capacity)
        else:
            if needs:
                plan = db.query(ProductionPlan).filter(ProductionPlan.order_fk == order.id,
                    ProductionPlan.status.in_(["APPROVED", "RELEASED", "IN_PROGRESS"])).order_by(ProductionPlan.id.desc()).first()
                start = max(date.today(), plan.plan_date) if plan and plan.plan_date else date.today()
                projection = start + timedelta(days=days)
                source = "CAPACITY_ESTIMATE"
    buffer = (order.buyer_deadline - projection).days if order.buyer_deadline and projection else None
    status = "UNKNOWN" if buffer is None else "ON_TRACK" if buffer >= 0 else "LATE_RISK"
    if order.buyer_deadline and order.buyer_deadline < date.today() and order.shipment_status != "DELIVERED":
        status = "LATE_RISK"
    return {"order_id": order.order_id, "buyer": order.buyer, "deadline": order.buyer_deadline,
            "projected_shipment": projection, "buffer_days": buffer, "status": status,
            "source": source}


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    issues = db.query(ExceptionItem).filter(ExceptionItem.status.in_(["OPEN", "IN_PROGRESS"]))
    active = db.query(Order).filter(Order.overall_status != "CLOSED").all()
    return {"active_orders": len(active),
            "critical": issues.filter(ExceptionItem.severity == "RED").count(),
            "attention": issues.filter(ExceptionItem.severity == "YELLOW").count(),
            "on_track": sum(forecast_row(db,o)["status"] == "ON_TRACK" for o in active),
            "unknown_forecast": sum(forecast_row(db,o)["status"] == "UNKNOWN" for o in active),
            "waiting": sum(o.overall_status in ("NEW", "HOLD") for o in active),
            "as_of": datetime.now(timezone.utc)}


@router.get("/morning-priority")
def morning_priority(db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    severity_rank = case((ExceptionItem.severity == "RED", 0), (ExceptionItem.severity == "YELLOW", 1), else_=2)
    items = db.query(ExceptionItem, Order).outerjoin(Order, ExceptionItem.order_fk == Order.id).filter(
        ExceptionItem.status.in_(["OPEN", "IN_PROGRESS"])
    ).order_by(severity_rank, ExceptionItem.due_date.asc().nullslast(), ExceptionItem.id).all()
    return [{"id": e.id, "order_id": o.order_id if o else None, "severity": e.severity, "title": e.title,
             "owner": e.owner_name or e.owner_role, "due_date": e.due_date, "next_action": e.next_action} for e, o in items]


def capacity_rows(db):
    today = date.today()
    snapshots = db.query(CapacitySnapshot).filter(CapacitySnapshot.snapshot_date <= today).order_by(
        CapacitySnapshot.snapshot_date.desc(), CapacitySnapshot.id.desc()).all()
    latest = {}
    for snapshot in snapshots:
        latest.setdefault(snapshot.process, snapshot)
    remaining = case((ProductionMovement.qty_in - ProductionMovement.qty_done - ProductionMovement.qty_reject > 0,
                      ProductionMovement.qty_in - ProductionMovement.qty_done - ProductionMovement.qty_reject), else_=0)
    rows = db.query(ProductionMovement.process, func.sum(remaining)).join(
        Article, Article.id == ProductionMovement.article_id).join(Order, Order.id == Article.order_fk).filter(
        Order.overall_status != "CLOSED").group_by(ProductionMovement.process).all()
    wip = {process: int(qty or 0) for process, qty in rows}
    result = []
    for process in sorted(set(latest) | set(wip)):
        snap = latest.get(process)
        stale = not snap or snap.snapshot_date != today
        result.append({"process": process, "capacity": snap.capacity if snap else None,
                       "planned_load": snap.planned_load if snap else None, "current_wip": wip.get(process, 0),
                       "snapshot_date": snap.snapshot_date if snap else None, "is_stale": stale,
                       "utilization": round(snap.planned_load / snap.capacity * 100, 1) if snap and snap.capacity and not stale else None})
    return result


@router.get("/wip-capacity")
def wip_capacity(db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    return capacity_rows(db)


class CapacityIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    process: str = Field(min_length=1, max_length=80)
    snapshot_date: date
    capacity: int = Field(ge=0)
    planned_load: int = Field(ge=0)


@router.post("/wip-capacity")
def record_capacity(data: CapacityIn, db: Session = Depends(get_db), user=Depends(require_roles(Role.COO_MANAGER))):
    snapshot = CapacitySnapshot(**data.model_dump(), current_wip=0)
    db.add(snapshot)
    db.flush()
    log_audit(db, user, "CREATE", "CapacitySnapshot", snapshot.id, data.model_dump_json())
    db.commit()
    return {"id": snapshot.id, **data.model_dump()}


@router.get("/forecast")
def forecast(db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    return [forecast_row(db,o) for o in db.query(Order).filter(Order.overall_status != "CLOSED").order_by(Order.id).all()]


class ForecastIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projected_shipment: Optional[date]


@router.patch("/forecast/{order_id}")
def update_forecast(order_id: str, data: ForecastIn, db: Session = Depends(get_db), user=Depends(require_roles(Role.COO_MANAGER))):
    order = db.query(Order).filter(Order.order_id == order_id).with_for_update().first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.overall_status == "CLOSED":
        raise HTTPException(409, "Closed orders cannot be rescheduled")
    old = order.projected_shipment
    order.projected_shipment = data.projected_shipment
    order.buffer_days = (order.buyer_deadline - data.projected_shipment).days if order.buyer_deadline and data.projected_shipment else None
    log_audit(db, user, "UPDATE", "OrderForecast", order.id, f"projected_shipment: {old} -> {data.projected_shipment}",
              obj=order, source_module="OrderForecast")
    db.commit()
    return forecast_row(db,order)


@router.get("/process-movement/{order_id}")
def process_movement(order_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*MASTER_ROLES))):
    order = db.query(Order).filter(Order.order_id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    rows = db.query(ProductionMovement).join(Article, Article.id == ProductionMovement.article_id).filter(
        Article.order_fk == order.id).order_by(ProductionMovement.id).all()
    return [{"id": r.id, "article_id": r.article_id, "process": r.process, "qty_in": r.qty_in, "qty_done": r.qty_done,
             "wip": max(r.qty_in-r.qty_done-r.qty_reject, 0), "qty_reject": r.qty_reject, "status": r.status,
             "pic": r.pic_name, "target_date": r.target_date} for r in rows]
