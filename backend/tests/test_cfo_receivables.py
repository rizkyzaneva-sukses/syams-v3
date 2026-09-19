"""AR aging / collection queue (revisi #17) and AP supplier & makloon (revisi #20).

The router is registered here with ``include_router`` (AGENT-RULES §3) so these
tests prove the endpoints work before the orchestrator wires them into main.py.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import models as m
from app.routers.cfo_receivables import router as cfo_receivables_router


@pytest.fixture
def api_client(client):
    """Attach our router to the app the shared ``client`` fixture already wraps."""
    client.app.include_router(cfo_receivables_router, prefix="/api")
    return client


def call(client, headers, role, path, **kwargs):
    response = client.get("/api" + path, headers=headers(role), **kwargs)
    return response


def seed(db):
    """One order with four invoices covering every aging bucket, plus POs."""
    today = date.today()
    order = m.Order(order_id="SO-AR-001", buyer="Buyer Alpha", order_type=m.OrderType.REPEAT_PRODUCTION)
    order2 = m.Order(order_id="SO-AR-002", buyer="Buyer Beta", order_type=m.OrderType.REPEAT_PRODUCTION)
    db.add_all([order, order2])
    db.commit()

    # not due / 1-30 / 31-60 / >60
    db.add_all([
        m.Invoice(invoice_no="INV-OK", order_fk=order.id, amount=Decimal("1000000"),
                  paid_amount=Decimal("0"), due_date=today + timedelta(days=10), status="UNPAID"),
        m.Invoice(invoice_no="INV-30", order_fk=order.id, amount=Decimal("2000000"),
                  paid_amount=Decimal("0"), due_date=today - timedelta(days=20), status="UNPAID"),
        m.Invoice(invoice_no="INV-60", order_fk=order2.id, amount=Decimal("3000000"),
                  paid_amount=Decimal("1000000"), due_date=today - timedelta(days=45), status="PARTIAL"),
        m.Invoice(invoice_no="INV-90", order_fk=order2.id, amount=Decimal("4000000"),
                  paid_amount=Decimal("0"), due_date=today - timedelta(days=95), status="UNPAID"),
    ])
    db.commit()

    db.add_all([
        m.Payment(invoice_no="INV-60", invoice_id=3, amount=Decimal("1000000"),
                  payment_date=today - timedelta(days=40), method="TRANSFER",
                  notes="TF BCA 12345 — bukti terlampir"),
        m.Payment(invoice_no="INV-30", invoice_id=2, amount=Decimal("500000"),
                  payment_date=today - timedelta(days=10), method="TRANSFER", notes="??"),
    ])
    db.add_all([
        m.PurchaseOrder(po_no="PO-SUP-1", order_fk=order.id, item="Kain", qty=Decimal("100"),
                         unit="meter", supplier="PT Tekstil Makmur", amount=Decimal("5000000"),
                         status="APPROVED", material_status="READY", arrival_date=today + timedelta(days=5)),
        m.PurchaseOrder(po_no="PO-MKL-1", order_fk=order.id, item="Jahit", qty=Decimal("200"),
                         unit="pcs", supplier="CV Makloon Jaya", amount=Decimal("3000000"),
                         status="APPROVED", material_status="READY", arrival_date=today - timedelta(days=40)),
        m.PurchaseOrder(po_no="PO-WAIT-1", order_fk=order2.id, item="Benang", qty=Decimal("50"),
                         unit="roll", supplier="Supplier Tunggu", amount=Decimal("1000000"),
                         status="PENDING", material_status="WAITING", arrival_date=None),
    ])
    db.commit()
    # Payment that explicitly references the makloon PO -> reduces its AP.
    db.add(m.Payment(invoice_no="PO-MKL-1", invoice_id=None, amount=Decimal("1000000"),
                     payment_date=today, method="TRANSFER", notes="Bayar PO-MKL-1 makloon"))
    db.commit()
    return order, order2


def test_ar_aging_buckets_and_collection_queue(api_client, headers, db):
    order, order2 = seed(db)
    body = call(api_client, headers, "CFO_MANAGER", "/cfo/ar-aging").json()
    buckets = {row["invoice_no"]: row["aging_bucket"] for row in body["rows"]}
    assert buckets == {"INV-OK": "not_due", "INV-30": "d1_30", "INV-60": "d31_60", "INV-90": "d_over_60"}

    # Invoice INV-30 has a payment whose reference is too short -> unverified.
    unverified = {row["invoice_no"] for row in body["rows"] if row["unverified_payment_count"]}
    assert unverified == {"INV-30"}
    assert body["summary"]["invoices_with_unverified_payment"] == ["INV-30"]

    # INV-30 keeps its 500k ledger payment (outstanding 1.5jt) but the reference
    # is rejected as evidence, so it still needs CFO follow-up.
    # Outstanding 9jt: the makloon PO payment is no longer netted against an
    # invoice (see test_ap_summary_separates_supplier_and_makloon).
    assert body["summary"]["total_outstanding"] == 9000000.0
    assert body["summary"]["critical_count"] == 1
    assert body["summary"]["overdue_count"] == 3
    bucket_map = {b["bucket"]: b for b in body["summary"]["buckets"]}
    assert bucket_map["d_over_60"]["outstanding"] == 4000000.0
    assert bucket_map["d31_60"]["outstanding"] == 2000000.0

    # Collection queue carries the required revisi #17 fields.
    queue = {row["invoice_no"]: row for row in body["collection_queue"]}
    assert set(queue) == {"INV-OK", "INV-30", "INV-60", "INV-90"}
    assert queue["INV-90"]["next_action"] == "ESCALATE_CEO"
    assert queue["INV-90"]["owner"] == "CFO_MANAGER"
    assert queue["INV-60"]["aging"] == "31–60 hari"
    assert queue["INV-30"]["next_action"] == "FOLLOW_UP"

    buyers = {row["buyer"]: row for row in body["by_buyer"]}
    assert buyers["Buyer Beta"]["d_over_60"] == 4000000.0
    assert buyers["Buyer Alpha"]["invoice_count"] == 2


def test_ar_aging_filters_and_partial_payment(api_client, headers, db):
    seed(db)
    only_over60 = call(api_client, headers, "FINANCE_SUPPORT", "/cfo/ar-aging?bucket=d_over_60").json()
    assert [row["invoice_no"] for row in only_over60["rows"]] == ["INV-90"]

    by_buyer = call(api_client, headers, "CFO_MANAGER", "/cfo/ar-aging?buyer=alpha").json()
    assert {row["buyer"] for row in by_buyer["rows"]} == {"Buyer Alpha"}

    outstanding_only = call(api_client, headers, "CEO", "/cfo/ar-aging?only_outstanding=true").json()
    assert all(row["outstanding"] > 0 for row in outstanding_only["rows"])

    bad = call(api_client, headers, "CFO_MANAGER", "/cfo/ar-aging?bucket=nonsense")
    assert bad.status_code == 400

    # Partial payment is visible: INV-60 paid 1jt of 3jt.
    partial = [row for row in call(api_client, headers, "CFO_MANAGER", "/cfo/ar-aging").json()["rows"]
               if row["invoice_no"] == "INV-60"][0]
    assert partial["partial"] is True and partial["paid"] == 1000000.0 and partial["outstanding"] == 2000000.0


def test_ar_aging_role_gating_hides_collection_ownership_from_cmo(api_client, headers, db):
    seed(db)
    assert call(api_client, headers, "CMO_MANAGER", "/cfo/ar-aging").status_code == 200
    cmo = call(api_client, headers, "CMO_SUPPORT", "/cfo/ar-aging").json()
    assert cmo["view"] == "CMO_STATUS_ONLY"
    assert "collection_queue" not in cmo
    assert "owner" not in cmo["rows"][0] and "next_action" not in cmo["rows"][0]
    assert call(api_client, headers, "COO_MANAGER", "/cfo/ar-aging").status_code == 403
    assert call(api_client, headers, "CHRO_MANAGER", "/cfo/ar-aging").status_code == 403


def test_ap_summary_separates_supplier_and_makloon(api_client, headers, db):
    """Klasifikasi HANYA dari vendor_type; tanpa kolom itu -> UNCLASSIFIED.

    Revisi #20 melarang menebak vendor dari nama supplier, jadi PO "CV Makloon
    Jaya" di sini TIDAK lagi otomatis jadi makloon, dan pembayaran `payments`
    lama yang menyebut nomor PO di `notes` TIDAK lagi mengurangi AP.
    """
    seed(db)
    body = call(api_client, headers, "CFO_MANAGER", "/cfo/ap-summary").json()
    kinds = {row["po_no"]: row["vendor_type_class"] for row in body["rows"]}
    assert kinds == {"PO-SUP-1": "UNCLASSIFIED", "PO-MKL-1": "UNCLASSIFIED", "PO-WAIT-1": "UNCLASSIFIED"}

    # Tanpa vendor_type, baris tidak mengotori supplier/makloon sama sekali.
    assert body["summary"]["supplier"]["count"] == 0
    assert body["summary"]["makloon"]["count"] == 0
    assert body["summary"]["unclassified"]["count"] == 3
    assert set(body["summary"]["unclassified_pos"]) == {"PO-SUP-1", "PO-MKL-1", "PO-WAIT-1"}
    assert body["summary"]["total"]["count"] == 3

    # Pembayaran `payments` yang menebak PO lewat notes tidak lagi mengurangi AP.
    makloon = [row for row in body["rows"] if row["po_no"] == "PO-MKL-1"][0]
    assert makloon["paid"] == 0.0
    assert makloon["outstanding"] == 3000000.0
    assert makloon["payment_schedule"] == "OVERDUE"
    assert body["summary"]["cash_plan"]["overdue"] == 3000000.0

    # PO yang materialnya belum diterima tetap dikecualikan dari outstanding.
    wait = [row for row in body["rows"] if row["po_no"] == "PO-WAIT-1"][0]
    assert wait["received"] is False and wait["outstanding"] == 0.0 and wait["status"] == "NOT_RECEIVED"

    # Filter UNCLASSIFIED valid; nama vendor yang tidak dikenal tetap 400.
    unclassified = call(api_client, headers, "FINANCE_SUPPORT", "/cfo/ap-summary?vendor_type=UNCLASSIFIED").json()
    assert len(unclassified["rows"]) == 3
    assert call(api_client, headers, "CFO_MANAGER", "/cfo/ap-summary?vendor_type=BOGUS").status_code == 400


def test_ap_summary_uses_real_vendor_type_column(api_client, headers, db):
    """Begitu kolom vendor_type ada, pemisahan memakai kolom itu — bukan nama."""
    seed(db)
    from sqlalchemy import inspect as sa_inspect

    if "vendor_type" not in {c["name"] for c in sa_inspect(db.get_bind()).get_columns("purchase_orders")}:
        pytest.skip("kolom purchase_orders.vendor_type belum ada di models.py")

    # Nama menyesatkan: PO "CV Makloon Jaya" diberi vendor_type SUPPLIER.
    db.query(m.PurchaseOrder).filter_by(po_no="PO-MKL-1").one().vendor_type = "SUPPLIER"
    db.query(m.PurchaseOrder).filter_by(po_no="PO-SUP-1").one().vendor_type = "MAKLOON"
    db.query(m.PurchaseOrder).filter_by(po_no="PO-WAIT-1").one().vendor_type = "SUPPLIER"
    db.commit()

    body = call(api_client, headers, "CFO_MANAGER", "/cfo/ap-summary").json()
    kinds = {row["po_no"]: row["vendor_type_class"] for row in body["rows"]}
    assert kinds == {"PO-MKL-1": "SUPPLIER", "PO-SUP-1": "MAKLOON", "PO-WAIT-1": "SUPPLIER"}
    assert body["summary"]["makloon"]["count"] == 1
    assert body["summary"]["supplier"]["count"] == 2
    assert body["summary"]["unclassified"]["count"] == 0
    assert body["summary"]["makloon"]["outstanding"] == 5000000.0
    # AP payments come from the real ledger now, not from PO numbers in notes.
    assert body["ap_payment_source"] == "ap_payments.po_fk"


def test_ap_summary_is_read_only_and_never_deletes(api_client, headers, db):
    seed(db)
    before = db.query(m.PurchaseOrder).count()
    # No write verbs exist on these endpoints at all.
    for method in ("post", "put", "patch", "delete"):
        response = getattr(api_client, method)("/api/cfo/ap-summary", headers=headers("CFO_MANAGER"))
        assert response.status_code == 405, (method, response.status_code)
    assert call(api_client, headers, "CFO_MANAGER", "/cfo/ap-summary").status_code == 200
    assert db.query(m.PurchaseOrder).count() == before
    assert db.query(m.Invoice).count() == 4


def test_cmo_cannot_read_ap(api_client, headers, db):
    seed(db)
    assert call(api_client, headers, "CMO_MANAGER", "/cfo/ap-summary").status_code == 403
    assert call(api_client, headers, "CMO_SUPPORT", "/cfo/ap-summary").status_code == 403
    assert call(api_client, headers, "CEO", "/cfo/ap-summary").status_code == 200
