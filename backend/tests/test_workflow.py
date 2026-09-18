from datetime import date, timedelta
import json
import pytest
from app import models as m
from app.flow_engine import FlowEngine
from app.workflow import deliveries_ready


def call(client, headers, method, path, role, body=None, expected=200):
    response = client.request(method, "/api" + path, headers=headers(role), json=body)
    assert response.status_code == expected, response.text
    return response.json()


def accepted_order(client, headers, payload, po_number):
    """Create test data through the same Deby → Cecep handoff as production."""
    po = call(client, headers, "POST", "/cmo/po-intake", "CMO_SUPPORT", {
        **payload, "po_number": po_number,
        "buyer_deadline": payload.get("buyer_deadline") or str(date.today() + timedelta(days=30)),
    }, expected=201)
    upload = client.post(f"/api/cmo/po-intake/{po['id']}/document",
                         headers=headers("CMO_SUPPORT"),
                         files={"document": ("po.pdf", b"%PDF-1.4\ntest", "application/pdf")})
    assert upload.status_code == 200, upload.text
    call(client, headers, "POST", f"/cmo/po-intake/{po['id']}/check", "CMO_SUPPORT")
    call(client, headers, "POST", f"/cmo/po-intake/{po['id']}/submit", "CMO_SUPPORT")
    accepted = call(client, headers, "POST", f"/cmo/po-intake/{po['id']}/review",
                    "CMO_MANAGER", {"action": "ACCEPT", "note": "Test PO reviewed"})
    return call(client, headers, "GET", "/orders/" + accepted["order_id"], "CMO_MANAGER")


@pytest.fixture
def order(client, headers):
    return accepted_order(client, headers, {
        "buyer": "Buyer", "order_type": "SAMPLE_PRODUCTION", "articles": [
            {"article_code": "A", "qty": 10, "sample_required": True, "production_route": "Cutting>QC>Packing"},
            {"article_code": "B", "qty": 5, "sample_required": True, "production_route": "Cutting>QC>Packing"},
        ]}, "PO-WORKFLOW-001")


def ready_order(client, headers, order, paid=0):
    oid = order["id"]
    call(client, headers, "PUT", "/config/business-policy", "CEO", {"minimum_margin_percent": 10, "minimum_dp_percent": 10, "cfo_quotation_limit": 1000, "allow_credit_terms": True})
    quotation = call(client, headers, "POST", "/cmo/quotations", "CMO_MANAGER", {"order_fk": oid, "quotation_no": "Q1", "status": "DRAFT", "payment_plan": "Approved credit terms", "pricing_lines": [
        {"article_id": order["articles"][0]["id"], "unit_price": 5, "unit_hpp": 2},
        {"article_id": order["articles"][1]["id"], "unit_price": 10, "unit_hpp": 4},
    ]})
    call(client, headers, "PATCH", f"/cmo/quotations/{quotation['id']}", "CFO_MANAGER", {"status": "APPROVED", "approval_reason": "Margin and terms checked"})
    invoice = call(client, headers, "POST", "/cfo/invoices", "CFO_MANAGER", {"order_fk": oid, "invoice_no": "I1", "amount": 100})
    if paid:
        call(client, headers, "POST", "/cfo/payments", "FINANCE_SUPPORT", {"invoice_no": "I1", "amount": paid})
    call(client, headers, "POST", f"/cfo/orders/{oid}/finance-gate", "CFO_MANAGER", {"action": "APPROVE", "reason": "Agreed credit terms; production authorized", "term_kind": "CREDIT", "credit_due_date": str(date.today()+timedelta(days=30)), "evidence_ref": "Signed contract CR-01"})
    for article in order["articles"]:
        call(client, headers, "POST", "/cmo/samples", "CMO_MANAGER", {"order_fk": oid, "article_code": article["article_code"], "status": "APPROVED", "notes": "Customer signed sample approval"})
    spk = call(client, headers, "POST", "/cmo/spk", "CMO_MANAGER", {"order_fk": oid, "spk_no": "SPK1"})
    call(client, headers, "POST", f"/cmo/spk/{spk['id']}/generate", "CMO_MANAGER")
    printed = client.post(f"/api/cmo/spk/{spk['id']}/print", headers=headers("CMO_MANAGER"))
    assert printed.status_code == 200 and printed.content.startswith(b"%PDF"), printed.text
    call(client, headers, "POST", f"/cmo/spk/{spk['id']}/release", "CMO_MANAGER",
         {"version_id": spk["id"], "reason": "Commercial and customer approvals checked"})
    call(client, headers, "POST", "/coo/production-plans", "COO_MANAGER", {"order_fk": oid, "status": "APPROVED", "plan_date": str(date.today())})
    call(client, headers, "POST", "/coo/material-requests", "COO_MANAGER", {"order_fk": oid, "item_name": "Fabric", "qty": 15, "unit": "m"})
    call(client, headers, "POST", "/cfo/purchase-orders", "CFO_MANAGER", {"order_fk": oid, "po_no": "PO1", "item": "Fabric", "qty": 15, "unit": "m", "status": "RECEIVED", "material_status": "READY", "arrival_date": str(date.today())})
    for article in order["articles"]:
        call(client, headers, "POST", "/coo/bom", "COO_MANAGER", {"article_id": article["id"], "material_name": "Fabric", "unit": "m", "qty_per_unit": 1, "planned_unit_cost": 1})
    for article in order["articles"]:
        call(client, headers, "POST", "/coo/movements", "PRODUCTION_PIC", {"article_id": article["id"], "process": "Cutting", "qty_in": article["qty"], "qty_done": article["qty"], "status": "DONE"})
        call(client, headers, "POST", "/coo/qc-records", "COO_MANAGER", {"order_fk": oid, "article_code": article["article_code"], "process": "Final", "total_checked": article["qty"], "total_pass": article["qty"], "status": "PASS"})
    return invoice


def test_complete_workflow_separates_finance_ceo_delivery_and_closing(client, headers, order, db):
    ready_order(client, headers, order, paid=25)
    oid = order["id"]
    spk = db.query(m.SPK).filter_by(order_fk=oid).one()
    manager = db.query(m.User).filter_by(role=m.Role.CMO_MANAGER).one()
    assert spk.status == "RELEASED" and spk.released_by == manager.id
    assert spk.released_at is not None and spk.released_version == spk.version
    assert spk.release_reason == "Commercial and customer approvals checked"
    assert spk.correction_reason is None
    assert json.loads(spk.release_prerequisites)["evidence"]["spk_version_id"] == spk.id
    assert db.query(m.AuditLog).filter_by(entity="SPK", entity_id=spk.id, action="SPK_RELEASE").count() == 1
    shipment = call(client, headers, "POST", "/coo/shipments", "SHIPMENT_ADMIN", {"order_fk": oid, "shipment_no": "S1", "packing_status": "PACKED"})
    sid = shipment["id"]
    call(client, headers, "POST", f"/coo/order-closing/{oid}", "COO_MANAGER", {"order_fk": oid, "operational_close_status": "CLOSED"}, expected=400)
    call(client, headers, "POST", f"/coo/order-closing/{oid}", "CMO_SUPPORT", {"order_fk": oid, "operational_close_status": "CLOSED"}, expected=403)
    call(client, headers, "GET", "/coo/order-closing", "CMO_SUPPORT", expected=403)
    call(client, headers, "GET", f"/coo/order-closing/{oid}", "CMO_SUPPORT", expected=403)
    call(client, headers, "PATCH", f"/coo/shipments/{sid}", "SHIPMENT_ADMIN", {"finance_gate": "CLEAR"}, expected=403)
    call(client, headers, "PATCH", f"/cfo/shipments/{sid}/gate", "CFO_MANAGER", {"finance_gate": "CLEAR", "ceo_approval": "APPROVED"}, expected=403)
    gate = call(client, headers, "POST", f"/cfo/shipments/{sid}/gate", "CFO_MANAGER", {"action": "APPROVE"})
    assert (gate["finance_gate"], gate["ceo_approval"]) == ("HOLD", "PENDING")
    call(client, headers, "PATCH", f"/coo/shipments/{sid}", "SHIPMENT_ADMIN", {"status": "SHIPPED", "shipped_date": str(date.today())}, expected=400)
    rejected = call(client, headers, "POST", f"/ceo/shipments/{sid}/approve-shipment", "CEO", {"action": "REJECT", "reason": "Need credit review"})
    assert rejected["finance_gate"] == "HOLD"
    call(client, headers, "POST", f"/cfo/shipments/{sid}/gate", "CFO_MANAGER", {"action": "APPROVE"})
    approved = call(client, headers, "POST", f"/ceo/shipments/{sid}/approve-shipment", "CEO", {"action": "APPROVE", "reason": "Credit reviewed and accepted"})
    assert float(approved["approved_outstanding"]) == 75
    call(client, headers, "PATCH", f"/coo/shipments/{sid}", "SHIPMENT_ADMIN", {"status": "DELIVERED", "shipped_date": str(date.today())}, expected=403)
    call(client, headers, "PATCH", f"/coo/shipments/{sid}", "SHIPMENT_ADMIN", {"status": "SHIPPED", "shipped_date": str(date.today()), "tracking_no": "TR1"})
    call(client, headers, "POST", "/coo/deliveries", "CMO_MANAGER", {"shipment_fk": sid}, expected=405)
    call(client, headers, "POST", "/cmo/delivery-confirmations", "COO_MANAGER", {"shipment_fk": sid}, expected=403)
    call(client, headers, "POST", "/cmo/delivery-confirmations", "CMO_SUPPORT", {"shipment_fk": sid, "status": "CONFIRMED", "confirmed_by_customer": "Buyer contact", "confirmation_date": str(date.today())}, expected=403)
    delivery = call(client, headers, "POST", "/cmo/delivery-confirmations", "CMO_MANAGER", {"shipment_fk": sid, "status": "CONFIRMED", "confirmed_by_customer": "Buyer contact", "confirmation_date": str(date.today())})
    call(client, headers, "PATCH", f"/cmo/delivery-confirmations/{delivery['id']}", "CMO_SUPPORT", {"feedback": "changed"}, expected=403)
    assert call(client, headers, "GET", "/coo/deliveries", "CMO_SUPPORT")[0]["id"] == delivery["id"]
    assert call(client, headers, "GET", "/coo/shipments", "CMO_SUPPORT")[0]["status"] == "SHIPPED"
    db.expire_all()
    assert db.get(m.Shipment, sid).status == "SHIPPED"
    call(client, headers, "POST", f"/coo/order-closing/{oid}", "CMO_MANAGER", {"order_fk": oid, "customer_close_status": "CLOSED"}, expected=400)
    call(client, headers, "POST", f"/coo/order-closing/{oid}", "COO_MANAGER", {"order_fk": oid, "operational_close_status": "CLOSED"}, expected=400)
    call(client, headers, "PATCH", f"/coo/shipments/{sid}", "CMO_MANAGER", {"status": "DELIVERED", "delivery_date": str(date.today())}, expected=403)
    call(client, headers, "PATCH", f"/coo/shipments/{sid}", "SHIPMENT_ADMIN", {"status": "DELIVERED", "delivery_date": str(date.today())}, expected=403)
    call(client, headers, "PATCH", f"/coo/shipments/{sid}", "COO_MANAGER", {"status": "DELIVERED"}, expected=400)
    handover = call(client, headers, "PATCH", f"/coo/shipments/{sid}", "COO_MANAGER", {"status": "DELIVERED", "delivery_date": str(date.today())})
    assert handover["status"] == "DELIVERED"
    call(client, headers, "POST", f"/coo/order-closing/{oid}", "CMO_MANAGER", {"order_fk": oid, "customer_close_status": "CLOSED", "operational_close_status": "OPEN"}, expected=403)
    call(client, headers, "POST", f"/coo/order-closing/{oid}", "CMO_MANAGER", {"order_fk": oid, "customer_close_status": "CLOSED"})
    call(client, headers, "PATCH", f"/coo/order-closing/{oid}", "CMO_MANAGER", {"operational_close_status": "OPEN"}, expected=403)
    call(client, headers, "PATCH", f"/coo/order-closing/{oid}", "CMO_SUPPORT", {"operational_close_status": "CLOSED"}, expected=403)
    call(client, headers, "PATCH", f"/coo/order-closing/{oid}", "CMO_MANAGER", {"operational_close_status": "CLOSED"}, expected=403)
    call(client, headers, "PATCH", f"/coo/order-closing/{oid}", "CFO_MANAGER", {"operational_close_status": "CLOSED"}, expected=403)
    call(client, headers, "PATCH", f"/coo/order-closing/{oid}", "COO_MANAGER", {"financial_close_status": "CLOSED"}, expected=403)
    call(client, headers, "PATCH", f"/coo/order-closing/{oid}", "CMO_MANAGER", {"financial_close_status": "CLOSED"}, expected=403)
    call(client, headers, "PATCH", f"/coo/order-closing/{oid}", "CFO_MANAGER", {"financial_close_status": "CLOSED"}, expected=400)
    call(client, headers, "POST", "/cfo/payments", "CFO_MANAGER", {"invoice_no": "I1", "amount": 75})
    result = call(client, headers, "PATCH", f"/coo/order-closing/{oid}", "CFO_MANAGER", {"financial_close_status": "CLOSED"})
    assert result["order_close_status"] == "OPEN"
    assert call(client, headers, "GET", "/orders", "CMO_SUPPORT")[0]["operational_close_status"] == "OPEN"
    result = call(client, headers, "PATCH", f"/coo/order-closing/{oid}", "COO_MANAGER", {"operational_close_status": "CLOSED"})
    assert result["order_close_status"] == "CLOSED"
    db.expire_all()
    assert db.get(m.Order, oid).overall_status == "CLOSED"
    assert db.query(m.AuditLog).filter_by(entity="Payment", action="CREATE").count() == 2
    assert call(client, headers, "GET", "/coo/order-closing", "CFO_MANAGER")[0]["order_fk"] == oid


def test_invoice_payment_source_and_atomic_audit(client, headers, order, db):
    invoice = call(client, headers, "POST", "/cfo/invoices", "CFO_MANAGER", {"order_fk": order["id"], "invoice_no": "I2", "amount": 100})
    call(client, headers, "PATCH", f"/cfo/invoices/{invoice['id']}", "CFO_MANAGER", {"paid_amount": 100, "status": "PAID"}, expected=400)
    call(client, headers, "POST", "/cfo/payments", "CFO_MANAGER", {"invoice_no": "I2", "amount": 40})
    before = db.query(m.AuditLog).count()
    call(client, headers, "POST", "/cfo/payments", "CFO_MANAGER", {"invoice_no": "I2", "amount": 70}, expected=400)
    assert db.query(m.Payment).count() == 1
    assert db.query(m.AuditLog).count() == before
    assert float(db.get(m.Invoice, invoice["id"]).paid_amount) == 40
    assert db.get(m.Order, order["id"]).finance_status == "PARTIAL"


def test_flow_requires_assessment_owner_and_latest_every_article(client, headers, order, db):
    oid = order["id"]
    call(client, headers, "POST", "/cmo/quotations", "CFO_MANAGER", {"order_fk": oid, "quotation_no": "Q-CFO", "amount": 100, "status": "DRAFT"}, expected=403)
    call(client, headers, "POST", "/cmo/quotations", "CMO_MANAGER", {"order_fk": oid, "quotation_no": "Q", "amount": 100, "status": "APPROVED"}, expected=403)
    call(client, headers, "POST", "/cfo/invoices", "CFO_MANAGER", {"order_fk": oid, "invoice_no": "I", "amount": 100})
    call(client, headers, "POST", f"/orders/{order['order_id']}/flow/advance", "CFO_MANAGER", {"target_step": "INVOICE"}, expected=400)
    call(client, headers, "POST", f"/orders/{order['order_id']}/flow/advance", "HR_SUPPORT", {"target_step": "INVOICE"}, expected=403)
    call(client, headers, "POST", "/cmo/samples", "SAMPLE_PIC", {"order_fk": oid, "article_code": "A", "status": "APPROVED", "notes": "fake"}, expected=403)
    call(client, headers, "POST", "/cmo/samples", "CMO_MANAGER", {"order_fk": oid, "article_code": "A", "status": "APPROVED", "notes": "Customer signed"})
    assert not FlowEngine._check_step_prerequisite(db.get(m.Order, oid), "SAMPLE_APPROVED")[0]
    call(client, headers, "POST", "/cmo/samples", "CMO_MANAGER", {"order_fk": oid, "article_code": "B", "status": "APPROVED", "notes": "Customer signed"})
    assert FlowEngine._check_step_prerequisite(db.get(m.Order, oid), "SAMPLE_APPROVED")[0]
    call(client, headers, "POST", "/cmo/samples", "SAMPLE_PIC", {"order_fk": oid, "article_code": "A", "status": "REVISION"})
    assert not FlowEngine._check_step_prerequisite(db.get(m.Order, oid), "SAMPLE_APPROVED")[0]


def test_movement_gate_routing_and_update_quantity(client, headers, order):
    article = order["articles"][0]
    call(client, headers, "POST", "/coo/movements", "COO_MANAGER", {"article_id": article["id"], "process": "Cutting", "qty_in": 10}, expected=400)
    ready_order(client, headers, order)
    records = call(client, headers, "GET", "/coo/movements", "COO_MANAGER")
    mov = next(x for x in records if x["article_id"] == article["id"])
    call(client, headers, "PATCH", f"/coo/movements/{mov['id']}", "COO_MANAGER", {"qty_reject": 2, "reject_reason": "bad"}, expected=400)
    call(client, headers, "PATCH", f"/coo/movements/{mov['id']}", "COO_MANAGER", {"qty_in": -1}, expected=400)
    call(client, headers, "POST", "/coo/movements", "COO_MANAGER", {"article_id": article["id"], "process": "Packing", "qty_in": 10}, expected=400)
    call(client, headers, "POST", "/coo/qc-records", "COO_MANAGER", {"order_fk": order["id"], "article_code": "A", "process": "Final", "total_checked": 10, "total_pass": 9, "total_reject": 1, "status": "PASS", "reject_reason": "rework"}, expected=400)


def test_sensitive_read_and_task_owner_scope(client, headers, users, db):
    for path in ("/cfo/invoices", "/cfo/payments", "/chro/performances", "/chro/issues"):
        call(client, headers, "GET", path, "SHIPMENT_ADMIN", expected=403)
    task = m.Task(title="Private task", assigned_to_id=users[m.Role.PRODUCTION_PIC].id)
    db.add(task); db.commit()
    assert call(client, headers, "GET", "/tasks", "HR_SUPPORT") == []
    call(client, headers, "PATCH", f"/tasks/{task.id}", "HR_SUPPORT", {"status": "DONE"}, expected=403)
    call(client, headers, "PATCH", f"/tasks/{task.id}", "PRODUCTION_PIC", {"status": "DONE"})
    call(client, headers, "PATCH", f"/tasks/{task.id}", "PRODUCTION_PIC", {"assigned_to_id": users[m.Role.HR_SUPPORT].id}, expected=403)


def test_multiple_shipments_all_require_delivery(client, headers, order, db):
    for number in ("S1", "S2"):
        shipment = m.Shipment(order_fk=order["id"], shipment_no=number, status="SHIPPED")
        db.add(shipment); db.flush()
        if number == "S1":
            db.add(m.DeliveryConfirmation(shipment_fk=shipment.id, status="CONFIRMED"))
    db.commit()
    assert not FlowEngine._check_step_prerequisite(db.get(m.Order, order["id"]), "DELIVERED")[0]


def test_legacy_customer_confirmation_without_handover_date_stays_open(order, db):
    shipment = m.Shipment(order_fk=order["id"], shipment_no="LEGACY-DELIVERY", status="DELIVERED", shipped_date=date.today(), packing_status="PACKED")
    db.add(shipment); db.flush()
    db.add(m.DeliveryConfirmation(shipment_fk=shipment.id, status="CONFIRMED", confirmed_by_customer="Buyer", confirmation_date=date.today()))
    db.commit()
    assert not deliveries_ready(db, db.get(m.Order, order["id"]))


def test_sample_only_blocks_spk_and_bad_order_articles(client, headers):
    sample = accepted_order(client, headers, {"buyer": "Sample buyer", "order_type": "SAMPLE_ONLY", "articles": [{"article_code": "S", "qty": 1}]}, "PO-SAMPLE-001")
    assert sample["articles"][0]["sample_required"]
    call(client, headers, "POST", "/cmo/spk", "CMO_MANAGER", {"order_fk": sample["id"], "spk_no": "SPK-S"}, expected=400)
    invalid = call(client, headers, "POST", "/cmo/po-intake", "CMO_SUPPORT", {"buyer": "Bad", "order_type": "REPEAT_PRODUCTION", "articles": [{"article_code": "X", "qty": 1}, {"article_code": "X", "qty": 2}]}, expected=201)
    checked = call(client, headers, "POST", f"/cmo/po-intake/{invalid['id']}/check", "CMO_SUPPORT")
    assert "Kode article unik dan tidak kosong" in checked["missing_items"]


def test_pricing_limit_and_dp_policy_require_real_evidence(client, headers, order):
    article_a, article_b = order["articles"]
    quote = call(client, headers, "POST", "/cmo/quotations", "CMO_MANAGER", {
        "quotation_no": "POL-1", "order_fk": order["id"], "payment_plan": "DP 40%, balance on delivery",
        "pricing_lines": [
            {"article_id": article_a["id"], "unit_price": 5, "unit_hpp": 2},
            {"article_id": article_b["id"], "unit_price": 10, "unit_hpp": 4},
        ],
    })
    assert float(quote["amount"]) == 100
    assert float(quote["hpp_total"]) == 40
    call(client, headers, "PATCH", f"/cmo/quotations/{quote['id']}", "CFO_MANAGER",
         {"status": "APPROVED", "approval_reason": "Reviewed"}, expected=409)
    call(client, headers, "PUT", "/config/business-policy", "CEO", {
        "minimum_margin_percent": 30, "minimum_dp_percent": 40,
        "cfo_quotation_limit": 50, "allow_credit_terms": False,
    })
    call(client, headers, "PATCH", f"/cmo/quotations/{quote['id']}", "CFO_MANAGER",
         {"status": "APPROVED", "approval_reason": "Reviewed"}, expected=400)
    call(client, headers, "POST", f"/ceo/quotations/{quote['id']}/approve-limit", "CEO", {"reason": "Large quote reviewed"})
    call(client, headers, "PATCH", f"/cmo/quotations/{quote['id']}", "CFO_MANAGER",
         {"status": "APPROVED", "approval_reason": "Margin and price confirmed"})
    call(client, headers, "POST", "/cfo/invoices", "CFO_MANAGER", {
        "invoice_no": "POL-INV", "order_fk": order["id"], "amount": 100,
    })
    call(client, headers, "POST", "/cfo/payments", "CFO_MANAGER", {"invoice_no": "POL-INV", "amount": 20})
    gate = f"/cfo/orders/{order['id']}/finance-gate"
    base = {"action": "APPROVE", "reason": "DP verified", "term_kind": "DP",
            "required_dp_amount": 20, "evidence_ref": "Bank TX-1"}
    call(client, headers, "POST", gate, "CFO_MANAGER", base, expected=400)
    call(client, headers, "POST", "/cfo/payments", "CFO_MANAGER", {"invoice_no": "POL-INV", "amount": 20})
    call(client, headers, "POST", gate, "CFO_MANAGER", {**base, "required_dp_amount": 40})


def test_legacy_invoice_balance_requires_cfo_reconciliation(client, headers, order, db):
    invoice = call(client, headers, "POST", "/cfo/invoices", "CFO_MANAGER", {
        "invoice_no": "LEG-1", "order_fk": order["id"], "amount": 100,
    })
    inv = db.get(m.Invoice, invoice["id"])
    inv.paid_amount = 50
    inv.opening_paid_amount = 30
    inv.reconciliation_status = "NEEDS_REVIEW"
    db.add(m.Payment(invoice_no="LEG-1", invoice_id=inv.id, amount=20))
    db.commit()
    call(client, headers, "POST", "/cfo/payments", "CFO_MANAGER",
         {"invoice_no": "LEG-1", "amount": 10}, expected=400)
    call(client, headers, "POST", f"/cfo/invoices/{inv.id}/reconcile", "FINANCE_SUPPORT",
         {"opening_paid_amount": 30, "evidence_ref": "Bank statement"}, expected=403)
    result = call(client, headers, "POST", f"/cfo/invoices/{inv.id}/reconcile", "CFO_MANAGER",
         {"opening_paid_amount": 30, "evidence_ref": "Bank statement 2025-12"})
    assert result["reconciliation_status"] == "VERIFIED"
    assert float(result["paid_amount"]) == 50
    call(client, headers, "POST", "/cfo/payments", "CFO_MANAGER",
         {"invoice_no": "LEG-1", "amount": 10})


def test_bom_consumption_cost_and_rework_lineage(client, headers, order):
    ready_order(client, headers, order)
    cost = call(client, headers, "GET", f"/coo/actual-cost/{order['id']}", "CFO_MANAGER")
    assert float(cost["planned_material_cost"]) == 15
    assert not cost["cost_complete"]
    bom = call(client, headers, "GET", f"/coo/bom?order_fk={order['id']}", "COO_MANAGER")
    for item in bom:
        article = next(a for a in order["articles"] if a["id"] == item["article_id"])
        call(client, headers, "POST", "/coo/material-consumptions", "PRODUCTION_PIC", {
            "bom_item_id": item["id"], "qty": article["qty"], "actual_unit_cost": 2,
            "evidence_ref": f"Warehouse issue {article['article_code']}",
        })
    call(client, headers, "POST", "/coo/material-consumptions", "PRODUCTION_PIC", {
        "bom_item_id": bom[0]["id"], "qty": 1, "actual_unit_cost": 2,
        "evidence_ref": "Excess issue",
    }, expected=400)
    cost = call(client, headers, "GET", f"/coo/actual-cost/{order['id']}", "CFO_MANAGER")
    assert cost["cost_complete"] and float(cost["actual_material_cost"]) == 30
    assert cost["actual_margin"] is None
    call(client, headers, "POST", "/coo/production-costs", "COO_MANAGER", {
        "article_id": order["articles"][0]["id"], "category": "LABOR", "amount": 10,
        "evidence_ref": "Payroll allocation A",
    })
    reviewed = call(client, headers, "POST", f"/cfo/orders/{order['id']}/cost-review", "CFO_MANAGER", {
        "evidence_ref": "All labor and overhead allocations checked; overhead zero",
    })
    assert reviewed["cost_verified"] and float(reviewed["actual_margin"]) == 60
    call(client, headers, "POST", "/coo/production-costs", "COO_MANAGER", {
        "article_id": order["articles"][1]["id"], "category": "OVERHEAD", "amount": 5,
        "evidence_ref": "Electricity allocation B",
    })
    stale = call(client, headers, "GET", f"/coo/actual-cost/{order['id']}", "CFO_MANAGER")
    assert not stale["cost_verified"] and stale["actual_margin"] is None
    failed = call(client, headers, "POST", "/coo/qc-records", "COO_MANAGER", {
        "order_fk": order["id"], "article_code": "A", "process": "Final",
        "total_checked": 10, "total_pass": 8, "total_reject": 2,
        "status": "FAIL", "reject_reason": "Loose seam",
    })
    call(client, headers, "POST", "/coo/qc-records", "COO_MANAGER", {
        "order_fk": order["id"], "article_code": "A", "process": "Final",
        "total_checked": 10, "total_pass": 10, "status": "PASS",
    }, expected=400)
    passed = call(client, headers, "POST", "/coo/qc-records", "COO_MANAGER", {
        "order_fk": order["id"], "article_code": "A", "process": "Final",
        "total_checked": 10, "total_pass": 10, "status": "PASS",
        "rework_parent_id": failed["id"],
    })
    assert passed["rework_parent_id"] == failed["id"]
    call(client, headers, "DELETE", f"/coo/qc-records/{failed['id']}", "COO_MANAGER", expected=400)


def test_capacity_forecast_uses_daily_capacity_and_manual_override(client, headers, order, db):
    for process in ("CUTTING", "QC", "PACKING"):
        db.add(m.CapacitySnapshot(snapshot_date=date.today(), process=process, capacity=5, planned_load=0))
    db.commit()
    rows = call(client, headers, "GET", "/master/forecast", "COO_MANAGER")
    forecast = next(r for r in rows if r["order_id"] == order["order_id"])
    assert forecast["source"] == "CAPACITY_ESTIMATE"
    assert forecast["projected_shipment"] == str(date.today() + timedelta(days=9))
    manual = call(client, headers, "PATCH", f"/master/forecast/{order['order_id']}", "COO_MANAGER", {
        "projected_shipment": str(date.today() + timedelta(days=12)),
    })
    assert manual["source"] == "MANUAL"


def test_sensitive_module_reads_follow_role_matrix(client, headers, order):
    for path in ("/orders", "/master/summary", "/master/forecast", "/cmo/customers", "/cmo/quotations", "/cmo/spk", "/coo/material-requests", "/coo/qc-records", "/coo/bom", "/coo/deliveries", f"/coo/order-closing/{order['id']}", f"/orders/{order['order_id']}/flow"):
        call(client, headers, "GET", path, "HR_SUPPORT", expected=403)


def test_dashboard_kpis_have_traceable_denominators_and_lists_paginate(client, headers, order):
    ready_order(client, headers, order)
    cfo = call(client, headers, "GET", "/dashboard/CFO", "CFO_MANAGER")
    assert cfo["kpis"]["approved_quote_margin"]["value"] == 60
    assert cfo["kpis"]["approved_quote_margin"]["denominator"] == 100
    coo = call(client, headers, "GET", "/dashboard/COO", "COO_MANAGER")
    assert coo["kpis"]["qc_inspection_pass"]["numerator"] == 15
    assert coo["kpis"]["qc_inspection_pass"]["denominator"] == 15
    assert "approved_quote_margin" not in coo["kpis"]
    second = accepted_order(client, headers, {
        "buyer": "Second", "order_type": "SAMPLE_ONLY", "articles": [{"article_code": "C", "qty": 1}],
    }, "PO-WORKFLOW-SECOND")
    page = call(client, headers, "GET", "/orders?limit=1&offset=1", "COO_MANAGER")
    assert len(page) == 1 and page[0]["id"] == second["id"]
    call(client, headers, "GET", "/orders?limit=501", "COO_MANAGER", expected=422)
