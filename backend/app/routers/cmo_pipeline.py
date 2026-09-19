"""Sales pipeline and demand gap (Revisi #14 poin 6 / #13 poin 4).

Revisi #10/#13/#14 all require a Sales Pipeline with weighted demand and a
Demand Gap against capacity. The dashboard previously reported these as
``unavailable_features``, so this router is the first implementation.

Read-only. Pipeline rows are derived from recorded buyers, orders and
quotations — nothing is mutated here, and permissions are enforced server-side.
"""
from datetime import date, datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from .. import models as m
from .master import capacity_rows

router = APIRouter(prefix="/cmo", tags=["cmo-pipeline"])

VIEW_ROLES = {"CEO", "CMO_MANAGER", "CMO_SUPPORT"}

# Opportunity stages, in the order a buyer moves through them.
STAGES = [
    ("BUYER", "Buyer / Prospek"),
    ("QUOTATION", "Quotation Disiapkan"),
    ("APPROVED", "Quotation Disetujui"),
    ("ORDER", "Order Aktif"),
    ("PRODUCTION", "Produksi"),
    ("SHIPMENT", "Pengiriman"),
    ("CLOSED", "Selesai"),
]
STAGE_ORDER = {key: index for index, (key, _) in enumerate(STAGES)}

# Probability weights per stage, used for weighted demand.
PROBABILITY = {
    "BUYER": 10, "QUOTATION": 40, "APPROVED": 70,
    "ORDER": 90, "PRODUCTION": 95, "SHIPMENT": 98, "CLOSED": 100,
}


def _require_view(user):
    if user.role.value not in VIEW_ROLES:
        raise HTTPException(403, "Sales Pipeline tidak tersedia untuk peran ini.")


def _stage_for_order(order):
    """Map an order's recorded progress to a pipeline stage.

    ``production_status`` lives on Article, not Order, so production progress is
    derived from the order's articles.
    """
    if order.overall_status == "CLOSED" or order.financial_close_status == "CLOSED":
        return "CLOSED"
    if order.shipment_status in {"SHIPPED", "DELIVERED"}:
        return "SHIPMENT"
    article_statuses = {article.production_status for article in order.articles}
    if article_statuses & {"IN_PROGRESS", "DONE"}:
        return "PRODUCTION"
    return "ORDER"


def _order_qty(order):
    return sum(int(article.qty or 0) for article in order.articles)


def _quote_value(db, order):
    """Approved quotation amount for an order, if one exists."""
    quote = (db.query(m.Quotation)
             .filter(m.Quotation.order_fk == order.id)
             .order_by(m.Quotation.id.desc()).first())
    if quote is None:
        return None, None
    return float(quote.amount or 0), quote.margin_percent


@router.get("/sales-pipeline")
def sales_pipeline(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Buyer/opportunity pipeline with weighted demand and Demand Gap."""
    _require_view(user)

    buyers = db.query(m.Customer).order_by(m.Customer.name).all()
    orders = db.query(m.Order).all()
    orders_by_buyer = {}
    for order in orders:
        orders_by_buyer.setdefault(order.buyer, []).append(order)

    rows = []
    seen_buyers = set()
    for buyer in buyers:
        seen_buyers.add(buyer.name)
        rows.append(_buyer_row(db, buyer.name, buyer.country, orders_by_buyer.get(buyer.name, [])))

    # Buyers recorded only on an order (not yet in the customer master).
    for name in sorted(orders_by_buyer):
        if name not in seen_buyers:
            rows.append(_buyer_row(db, name, None, orders_by_buyer[name]))

    rows.sort(key=lambda row: (STAGE_ORDER.get(row["stage"], 99), -row["expected_qty"]))

    # Demand gap: weighted demand against recorded daily capacity.
    capacity = capacity_rows(db)
    capacity_total = sum(
        int(row["capacity"] or 0) for row in capacity if row["capacity"] is not None
    )
    weighted_demand = sum(row["weighted_qty"] for row in rows)
    gap = weighted_demand - capacity_total if capacity_total else None

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "stages": [{"key": key, "label": label,
                    "count": sum(1 for row in rows if row["stage"] == key),
                    "expected_qty": sum(row["expected_qty"] for row in rows if row["stage"] == key)}
                   for key, label in STAGES],
        "rows": rows,
        "demand_gap": {
            "weighted_demand_qty": weighted_demand,
            "capacity_per_day": capacity_total if capacity_total else None,
            "gap_qty": gap,
            "verdict": ("BELUM ADA KAPASITAS" if not capacity_total
                        else "KAPASITAS CUKUP" if gap is not None and gap <= 0
                        else "DEMAND MELEBIHI KAPASITAS"),
            "note": "Kapasitas harian dijumlahkan dari snapshot proses yang tercatat.",
        },
    }


def _buyer_row(db, name, country, buyer_orders):
    """One pipeline row: the buyer's furthest-along order decides its stage."""
    if not buyer_orders:
        return {
            "buyer": name, "buyer_id": name, "country": country,
            "stage": "BUYER", "stage_label": dict(STAGES)["BUYER"],
            "order_id": None, "expected_qty": 0, "weighted_qty": 0,
            "probability": PROBABILITY["BUYER"], "expected_value": None,
            "margin_percent": None, "next_action": "Hubungi buyer & catat kebutuhan",
            "next_follow_up": None, "owner": "CMO_SUPPORT",
            "target_close": None, "repeat_opportunity": False,
        }

    order = max(buyer_orders, key=lambda item: STAGE_ORDER.get(_stage_for_order(item), 0))
    stage = _stage_for_order(order)
    qty = _order_qty(order)
    probability = PROBABILITY[stage]
    value, margin = _quote_value(db, order)
    stage_label = stages_label(stage)

    next_action = {
        "ORDER": "Review & aktifkan order",
        "PRODUCTION": "Pantau progres produksi",
        "SHIPMENT": "Konfirmasi penerimaan buyer",
        "CLOSED": "Cari peluang repeat order",
    }.get(stage, "Lanjutkan proses")

    return {
        "buyer": name, "buyer_id": name, "country": country,
        "stage": stage, "stage_label": stage_label,
        "order_id": order.order_id, "expected_qty": qty,
        "weighted_qty": round(qty * probability / 100),
        "probability": probability, "expected_value": value,
        "margin_percent": margin,
        "next_action": next_action,
        "next_follow_up": order.buyer_deadline,
        "owner": "CMO_MANAGER" if stage in {"ORDER", "PRODUCTION"} else "CMO_SUPPORT",
        "target_close": order.buyer_deadline,
        "repeat_opportunity": len(buyer_orders) > 1,
    }


def stages_label(stage):
    return dict(STAGES).get(stage, stage)


@router.get("/buyer-crm")
def buyer_crm(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Buyer CRM (revisi #14 poin 6): Buyer/Opportunity, stage, customer
    commitment, after-sales, next follow-up, owner dan repeat opportunity.

    Customer commitment and after-sales live here rather than as separate menus,
    which is what the locked blueprint requires. Read-only.
    """
    _require_view(user)

    customers = db.query(m.Customer).order_by(m.Customer.name).all()
    orders = db.query(m.Order).all()
    orders_by_buyer = {}
    for order in orders:
        orders_by_buyer.setdefault(order.buyer, []).append(order)

    # Delivery confirmations carry the after-sales / commitment signal.
    confirmations = {}
    for row in db.query(m.DeliveryConfirmation).all():
        shipment = db.get(m.Shipment, row.shipment_fk)
        if shipment is None:
            continue
        order = db.get(m.Order, shipment.order_fk)
        if order is None:
            continue
        confirmations.setdefault(order.buyer, []).append(row)

    rows = []
    seen = set()
    for customer in customers:
        seen.add(customer.name)
        rows.append(_crm_row(customer.name, customer, orders_by_buyer.get(customer.name, []),
                             confirmations.get(customer.name, [])))
    for name in sorted(orders_by_buyer):
        if name not in seen:
            rows.append(_crm_row(name, None, orders_by_buyer[name], confirmations.get(name, [])))

    # Most urgent follow-up first: overdue, then soonest, then no date.
    rows.sort(key=lambda row: (row["next_follow_up"] is None, row["next_follow_up"] or "9999-12-31"))
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "total_buyers": len(rows),
        "repeat_buyers": sum(1 for row in rows if row["repeat_opportunity"]),
        "rows": rows,
    }


def _crm_row(name, customer, buyer_orders, confirmations):
    active = [o for o in buyer_orders if o.overall_status != "CLOSED"]
    closed = [o for o in buyer_orders if o.overall_status == "CLOSED"]
    latest = max(buyer_orders, key=lambda o: o.id) if buyer_orders else None

    # Customer commitment: promised delivery date on the active order furthest along.
    commitment_order = max(active, key=lambda o: o.id) if active else latest
    promised = None
    if commitment_order is not None:
        promised = commitment_order.projected_shipment or commitment_order.buyer_deadline

    # After-sales: latest recorded delivery confirmation for this buyer.
    after_sales = None
    if confirmations:
        latest_confirmation = max(confirmations, key=lambda c: c.id)
        after_sales = {
            "confirmed_by_customer": latest_confirmation.confirmed_by_customer,
            "confirmation_date": latest_confirmation.confirmation_date.isoformat()
                                 if latest_confirmation.confirmation_date else None,
            "feedback": latest_confirmation.feedback,
            "status": latest_confirmation.status,
        }

    follow_up = promised
    return {
        "buyer": name,
        "buyer_id": customer.id if customer else None,
        "country": customer.country if customer else None,
        "contact_name": customer.contact_name if customer else None,
        "contact_info": customer.contact_info if customer else None,
        "notes": customer.notes if customer else None,
        "total_orders": len(buyer_orders),
        "active_orders": len(active),
        "closed_orders": len(closed),
        "latest_order_id": latest.order_id if latest else None,
        "customer_commitment": promised,
        "next_follow_up": follow_up,
        "owner": "CMO_SUPPORT" if active else "CMO_MANAGER",
        "after_sales": after_sales,
        "repeat_opportunity": len(buyer_orders) > 1,
        "next_action": ("Konfirmasi komitmen pengiriman ke buyer" if active
                        else "Tawarkan repeat order" if buyer_orders
                        else "Hubungi & catat kebutuhan buyer"),
    }


@router.get("/reports")
def cmo_reports(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """CMO performance report (Revisi #14 poin 8). Read-only, no data changes."""
    _require_view(user)

    quotes = db.query(m.Quotation).all()
    orders = db.query(m.Order).all()
    spks = db.query(m.SPK).all()
    samples = db.query(m.SampleRecord).all()

    approved = [q for q in quotes if q.status == "APPROVED"]
    rejected = [q for q in quotes if q.status == "REJECTED"]
    decided = len(approved) + len(rejected)
    decided_samples = [s for s in samples if s.customer_approved_by_id is not None]
    released = [k for k in spks if k.status == "RELEASED"]

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "pipeline": {
            "total_buyers": db.query(m.Customer).count(),
            "total_orders": len(orders),
            "active_orders": sum(1 for o in orders if o.overall_status != "CLOSED"),
            "closed_orders": sum(1 for o in orders if o.overall_status == "CLOSED"),
        },
        "quotation": {
            "total": len(quotes),
            "approved": len(approved),
            "rejected": len(rejected),
            "conversion_percent": round(len(approved) / decided * 100, 1) if decided else None,
            "approved_value": sum(float(q.amount or 0) for q in approved),
        },
        "sample": {
            "total": len(samples),
            "decided": len(decided_samples),
            "approval_percent": round(len(decided_samples) / len(samples) * 100, 1) if samples else None,
        },
        "spk": {
            "total": len(spks),
            "released": len(released),
            "release_percent": round(len(released) / len(spks) * 100, 1) if spks else None,
        },
    }
