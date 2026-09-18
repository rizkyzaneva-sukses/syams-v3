"""Business invariants shared by mutation endpoints and the flow engine.

Every module mutation validates before flush and writes its audit in the same
transaction. Derived order fields are updated only after validated records exist.
"""
import json
from datetime import date
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import inspect, func, or_
from sqlalchemy.exc import IntegrityError
from . import models as m
from .audit import log_audit
from .business_policy import get_policy


def fail(message, status=400):
    raise HTTPException(status, message)


def role(user):
    return user.role.value if hasattr(user.role, "value") else user.role


def require(user, *roles):
    if not user or role(user) not in roles:
        fail("Role not allowed for this action", 403)


def get(db, model, ident):
    obj = db.get(model, ident) if ident is not None else None
    if obj is None:
        fail(f"{model.__name__} not found", 404)
    return obj


def changes(obj):
    state = inspect(obj)
    return {a.key for a in state.attrs if a.history.has_changes()}


def original(obj, key):
    history = inspect(obj).attrs[key].history
    return history.deleted[0] if history.deleted else getattr(obj, key)


def invoices_total(db, order_id):
    invoices = db.query(m.Invoice).filter_by(order_fk=order_id).all()
    total = sum((Decimal(i.amount or 0) for i in invoices), Decimal(0))
    paid = sum((Decimal(i.paid_amount or 0) for i in invoices), Decimal(0))
    return total, paid


def invoices_reconciled(db, order_id):
    invoices = db.query(m.Invoice).filter_by(order_fk=order_id).all()
    return bool(invoices) and all(i.reconciliation_status == "VERIFIED" for i in invoices)


def finance_ready(db, order):
    total, paid = invoices_total(db, order.id)
    if (total <= 0 or not invoices_reconciled(db, order.id)
            or order.finance_gate_status != "APPROVED" or not order.finance_verified_by_id
            or not order.payment_evidence_ref):
        return False
    if order.finance_term_kind == "FULL":
        return paid >= total
    if order.finance_term_kind == "DP":
        return bool(order.required_dp_amount and paid >= order.required_dp_amount)
    if order.finance_term_kind == "CREDIT":
        return bool(order.credit_due_date)
    return False


def quotation_ready(db, order):
    q = db.query(m.Quotation).filter_by(order_fk=order.id).order_by(m.Quotation.id.desc()).first()
    return bool(q and q.status == "APPROVED" and q.approved_by_id
                and q.pricing_breakdown and (not q.valid_until or q.valid_until >= date.today()))


def price_quotation(db, quotation):
    """Validate a full article price sheet and derive sale, HPP, and margin."""
    if not quotation.pricing_breakdown:
        fail("Per-article pricing and HPP are required")
    try:
        lines = json.loads(quotation.pricing_breakdown)
        articles = db.query(m.Article).filter_by(order_fk=quotation.order_fk).all()
        by_id = {a.id: a for a in articles}
        if not isinstance(lines, list) or len(lines) != len(articles):
            fail("Pricing must cover every article exactly once")
        canonical = []
        sale = cost = Decimal(0)
        for line in lines:
            article_id = int(line["article_id"])
            article = by_id.get(article_id)
            if article is None or article_id in {item["article_id"] for item in canonical}:
                fail("Pricing has a duplicate or unrelated article")
            unit_price = Decimal(str(line["unit_price"]))
            unit_hpp = Decimal(str(line["unit_hpp"]))
            if not unit_price.is_finite() or not unit_hpp.is_finite() or unit_price <= 0 or unit_hpp < 0:
                fail("Price must be positive and HPP must be non-negative")
            sale += unit_price * article.qty
            cost += unit_hpp * article.qty
            canonical.append({"article_id": article_id, "article_code": article.article_code,
                "qty": article.qty, "unit_price": str(unit_price), "unit_hpp": str(unit_hpp)})
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        fail("Invalid per-article pricing")
    quotation.amount = sale.quantize(Decimal("0.01"))
    quotation.hpp_total = cost.quantize(Decimal("0.01"))
    quotation.margin_amount = (sale - cost).quantize(Decimal("0.01"))
    quotation.margin_percent = ((sale - cost) / sale * 100).quantize(Decimal("0.01"))
    quotation.pricing_breakdown = json.dumps(canonical)
    return sale, cost


def samples_ready(db, order):
    articles = db.query(m.Article).filter_by(order_fk=order.id).all()
    required = [a for a in articles if a.sample_required or order.order_type == m.OrderType.SAMPLE_ONLY]
    if order.order_type in (m.OrderType.SAMPLE_ONLY, m.OrderType.SAMPLE_PRODUCTION) and not required:
        return False
    for a in required:
        s = db.query(m.SampleRecord).filter(m.SampleRecord.order_fk == order.id,
            or_(m.SampleRecord.article_id == a.id,
                (m.SampleRecord.article_id.is_(None)) & (m.SampleRecord.article_code == a.article_code))
        ).order_by(m.SampleRecord.id.desc()).first()
        if not s or s.status != "APPROVED" or not s.customer_approved_by_id:
            return False
    return True


def spk_ready(db, order):
    spk = db.query(m.SPK).filter_by(order_fk=order.id).order_by(m.SPK.id.desc()).first()
    return bool(spk and spk.status == "RELEASED" and spk.snapshot)


def production_ready(db, order):
    if order.order_type == m.OrderType.SAMPLE_ONLY:
        fail("Sample Only orders cannot enter production")
    if not quotation_ready(db, order) or not finance_ready(db, order) or not samples_ready(db, order):
        fail("Approved quotation, CFO payment assessment and required sample approvals are required")
    if not spk_ready(db, order):
        fail("Latest SPK must be RELEASED")
    plan = db.query(m.ProductionPlan).filter_by(order_fk=order.id).order_by(m.ProductionPlan.id.desc()).first()
    if not plan or plan.status not in ("APPROVED", "RELEASED", "IN_PROGRESS", "DONE"):
        fail("Approved production plan required")
    materials_ready(db, order)


def materials_ready(db, order):
    requests = db.query(m.MaterialRequest).filter(m.MaterialRequest.order_fk == order.id, m.MaterialRequest.status != "CANCELLED").all()
    pos = db.query(m.PurchaseOrder).filter(m.PurchaseOrder.order_fk == order.id, m.PurchaseOrder.status != "CANCELLED").all()
    if not requests or not pos or any(p.material_status != "READY" for p in pos):
        fail("Material requirements and received, READY purchase orders are required")
    bom_needed = {}
    for article in order.articles:
        items = db.query(m.BOMItem).filter_by(article_id=article.id).all()
        if not items:
            fail(f"BOM required for article {article.article_code}")
        for item in items:
            key = (item.material_name, item.unit)
            bom_needed[key] = bom_needed.get(key, Decimal(0)) + Decimal(article.qty) * Decimal(item.qty_per_unit)
    needed = {}
    for request in requests:
        key = (request.item_name, request.unit)
        needed[key] = needed.get(key, Decimal(0)) + Decimal(request.qty or 0)
    for key, quantity in bom_needed.items():
        if needed.get(key, Decimal(0)) < quantity:
            fail(f"Material request below article BOM requirement: {key[0]}")
    for (item, unit), quantity in needed.items():
        received = sum((Decimal(p.qty or 0) for p in pos if p.item == item and p.unit == unit and p.material_status == "READY"), Decimal(0))
        if received < quantity:
            fail(f"Material requirement not fulfilled: {item}")


def route_for(article):
    # Accept both the ASCII ">" separator and the "→" arrow: the order form
    # placeholder shows an arrow, so routes typed to match the UI hint would
    # otherwise collapse into a single bogus process name.
    raw = (article.production_route or "").replace("\u2192", ">").replace("->", ">")
    return [p.strip().upper() for p in raw.split(">") if p.strip()]


def qc_ready(db, order):
    articles = db.query(m.Article).filter_by(order_fk=order.id).all()
    if not articles:
        return False
    for a in articles:
        q = db.query(m.QCRecord).filter(m.QCRecord.order_fk == order.id,
            or_(m.QCRecord.article_id == a.id,
                (m.QCRecord.article_id.is_(None)) & (m.QCRecord.article_code == a.article_code)),
            func.upper(m.QCRecord.process).in_(["QC", "FINAL", "FINAL QC"])).order_by(m.QCRecord.id.desc()).first()
        if not q or q.status != "PASS" or q.total_reject or q.total_pass < a.qty:
            return False
    return True


def shipment_ready(db, shipment):
    order = get(db, m.Order, shipment.order_fk)
    production_ready(db, order)
    if not qc_ready(db, order) or shipment.packing_status != "PACKED":
        fail("Final QC PASS for every article and PACKED shipment are required")
    total, paid = invoices_total(db, order.id)
    outstanding = max(total - paid, Decimal(0))
    if total <= 0 or not invoices_reconciled(db, order.id) or shipment.finance_gate != "CLEAR" or not shipment.finance_assessed_by_id:
        fail("CFO shipment assessment must be CLEAR")
    if outstanding > 0 and (shipment.ceo_approval != "APPROVED" or shipment.approved_outstanding is None or outstanding > shipment.approved_outstanding):
        fail("Current outstanding requires persisted CEO approval after CFO assessment")


def deliveries_ready(db, order):
    shipments = db.query(m.Shipment).filter_by(order_fk=order.id).all()
    if not shipments:
        return False
    for s in shipments:
        d = db.query(m.DeliveryConfirmation).filter_by(shipment_fk=s.id).order_by(m.DeliveryConfirmation.id.desc()).first()
        if s.status != "DELIVERED" or not s.delivery_date or not d or d.status != "CONFIRMED":
            return False
    return True


def operational_ready(db, order):
    if order.order_type == m.OrderType.SAMPLE_ONLY:
        if not samples_ready(db, order):
            fail("Required sample work and buyer approval must be complete")
        return
    production_ready(db, order)
    if not qc_ready(db, order):
        fail("Final QC must pass for every article")
    movements = db.query(m.ProductionMovement).join(m.Article, m.ProductionMovement.article_id == m.Article.id).filter(m.Article.order_fk == order.id).all()
    if any(x.qty_in != x.qty_done + x.qty_reject for x in movements):
        fail("Open production WIP must be reconciled before operational closing")
    shipments = db.query(m.Shipment).filter_by(order_fk=order.id).all()
    if not shipments or any(s.status != "DELIVERED" or not s.delivery_date or s.packing_status != "PACKED" for s in shipments):
        fail("Every shipment must be packed and physically handed over")


STATUSES = {
    m.Quotation: {"DRAFT", "SENT", "APPROVED", "REJECTED", "EXPIRED"},
    m.SampleRecord: {"PROCESS", "IN_PROCESS", "REVISION", "PENDING", "COMPLETED", "APPROVED", "REJECTED"},
    m.SPK: {"DRAFT", "GENERATED", "PRINTED", "RELEASED", "VOID"},
    m.Invoice: {"UNPAID", "PARTIAL", "PAID"},
    m.PurchaseOrder: {"PENDING", "APPROVED", "ORDERED", "RECEIVED", "CANCELLED"},
    m.MaterialRequest: {"REQUESTED", "APPROVED", "ORDERED", "RECEIVED", "CANCELLED"},
    m.ProductionMovement: {"WAITING", "IN_PROCESS", "DONE", "HOLD"},
    m.ProductionPlan: {"PLANNING", "APPROVED", "RELEASED", "IN_PROGRESS", "DONE", "CANCELLED"},
    m.QCRecord: {"PASS", "FAIL", "REWORK", "PENDING"},
    m.Shipment: {"NOT_READY", "PREPARING", "READY", "HOLD", "SHIPPED", "DELIVERED"},
    m.DeliveryConfirmation: {"PENDING", "CONFIRMED", "ISSUE"},
    m.Task: {"OPEN", "IN_PROGRESS", "DONE", "CANCELLED"},
    m.ExceptionItem: {"OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"},
    m.EmployeeIssue: {"OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"},
}


def validate(db, obj, user, deleting=False):
    creating = obj in db.new
    changed = changes(obj)
    if getattr(obj, "order_fk", None) and not isinstance(obj, (m.DeliveryConfirmation, m.OrderClosing, m.Task, m.ExceptionItem)):
        dispatched = db.query(m.Shipment).filter(m.Shipment.order_fk == obj.order_fk, m.Shipment.status.in_(("SHIPPED", "DELIVERED"))).first()
        if dispatched and not isinstance(obj, m.Shipment):
            fail("Dispatched order source records are immutable")
    if not deleting:
        allowed = STATUSES.get(type(obj))
        if allowed and obj.status is not None and obj.status not in allowed:
            fail(f"Invalid {type(obj).__name__} status")
        for key in ("amount", "qty", "qty_in", "qty_done", "qty_reject", "total_checked", "total_pass", "total_reject"):
            value = getattr(obj, key, None)
            if value is not None and (not Decimal(str(value)).is_finite() or value < 0):
                fail(f"{key} must be a finite non-negative number")
        for key in ("quality", "responsibility", "discipline", "spiritual", "attitude", "skill"):
            value = getattr(obj, key, None)
            if value is not None and (not Decimal(str(value)).is_finite() or not 0 <= value <= 100):
                fail(f"{key} must be between 0 and 100")
        if hasattr(obj, "order_fk") and obj.order_fk is not None:
            order = get(db, m.Order, obj.order_fk)
            if order.overall_status == "CLOSED" and not isinstance(obj, (m.Task, m.ExceptionItem)):
                fail("Closed order is immutable")
        for field, model in (("employee_id", m.Employee), ("assigned_to_id", m.User)):
            ident = getattr(obj, field, None)
            if ident is not None:
                get(db, model, ident)
    else:
        order = get(db, m.Order, obj.order_fk) if getattr(obj, "order_fk", None) else None
        if order and order.overall_status == "CLOSED":
            fail("Closed order is immutable")

    if isinstance(obj, m.Quotation):
        if not obj.order_fk:
            fail("Quotation requires an order")
        if deleting and obj.status == "APPROVED":
            fail("Approved quotation cannot be deleted")
        if not creating and original(obj, "status") == "APPROVED" and changed:
            fail("Approved quotation is immutable; create a revision")
        if obj.pricing_breakdown and not deleting:
            price_quotation(db, obj)
        if not creating and changed.intersection({"pricing_breakdown", "payment_plan", "valid_until", "notes", "amount"}):
            require(user, "CMO_MANAGER")
            obj.ceo_approved_by_id = None
            obj.ceo_approval_reason = None
        if obj.status == "APPROVED" and (creating or "status" in changed):
            require(user, "CFO_MANAGER")
            policy = get_policy(db)
            if not obj.pricing_breakdown:
                fail("Approved quotation requires per-article pricing and HPP")
            if not obj.payment_plan or not obj.payment_plan.strip() or not obj.approval_reason or not obj.approval_reason.strip():
                fail("Payment plan and CFO approval reason are required")
            if obj.margin_percent < policy.minimum_margin_percent:
                fail("Quotation margin is below the configured minimum")
            if obj.amount > policy.cfo_quotation_limit and not obj.ceo_approved_by_id:
                fail("Quotation exceeds CFO limit and needs CEO approval")
            obj.approved_by_id = user.id
    elif isinstance(obj, m.SampleRecord):
        a = db.query(m.Article).filter_by(order_fk=obj.order_fk, article_code=obj.article_code).first()
        if not a:
            fail("Article code does not belong to this order")
        if obj.article_id is not None and obj.article_id != a.id:
            fail("Sample article identity conflicts with article code")
        obj.article_id = a.id
        if deleting:
            if obj.status == "APPROVED" or spk_ready(db, get(db, m.Order, obj.order_fk)):
                fail("Approved or released sample history cannot be deleted")
        elif not creating and original(obj, "status") == "APPROVED" and changed:
            fail("Approved sample is immutable; create a revision")
        elif obj.status == "APPROVED":
            require(user, "CMO_MANAGER")
            if not obj.notes or not obj.notes.strip():
                fail("Customer approval evidence is required in notes")
            obj.customer_approved_by_id = user.id
    elif isinstance(obj, m.SPK):
        order = get(db, m.Order, obj.order_fk)
        if order.order_type == m.OrderType.SAMPLE_ONLY:
            fail("Sample Only orders cannot have an SPK")
        if creating:
            if obj.status != "DRAFT" or obj.snapshot:
                fail("New SPK must begin as a draft")
            obj.version = (db.query(func.max(m.SPK.version)).filter_by(order_fk=obj.order_fk).scalar() or 0) + 1
        else:
            previous = original(obj, "status")
            if previous in ("RELEASED", "VOID"):
                fail("Released or void SPK is immutable; create a new version")
            if deleting:
                if previous != "DRAFT":
                    fail("Only draft SPK can be deleted")
            elif previous != "DRAFT" and changed - {"status"}:
                fail("Generated SPK document is locked; create a new version")
            if not deleting and "status" in changed:
                action = db.info.get("spk_action")
                transitions = {"GENERATE": ("DRAFT", "GENERATED"),
                               "PRINT": ("GENERATED", "PRINTED"),
                               "RELEASE": ("PRINTED", "RELEASED"),
                               "VOID": (previous, "VOID")}
                if action not in transitions or (previous, obj.status) != transitions[action]:
                    fail("Invalid SPK status transition")
                if action in ("RELEASE", "VOID"):
                    require(user, "CMO_MANAGER")
                else:
                    require(user, "CMO_MANAGER", "CMO_SUPPORT")
                if action == "GENERATE" and not obj.snapshot:
                    fail("Generated SPK requires a locked document snapshot")
                if action in ("PRINT", "RELEASE") and not obj.snapshot:
                    fail("SPK document must be generated first")
        if not deleting and obj.status == "RELEASED" and (creating or "status" in changed):
            if not quotation_ready(db, order) or not finance_ready(db, order) or not samples_ready(db, order):
                fail("Quotation, payment assessment and required samples must be approved before SPK release")
            if not order.articles or any(not route_for(a) for a in order.articles):
                fail("Every article requires a production route")
    elif isinstance(obj, m.Invoice):
        if creating and (obj.paid_amount or obj.status not in (None, "UNPAID")):
            fail("Record payments through the payments endpoint")
        if not creating and changed.intersection({"paid_amount", "status"}):
            fail("Invoice payment totals and status are derived from payment records")
        if deleting and (obj.paid_amount or db.query(m.Payment).filter_by(invoice_no=obj.invoice_no).first()):
            fail("Invoice with payments cannot be deleted")
        if not deleting and obj.amount <= 0:
            fail("Invoice amount must be positive")
        if not deleting and Decimal(obj.amount) < Decimal(obj.paid_amount or 0):
            fail("Invoice amount cannot be lower than payments")
        if creating or deleting or "amount" in changed:
            order = get(db, m.Order, obj.order_fk)
            order.finance_gate_status = "PENDING"
            order.finance_verified_by_id = None
    elif isinstance(obj, m.Payment):
        inv = db.query(m.Invoice).filter_by(invoice_no=obj.invoice_no).populate_existing().with_for_update().first()
        if not inv:
            fail("Invoice not found", 404)
        if obj.amount <= 0:
            fail("Payment amount must be positive")
        if get(db, m.Order, inv.order_fk).overall_status == "CLOSED":
            fail("Closed order is immutable")
        if inv.reconciliation_status != "VERIFIED":
            fail("Invoice ledger must be reconciled before new payments")
        obj.invoice_id = inv.id
        # Existing paid balance is retained as a legacy opening balance.
        if Decimal(inv.paid_amount or 0) + Decimal(str(obj.amount)) > Decimal(inv.amount):
            fail("Payment exceeds invoice outstanding")
        inv.paid_amount = Decimal(inv.paid_amount or 0) + Decimal(str(obj.amount))
        inv.status = "PAID" if inv.paid_amount >= inv.amount else "PARTIAL"
    elif isinstance(obj, m.PurchaseOrder):
        if not deleting and obj.material_status not in (None, "WAITING", "PARTIAL", "READY"):
            fail("Invalid material status")
        if not deleting and obj.material_status == "READY" and (obj.status != "RECEIVED" or not obj.arrival_date):
            fail("READY material requires RECEIVED status and arrival date")
    elif isinstance(obj, m.BOMItem):
        article = get(db, m.Article, obj.article_id)
        if Decimal(obj.qty_per_unit or 0) <= 0 or Decimal(obj.planned_unit_cost or 0) < 0:
            fail("BOM quantity must be positive and planned unit cost nonnegative")
        if db.query(m.ProductionMovement).filter_by(article_id=article.id).first():
            fail("BOM cannot change after production has started")
    elif isinstance(obj, m.MaterialConsumption):
        item = get(db, m.BOMItem, obj.bom_item_id)
        article = get(db, m.Article, item.article_id)
        order = get(db, m.Order, article.order_fk)
        if order.overall_status == "CLOSED":
            fail("Closed order is immutable")
        if Decimal(obj.qty or 0) <= 0 or Decimal(obj.actual_unit_cost or 0) < 0 or not (obj.evidence_ref or "").strip():
            fail("Actual consumption requires positive quantity, nonnegative cost and evidence")
        if deleting:
            fail("Consumption ledger is append-only")
        received = sum((Decimal(p.qty or 0) for p in db.query(m.PurchaseOrder).filter_by(order_fk=order.id).all()
                        if p.item == item.material_name and p.unit == item.unit and p.material_status == "READY"), Decimal(0))
        used = sum((Decimal(c.qty) for c, b in db.query(m.MaterialConsumption, m.BOMItem).join(m.BOMItem, m.BOMItem.id == m.MaterialConsumption.bom_item_id)
                    .join(m.Article, m.Article.id == m.BOMItem.article_id).filter(m.Article.order_fk == order.id,
                    m.BOMItem.material_name == item.material_name, m.BOMItem.unit == item.unit,
                    m.MaterialConsumption.id != (obj.id or -1)).all()), Decimal(0))
        if used + Decimal(obj.qty) > received:
            fail("Material consumption exceeds received quantity")
    elif isinstance(obj, m.ProductionCostEntry):
        article = get(db, m.Article, obj.article_id)
        order = get(db, m.Order, article.order_fk)
        if order.overall_status == "CLOSED" or deleting or not creating:
            fail("Production cost ledger is append-only for open orders")
        if obj.category not in ("LABOR", "OVERHEAD", "OTHER") or Decimal(obj.amount or 0) <= 0 or not (obj.evidence_ref or "").strip():
            fail("Production cost requires valid category, positive amount and evidence")
    elif isinstance(obj, m.ProductionPlan):
        order = get(db, m.Order, obj.order_fk)
        if order.order_type == m.OrderType.SAMPLE_ONLY or not spk_ready(db, order):
            fail("Production plan requires a released production SPK")
        if obj.status in ("APPROVED", "RELEASED") and not obj.plan_date:
            fail("Approved plan requires a plan date")
    elif isinstance(obj, m.ProductionMovement):
        a = get(db, m.Article, obj.article_id)
        production_ready(db, get(db, m.Order, a.order_fk))
        route = route_for(a)
        process = obj.process.upper()
        if process not in route or len(set(route)) != len(route):
            fail("Process must belong to a unique, ordered article routing")
        if role(user) == "PRINTING_PIC" and process not in ("PRINTING", "BORDIR"):
            fail("Printing PIC can only update printing or embroidery", 403)
        if role(user) == "SAMPLE_PIC":
            fail("Sample PIC cannot update mass production", 403)
        qi, qd, qr = obj.qty_in or 0, obj.qty_done or 0, obj.qty_reject or 0
        if qd + qr > qi or (obj.status == "DONE" and qd + qr != qi):
            fail("Done plus reject must not exceed input; DONE must account for all input")
        if qr and not obj.reject_reason:
            fail("Reject reason required")
        others = db.query(m.ProductionMovement).filter(m.ProductionMovement.article_id == a.id, m.ProductionMovement.id != (obj.id or -1)).all()
        same_input = sum(x.qty_in for x in others if x.process.upper() == process)
        idx = route.index(process)
        available = a.qty if idx == 0 else sum(x.qty_done for x in others if x.process.upper() == route[idx - 1])
        if same_input + qi > available:
            fail("Input exceeds approved quantity available from the previous process")
        if idx + 1 < len(route):
            downstream = sum(x.qty_in for x in others if x.process.upper() == route[idx + 1])
            done = qd + sum(x.qty_done for x in others if x.process.upper() == process)
            if downstream > done:
                fail("Cannot reduce completed quantity below downstream input")
    elif isinstance(obj, m.QCRecord):
        a = db.query(m.Article).filter_by(order_fk=obj.order_fk, article_code=obj.article_code).first()
        if not a:
            fail("Article code does not belong to this order")
        if obj.article_id is not None and obj.article_id != a.id:
            fail("QC article identity conflicts with article code")
        obj.article_id = a.id
        parent = get(db, m.QCRecord, obj.rework_parent_id) if obj.rework_parent_id else None
        if parent:
            if parent.id == obj.id or parent.order_fk != obj.order_fk or parent.article_code != obj.article_code or parent.process.upper() != obj.process.upper():
                fail("Rework parent must be a different QC record for the same article and process")
            if parent.status not in ("FAIL", "REWORK") or parent.total_reject <= 0:
                fail("Rework parent must have unresolved rejected units")
            if obj.total_checked > parent.total_reject and obj.status != "PASS":
                fail("Rework inspection exceeds rejected quantity")
        elif not creating and "rework_parent_id" in changed:
            fail("Rework lineage cannot be removed")
        if deleting and (obj.status == "PASS" or db.query(m.QCRecord).filter_by(rework_parent_id=obj.id).first()):
            fail("Passed QC and records with rework descendants cannot be deleted")
        if not deleting:
            prior = db.query(m.QCRecord).filter(m.QCRecord.order_fk == obj.order_fk,
                m.QCRecord.article_code == obj.article_code,
                func.upper(m.QCRecord.process) == obj.process.upper(),
                m.QCRecord.id != (obj.id or -1)).order_by(m.QCRecord.id.desc()).first()
            if creating and prior and prior.status in ("FAIL", "REWORK") and not parent:
                fail("QC after a failed inspection must link its rework parent")
            if creating and prior and prior.status in ("FAIL", "REWORK") and parent and parent.id != prior.id:
                fail("Rework parent must be the latest failed inspection")
            if not creating and db.query(m.QCRecord).filter_by(rework_parent_id=obj.id).first() and changed.intersection({"status", "total_checked", "total_pass", "total_reject", "article_code", "process"}):
                fail("QC record with rework descendants cannot be modified")
            if obj.total_pass + obj.total_reject != obj.total_checked or obj.total_checked > a.qty:
                fail("QC pass plus reject must equal checked, within article quantity")
            if obj.status == "PASS" and (obj.total_reject or obj.total_checked <= 0):
                fail("QC PASS requires checked units and zero unresolved rejects")
            if obj.total_reject and not obj.reject_reason:
                fail("QC rejects require a reason")
            if obj.process.upper() in ("QC", "FINAL", "FINAL QC"):
                route = route_for(a)
                qc_index = route.index("QC") if "QC" in route else len(route)
                prior = route[qc_index - 1] if qc_index else None
                completed = sum(x.qty_done for x in db.query(m.ProductionMovement).filter_by(article_id=a.id).all() if x.process.upper() == prior)
                if obj.total_checked > completed:
                    fail("Final QC exceeds completed production quantity")
    elif isinstance(obj, m.Shipment):
        if creating:
            if obj.finance_gate not in (None, "PENDING") or obj.ceo_approval not in (None, "NOT_REQUIRED"):
                fail("Shipment approvals must use the CFO and CEO approval endpoints", 403)
        elif changed.intersection({"finance_gate", "ceo_approval", "finance_assessed_by_id", "approved_outstanding"}) and not db.info.get("shipment_approval"):
            fail("Shipment approvals must use the CFO and CEO approval endpoints", 403)
        if obj.packing_status not in (None, "PENDING", "PACKED"):
            fail("Invalid packing status")
        if obj.packing_status == "PACKED" and not qc_ready(db, get(db, m.Order, obj.order_fk)):
            fail("Final QC must pass before packing")
        if not creating and original(obj, "status") in ("SHIPPED", "DELIVERED"):
            if deleting or "packing_status" in changed:
                fail("Dispatched shipment packing cannot be changed")
            if "status" in changed and not (original(obj, "status") == "SHIPPED" and obj.status == "DELIVERED"):
                fail("Physical handover must advance a shipped shipment to delivered")
            if "status" in changed and role(user) != "COO_MANAGER":
                fail("Only COO Manager may record physical handover", 403)
        if obj.status in ("SHIPPED", "DELIVERED"):
            shipment_ready(db, obj)
            if not obj.shipped_date:
                fail("Shipped date required")
        if obj.status == "DELIVERED":
            if creating:
                fail("Physical handover requires a shipped shipment")
            if not obj.delivery_date:
                fail("Physical handover date required")
        elif obj.delivery_date:
            fail("Physical handover date requires DELIVERED status")
    elif isinstance(obj, m.DeliveryConfirmation):
        require(user, "CMO_MANAGER")
        shipment = get(db, m.Shipment, obj.shipment_fk)
        if shipment.status not in ("SHIPPED", "DELIVERED"):
            fail("Delivery can only be recorded after shipment")
        if not creating and original(obj, "status") == "CONFIRMED":
            fail("Confirmed delivery is immutable; create a correction record")
        if obj.status == "CONFIRMED" and (not obj.confirmed_by_customer or not obj.confirmation_date):
            fail("Customer identity and confirmation date required")
        # Customer acknowledgement is separate from COO physical handover.
    elif isinstance(obj, m.OrderClosing):
        order = get(db, m.Order, obj.order_fk)
        if creating and db.query(m.OrderClosing).filter_by(order_fk=obj.order_fk).first():
            fail("Closing already exists; update the order closing", 409)
        for field, owner in (("customer_close_status", "CMO_MANAGER"), ("operational_close_status", "COO_MANAGER"), ("financial_close_status", "CFO_MANAGER")):
            value = getattr(obj, field)
            if value not in (None, "OPEN", "CLOSED"):
                fail("Closing status must be OPEN or CLOSED")
            if field in changed and (not creating or value == "CLOSED"):
                require(user, owner)
        if obj.customer_close_status == "CLOSED":
            if order.order_type == m.OrderType.SAMPLE_ONLY:
                if not samples_ready(db, order):
                    fail("Required customer sample approvals are incomplete")
            elif not deliveries_ready(db, order):
                fail("All shipments require customer delivery confirmation")
        if obj.operational_close_status == "CLOSED":
            operational_ready(db, order)
        total, paid = invoices_total(db, order.id)
        if obj.financial_close_status == "CLOSED" and (total <= 0 or paid < total or not invoices_reconciled(db, order.id)):
            fail("Financial closing requires invoices with zero outstanding")
        all_closed = obj.customer_close_status == obj.operational_close_status == obj.financial_close_status == "CLOSED"
        obj.order_close_status = "CLOSED" if all_closed else "OPEN"
        obj.close_date = date.today() if all_closed else None
        obj.closed_by = user.name if all_closed else None
    elif isinstance(obj, m.Task) and not creating:
        if role(user) != "CEO":
            if obj.assigned_to_id != user.id or changed - {"status"}:
                fail("Only the assignee may update task status; CEO may reassign", 403)
    elif isinstance(obj, m.Task) and creating and role(user) != "CEO":
        assignee = get(db, m.User, obj.assigned_to_id)
        division = role(user).split("_")[0]
        groups = {"CMO": {"CMO_MANAGER", "CMO_SUPPORT", "SAMPLE_PIC"}, "COO": {"COO_MANAGER", "PRODUCTION_PIC", "PRINTING_PIC", "SHIPMENT_ADMIN"}}
        if role(assignee) not in groups.get(division, {role(user)}):
            fail("Task assignment must stay within your division", 403)
    elif isinstance(obj, m.ExceptionItem) and not creating:
        if role(user) != "CEO":
            if obj.owner_role != role(user) or (obj.owner_name and obj.owner_name != user.name) or changed.intersection({"owner_role", "owner_name"}):
                fail("Only the exception owner may update it; CEO may reassign", 403)


def sync_order(db, order_id):
    order = get(db, m.Order, order_id)
    total, paid = invoices_total(db, order_id)
    order.finance_status = "PAID" if total > 0 and paid >= total else "PARTIAL" if paid > 0 else "UNPAID"
    pos = db.query(m.PurchaseOrder).filter_by(order_fk=order_id).all()
    try:
        materials_ready(db, order)
        order.material_status = "READY"
    except HTTPException:
        order.material_status = "WAITING" if pos else "NOT_REQUESTED"
    shipments = db.query(m.Shipment).filter_by(order_fk=order_id).all()
    order.shipment_status = "DELIVERED" if shipments and deliveries_ready(db, order) else "SHIPPED" if shipments and all(s.status in ("SHIPPED", "DELIVERED") for s in shipments) else "PREPARING" if shipments else "NOT_READY"
    for a in order.articles:
        sample = db.query(m.SampleRecord).filter(m.SampleRecord.order_fk == order_id,
            or_(m.SampleRecord.article_id == a.id,
                (m.SampleRecord.article_id.is_(None)) & (m.SampleRecord.article_code == a.article_code))).order_by(m.SampleRecord.id.desc()).first()
        a.sample_status = sample.status if sample else "PROCESS" if a.sample_required else "NOT_REQUIRED"
        movements = db.query(m.ProductionMovement).filter_by(article_id=a.id).all()
        route = route_for(a)
        last_done = sum(x.qty_done for x in movements if route and x.process.upper() == route[-1])
        a.production_status = "DONE" if movements and last_done >= a.qty and all(x.status == "DONE" for x in movements) else "IN_PROCESS" if movements else "NOT_STARTED"
    closing = db.query(m.OrderClosing).filter_by(order_fk=order_id).first()
    if closing:
        order.customer_close_status = closing.customer_close_status
        order.operational_close_status = closing.operational_close_status
        order.financial_close_status = closing.financial_close_status
        if closing.order_close_status == "CLOSED":
            order.overall_status = "CLOSED"
            order.flow_step = "CLOSED"
    else:
        order.customer_close_status = "OPEN"
        order.operational_close_status = "OPEN"
        order.financial_close_status = "OPEN"
    if order.flow_step != "CLOSED":
        order.overall_status = "COMPLETED" if order.flow_step == "DELIVERED" else "ACTIVE" if order.flow_step not in (None,"ORDER","INVOICE") else "NEW"


def commit_changes(db, user):
    """Validate, synchronize and audit atomically; never swallow audit failures."""
    pending = list(db.new) + [x for x in db.dirty if db.is_modified(x)] + list(db.deleted)
    pending = [x for x in pending if not isinstance(x, m.AuditLog)]
    order_ids = set()
    logs = []
    try:
        # Serialize writes touching the same order (including payment balances).
        for obj in pending:
            oid = getattr(obj, "order_fk", None)
            if isinstance(obj, m.Order):
                oid = obj.id
            elif isinstance(obj, m.Payment):
                inv = db.query(m.Invoice).filter_by(invoice_no=obj.invoice_no).first()
                oid = inv.order_fk if inv else None
            elif isinstance(obj, m.ProductionMovement):
                article = get(db, m.Article, obj.article_id)
                oid = article.order_fk
            elif isinstance(obj, m.BOMItem):
                oid = get(db, m.Article, obj.article_id).order_fk
            elif isinstance(obj, m.MaterialConsumption):
                oid = get(db, m.Article, get(db, m.BOMItem, obj.bom_item_id).article_id).order_fk
            elif isinstance(obj, m.ProductionCostEntry):
                oid = get(db, m.Article, obj.article_id).order_fk
            elif isinstance(obj, m.DeliveryConfirmation):
                oid = get(db, m.Shipment, obj.shipment_fk).order_fk
            if oid:
                order_ids.add(oid)
        for oid in sorted(order_ids):
            db.query(m.Order).filter_by(id=oid).with_for_update().first()
        for obj in pending:
            deleting = obj in db.deleted
            action = "DELETE" if deleting else "CREATE" if obj in db.new else "UPDATE"
            validate(db, obj, user, deleting)
            logs.append((obj, action, ", ".join(sorted(changes(obj)))))
        db.flush()
        for oid in order_ids:
            sync_order(db, oid)
        for obj, action, detail in logs:
            log_audit(db, user, action, type(obj).__name__, obj.id, detail)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Duplicate identifier or invalid related record") from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.info.pop("shipment_approval", None)
