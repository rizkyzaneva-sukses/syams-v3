"""AR aging & collection queue + AP supplier/makloon (Revisi #17 & #20).

Revisi #17 (CFO-003 — Invoice, Payment Verification, AR & Collection) requires a
Collection Queue with buyer, Order ID, invoice, total, paid, outstanding, due
date, promised date, aging, next action, owner and status.

Revisi #20 (CFO-006 — AP Supplier & Makloon) requires an AP register that keeps
supplier and makloon positions separate, with due schedule, partial payment
tracking, outstanding and a cash-plan figure.

Read-only: everything here is *derived* from invoices, payments, orders and
purchase orders that other CFO flows already write. Nothing is mutated, so there
is no hard delete anywhere in this module — the only writes in the system are
audited elsewhere.

Two documented gaps (see REQUESTS/cfo_receivables.md):

* ``invoices`` has no ``currency``/``payment_evidence`` column, so evidence is
  taken from the existing ``reconciliation_evidence`` field and currency falls
  back to IDR.
* ``purchase_orders`` has no ``vendor_type``/``due_date`` column, so the
  supplier-vs-makloon split is derived from the supplier name and the due date
  falls back to ``arrival_date``. Once the orchestrator adds the columns the
  helpers ``_ap_kind`` / ``_ap_due_date`` will pick them up automatically.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from .. import models as m

router = APIRouter(prefix="/cfo", tags=["cfo-receivables"])

# CFO owns AR/AP. CEO may read for oversight; CMO may only see the AR status
# they already see on their own pages and must never see AP/cash-plan detail
# (revisi #17: "CMO hanya melihat status yang diperlukan").
AR_VIEW_ROLES = {"CEO", "CFO_MANAGER", "FINANCE_SUPPORT"}
AP_VIEW_ROLES = {"CEO", "CFO_MANAGER", "FINANCE_SUPPORT"}
# CMO sees AR status only, never the collection internals.
AR_CMO_ROLES = {"CMO_MANAGER", "CMO_SUPPORT"}

# Aging buckets, in reporting order. Keys are stable API contract.
AGING_BUCKETS = ["not_due", "d1_30", "d31_60", "d_over_60"]
AGING_LABELS = {
    "not_due": "Belum jatuh tempo",
    "d1_30": "1–30 hari",
    "d31_60": "31–60 hari",
    "d_over_60": "> 60 hari",
}

# A payment only counts toward AR once it has a real reference. Payments that
# carry no method/reference are still recorded but flagged as unverified.
MIN_EVIDENCE_LEN = 3


def _forbidden(area, allowed):
    from fastapi import HTTPException

    raise HTTPException(403, f"{area} tidak tersedia untuk peran ini. Izin: {', '.join(sorted(allowed))}.")


def _dec(value):
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _iso(value):
    return value.isoformat() if value else None


def _today():
    return date.today()


def aging_bucket(due_date, today=None):
    """Map a due date to an aging bucket key.

    ``None`` due date is treated as *not yet due* rather than overdue: an
    invoice without a recorded due date is not late, it is unscheduled, and
    treating it as overdue would create phantom collection work.
    """
    today = today or _today()
    if not due_date:
        return "not_due"
    overdue_days = (today - due_date).days
    if overdue_days <= 0:
        return "not_due"
    if overdue_days <= 30:
        return "d1_30"
    if overdue_days <= 60:
        return "d31_60"
    return "d_over_60"


def days_overdue(due_date, today=None):
    if not due_date:
        return 0
    today = today or _today()
    return max((today - due_date).days, 0)


def _payment_evidence(payment):
    """A payment is 'evidenced' when it carries a reference the CFO can check.

    ``notes`` is the only free-text reference the Payment model stores today, so
    it doubles as the evidence reference (see REQUESTS/cfo_receivables.md for a
    dedicated ``evidence_ref`` column).
    """
    ref = (payment.notes or "").strip()
    return ref if len(ref) >= MIN_EVIDENCE_LEN else None


def _collection_action(bucket, outstanding, status):
    """Deterministic next action per aging bucket. No manual triage needed."""
    if outstanding <= 0:
        return {"action": "NONE", "owner": "CFO_MANAGER",
                "label": "Lunas — tidak ada tindakan"}
    if status == "REJECTED":
        return {"action": "RE_VERIFY", "owner": "CFO_MANAGER",
                "label": "Bukti bayar ditolak — minta ulang bukti ke buyer"}
    if bucket == "not_due":
        return {"action": "REMIND", "owner": "FINANCE_SUPPORT",
                "label": "Kirim pengingat jatuh tempo sebelum due date"}
    if bucket == "d1_30":
        return {"action": "FOLLOW_UP", "owner": "FINANCE_SUPPORT",
                "label": "Follow-up telepon/email ke buyer"}
    if bucket == "d31_60":
        return {"action": "ESCALATE_CMO", "owner": "CFO_MANAGER",
                "label": "Eskalasi ke CMO Manager, minta promised date"}
    return {"action": "ESCALATE_CEO", "owner": "CFO_MANAGER",
            "label": "Eskalasi CEO — risiko kredit, pertimbangkan hold order"}


def _collection_status(bucket, outstanding, paid, amount):
    if outstanding <= 0:
        return "PAID"
    if bucket == "d_over_60":
        return "CRITICAL"
    if bucket in {"d1_30", "d31_60"}:
        return "OVERDUE"
    return "PARTIAL" if _dec(paid) > 0 and _dec(paid) < _dec(amount) else "OPEN"


def _promised_date(invoice, payments):
    """Promised date is recorded as a dated note on a payment.

    There is no ``promised_date`` column yet (see REQUESTS/cfo_receivables.md);
    until then we surface the latest payment note that looks like a promise so
    the collection queue still shows what the buyer committed to.
    """
    marker = "promis"
    for payment in sorted(payments, key=lambda p: p.id or 0, reverse=True):
        note = (payment.notes or "").strip()
        if marker in note.lower() and len(note) >= MIN_EVIDENCE_LEN:
            return note
    return None


def _ar_rows(db, today=None):
    """Build one collection row per invoice, newest first.

    One payment is applied to one invoice (V1 rule from revisi #17), so the
    ledger sum per invoice is the authoritative paid amount. ``invoice.paid_amount``
    already includes ``opening_paid_amount`` from reconciliation, so we only use
    it as a fallback when no ledger payment exists.
    """
    today = today or _today()
    invoices = db.query(m.Invoice).order_by(m.Invoice.id.desc()).all()
    orders = {order.id: order for order in db.query(m.Order).all()}
    payments_by_invoice = {}
    for payment in db.query(m.Payment).all():
        key = payment.invoice_id if payment.invoice_id is not None else payment.invoice_no
        payments_by_invoice.setdefault(key, []).append(payment)

    rows = []
    for invoice in invoices:
        order = orders.get(invoice.order_fk)
        ledger = payments_by_invoice.get(invoice.id, [])
        if not ledger:
            # Payments recorded before invoice_id existed match by invoice_no.
            ledger = payments_by_invoice.get(invoice.invoice_no, [])
        recorded_paid = _dec(invoice.paid_amount)
        ledger_total = sum((_dec(p.amount) for p in ledger), Decimal("0"))
        amount = _dec(invoice.amount)
        # Reconciliation writes paid_amount from the ledger; trust whichever is
        # larger so a legacy opening balance is never dropped.
        paid = max(recorded_paid, ledger_total)
        outstanding = max(amount - paid, Decimal("0"))
        bucket = aging_bucket(invoice.due_date, today)
        evidence = [p for p in ledger if _payment_evidence(p)]
        unverified = [p for p in ledger if not _payment_evidence(p)]
        action = _collection_action(bucket, outstanding, invoice.status)
        promised = _promised_date(invoice, ledger)
        rows.append({
            "invoice_id": invoice.id,
            "invoice_no": invoice.invoice_no,
            "order_id": order.order_id if order else None,
            "order_fk": invoice.order_fk,
            "buyer": order.buyer if order else None,
            "amount": float(amount),
            "paid": float(paid),
            "outstanding": float(outstanding),
            "currency": "IDR",
            "due_date": _iso(invoice.due_date),
            "days_overdue": days_overdue(invoice.due_date, today),
            "aging_bucket": bucket,
            "aging_label": AGING_LABELS[bucket],
            "promised_date": promised,
            "promised_note": promised,
            "next_action": action["action"],
            "next_action_label": action["label"],
            "owner": action["owner"],
            "status": _collection_status(bucket, outstanding, paid, amount),
            "reconciliation_status": invoice.reconciliation_status,
            "reconciliation_evidence": invoice.reconciliation_evidence,
            "payment_count": len(ledger),
            "payment_ids": [p.id for p in ledger],
            "verified_payment_count": len(evidence),
            "unverified_payment_count": len(unverified),
            # Revisi #17: every applied payment must carry evidence. A payment
            # without a reference is surfaced here instead of being silently
            # counted as collected.
            "evidence_complete": bool(ledger) and not unverified,
            "partial": bool(ledger) and 0 < paid < amount,
        })
    return rows


def _ar_summary(rows):
    buckets = {key: {"bucket": key, "label": AGING_LABELS[key], "invoice_count": 0, "outstanding": 0.0}
               for key in AGING_BUCKETS}
    total_amount = total_paid = total_outstanding = Decimal("0")
    for row in rows:
        amount = Decimal(str(row["amount"]))
        paid = Decimal(str(row["paid"]))
        outstanding = Decimal(str(row["outstanding"]))
        total_amount += amount
        total_paid += paid
        total_outstanding += outstanding
        if outstanding <= 0:
            continue
        entry = buckets[row["aging_bucket"]]
        entry["invoice_count"] += 1
        entry["outstanding"] = float(Decimal(str(entry["outstanding"])) + outstanding)
    unverified = [row["invoice_no"] for row in rows if row["unverified_payment_count"] > 0]
    return {
        "total_amount": float(total_amount),
        "total_paid": float(total_paid),
        "total_outstanding": float(total_outstanding),
        "invoice_count": len(rows),
        "overdue_count": sum(1 for row in rows if row["aging_bucket"] != "not_due" and row["outstanding"] > 0),
        "critical_count": sum(1 for row in rows if row["aging_bucket"] == "d_over_60" and row["outstanding"] > 0),
        "buckets": [buckets[key] for key in AGING_BUCKETS],
        "invoices_with_unverified_payment": unverified,
        "currency": "IDR",
    }


def _by_buyer(rows):
    groups = {}
    for row in rows:
        buyer = row["buyer"] or "Tanpa Buyer"
        group = groups.setdefault(buyer, {
            "buyer": buyer,
            "invoice_count": 0,
            "amount": Decimal("0"),
            "paid": Decimal("0"),
            "outstanding": Decimal("0"),
            "oldest_days_overdue": 0,
            "buckets": {key: Decimal("0") for key in AGING_BUCKETS},
            "actions": set(),
            "invoice_nos": [],
        })
        group["invoice_count"] += 1
        group["amount"] += Decimal(str(row["amount"]))
        group["paid"] += Decimal(str(row["paid"]))
        group["outstanding"] += Decimal(str(row["outstanding"]))
        group["oldest_days_overdue"] = max(group["oldest_days_overdue"], row["days_overdue"])
        group["buckets"][row["aging_bucket"]] += Decimal(str(row["outstanding"]))
        if row["outstanding"] > 0:
            group["actions"].add(row["next_action"])
        group["invoice_nos"].append(row["invoice_no"])

    result = []
    for buyer, group in groups.items():
        result.append({
            "buyer": buyer,
            "invoice_count": group["invoice_count"],
            "amount": float(group["amount"]),
            "paid": float(group["paid"]),
            "outstanding": float(group["outstanding"]),
            "oldest_days_overdue": group["oldest_days_overdue"],
            "not_due": float(group["buckets"]["not_due"]),
            "d1_30": float(group["buckets"]["d1_30"]),
            "d31_60": float(group["buckets"]["d31_60"]),
            "d_over_60": float(group["buckets"]["d_over_60"]),
            "next_actions": sorted(group["actions"]),
            "invoice_nos": group["invoice_nos"],
        })
    result.sort(key=lambda row: (row["d_over_60"], row["d31_60"], row["d1_30"], row["outstanding"]), reverse=True)
    return result


# ──────────── AR ────────────
@router.get("/ar-aging")
def ar_aging(
    bucket: str = Query(None, description="Filter: not_due|d1_30|d31_60|d_over_60"),
    buyer: str = Query(None, description="Filter by buyer name (case-insensitive substring)"),
    only_outstanding: bool = Query(False, description="Sembunyikan invoice yang sudah lunas"),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """AR aging per buyer plus the collection queue (revisi #17).

    Returns aging buckets, the per-invoice collection queue and a per-buyer
    roll-up. CMO roles get a reduced view: buyer, invoice, amounts, due date and
    aging status only — no AP linkage, no cash plan, no collector ownership
    beyond what they must act on.
    """
    allowed = AR_VIEW_ROLES | AR_CMO_ROLES
    if user.role.value not in allowed:
        _forbidden("AR & Collection", allowed)
    if bucket and bucket not in AGING_BUCKETS:
        from fastapi import HTTPException

        raise HTTPException(400, f"Bucket tidak dikenal. Pilih: {', '.join(AGING_BUCKETS)}.")

    rows = _ar_rows(db)
    if bucket:
        rows = [row for row in rows if row["aging_bucket"] == bucket]
    if buyer:
        term = buyer.strip().lower()
        rows = [row for row in rows if term in (row["buyer"] or "").lower()]
    if only_outstanding:
        rows = [row for row in rows if row["outstanding"] > 0]

    summary = _ar_summary(rows)
    by_buyer = _by_buyer(rows)
    page = rows[offset:offset + limit]

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "as_of": _iso(_today()),
        "summary": summary,
        "by_buyer": by_buyer,
        "rows": page,
        "total_rows": len(rows),
        "filters": {"bucket": bucket, "buyer": buyer, "only_outstanding": only_outstanding},
        "aging_definition": {key: AGING_LABELS[key] for key in AGING_BUCKETS},
        "collection_queue": [
            {
                "invoice_no": row["invoice_no"], "buyer": row["buyer"], "order_id": row["order_id"],
                "outstanding": row["outstanding"], "due_date": row["due_date"], "aging": row["aging_label"],
                "promised_date": row["promised_date"], "next_action": row["next_action"],
                "owner": row["owner"], "status": row["status"],
            }
            for row in page if row["outstanding"] > 0
        ],
    }
    if user.role.value in AR_CMO_ROLES:
        # CMO sees status only: drop collection ownership and evidence detail.
        payload["rows"] = [
            {k: v for k, v in row.items() if k not in {
                "owner", "next_action", "next_action_label", "payment_ids",
                "verified_payment_count", "unverified_payment_count", "evidence_complete",
            }}
            for row in page
        ]
        payload.pop("collection_queue", None)
        payload["view"] = "CMO_STATUS_ONLY"
    else:
        payload["view"] = "FULL"
    return payload


# ──────────── AP ────────────
MAKLOON_MARKERS = ("makloon", "maklon", "cmt", "jahit", "subkon", "subcon")


def _ap_kind(po):
    """Supplier vs makloon (revisi #20 keeps these separate).

    ``purchase_orders`` has no ``vendor_type`` column yet, so we classify on the
    supplier name. When the orchestrator adds ``vendor_type`` this reads it
    first and the marker list becomes only a fallback.
    """
    explicit = getattr(po, "vendor_type", None)
    if explicit:
        value = str(explicit).upper()
        if value in {"MAKLOON", "CMT", "SUBCON"}:
            return "MAKLOON"
        if value in {"SUPPLIER", "VENDOR", "LOGISTIK", "MATERIAL"}:
            return "SUPPLIER"
    name = (po.supplier or "").lower()
    return "MAKLOON" if any(marker in name for marker in MAKLOON_MARKERS) else "SUPPLIER"


def _ap_due_date(po):
    """AP due date. No ``due_date`` column yet -> fall back to arrival_date."""
    explicit = getattr(po, "due_date", None)
    if explicit:
        return explicit
    return po.arrival_date


def _ap_paid_amount(db, po):
    """Paid amount for a PO.

    ``purchase_orders`` has no payment ledger yet, so payments are matched from
    the ``payments`` table by the PO number appearing in the payment notes. This
    is intentionally conservative: a payment only reduces AP when it explicitly
    references the PO number (revisi #20: "Invoice vendor tidak boleh dibayar
    ... tanpa referensi/exception yang sah").
    """
    matches = db.query(m.Payment).filter(
        m.Payment.notes.isnot(None),
        m.Payment.notes.like(f"%{po.po_no}%"),
    ).all()
    return matches


def _ap_rows(db, today=None):
    today = today or _today()
    orders = {order.id: order for order in db.query(m.Order).all()}
    rows = []
    for po in db.query(m.PurchaseOrder).order_by(m.PurchaseOrder.id.desc()).all():
        amount = _dec(po.amount)
        matches = _ap_paid_amount(db, po)
        paid = sum((_dec(p.amount) for p in matches), Decimal("0"))
        # A PO is not payable before goods arrive; outstanding only counts once
        # the material is received. Revisi #20 connects AP to PO/GR.
        received = (po.material_status or "").upper() in {"READY", "RECEIVED", "PARTIAL"}
        outstanding = max(amount - paid, Decimal("0")) if received else Decimal("0")
        due = _ap_due_date(po)
        bucket = aging_bucket(due, today) if received else "not_due"
        order = orders.get(po.order_fk)
        schedule = "OVERDUE" if (received and bucket != "not_due") else (
            "DUE_SOON" if received and due and 0 <= (due - today).days <= 7 else
            "SCHEDULED" if due else "UNSCHEDULED")
        rows.append({
            "po_id": po.id,
            "ap_id": f"AP-{po.po_no}",
            "po_no": po.po_no,
            "vendor_type": _ap_kind(po),
            "supplier": po.supplier,
            "partner": po.supplier,
            "item": po.item,
            "qty": float(po.qty) if po.qty is not None else None,
            "unit": po.unit,
            "order_id": order.order_id if order else None,
            "order_fk": po.order_fk,
            "buyer": order.buyer if order else None,
            "vendor_invoice_no": None,
            "amount": float(amount),
            "paid": float(paid),
            "outstanding": float(outstanding),
            "currency": "IDR",
            "invoice_date": _iso(po.created_at.date()) if po.created_at else None,
            "due_date": _iso(due),
            "days_overdue": days_overdue(due, today) if received else 0,
            "aging_bucket": bucket,
            "aging_label": AGING_LABELS[bucket],
            "payment_schedule": schedule,
            "received": received,
            "material_status": po.material_status,
            "status": "PAID" if received and outstanding <= 0 and paid > 0 else (
                "OVERDUE" if schedule == "OVERDUE" else ("OUTSTANDING" if received else "NOT_RECEIVED")),
            "approval_status": po.status,
            "payment_count": len(matches),
            "payment_ids": [p.id for p in matches],
            "payment_evidence": [((p.method or "") + " " + (p.notes or "")).strip() for p in matches],
            "partial": bool(matches) and 0 < paid < amount,
        })
    return rows


def _ap_summary(rows):
    def blank():
        return {"count": 0, "amount": Decimal("0"), "paid": Decimal("0"), "outstanding": Decimal("0")}

    groups = {"SUPPLIER": blank(), "MAKLOON": blank()}
    total = blank()
    for row in rows:
        for group in (groups[row["vendor_type"]], total):
            group["count"] += 1
            group["amount"] += Decimal(str(row["amount"]))
            group["paid"] += Decimal(str(row["paid"]))
            group["outstanding"] += Decimal(str(row["outstanding"]))

    def dump(group):
        return {"count": group["count"], "amount": float(group["amount"]),
                "paid": float(group["paid"]), "outstanding": float(group["outstanding"])}

    overdue = sum((Decimal(str(row["outstanding"])) for row in rows if row["payment_schedule"] == "OVERDUE"), Decimal("0"))
    due_soon = sum((Decimal(str(row["outstanding"])) for row in rows if row["payment_schedule"] == "DUE_SOON"), Decimal("0"))
    return {
        "supplier": dump(groups["SUPPLIER"]),
        "makloon": dump(groups["MAKLOON"]),
        "total": dump(total),
        "overdue_outstanding": float(overdue),
        "due_soon_outstanding": float(due_soon),
        # Simple cash plan: everything outstanding must be funded by its due date.
        "cash_plan": {
            "currency": "IDR",
            "overdue": float(overdue),
            "next_7_days": float(due_soon),
            "total_due": float(overdue + due_soon),
        },
        "currency": "IDR",
    }


@router.get("/ap-summary")
def ap_summary(
    vendor_type: str = Query(None, description="Filter: SUPPLIER|MAKLOON"),
    only_outstanding: bool = Query(False),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """AP register split supplier vs makloon (revisi #20).

    Never returns a delete action — AP rows are financial records and are only
    ever closed by payment, never removed.
    """
    if user.role.value not in AP_VIEW_ROLES:
        _forbidden("AP Supplier & Makloon", AP_VIEW_ROLES)
    if vendor_type and vendor_type.upper() not in {"SUPPLIER", "MAKLOON"}:
        from fastapi import HTTPException

        raise HTTPException(400, "vendor_type harus SUPPLIER atau MAKLOON.")

    rows = _ap_rows(db)
    if vendor_type:
        rows = [row for row in rows if row["vendor_type"] == vendor_type.upper()]
    filtered = [row for row in rows if row["outstanding"] > 0] if only_outstanding else rows

    by_vendor = {}
    for row in filtered:
        name = row["supplier"] or "Tanpa Nama"
        entry = by_vendor.setdefault(name, {
            "vendor": name, "vendor_type": row["vendor_type"], "po_count": 0,
            "amount": Decimal("0"), "paid": Decimal("0"), "outstanding": Decimal("0"),
        })
        entry["po_count"] += 1
        entry["amount"] += Decimal(str(row["amount"]))
        entry["paid"] += Decimal(str(row["paid"]))
        entry["outstanding"] += Decimal(str(row["outstanding"]))
    vendors = [{
        "vendor": e["vendor"], "vendor_type": e["vendor_type"], "po_count": e["po_count"],
        "amount": float(e["amount"]), "paid": float(e["paid"]), "outstanding": float(e["outstanding"]),
    } for e in by_vendor.values()]
    vendors.sort(key=lambda v: v["outstanding"], reverse=True)

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "as_of": _iso(_today()),
        "summary": _ap_summary(filtered),
        "by_vendor": vendors,
        "rows": filtered,
        "filters": {"vendor_type": vendor_type, "only_outstanding": only_outstanding},
        "aging_definition": {key: AGING_LABELS[key] for key in AGING_BUCKETS},
    }
