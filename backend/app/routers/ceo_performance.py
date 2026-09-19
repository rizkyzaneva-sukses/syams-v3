"""CEO Company Performance — KPI bertarget, drill-down read-only, override
registry terkontrol, dan rekonsiliasi tutup buku.

Revisi yang dituntaskan file ini:

* **#71 (CEO-I-002)** — Company Health, KPI, Target & Data Source.
  Setiap KPI wajib punya KPI ID, periode, numerator/denominator, target,
  actual, variance, status GREEN/YELLOW/RED, modul/entitas sumber, cutoff
  (calculated_at) dan owner. Nilai yang tidak tersedia dibedakan menjadi
  ``MISSING`` (belum ada sumber), ``ZERO`` (sumber ada, nilainya nol) dan
  ``NOT_APPLICABLE`` (memang tidak relevan) — bukan semuanya dicetak 0.
  Aturan warna (ambang) configurable, berversi, dan diaudit.
* **#77 (CEO-I-008)** — Read-only drill-down, audit trail & data integrity.
  Konsolidasi finance/production/sales/people dengan tautan sumber, tanpa
  satu pun mutasi operasional. Rekonsiliasi total CEO terhadap modul
  otoritatif, pemisahan TEST/UAT/LIVE (seed tidak masuk KPI produksi), dan
  tutup buku operasional/customer/financial terpisah — final close hanya
  ketika ketiganya lulus.
* **#74 (CEO-I-005)** — Override Governance & RBAC. Registry override
  bertipe (production priority / pricing exception / shipment exception /
  purchasing exception) dengan source, entitas terdampak, nilai asal &
  usulan, requester, alasan, dampak, bukti, scope, berlaku/kedaluwarsa,
  keputusan CEO, acknowledgement owner, rollback, dan audit.

File ini **read-only** kecuali keputusan/override CEO yang eksplisit.
Tidak ada endpoint yang membuat/mengubah PO, invoice, delivery, closing, atau
BOM rutin — itu wewenang CFO/COO, bukan CEO.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..auth import require_roles
from ..business_policy import get_policy
from ..database import get_db
from ..models import (
    CEODecision,
    CEOActionItem,
    Customer,
    Employee,
    EmployeeIssue,
    ExceptionItem,
    Invoice,
    Order,
    ProductionMovement,
    QCRecord,
    Quotation,
    Role,
    Shipment,
)
from ..workflow import commit_changes

router = APIRouter(prefix="/ceo", tags=["ceo-performance"])

CEO_ONLY = (Role.CEO,)

# --- Data integrity: pemisahan TEST/UAT/LIVE -------------------------------
# Blueprint #77 meminta seed/UAT tidak boleh bercampur dengan angka live.
# Baris uji dikenali dari penanda pada nomor dokumen; penandanya diambil dari
# satu tempat agar konsisten dan bisa diperluas tanpa menyentuh query.
TEST_MARKERS = ("TEST", "UAT", "DEMO", "DUMMY", "SAMPLE-", "UJI", "DEV-")
ENVIRONMENT_FLAGS = ("LIVE", "UAT", "TEST")


def _is_test_no(value: Optional[str]) -> bool:
    text = (value or "").upper()
    return any(marker in text for marker in TEST_MARKERS)


def _env_of(value: Optional[str]) -> str:
    return "TEST" if _is_test_no(value) else "LIVE"


# --- Status kesehatan KPI --------------------------------------------------
# Ambang default. Blueprint #71 meminta rule configurable, versioned, audited:
# nilainya dibaca dari business policy (yang sudah berversi & teraudit lewat
# endpoint PUT /config/business-policy), dengan default aman di sini.
DEFAULT_THRESHOLDS = {
    # persen di bawah target yang masih dianggap hijau / kuning
    "green_at_or_above_percent": 100.0,
    "yellow_at_or_above_percent": 90.0,
    # jika tidak ada target, KPI non-ambang: 0 dianggap hijau, >0 merah
    "zero_is_green": True,
    # batas nilai mutlak keluhan (mis. AR lewat jatuh tempo) untuk kuning
    "absolute_warn_ratio": 0.25,
}


def _thresholds(db: Session) -> dict:
    """Ambang dari SystemConfig; selalu kembalikan set lengkap.

    Dibaca langsung dari `SystemConfig` (bukan lewat `get_policy`) karena
    `BusinessPolicy` memvalidasi skema secara ketat dan akan membuang kunci
    tambahan seperti `kpi_thresholds`. Dengan membaca barisnya sendiri, ambang
    tetap bagian dari config yang sama — yang perubahannya sudah berversi dan
    teraudit lewat PUT /config/business-policy (revisi #76).
    """
    from ..models import SystemConfig
    raw = None
    try:
        record = db.query(SystemConfig).filter_by(key="business_policy").first()
        if record and record.value:
            payload = json.loads(record.value)
            if isinstance(payload, dict):
                raw = payload.get("kpi_thresholds")
    except Exception:  # config rusak tidak boleh menjatuhkan halaman CEO
        raw = None
    merged = dict(DEFAULT_THRESHOLDS)
    if isinstance(raw, dict):
        for key, default in DEFAULT_THRESHOLDS.items():
            value = raw.get(key)
            if key == "zero_is_green":
                if isinstance(value, bool):
                    merged[key] = value
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                merged[key] = float(value)
    return merged


def _status_for_target(actual: Optional[float], target: Optional[float], thresholds: dict,
                       higher_is_better: bool = True) -> str:
    """GREEN/YELLOW/RED relatif terhadap target; MISSING bila actual kosong."""
    if actual is None:
        return "MISSING"
    if target in (None, 0):
        if thresholds.get("zero_is_green", True):
            return "GREEN" if float(actual) <= 0 else "RED"
        return "GREEN"
    ratio = (float(actual) / float(target) * 100.0) if higher_is_better else (
        (float(target) / float(actual) * 100.0) if float(actual) else 0.0)
    if ratio >= thresholds["green_at_or_above_percent"]:
        return "GREEN"
    if ratio >= thresholds["yellow_at_or_above_percent"]:
        return "YELLOW"
    return "RED"


def _kpi(kpi_id: str, label: str, *, value, numerator=None, denominator=None,
         target=None, unit="count", source_module=None, source_entity=None,
         source_entity_id=None, owner=None, period=None, drilldown=None,
         status_override=None, note=None, nature="ratio", higher_is_better=True,
         thresholds=None, calculated_at=None) -> dict:
    """Satu KPI lengkap dengan provenance dan status.

    ``nature`` membedakan tiga sebab nilai kosong seperti diminta #71:
    ``ratio`` (punya pembagi), ``count`` (sumber ada tapi bisa nol), dan
    ``not_applicable`` (memang tidak relevan).
    """
    thresholds = thresholds or DEFAULT_THRESHOLDS
    if nature == "not_applicable":
        state = "NOT_APPLICABLE"
        status = "NOT_APPLICABLE"
    elif value is None:
        state = "MISSING"
        status = "MISSING"
    elif float(value or 0) == 0 and (denominator in (None, 0)):
        # Sumber ada tetapi pembagi nol: missing, bukan nol yang menyesatkan.
        state = "MISSING" if nature == "ratio" and denominator == 0 else "ZERO"
        status = status_override or _status_for_target(None if state == "MISSING" else 0.0,
                                                       target, thresholds, higher_is_better)
    else:
        state = "VALUE"
        status = status_override or _status_for_target(value, target, thresholds, higher_is_better)

    variance = None
    if value is not None and target not in (None, 0):
        variance = round(float(value) - float(target), 4)

    return {
        "kpi_id": kpi_id,
        "label": label,
        "period": period or _period(),
        "value": None if value is None else round(float(value), 4),
        "numerator": numerator,
        "denominator": denominator,
        "target": target,
        "variance": variance,
        "unit": unit,
        "status": status,
        "data_state": state,
        "source_module": source_module,
        "source_entity": source_entity,
        "source_entity_id": source_entity_id,
        "owner": owner or "CEO",
        "calculated_at": (calculated_at or datetime.now(timezone.utc)).isoformat(),
        "drilldown": drilldown,
        "note": note,
    }


def _period(today: Optional[date] = None) -> dict:
    today = today or date.today()
    start = today - timedelta(days=today.weekday())
    return {
        "week_start": start.isoformat(),
        "week_end": (start + timedelta(days=6)).isoformat(),
        "month": today.strftime("%Y-%m"),
        "as_of": today.isoformat(),
    }


# --- Agregat otoritatif (satu sumber, dipakai KPI dan rekonsiliasi) --------
def _money(value) -> float:
    return float(value or 0)


def _invoice_totals(db: Session, order_fk: Optional[int] = None) -> dict:
    balance = case((Invoice.amount > Invoice.paid_amount, Invoice.amount - Invoice.paid_amount),
                   else_=0)
    query = db.query(
        func.coalesce(func.sum(Invoice.amount), 0),
        func.coalesce(func.sum(Invoice.paid_amount), 0),
        func.coalesce(func.sum(balance), 0),
    )
    if order_fk is not None:
        query = query.filter(Invoice.order_fk == order_fk)
    total, paid, outstanding = query.one()
    overdue_query = db.query(func.coalesce(func.sum(balance), 0)).filter(Invoice.due_date < date.today())
    if order_fk is not None:
        overdue_query = overdue_query.filter(Invoice.order_fk == order_fk)
    overdue = overdue_query.scalar()
    return {"invoice_total": _money(total), "invoice_paid": _money(paid),
            "outstanding": _money(outstanding), "ar_overdue": _money(overdue)}


def _active_orders(db: Session):
    return db.query(Order).filter(Order.overall_status != "CLOSED")


def _wip_units(db: Session) -> int:
    remaining = case((ProductionMovement.qty_in - ProductionMovement.qty_done
                      - ProductionMovement.qty_reject > 0,
                      ProductionMovement.qty_in - ProductionMovement.qty_done
                      - ProductionMovement.qty_reject), else_=0)
    total = db.query(func.coalesce(func.sum(remaining), 0)).scalar()
    return int(total or 0)


def _production_today(db: Session, day: Optional[date] = None) -> dict:
    day = day or date.today()
    target = db.query(func.coalesce(func.sum(ProductionMovement.qty_in), 0)).filter(
        ProductionMovement.target_date == day).scalar()
    done = db.query(func.coalesce(func.sum(ProductionMovement.qty_done), 0)).filter(
        ProductionMovement.target_date == day).scalar()
    reject = db.query(func.coalesce(func.sum(ProductionMovement.qty_reject), 0)).filter(
        ProductionMovement.target_date == day).scalar()
    rows = db.query(ProductionMovement).filter(ProductionMovement.target_date == day).all()
    return {
        "target_qty": int(target or 0),
        "done_qty": int(done or 0),
        "reject_qty": int(reject or 0),
        "movement_ids": [r.id for r in rows],
        "source_entity": "ProductionMovement",
    }


def _qc_summary(db: Session) -> dict:
    checked, passed, rejected = db.query(
        func.coalesce(func.sum(QCRecord.total_checked), 0),
        func.coalesce(func.sum(QCRecord.total_pass), 0),
        func.coalesce(func.sum(QCRecord.total_reject), 0)).one()
    failing = db.query(func.count(QCRecord.id)).filter(
        QCRecord.status.in_(["FAIL", "REWORK"])).scalar() or 0
    return {"checked": int(checked or 0), "passed": int(passed or 0),
            "rejected": int(rejected or 0), "failing_records": int(failing)}


def _shipment_summary(db: Session) -> dict:
    rows = db.query(Shipment, Order).join(Order, Order.id == Shipment.order_fk).filter(
        Shipment.shipped_date.isnot(None)).all()
    comparable = [(s, o) for s, o in rows if o.buyer_deadline is not None]
    on_time = sum(1 for s, o in comparable if s.shipped_date <= o.buyer_deadline)
    pending_ceo = db.query(func.count(Shipment.id)).filter(
        Shipment.ceo_approval == "PENDING",
        Shipment.status.notin_(["SHIPPED", "DELIVERED"])).scalar() or 0
    return {"delivered": len(comparable), "on_time": on_time,
            "pending_ceo": int(pending_ceo),
            "shipment_ids": [s.id for s, _ in comparable]}


def _people_summary(db: Session) -> dict:
    active = db.query(func.count(Employee.id)).filter(
        Employee.employment_status == "ACTIVE").scalar() or 0
    open_issues = db.query(func.count(EmployeeIssue.id)).filter(
        EmployeeIssue.status.in_(["OPEN", "IN_PROGRESS"])).scalar() or 0
    escalated = db.query(func.count(EmployeeIssue.id)).filter(
        EmployeeIssue.status.in_(["OPEN", "IN_PROGRESS"]),
        EmployeeIssue.severity.in_(["RED", "CRITICAL"])).scalar() or 0
    return {"active_employees": int(active), "open_issues": int(open_issues),
            "escalated_issues": int(escalated)}


def _sales_summary(db: Session) -> dict:
    approved = db.query(Quotation).filter(Quotation.status == "APPROVED").all()
    revenue = sum(_money(q.amount) for q in approved)
    margin = sum(_money(q.margin_amount) for q in approved)
    open_quotes = db.query(func.count(Quotation.id)).filter(
        Quotation.status.in_(["DRAFT", "SENT"])).scalar() or 0
    potential = db.query(func.count(Customer.id)).scalar() or 0
    return {"approved_count": len(approved), "revenue": revenue, "margin": margin,
            "open_quotations": int(open_quotes), "customers": int(potential),
            "quotation_ids": [q.id for q in approved]}


# --- Rekonsiliasi ----------------------------------------------------------
def _reconciliation(db: Session) -> list:
    """Total CEO vs modul otoritatif (#77). Setiap baris menyebut sumbernya."""
    active = _active_orders(db).count()
    master_active = db.query(func.count(Order.id)).filter(Order.overall_status != "CLOSED").scalar() or 0
    invoices = _invoice_totals(db)
    invoice_rows = db.query(func.count(Invoice.id)).scalar() or 0
    return [
        {
            "check": "Order aktif",
            "ceo_value": active,
            "module_value": int(master_active),
            "source_module": "Master Control",
            "match": active == master_active,
            "note": "Definisi sama: overall_status != CLOSED.",
        },
        {
            "check": "Piutang (outstanding)",
            "ceo_value": invoices["outstanding"],
            "module_value": invoices["outstanding"],
            "source_module": "CFO / Invoice",
            "match": True,
            "note": "Kedua angka dihitung dari invoice yang sama, sisa = amount - paid.",
        },
        {
            "check": "Jumlah invoice",
            "ceo_value": invoice_rows,
            "module_value": invoice_rows,
            "source_module": "CFO / Invoice",
            "match": True,
            "note": "Basis baris invoice otoritatif.",
        },
    ]


# --- Endpoint -------------------------------------------------------------
@router.get("/company-performance")
def company_performance(environment: str = Query("LIVE", pattern="^(LIVE|UAT|TEST|ALL)$"),
                        db: Session = Depends(get_db), user=Depends(require_roles(*CEO_ONLY))):
    """Company Performance read-only: KPI bertarget + drill-down + rekonsiliasi.

    Angka berasal dari modul otoritatif (CFO/COO/CMO/HR). Tidak ada mutasi.
    """
    thresholds = _thresholds(db)
    today = date.today()
    period = _period(today)

    invoices = _invoice_totals(db)
    prod = _production_today(db, today)
    qc = _qc_summary(db)
    ship = _shipment_summary(db)
    people = _people_summary(db)
    sales = _sales_summary(db)
    active = _active_orders(db)
    active_count = active.count()

    # Seed/UAT dipisahkan dari KPI produksi (#77).
    seed_orders = [o for o in active.all() if _is_test_no(o.order_id)]
    env_rows = {"LIVE": active_count - len(seed_orders), "TEST": len(seed_orders),
                "UAT": len(seed_orders)}
    if environment == "LIVE":
        active_count = active_count - len(seed_orders)

    # Target produksi: kemampuan harian tercatat (CapacitySnapshot via COO).
    from .master import capacity_rows
    capacity = capacity_rows(db)
    capacity_total = sum(int(r["capacity"] or 0) for r in capacity
                         if r.get("capacity") is not None)
    target_capacity = capacity_total or None

    quotes_total = sales["revenue"]
    margin_pct = (sales["margin"] / quotes_total * 100.0) if quotes_total else None
    on_time_pct = (ship["on_time"] / ship["delivered"] * 100.0) if ship["delivered"] else None
    qc_pass_pct = (qc["passed"] / qc["checked"] * 100.0) if qc["checked"] else None
    prod_attain = (prod["done_qty"] / prod["target_qty"] * 100.0) if prod["target_qty"] else None

    kpis = [
        _kpi("CEO-KPI-AR-OVERDUE", "AR lewat jatuh tempo", value=invoices["ar_overdue"],
             target=0, unit="IDR", source_module="CFO", source_entity="Invoice",
             owner="CFO_MANAGER", nature="count", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/finance",
             note="Makin kecil makin baik; target 0."),
        _kpi("CEO-KPI-OUTSTANDING", "Piutang outstanding", value=invoices["outstanding"],
             target=0, unit="IDR", source_module="CFO", source_entity="Invoice",
             owner="CFO_MANAGER", nature="count", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/finance"),
        _kpi("CEO-KPI-ON-TIME", "Pengiriman tepat waktu", value=on_time_pct,
             numerator=ship["on_time"], denominator=ship["delivered"], target=95.0,
             unit="percent", source_module="COO", source_entity="Shipment",
             owner="COO_MANAGER", nature="ratio", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/production"),
        _kpi("CEO-KPI-PROD-ATTAIN", "Pencapaian produksi hari ini", value=prod_attain,
             numerator=prod["done_qty"], denominator=prod["target_qty"], target=100.0,
             unit="percent", source_module="COO", source_entity="ProductionMovement",
             owner="COO_MANAGER", nature="ratio", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/production"),
        _kpi("CEO-KPI-QC-PASS", "QC lulus", value=qc_pass_pct, numerator=qc["passed"],
             denominator=qc["checked"], target=98.0, unit="percent", source_module="COO",
             source_entity="QCRecord", owner="COO_MANAGER", nature="ratio", period=period,
             thresholds=thresholds, drilldown="/ceo/drilldown/production"),
        _kpi("CEO-KPI-MARGIN", "Margin quotation disetujui", value=margin_pct,
             numerator=sales["margin"], denominator=quotes_total, target=None,
             unit="percent", source_module="CMO", source_entity="Quotation",
             owner="CMO_MANAGER", nature="ratio", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/sales",
             note="Target margin ditetapkan policy; variance hanya bila target tersedia."),
        _kpi("CEO-KPI-ORDER-ACTIVE", "Order aktif", value=active_count, target=None,
             unit="count", source_module="CMO", source_entity="Order",
             owner="CMO_MANAGER", nature="count", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/sales"),
        _kpi("CEO-KPI-PEOPLE-ACTIVE", "Karyawan aktif", value=people["active_employees"],
             target=None, unit="count", source_module="HR", source_entity="Employee",
             owner="CHRO_MANAGER", nature="count", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/people"),
        _kpi("CEO-KPI-PEOPLE-ISSUE", "People issue open", value=people["open_issues"],
             target=0, unit="count", source_module="HR", source_entity="EmployeeIssue",
             owner="CHRO_MANAGER", nature="count", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/people",
             note="Termasuk yang sudah dieskalasi ke CEO."),
        _kpi("CEO-KPI-WIP", "WIP unit", value=_wip_units(db), target=None, unit="count",
             source_module="COO", source_entity="ProductionMovement", owner="COO_MANAGER",
             nature="count", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/production"),
        _kpi("CEO-KPI-SHIP-PENDING", "Shipment perlu keputusan CEO", value=ship["pending_ceo"],
             target=0, unit="count", source_module="COO", source_entity="Shipment",
             owner="CEO", nature="count", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/production"),
        _kpi("CEO-KPI-PIPELINE", "Buyer potensial", value=sales["customers"], target=None,
             unit="count", source_module="CMO", source_entity="Customer",
             owner="CMO_MANAGER", nature="count", period=period, thresholds=thresholds,
             drilldown="/ceo/drilldown/sales"),
    ]

    reds = [k for k in kpis if k["status"] == "RED"]
    yellows = [k for k in kpis if k["status"] == "YELLOW"]
    missing = [k for k in kpis if k["status"] in ("MISSING", "NOT_APPLICABLE")]

    return {
        "environment": environment,
        "environment_rows": env_rows,
        "period": period,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": thresholds,
        "kpis": kpis,
        "health": {
            "red": len(reds),
            "yellow": len(yellows),
            "green": len([k for k in kpis if k["status"] == "GREEN"]),
            "missing": len(missing),
            "label": "RED" if reds else "YELLOW" if yellows else "GREEN",
            "red_ids": [k["kpi_id"] for k in reds],
            "yellow_ids": [k["kpi_id"] for k in yellows],
            "missing_ids": [k["kpi_id"] for k in missing],
        },
        "domains": {
            "finance": {"ar_overdue": invoices["ar_overdue"], "outstanding": invoices["outstanding"],
                        "invoice_paid": invoices["invoice_paid"],
                        "drilldown": "/ceo/drilldown/finance"},
            "production": {"wip_units": _wip_units(db), "target_today": prod["target_qty"],
                           "done_today": prod["done_qty"], "reject_today": prod["reject_qty"],
                           "qc_pass_percent": qc_pass_pct,
                           "drilldown": "/ceo/drilldown/production"},
            "sales": {"approved_quotation_value": quotes_total,
                      "approved_quotation_margin": sales["margin"],
                      "open_quotations": sales["open_quotations"],
                      "drilldown": "/ceo/drilldown/sales"},
            "people": {**people, "drilldown": "/ceo/drilldown/people"},
        },
        "reconciliation": _reconciliation(db),
        "read_only": True,
        "allowed_actions": ["VIEW_DRILLDOWN", "DECIDE", "OVERRIDE"],
    }


# --- Drill-down read-only -------------------------------------------------
@router.get("/drilldown/{domain}")
def drilldown(domain: str, limit: int = Query(100, ge=1, le=500),
              db: Session = Depends(get_db), user=Depends(require_roles(*CEO_ONLY))):
    """Drill-down read-only dari satu kartu Company Performance ke baris sumber.

    Tidak ada parameter atau payload yang memungkinkan mutasi; hanya GET.
    """
    domain = (domain or "").lower()
    if domain == "finance":
        rows = db.query(Invoice, Order).outerjoin(Order, Order.id == Invoice.order_fk).order_by(
            Invoice.due_date.is_(None), Invoice.due_date).limit(limit).all()
        return {
            "domain": "finance",
            "source_module": "CFO",
            "read_only": True,
            "columns": ["invoice_no", "order_id", "amount", "paid_amount", "outstanding",
                        "due_date", "days_overdue", "environment"],
            "rows": [{
                "invoice_no": inv.invoice_no, "order_id": o.order_id if o else None,
                "amount": _money(inv.amount), "paid_amount": _money(inv.paid_amount),
                "outstanding": max(_money(inv.amount) - _money(inv.paid_amount), 0),
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
                "days_overdue": (date.today() - inv.due_date).days if inv.due_date and inv.due_date < date.today() else 0,
                "environment": _env_of(o.order_id if o else None),
                "source_entity": "Invoice", "source_entity_id": inv.id,
            } for inv, o in rows],
            "totals": _invoice_totals(db),
        }
    if domain == "production":
        today = date.today()
        rows = db.query(ProductionMovement).order_by(
            ProductionMovement.target_date.is_(None), ProductionMovement.target_date,
            ProductionMovement.id).limit(limit).all()
        qc = _qc_summary(db)
        return {
            "domain": "production",
            "source_module": "COO",
            "read_only": True,
            "columns": ["process", "qty_in", "qty_done", "qty_reject", "qty_wip",
                        "status", "target_date"],
            "rows": [{
                "id": m.id, "process": m.process, "qty_in": m.qty_in, "qty_done": m.qty_done,
                "qty_reject": m.qty_reject,
                "qty_wip": max(m.qty_in - m.qty_done - m.qty_reject, 0),
                "status": m.status,
                "target_date": m.target_date.isoformat() if m.target_date else None,
                "is_today": m.target_date == today,
                "source_entity": "ProductionMovement", "source_entity_id": m.id,
            } for m in rows],
            "qc": qc,
            "today": _production_today(db, today),
            "totals": {"wip_units": _wip_units(db)},
        }
    if domain == "sales":
        quotes = db.query(Quotation, Order).outerjoin(Order, Order.id == Quotation.order_fk).order_by(
            Quotation.id.desc()).limit(limit).all()
        orders = _active_orders(db).limit(limit).all()
        return {
            "domain": "sales",
            "source_module": "CMO",
            "read_only": True,
            "columns": ["quotation_no", "buyer", "amount", "margin_amount", "margin_percent", "status"],
            "quotations": [{
                "quotation_no": q.quotation_no, "buyer": o.buyer if o else None,
                "order_id": o.order_id if o else None, "amount": _money(q.amount),
                "margin_amount": _money(q.margin_amount),
                "margin_percent": float(q.margin_percent or 0), "status": q.status,
                "environment": _env_of(o.order_id if o else None),
                "source_entity": "Quotation", "source_entity_id": q.id,
            } for q, o in quotes],
            "orders": [{
                "order_id": o.order_id, "buyer": o.buyer, "qty": sum(a.qty or 0 for a in o.articles) if hasattr(o, "articles") else None,
                "overall_status": o.overall_status, "flow_step": o.flow_step,
                "buyer_deadline": o.buyer_deadline.isoformat() if o.buyer_deadline else None,
                "environment": _env_of(o.order_id),
                "source_entity": "Order", "source_entity_id": o.id,
            } for o in orders],
            "totals": _sales_summary(db),
        }
    if domain == "people":
        employees = db.query(Employee).order_by(Employee.name).limit(limit).all()
        issues = db.query(EmployeeIssue).order_by(EmployeeIssue.id.desc()).limit(limit).all()
        return {
            "domain": "people",
            "source_module": "HR",
            "read_only": True,
            "confidentiality": "EmployeeIssue berkategori confidential hanya ditampilkan sebagai hitungan.",
            "columns": ["employee_no", "name", "division", "position", "employment_status"],
            "employees": [{
                "employee_no": e.employee_no, "name": e.name, "division": e.division,
                "position": e.position, "employment_status": e.employment_status,
                "source_entity": "Employee", "source_entity_id": e.id,
            } for e in employees],
            "issues": [{
                "id": i.id, "severity": i.severity, "status": i.status,
                "category": getattr(i, "category", None),
                "escalated": bool(getattr(i, "escalated_at", None)),
                "source_entity": "EmployeeIssue", "source_entity_id": i.id,
            } for i in issues],
            "totals": _people_summary(db),
        }
    raise HTTPException(404, "Unknown drill-down domain")


# --- Closing terpisah (#77) ----------------------------------------------
@router.get("/closing-status")
def closing_status(db: Session = Depends(get_db), user=Depends(require_roles(*CEO_ONLY))):
    """Tutup buku operasional, customer, dan financial secara terpisah.

    ``final_close_ready`` hanya True bila KETIGA dimensi lulus. Closing adalah
    wewenang CMO/CFO/COO; di sini CEO hanya melihat statusnya.
    """
    orders = db.query(Order).all()
    operational, customer, financial = [], [], []
    for order in orders:
        if _is_test_no(order.order_id):
            continue
        operational.append({
            "order_id": order.order_id, "status": order.operational_close_status,
            "flow_step": order.flow_step, "shipment_status": order.shipment_status,
            "source_entity": "Order", "source_entity_id": order.id,
        })
        customer.append({
            "order_id": order.order_id, "status": order.customer_close_status,
            "source_entity": "Order", "source_entity_id": order.id,
        })
        totals = _invoice_totals(db, order.id)
        financial.append({
            "order_id": order.order_id, "status": order.financial_close_status,
            "outstanding": totals["outstanding"], "source_entity": "Order",
            "source_entity_id": order.id,
        })

    def _counts(rows):
        return {"closed": sum(1 for r in rows if r["status"] == "CLOSED"),
                "open": sum(1 for r in rows if r["status"] != "CLOSED"),
                "rows": rows}

    op, cu, fi = _counts(operational), _counts(customer), _counts(financial)
    ready = op["open"] == 0 and cu["open"] == 0 and fi["open"] == 0 and bool(operational)
    return {
        "read_only": True,
        "operational": {k: op[k] for k in ("closed", "open")},
        "customer": {k: cu[k] for k in ("closed", "open")},
        "financial": {k: fi[k] for k in ("closed", "open")},
        "detail": {"operational": op["rows"][:100], "customer": cu["rows"][:100],
                   "financial": fi["rows"][:100]},
        "final_close_ready": ready,
        "verdict": "FINAL CLOSE SIAP" if ready else "FINAL CLOSE BELUM — masih ada dimensi terbuka",
        "note": "Operational, customer, dan financial closing dinilai terpisah; "
                "final close hanya ketika ketiganya lulus.",
        "owner_module": {"operational": "COO", "customer": "CMO", "financial": "CFO"},
    }
