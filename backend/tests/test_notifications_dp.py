"""Notifikasi otomatis per proses, DP dalam Rupiah, dan kolom invoice (No PO, DP, Sisa Tagihan)."""
import json
from datetime import date, datetime, timedelta

import pytest

from app import models as m
from app.business_policy import BusinessPolicy, get_policy
from app.control_models import OrderStage
from app.control_service import ensure_control_defaults
from app.platform_models import Notification


def call(client, headers, role, method, path, body=None, expected=200):
    response = client.request(method, "/api" + path, headers=headers(role), json=body)
    assert response.status_code == expected, response.text
    return response.json() if response.content else None


def inbox(db, role=None, user_id=None):
    query = db.query(Notification)
    query = query.filter_by(role_target=role) if role else query.filter_by(user_id=user_id)
    return [(n.title, n.body, n.link_path, n.severity, n.category) for n in query.order_by(Notification.id)]


def titles(db, role):
    return [t[0] for t in inbox(db, role)]


def make_order(db, order_id="SYM-2610-001", flow_step="PRODUCTION", spk_days=0):
    order = m.Order(order_id=order_id, buyer="Kyan", order_type=m.OrderType.REPEAT_PRODUCTION, flow_step=flow_step,
                    overall_status="ACTIVE", buyer_deadline=date.today() + timedelta(days=30))
    order.articles.append(m.Article(article_code="Agape", garment_type="HOODIE", qty=100))
    db.add(order)
    db.flush()
    if spk_days is not None:
        db.add(m.SPK(order_fk=order.id, spk_no="SPK-1", status="RELEASED", released_at=datetime.utcnow() - timedelta(days=spk_days)))
    db.commit()
    return order


def accepted_order(client, headers, number="PO-77"):
    po = call(client, headers, "CMO_SUPPORT", "POST", "/cmo/po-intake", {
        "po_number": number, "buyer": "Kyan", "order_type": "REPEAT_PRODUCTION",
        "buyer_deadline": str(date.today() + timedelta(days=30)),
        "articles": [{"article_code": "A", "qty": 10, "garment_type": "HOODIE"}]}, expected=201)
    uploaded = client.post(f"/api/cmo/po-intake/{po['id']}/document", headers=headers("CMO_SUPPORT"),
                           files={"document": ("po.pdf", b"%PDF-1.4\n1 0 obj\n", "application/pdf")})
    assert uploaded.status_code == 200
    call(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/check")
    return po


# ───────────────────────────── notifikasi ─────────────────────────────

def test_po_flow_notifies_the_role_that_gets_the_next_task(client, headers, db):
    po = accepted_order(client, headers)
    assert titles(db, "CMO_MANAGER") == []
    call(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/submit")
    assert titles(db, "CMO_MANAGER") == ["PO PO-77 menunggu review"]
    assert inbox(db, "CMO_MANAGER")[0][2] == "/cmo/po-inbox"
    accepted = call(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "ACCEPT"})
    oid = accepted["order_id"]
    assert titles(db, "CFO_MANAGER") == [f"Order baru {oid}"]
    assert inbox(db, "CFO_MANAGER")[0][2] == "/cfo/invoices" and "DP" in inbox(db, "CFO_MANAGER")[0][1]
    assert titles(db, "CMO_SUPPORT") == [f"Order {oid} aktif"]
    assert titles(db, "COO_MANAGER") == [] and titles(db, "CEO") == []


def test_rejected_po_goes_back_to_deby(client, headers, db):
    po = accepted_order(client, headers, "PO-78")
    call(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/submit")
    call(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "REJECT", "note": "Qty tidak cocok"})
    rows = inbox(db, "CMO_SUPPORT")
    assert rows[-1][0] == "PO PO-78 ditolak — perlu revisi" and rows[-1][1] == "Qty tidak cocok" and rows[-1][3] == "WARNING"


def test_each_role_only_sees_its_own_notifications_in_the_api(client, headers, db):
    po = accepted_order(client, headers, "PO-79")
    call(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/submit")
    manager = call(client, headers, "CMO_MANAGER", "GET", "/platform/notifications")
    assert [n["title"] for n in manager] == ["PO PO-79 menunggu review"]
    assert call(client, headers, "CMO_MANAGER", "GET", "/platform/notifications/unread-count")["count"] == 1
    assert call(client, headers, "COO_MANAGER", "GET", "/platform/notifications") == []
    call(client, headers, "CMO_MANAGER", "POST", f"/platform/notifications/{manager[0]['id']}/read")
    assert call(client, headers, "CMO_MANAGER", "GET", "/platform/notifications/unread-count")["count"] == 0


def test_invoice_and_payment_notify_with_rupiah_amounts(client, headers, db):
    order = make_order(db, spk_days=None, flow_step="INVOICE")
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/invoices",
         {"invoice_no": "INV-1", "order_fk": order.id, "amount": 10_000_000, "dp_amount": 4_000_000}, 200)
    body = inbox(db, "CMO_SUPPORT")[-1]
    assert body[0] == "Invoice INV-1 terbit" and "Rp. 10.000.000" in body[1] and "Rp. 4.000.000" in body[1]


def test_spk_release_notifies_production_roles(db):
    order = make_order(db, spk_days=None, flow_step="SPK")
    spk = m.SPK(order_fk=order.id, spk_no="SPK-9", status="NEW")
    db.add(spk)
    db.commit()
    assert titles(db, "COO_MANAGER") == []
    spk.status = "PRINTED"
    db.commit()
    assert titles(db, "CMO_MANAGER") == ["SPK SPK-9 siap direlease"]
    spk.status = "RELEASED"
    db.commit()
    for role, link in (("COO_MANAGER", "/coo/planning"), ("PRODUCTION_PIC", "/coo/material-requests"),
                       ("PRINTING_PIC", "/master"), ("CMO_SUPPORT", "/cmo/today")):
        rows = inbox(db, role)
        assert rows[-1][0] == f"SPK SPK-9 dirilis — order {order.order_id}" and rows[-1][2] == link, role


def test_unrelated_edits_do_not_notify(db):
    order = make_order(db, spk_days=None, flow_step="SPK")
    spk = m.SPK(order_fk=order.id, spk_no="SPK-5", status="NEW")
    db.add(spk)
    db.commit()
    before = db.query(Notification).count()
    spk.notes = "catatan saja"
    db.commit()
    spk.status = "NEW"
    db.commit()
    assert db.query(Notification).count() == before


def test_finance_gate_and_sample_and_material_events(db):
    order = make_order(db, spk_days=None, flow_step="INVOICE")
    order.finance_gate_status = "APPROVED"
    db.commit()
    assert titles(db, "CMO_MANAGER")[-1] == f"Finance Gate {order.order_id} disetujui"
    sample = m.SampleRecord(order_fk=order.id, article_code="Agape", status="PROCESS")
    db.add(sample)
    db.commit()
    assert titles(db, "SAMPLE_PIC") == ["Sample baru: Agape"]
    sample.status = "APPROVED"
    db.commit()
    assert titles(db, "SAMPLE_PIC")[-1] == "Sample Agape: APPROVED" and titles(db, "CMO_SUPPORT")[-1] == "Sample Agape: APPROVED"
    db.add(m.MaterialRequest(order_fk=order.id, item_name="Cotton", qty=50, unit="m"))
    db.add(m.PurchaseOrder(po_no="PO-B1", order_fk=order.id, item="Cotton", qty=50, unit="m", amount=2_500_000))
    db.commit()
    assert titles(db, "PRODUCTION_PIC") == ["Permintaan material baru: Cotton"]
    assert titles(db, "CFO_MANAGER")[-1] == "PO pembelian PO-B1 menunggu persetujuan anggaran"
    assert "Rp. 2.500.000" in inbox(db, "CFO_MANAGER")[-1][1]


def test_exception_goes_to_owner_role_with_severity(db):
    order = make_order(db, spk_days=None, flow_step="INVOICE")
    db.add(m.ExceptionItem(order_fk=order.id, severity="RED", category="Mutu", title="Reject tinggi", owner_role="COO_MANAGER",
                           status="OPEN", next_action="Cek mesin"))
    db.add(m.ExceptionItem(order_fk=order.id, severity="YELLOW", category="HR", title="Rahasia", owner_role="CHRO_MANAGER",
                           status="OPEN", confidential=True))
    db.commit()
    assert inbox(db, "COO_MANAGER")[0][0] == "Exception: Reject tinggi" and inbox(db, "COO_MANAGER")[0][3] == "CRITICAL"
    secret = inbox(db, "CHRO_MANAGER")[0]
    assert secret[0] == "Exception rahasia baru" and secret[1] is None


def test_stage_done_hands_over_to_the_next_stage_owner(client, headers, db):
    ensure_control_defaults(db)
    order = make_order(db, spk_days=0)
    call(client, headers, "PRODUCTION_PIC", "POST", f"/control/orders/{order.order_id}/stages/BAHAN/done", {})
    assert titles(db, "PRODUCTION_PIC")[-1] == f"Giliran CUTTING — {order.order_id}"
    assert titles(db, "COO_MANAGER")[-1] == f"Giliran CUTTING — {order.order_id}"
    assert not [t for t in titles(db, "PRINTING_PIC") if t.startswith("Giliran")]       # Cutting bukan milik Printing
    call(client, headers, "PRODUCTION_PIC", "POST", f"/control/orders/{order.order_id}/stages/CUTTING/done", {})
    call(client, headers, "PRODUCTION_PIC", "POST", f"/control/orders/{order.order_id}/stages/SORTIR/done", {})
    assert titles(db, "PRINTING_PIC")[-1] == f"Giliran PRINTING — {order.order_id}"


def test_blocks_alert_managers_and_resolution_goes_back_to_the_reporter(client, headers, db, users):
    ensure_control_defaults(db)
    order = make_order(db, spk_days=0)
    view = call(client, headers, "PRODUCTION_PIC", "POST", f"/control/orders/{order.order_id}/blocks",
                {"stage_code": "BAHAN", "problem": "Bahan kurang", "next_action": "Order ulang"}, expected=201)
    for role in ("COO_MANAGER", "CMO_MANAGER", "PRODUCTION_PIC"):
        row = inbox(db, role)[-1]
        assert row[0] == f"Masalah BAHAN — {order.order_id}" and row[3] == "CRITICAL" and "Order ulang" in row[1], role
    assert not [t for t in titles(db, "CFO_MANAGER") if t.startswith("Masalah")]
    call(client, headers, "COO_MANAGER", "POST", f"/control/blocks/{view['open_blocks'][0]['id']}/resolve", {"note": "Datang"})
    reporter = inbox(db, user_id=users[m.Role.PRODUCTION_PIC].id)
    assert reporter[-1][0] == f"Masalah {order.order_id} sudah diselesaikan" and reporter[-1][1] == "Datang"


def test_notification_failures_never_break_the_business_transaction(db, monkeypatch):
    import app.notifications as notifications

    def broken(session, obj):
        raise RuntimeError("aturan rusak")

    monkeypatch.setattr(notifications, "rules_for", broken)
    order = make_order(db, spk_days=None, flow_step="INVOICE")
    assert db.query(m.Order).filter_by(order_id=order.order_id).one() is not None
    assert db.query(Notification).count() == 0


# ───────────────────────────── DP dalam Rupiah ─────────────────────────────

def test_policy_stores_dp_in_rupiah_and_reads_legacy_percent(client, headers, db):
    saved = call(client, headers, "CEO", "PUT", "/config/business-policy", {
        "minimum_margin_percent": 10, "minimum_dp_amount": 5_000_000, "cfo_quotation_limit": 100_000_000,
        "allow_credit_terms": False, "change_reason": "DP minimum pakai Rupiah"})
    assert float(saved["minimum_dp_amount"]) == 5_000_000 and "minimum_dp_percent" not in saved
    call(client, headers, "CEO", "PUT", "/config/business-policy", {
        "minimum_margin_percent": 10, "minimum_dp_percent": 30, "cfo_quotation_limit": 1000,
        "change_reason": "Pakai persen lagi"}, expected=422)
    call(client, headers, "CEO", "PUT", "/config/business-policy", {
        "minimum_margin_percent": 10, "minimum_dp_amount": -1, "cfo_quotation_limit": 1000,
        "change_reason": "DP negatif"}, expected=422)
    legacy = {"minimum_margin_percent": 10, "minimum_dp_percent": 30, "cfo_quotation_limit": 1000, "allow_credit_terms": False}
    policy = BusinessPolicy.model_validate(legacy)
    assert policy.minimum_dp_amount == 0
    db.query(m.SystemConfig).filter_by(key="business_policy").one().value = json.dumps(legacy)
    db.commit()
    assert get_policy(db).minimum_dp_amount == 0


def test_invoice_dp_is_validated_and_exposed(client, headers, db):
    order = make_order(db, spk_days=None, flow_step="INVOICE")
    base = {"invoice_no": "INV-9", "order_fk": order.id, "amount": 20_000_000}
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/invoices", {**base, "dp_amount": 25_000_000}, expected=400)
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/invoices", {**base, "dp_amount": -5}, expected=400)
    created = call(client, headers, "CFO_MANAGER", "POST", "/cfo/invoices", {**base, "dp_amount": 6_000_000})
    assert float(created["dp_amount"]) == 6_000_000
    listed = call(client, headers, "FINANCE_SUPPORT", "GET", "/cfo/invoices")
    assert float(listed[0]["dp_amount"]) == 6_000_000
    call(client, headers, "CFO_MANAGER", "PATCH", f"/cfo/invoices/{created['id']}", {"dp_amount": 30_000_000}, expected=400)
    changed = call(client, headers, "CFO_MANAGER", "PATCH", f"/cfo/invoices/{created['id']}", {"dp_amount": 8_000_000})
    assert float(changed["dp_amount"]) == 8_000_000
    default = call(client, headers, "CFO_MANAGER", "POST", "/cfo/invoices", {"invoice_no": "INV-10", "order_fk": order.id, "amount": 1000})
    assert float(default["dp_amount"]) == 0


def test_orders_expose_the_buyer_po_number_for_the_invoice_form(client, headers, db):
    po = accepted_order(client, headers, "PO-NO-5")
    call(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/submit")
    accepted = call(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "ACCEPT"})
    listing = call(client, headers, "CFO_MANAGER", "GET", "/orders")
    assert [o["po_number"] for o in listing if o["order_id"] == accepted["order_id"]] == ["PO-NO-5"]
    assert call(client, headers, "CFO_MANAGER", "GET", f"/orders/{accepted['order_id']}")["po_number"] == "PO-NO-5"
    legacy = make_order(db, "SYM-2610-099", spk_days=None, flow_step="INVOICE")
    assert [o["po_number"] for o in call(client, headers, "CFO_MANAGER", "GET", "/orders") if o["order_id"] == legacy.order_id] == [None]
