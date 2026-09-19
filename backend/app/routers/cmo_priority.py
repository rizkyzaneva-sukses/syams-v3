"""CMO Manager decision queues (Revisi #14 — blueprint final CMO Manager).

Action-first queues for Cecep. Every row carries the mandatory columns from
revisi #9/#13/#14: Task ID, Buyer ID, Order ID, Article ID, decision type,
current status, missing evidence/gate, next action, decision owner, due/SLA,
next handoff, updated_at.

Read-only: these endpoints derive state from recorded transactions and never
mutate data. All permission is enforced server-side here, not only in the UI.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from .. import models as m

router = APIRouter(prefix="/cmo", tags=["cmo-priority"])

# Roles that may read the commercial decision queues. Deby prepares, Cecep
# decides, CEO may observe. Finance/COO do not own these queues.
VIEW_ROLES = {"CEO", "CMO_MANAGER", "CMO_SUPPORT"}


def _require_view(user):
    if user.role.value not in VIEW_ROLES:
        raise HTTPException(403, "Antrean keputusan CMO tidak tersedia untuk peran ini.")


def _iso(value):
    return value.isoformat() if value is not None else None


def _queue_row(*, task_id, decision_type, order=None, buyer=None, article=None,
               status=None, gate=None, next_action=None, owner="CMO_MANAGER",
               due=None, handoff=None, updated=None, severity=None):
    """One decision-queue row. Columns mirror the mandatory queue contract."""
    return {
        "task_id": task_id,
        "decision_type": decision_type,
        "order_id": order.order_id if order is not None else None,
        "order_fk": order.id if order is not None else None,
        "buyer": buyer or (order.buyer if order is not None else None),
        "article_code": article,
        "status": status,
        "gate": gate,
        "next_action": next_action,
        "owner": owner,
        "due": _iso(due),
        "handoff": handoff,
        "updated_at": _iso(updated),
        "severity": severity,
    }


@router.get("/morning-priority")
def morning_priority(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Action-first decision queue for CMO Manager (revisi #14 poin 2).

    Sections follow the locked blueprint order: PO/draft order awaiting review,
    quotation awaiting approval, sample/PPM decision, SPK ready for Release to
    COO, then commercial exceptions. Only items needing a Cecep decision appear.
    """
    _require_view(user)
    queues = []

    # 1. PO / draft order awaiting CMO Manager review (Deby already submitted).
    pending_po = (db.query(m.POIntake)
                  .filter(m.POIntake.status == "SUBMITTED")
                  .order_by(m.POIntake.updated_at.asc()).all())
    queues.append({
        "key": "PO_REVIEW",
        "label": "PO / Draft Order Menunggu Review",
        "owner": "CMO_MANAGER",
        "handoff": "Cecep accept / reject & aktifkan Order",
        "rows": [_queue_row(
            task_id=f"PO-{po.id}", decision_type="PO_REVIEW",
            buyer=po.buyer, status=po.status,
            gate="Lengkap" if not (po.missing_items_json or "[]") .strip("[]") else "Belum lengkap",
            next_action="Review kelengkapan lalu terima atau tolak",
            due=po.buyer_deadline, handoff="Activate Order → CFO pricing",
            updated=po.updated_at, severity="YELLOW") for po in pending_po],
    })

    # 2. Quotation awaiting approval (Deby prepared, Cecep approves).
    pending_quotes = (db.query(m.Quotation)
                      .filter(m.Quotation.status.in_(["DRAFT", "SENT"]))
                      .order_by(m.Quotation.created_at.asc()).all())
    quote_rows = []
    for quote in pending_quotes:
        order = db.get(m.Order, quote.order_fk)
        quote_rows.append(_queue_row(
            task_id=f"QUO-{quote.id}", decision_type="QUOTATION_APPROVAL",
            order=order, status=quote.status,
            gate=f"Margin {quote.margin_percent or 0}%",
            next_action="Setujui atau tolak quotation",
            due=quote.valid_until, handoff="Kirim ke buyer → Order aktif",
            updated=quote.created_at, severity="YELLOW"))
    queues.append({
        "key": "QUOTATION_APPROVAL", "label": "Quotation Menunggu Approval",
        "owner": "CMO_MANAGER", "handoff": "Approve → kirim ke buyer",
        "rows": quote_rows,
    })

    # 3. Sample / PPM awaiting customer decision recorded by Cecep.
    pending_samples = (db.query(m.SampleRecord)
                       .filter(m.SampleRecord.customer_approved_by_id.is_(None))
                       .order_by(m.SampleRecord.id.asc()).all())
    queues.append({
        "key": "SAMPLE_DECISION", "label": "Sample / PPM Decision",
        "owner": "CMO_MANAGER", "handoff": "Keputusan → SPK Generate",
        "rows": [_queue_row(
            task_id=f"SMP-{s.id}", decision_type="SAMPLE_DECISION",
            order=db.get(m.Order, s.order_fk), article=s.article_code,
            status=s.status,
            gate=f"{len(s.evidence)} bukti" if s.evidence else "Bukti belum ada",
            next_action="Catat keputusan buyer sesuai bukti",
            due=s.completed_date, handoff="Cecep release SPK setelah gate lolos",
            updated=s.created_at, severity="YELLOW") for s in pending_samples],
    })

    # 4. SPK printed & ready for CMO SPK Release (handoff Release to COO).
    ready_spk = (db.query(m.SPK).filter(m.SPK.status == "PRINTED")
                 .order_by(m.SPK.id.asc()).all())
    queues.append({
        "key": "SPK_RELEASE", "label": "SPK Siap Release to COO",
        "owner": "CMO_MANAGER", "handoff": "Release to COO → Batch Release Siti",
        "rows": [_queue_row(
            task_id=f"SPK-{k.id}", decision_type="SPK_RELEASE",
            order=db.get(m.Order, k.order_fk), status=k.status,
            gate="Printed" if k.status == "PRINTED" else k.status,
            next_action="Periksa prasyarat lalu Release to COO",
            due=None, handoff="COO Batch Release",
            updated=k.created_at, severity="YELLOW") for k in ready_spk],
    })

    # 5. Commercial exceptions only — production/finance stay with COO/CFO/CEO.
    commercial = ("Sales", "Customer", "Quotation", "Order", "Delivery")
    open_exceptions = (db.query(m.ExceptionItem)
                       .filter(m.ExceptionItem.status.in_(["OPEN", "IN_PROGRESS"]))
                       .order_by(m.ExceptionItem.due_date.asc().nullslast(),
                                 m.ExceptionItem.id.asc()).all())
    exception_rows = []
    for item in open_exceptions:
        if not any(word.lower() in (item.category or "").lower() for word in commercial):
            continue
        order = db.get(m.Order, item.order_fk) if item.order_fk else None
        exception_rows.append(_queue_row(
            task_id=f"EXC-{item.id}", decision_type="COMMERCIAL_EXCEPTION",
            order=order, buyer=order.buyer if order else item.owner_name,
            status=item.status, gate=item.category, next_action=item.next_action,
            owner=item.owner_role or "CMO_MANAGER", due=item.due_date,
            handoff="Eskalasi CEO bila di luar kewenangan CMO",
            updated=item.created_at, severity=item.severity))
    queues.append({
        "key": "EXCEPTION_CENTER", "label": "Exception Center — Komersial",
        "owner": "CMO_MANAGER", "handoff": "Keputusan Cecep atau eskalasi CEO",
        "rows": exception_rows,
    })

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "queues": queues,
        "totals": {q["key"]: len(q["rows"]) for q in queues},
        "total_decisions": sum(len(q["rows"]) for q in queues),
    }