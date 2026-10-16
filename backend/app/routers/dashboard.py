"""Role-scoped dashboards derived from recorded transactions."""
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from ..database import get_db
from ..auth import get_current_user
from .. import models as m
from .master import capacity_rows

router = APIRouter(tags=["dashboards"])
MODULE_ROLES = {
    "CMO": {"CEO", "CMO_MANAGER", "CMO_SUPPORT"},
    "CFO": {"CEO", "CFO_MANAGER"},
    "COO": {"CEO", "COO_MANAGER", "PRODUCTION_PIC", "PRINTING_PIC", "SAMPLE_PIC", "SHIPMENT_ADMIN"},
    "CHRO": {"CEO", "CHRO_MANAGER", "HR_SUPPORT"},
    "CEO": {"CEO"},
    "SAMPLE": {"CEO", "COO_MANAGER", "SAMPLE_PIC", "CMO_MANAGER"},
    "PRINTING": {"CEO", "COO_MANAGER", "PRINTING_PIC"},
    "PRODUCTION": {"CEO", "COO_MANAGER", "PRODUCTION_PIC"},
    "SHIPMENT": {"CEO", "COO_MANAGER", "SHIPMENT_ADMIN", "CFO_MANAGER"},
}


def count(db, model, *conditions):
    return db.query(func.count(model.id)).filter(*conditions).scalar() or 0


def card(label, value, unit="count"):
    return {"label": label, "value": value, "unit": unit}


def money_summary(db):
    balance = case((m.Invoice.amount > m.Invoice.paid_amount, m.Invoice.amount - m.Invoice.paid_amount), else_=0)
    outstanding = float(db.query(func.coalesce(func.sum(balance), 0)).scalar())
    overdue = float(db.query(func.coalesce(func.sum(balance), 0)).filter(m.Invoice.due_date < date.today()).scalar())
    paid = float(db.query(func.coalesce(func.sum(m.Invoice.paid_amount), 0)).scalar())
    return outstanding, overdue, paid


def operational_kpis(db):
    delivered = db.query(m.Shipment, m.Order).join(m.Order, m.Order.id == m.Shipment.order_fk).filter(
        m.Shipment.status == "DELIVERED", m.Shipment.shipped_date.isnot(None),
        m.Order.buyer_deadline.isnot(None)).all()
    on_time = sum(shipment.shipped_date <= order.buyer_deadline for shipment, order in delivered)
    checked, passed = db.query(func.coalesce(func.sum(m.QCRecord.total_checked), 0),
        func.coalesce(func.sum(m.QCRecord.total_pass), 0)).one()
    approved = db.query(m.Quotation).filter(m.Quotation.status == "APPROVED").all()
    revenue = sum(float(q.amount or 0) for q in approved)
    margin = sum(float(q.margin_amount or 0) for q in approved)
    return {
        "on_time_shipments": {"value": round(on_time / len(delivered) * 100, 1) if delivered else None,
                              "numerator": on_time, "denominator": len(delivered), "unit": "percent"},
        "qc_inspection_pass": {"value": round(passed / checked * 100, 1) if checked else None,
                               "numerator": int(passed), "denominator": int(checked), "unit": "percent"},
        "approved_quote_margin": {"value": round(margin / revenue * 100, 1) if revenue else None,
                                  "numerator": margin, "denominator": revenue, "unit": "percent"},
    }


@router.get("/dashboard/{module}")
def dashboard(module: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    name = module.upper()
    role = user.role.value
    if name not in MODULE_ROLES and name not in {"TASK", "EXCEPTION"}:
        raise HTTPException(404, "Unknown module")
    if name in MODULE_ROLES and role not in MODULE_ROLES[name]:
        raise HTTPException(403, "Dashboard is not available for this role")
    cards, flows, unavailable = [], [], []
    extra = {}
    kpis = operational_kpis(db) if name in {"CEO", "CMO", "CFO", "COO"} else {}
    active = m.Order.overall_status != "CLOSED"
    if name == "CMO":
        cards = [card("Order Aktif", count(db, m.Order, active)), card("Customer", count(db, m.Customer)),
                 card("Quotation Menunggu", count(db, m.Quotation, m.Quotation.status.in_(["DRAFT", "SENT"]))),
                 card("Sample Belum Disetujui", count(db, m.SampleRecord, m.SampleRecord.status.notin_(["APPROVED", "REJECTED"]))),
                 card("SPK Released", count(db, m.SPK, m.SPK.status == "RELEASED"))]
        flows = ["Customer & Order", "Quotation", "Sample / PPM", "SPK Release", "Konfirmasi Customer", "Customer Closing"]
        cards.append(card("Pengiriman Tepat Waktu", kpis["on_time_shipments"]["value"], "percent"))
        unavailable = ["Sales pipeline dan demand engine", "Content & ads"]
    elif name == "CFO":
        outstanding, overdue, paid = money_summary(db)
        cards = [card("Outstanding", outstanding, "currency"), card("AR Lewat Jatuh Tempo", overdue, "currency"),
                 card("Pembayaran Invoice Tercatat", paid, "currency"),
                 card("PO Belum Diterima", count(db, m.PurchaseOrder, m.PurchaseOrder.status.notin_(["RECEIVED", "CANCELLED"]))),
                 card("Shipment Menunggu Gate", count(db, m.Shipment, m.Shipment.status.notin_(["SHIPPED", "DELIVERED"]), m.Shipment.finance_gate != "CLEAR"))]
        flows = ["Quotation Approval", "Invoice & Payment", "Finance Gate", "Purchasing", "Shipment Finance Gate", "Financial Closing"]
        cards.append(card("Margin Quotation Disetujui", kpis["approved_quote_margin"]["value"], "percent"))
        unavailable = ["Payroll, attendance dan team bonus", "Accounting, AP dan cashflow"]
    elif name == "COO":
        remaining = case((m.ProductionMovement.qty_in - m.ProductionMovement.qty_done - m.ProductionMovement.qty_reject > 0,
                          m.ProductionMovement.qty_in - m.ProductionMovement.qty_done - m.ProductionMovement.qty_reject), else_=0)
        wip = db.query(func.coalesce(func.sum(remaining), 0)).join(m.Article, m.Article.id == m.ProductionMovement.article_id).join(
            m.Order, m.Order.id == m.Article.order_fk).filter(active).scalar()
        cards = [card("WIP Aktif", int(wip)), card("Material Request Open", count(db, m.MaterialRequest, m.MaterialRequest.status.in_(["REQUESTED", "APPROVED", "ORDERED"]))),
                 card("QC Perlu Tindakan", count(db, m.QCRecord, m.QCRecord.status.in_(["FAIL", "REWORK"]))),
                 card("Shipment Belum Dikirim", count(db, m.Shipment, m.Shipment.status.notin_(["SHIPPED", "DELIVERED"])))]
        flows = ["Production Planning", "Material Requirement", "Purchasing Handoff", "Production & WIP", "QC & Packing", "Shipment"]
        extra["capacity"] = capacity_rows(db)
        cards.append(card("QC Inspection Pass", kpis["qc_inspection_pass"]["value"], "percent"))
        unavailable = ["Otomasi alokasi biaya tenaga kerja dan overhead"]
    elif name == "CHRO":
        average = db.query(func.avg(m.PerformanceRecord.total_score)).scalar()
        cards = [card("Karyawan Aktif", count(db, m.Employee, m.Employee.employment_status == "ACTIVE")),
                 card("Training Tercatat", count(db, m.TrainingRecord)),
                 card("Rata-rata Review Tercatat", round(float(average), 2) if average is not None else None, "score"),
                 card("People Issue Open", count(db, m.EmployeeIssue, m.EmployeeIssue.status.in_(["OPEN", "IN_PROGRESS"])))]
        flows = ["Employee Master", "Training", "Performance Review", "Employee Issue"]
        unavailable = ["Recruitment dan skill matrix", "Formula KPI berbobot"]
    elif name == "CEO":
        outstanding, overdue, _ = money_summary(db)
        cards = [card("Order Aktif", count(db, m.Order, active)),
                 card("Critical Issue", count(db, m.ExceptionItem, m.ExceptionItem.severity == "RED", m.ExceptionItem.status.in_(["OPEN", "IN_PROGRESS"]))),
                 card("Shipment Perlu CEO", count(db, m.Shipment, m.Shipment.ceo_approval == "PENDING", m.Shipment.status.notin_(["SHIPPED", "DELIVERED"]))),
                 card("AR Lewat Jatuh Tempo", overdue, "currency"),
                 card("Decision Open", count(db, m.CEODecision, m.CEODecision.action_status.in_(["OPEN", "IN_PROGRESS"])))]
        extra["outstanding"] = outstanding
        cards.append(card("Pengiriman Tepat Waktu", kpis["on_time_shipments"]["value"], "percent"))
        flows = ["Master Control", "Exception Review", "Shipment Approval", "Decision & Action Tracker"]
        unavailable = ["Strategic planning dan business review periodik"]
    elif name == "EXCEPTION":
        q = db.query(m.ExceptionItem)
        if role != "CEO":
            q = q.filter(m.ExceptionItem.owner_role == role)
        opened = q.filter(m.ExceptionItem.status.in_(["OPEN", "IN_PROGRESS"]))
        cards = [card("Critical Open", opened.filter(m.ExceptionItem.severity == "RED").count()),
                 card("Attention Open", opened.filter(m.ExceptionItem.severity == "YELLOW").count()), card("Exception Tersedia", q.count())]
        flows = ["Identify", "Assign Owner", "Action", "Resolve"]
    else:
        q = db.query(m.Task)
        if role != "CEO":
            q = q.filter(m.Task.assigned_to_id == user.id)
        cards = [card("Tugas Open", q.filter(m.Task.status == "OPEN").count()),
                 card("Tugas Berjalan", q.filter(m.Task.status == "IN_PROGRESS").count()),
                 card("Tugas Lewat Jatuh Tempo", q.filter(m.Task.status.in_(["OPEN", "IN_PROGRESS"]), m.Task.due_date < date.today()).count())]
        flows = ["My Tasks", "Update Progress", "History"]
    allowed_kpis = {"CMO": ("on_time_shipments",), "CFO": ("approved_quote_margin",),
                    "COO": ("qc_inspection_pass",)}
    visible_kpis = kpis if name == "CEO" else {k: kpis[k] for k in allowed_kpis.get(name, ())}
    return {"module": name, "cards": cards, "flows": flows, "unavailable_features": unavailable,
            "kpis": visible_kpis, "as_of": datetime.now(timezone.utc), **extra}
