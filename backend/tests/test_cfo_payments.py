"""CFO write flow — PAYMENT_REPORTED → VERIFY/REJECT (revisi #17) and AP ledger (revisi #20).

Router didaftarkan sendiri lewat ``include_router`` (AGENT-RULES §3) supaya tes
ini membuktikan endpointnya jalan sebelum orkestrator memasangnya di main.py.

Fokus tes ini adalah **jalur negatif**, karena inti revisi #17 justru larangan:
pembayaran TANPA bukti harus DITOLAK, dan uang yang sudah diputuskan tidak boleh
dimutasi ulang.

Tes AP ledger melewati (skip) bagian yang butuh ``purchase_orders.vendor_type``
dan tabel ``ap_payments`` kalau agent schema belum mendarat. Yang di-skip
dilaporkan di laporan akhir sebagai blocker, bukan disembunyikan.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import inspect as sa_inspect

from app import models as m
from app.routers.cfo_payments import router as cfo_payments_router


@pytest.fixture
def api_client(client):
    client.app.include_router(cfo_payments_router, prefix="/api")
    return client


def has_column(db, table, column):
    return column in {c["name"] for c in sa_inspect(db.get_bind()).get_columns(table)}


def has_table(db, table):
    return sa_inspect(db.get_bind()).has_table(table)


def payment_cols_ready(db):
    """Kolom yang BENAR-BENAR dibutuhkan alur tulis (lihat REQUIRED_PAYMENT_COLUMNS).

    ``rejected_by_id``/``rejected_at`` tidak ada di schema (lihat
    REQUESTS/cfo_writes.md); router memakai kolom decide yang tersedia untuk
    penolakan, jadi tes tidak boleh mensyaratkannya.
    """
    return all(has_column(db, "payments", c) for c in
               ("status", "evidence_ref", "verified_by_id", "verified_at", "rejection_reason"))


def ap_ready(db):
    return has_table(db, "ap_payments") and has_column(db, "purchase_orders", "vendor_type")


def post(client, headers, role, path, json=None, method="post"):
    """POST tanpa body kecuali `json` diberikan.

    Penting: jangan kirim `json=None` — httpx mengubahnya jadi body `null` dan
    FastAPI akan membalas 422 ("Field required") untuk endpoint tanpa body,
    sehingga tes negatif bisa lulus/ gagal karena alasan yang salah.
    """
    kwargs = {"headers": headers(role)}
    if json is not None:
        kwargs["json"] = json
    return getattr(client, method)("/api" + path, **kwargs)


def seed(db):
    today = date.today()
    order = m.Order(order_id="SO-PAY-001", buyer="Buyer Alpha", order_type=m.OrderType.REPEAT_PRODUCTION)
    db.add(order)
    db.commit()
    invoice = m.Invoice(invoice_no="INV-PAY-1", order_fk=order.id, amount=Decimal("5000000"),
                        paid_amount=Decimal("0"), due_date=today + timedelta(days=10),
                        status="UNPAID", reconciliation_status="VERIFIED")
    db.add(invoice)
    db.commit()
    return order, invoice


def report(client, headers, invoice_id, amount="1000000", evidence="BCA-TRF-99001",
           role="FINANCE_SUPPORT", **extra):
    body = {"amount": amount, "evidence_ref": evidence, **extra}
    return post(client, headers, role, f"/cfo/invoices/{invoice_id}/payments-report", json=body)


# ─────────────────────────── jalur bahagia revisi #17 ───────────────────────────

def test_finance_reports_then_cfo_verifies(api_client, headers, db):
    if not payment_cols_ready(db):
        pytest.skip("kolom payments (status/evidence_ref/verified_*) belum ada di models.py")
    _order, invoice = seed(db)

    reported = report(api_client, headers, invoice.id)
    assert reported.status_code == 201, reported.text
    body = reported.json()
    assert body["workflow"] == "PAYMENT_REPORTED"
    payment_id = body["payment"]["payment_id"]
    assert body["payment"]["status"] == "PAYMENT_REPORTED"
    assert body["payment"]["locked"] is False
    assert body["payment"]["allowed_next_actions"] == ["VERIFY", "REJECT"]
    assert body["payment"]["evidence_ref"] == "BCA-TRF-99001"

    # Pembayaran yang baru DILAPORKAN belum menutup piutang.
    assert body["invoice"]["paid"] == 0.0
    assert body["invoice"]["outstanding"] == 5000000.0
    assert body["invoice"]["pending_amount"] == 1000000.0
    assert db.get(m.Invoice, invoice.id).paid_amount == Decimal("0")

    # Finance TIDAK boleh memverifikasi laporannya sendiri.
    assert post(api_client, headers, "FINANCE_SUPPORT", f"/cfo/payment-decisions/{payment_id}/verify").status_code == 403

    verified = post(api_client, headers, "CFO_MANAGER", f"/cfo/payment-decisions/{payment_id}/verify")
    assert verified.status_code == 200, verified.text
    vbody = verified.json()
    assert vbody["workflow"] == "VERIFIED"
    assert vbody["payment"]["status"] == "VERIFIED"
    assert vbody["payment"]["locked"] is True
    assert vbody["payment"]["allowed_next_actions"] == []
    assert vbody["invoice"]["paid"] == 1000000.0
    assert vbody["invoice"]["outstanding"] == 4000000.0
    assert vbody["invoice"]["partial"] is True

    db.expire_all()
    refreshed = db.get(m.Invoice, invoice.id)
    assert refreshed.paid_amount == Decimal("1000000")
    assert refreshed.status == "PARTIAL"

    # Transisi status uang tercatat di audit.
    logs = db.query(m.AuditLog).filter(m.AuditLog.entity == "Payment",
                                       m.AuditLog.entity_id == payment_id).all()
    actions = {log.action: log for log in logs}
    assert "PAYMENT_REPORTED" in actions
    assert "PAYMENT_VERIFIED" in actions
    assert actions["PAYMENT_VERIFIED"].new_status == "VERIFIED"
    assert actions["PAYMENT_VERIFIED"].previous_status == "PAYMENT_REPORTED"
    assert actions["PAYMENT_VERIFIED"].source_module == "cfo_payments"


def test_cfo_verify_moves_invoice_to_paid_when_full(api_client, headers, db):
    if not payment_cols_ready(db):
        pytest.skip("kolom payments (status/evidence_ref/verified_*) belum ada")
    _order, invoice = seed(db)
    payment_id = report(api_client, headers, invoice.id, amount="5000000").json()["payment"]["payment_id"]
    body = post(api_client, headers, "CFO_MANAGER", f"/cfo/payment-decisions/{payment_id}/verify").json()
    assert body["invoice"]["outstanding"] == 0.0
    db.expire_all()
    assert db.get(m.Invoice, invoice.id).status == "PAID"


# ─────────────────────────── JALUR NEGATIF (inti revisi #17) ───────────────────────────

def test_payment_without_evidence_is_rejected(api_client, headers, db):
    """Tanpa bukti -> DITOLAK. Tidak ada pembayaran "terverifikasi" tanpa bukti."""
    if not payment_cols_ready(db):
        pytest.skip("kolom payments (status/evidence_ref/verified_*) belum ada")
    _order, invoice = seed(db)

    for bad in (None, "", "  ", "?", "??", "N/A", "tbd", "---"):
        body = {"amount": "1000000"}
        if bad is not None:
            body["evidence_ref"] = bad
        response = post(api_client, headers, "FINANCE_SUPPORT",
                        f"/cfo/invoices/{invoice.id}/payments-report", json=body)
        assert 400 <= response.status_code < 500, (bad, response.status_code, response.text)

    # Benar-benar tidak ada satu pun pembayaran yang tersimpan dari percobaan itu.
    assert db.query(m.Payment).count() == 0
    assert db.get(m.Invoice, invoice.id).paid_amount == Decimal("0")


def test_verify_twice_fails_and_reject_after_verify_fails(api_client, headers, db):
    """Immutability: uang yang sudah diputuskan tidak boleh dimutasi ulang."""
    if not payment_cols_ready(db):
        pytest.skip("kolom payments (status/evidence_ref/verified_*) belum ada")
    _order, invoice = seed(db)
    payment_id = report(api_client, headers, invoice.id).json()["payment"]["payment_id"]

    first = post(api_client, headers, "CFO_MANAGER", f"/cfo/payment-decisions/{payment_id}/verify")
    assert first.status_code == 200

    second = post(api_client, headers, "CFO_MANAGER", f"/cfo/payment-decisions/{payment_id}/verify")
    assert 400 <= second.status_code < 500, second.text
    assert second.status_code == 409

    late_reject = post(api_client, headers, "CFO_MANAGER", f"/cfo/payment-decisions/{payment_id}/reject",
                       json={"reason": "ternyata salah transfer"})
    assert 400 <= late_reject.status_code < 500, late_reject.text

    # Nilai invoice tidak berubah setelah percobaan mutasi ulang kedua.
    db.expire_all()
    assert db.get(m.Invoice, invoice.id).paid_amount == Decimal("1000000")
    assert db.query(m.Payment).count() == 1


def test_reject_requires_reason_and_locks_the_payment(api_client, headers, db):
    if not payment_cols_ready(db):
        pytest.skip("kolom payments (status/evidence_ref/verified_*) belum ada")
    _order, invoice = seed(db)
    payment_id = report(api_client, headers, invoice.id).json()["payment"]["payment_id"]

    for bad in (None, "", "   "):
        body = {} if bad is None else {"reason": bad}
        response = post(api_client, headers, "CFO_MANAGER", f"/cfo/payment-decisions/{payment_id}/reject", json=body)
        assert 400 <= response.status_code < 500, (bad, response.status_code, response.text)

    assert post(api_client, headers, "FINANCE_SUPPORT", f"/cfo/payment-decisions/{payment_id}/reject",
                json={"reason": "alasan"}).status_code == 403

    rejected = post(api_client, headers, "CFO_MANAGER", f"/cfo/payment-decisions/{payment_id}/reject",
                    json={"reason": "Bukti tidak terbaca, minta ulang ke buyer"})
    assert rejected.status_code == 200, rejected.text
    rbody = rejected.json()
    assert rbody["workflow"] == "REJECTED"
    assert rbody["payment"]["status"] == "REJECTED"
    assert rbody["payment"]["locked"] is True
    assert rbody["payment"]["rejection_reason"] == "Bukti tidak terbaca, minta ulang ke buyer"

    # Ditolak = tidak menutup piutang, dan catatannya TIDAK dihapus.
    assert rbody["payment"]["payment_id"] == payment_id
    db.expire_all()
    assert db.query(m.Payment).count() == 1
    assert db.get(m.Invoice, invoice.id).paid_amount == Decimal("0")

    # Sekali ditolak, tidak bisa diverifikasi belakangan.
    assert post(api_client, headers, "CFO_MANAGER", f"/cfo/payment-decisions/{payment_id}/verify").status_code == 409


def test_cfo_reject_leaves_audit_trail_with_reason(api_client, headers, db):
    if not payment_cols_ready(db):
        pytest.skip("kolom payments (status/evidence_ref/verified_*) belum ada")
    _order, invoice = seed(db)
    payment_id = report(api_client, headers, invoice.id).json()["payment"]["payment_id"]
    post(api_client, headers, "CFO_MANAGER", f"/cfo/payment-decisions/{payment_id}/reject",
         json={"reason": "Nominal tidak cocok dengan mutasi bank"})

    log = db.query(m.AuditLog).filter(m.AuditLog.entity == "Payment",
                                      m.AuditLog.action == "PAYMENT_REJECTED").one()
    assert log.new_status == "REJECTED"
    assert log.previous_status == "PAYMENT_REPORTED"
    assert "Nominal tidak cocok" in (log.reason or "")
    assert log.user_id is not None


def test_report_rejects_overpayment_and_bad_amounts(api_client, headers, db):
    if not payment_cols_ready(db):
        pytest.skip("kolom payments (status/evidence_ref/verified_*) belum ada")
    _order, invoice = seed(db)
    assert report(api_client, headers, invoice.id, amount="6000000").status_code == 400
    assert report(api_client, headers, invoice.id, amount="0").status_code == 422
    assert report(api_client, headers, invoice.id, amount="-5").status_code == 422

    # Dua laporan yang masing-masing sah tapi totalnya melebihi invoice -> ditolak.
    assert report(api_client, headers, invoice.id, amount="4000000").status_code == 201
    assert report(api_client, headers, invoice.id, amount="2000000").status_code == 400
    assert db.query(m.Payment).count() == 1


def test_role_gating_on_write_endpoints(api_client, headers, db):
    if not payment_cols_ready(db):
        pytest.skip("kolom payments (status/evidence_ref/verified_*) belum ada")
    _order, invoice = seed(db)
    for role in ("CEO", "CMO_MANAGER", "COO_MANAGER", "CHRO_MANAGER", "PRODUCTION_PIC"):
        assert report(api_client, headers, invoice.id, role=role).status_code == 403, role
    assert db.query(m.Payment).count() == 0


def test_payment_queue_lists_pending_verification(api_client, headers, db):
    if not payment_cols_ready(db):
        pytest.skip("kolom payments (status/evidence_ref/verified_*) belum ada")
    _order, invoice = seed(db)
    first = report(api_client, headers, invoice.id, amount="1000000").json()["payment"]["payment_id"]
    second = report(api_client, headers, invoice.id, amount="2000000",
                    evidence="MANDIRI-77120").json()["payment"]["payment_id"]
    post(api_client, headers, "CFO_MANAGER", f"/cfo/payment-decisions/{first}/verify")

    body = api_client.get("/api/cfo/payments-queue", headers=headers("CFO_MANAGER")).json()
    assert body["summary"]["pending_verification_count"] == 1
    assert body["summary"]["pending_verification_amount"] == 2000000.0
    assert body["summary"]["verified_count"] == 1

    pending_only = api_client.get("/api/cfo/payments-queue?status=PAYMENT_REPORTED",
                                  headers=headers("CFO_MANAGER")).json()
    assert [r["payment_id"] for r in pending_only["rows"]] == [second]

    assert api_client.get("/api/cfo/payments-queue?status=BOGUS",
                          headers=headers("CFO_MANAGER")).status_code == 400
    assert api_client.get("/api/cfo/payments-queue", headers=headers("PRODUCTION_PIC")).status_code == 403


def test_no_mutation_or_delete_path_exists(api_client, headers, db):
    """Catatan uang tidak pernah dihapus/ditimpa — koreksi lewat laporan baru."""
    if not payment_cols_ready(db):
        pytest.skip("kolom payments (status/evidence_ref/verified_*) belum ada")
    _order, invoice = seed(db)
    payment_id = report(api_client, headers, invoice.id).json()["payment"]["payment_id"]

    # Tidak ada endpoint mutasi generik: 404 (tidak ada) atau 405 (metode salah),
    # dua-duanya berarti "tidak ada jalan menghapus/menimpa pembayaran".
    for path in (f"/api/cfo/payment-decisions/{payment_id}",
                 f"/api/cfo/payment-decisions/{payment_id}/verify",
                 f"/api/cfo/invoices/{invoice.id}/payments-report"):
        for method in ("put", "patch", "delete"):
            response = getattr(api_client, method)(path, headers=headers("CFO_MANAGER"))
            assert response.status_code in (404, 405), (method, path, response.status_code)

    # Keputusan hanya lewat POST, dan hanya sekali.
    assert post(api_client, headers, "CFO_MANAGER",
                f"/cfo/payment-decisions/{payment_id}/verify").status_code == 200
    assert post(api_client, headers, "CFO_MANAGER",
                f"/cfo/payment-decisions/{payment_id}/verify").status_code == 409
    assert db.query(m.Payment).count() == 1


# ─────────────────────────── AP ledger (revisi #20) ───────────────────────────

def seed_pos(db):
    order = db.query(m.Order).filter_by(order_id="SO-PAY-001").first()
    db.add_all([
        m.PurchaseOrder(po_no="PO-SUP-A", order_fk=order.id, item="Kain", qty=Decimal("100"),
                        unit="meter", supplier="PT Tekstil Makmur", amount=Decimal("5000000"),
                        status="APPROVED", material_status="READY",
                        arrival_date=date.today() - timedelta(days=40)),
        m.PurchaseOrder(po_no="PO-MKL-A", order_fk=order.id, item="Jahit", qty=Decimal("200"),
                        unit="pcs", supplier="CV Makloon Jaya", amount=Decimal("3000000"),
                        status="APPROVED", material_status="READY",
                        arrival_date=date.today() - timedelta(days=20)),
    ])
    db.commit()


def test_ap_ledger_uses_real_vendor_type_not_supplier_name(api_client, headers, db):
    """Nama supplier yang berbunyi 'Makloon' TIDAK cukup untuk jadi makloon."""
    _order, invoice = seed(db)
    if not has_column(db, "purchase_orders", "vendor_type"):
        pytest.skip("kolom purchase_orders.vendor_type belum ada di models.py")
    seed_pos(db)
    # Nama mengandung "Makloon" tapi vendor_type eksplisit = SUPPLIER, dan
    # sebaliknya. Hasilnya harus mengikuti kolom, bukan nama.
    db.query(m.PurchaseOrder).filter_by(po_no="PO-MKL-A").one().vendor_type = "SUPPLIER"
    db.query(m.PurchaseOrder).filter_by(po_no="PO-SUP-A").one().vendor_type = "MAKLOON"
    db.commit()

    body = api_client.get("/api/cfo/ap-ledger", headers=headers("CFO_MANAGER")).json()
    rows = {row["po_no"]: row for row in body["rows"]}
    assert rows["PO-SUP-A"]["ap_kind"] == "MAKLOON"
    assert rows["PO-MKL-A"]["ap_kind"] == "SUPPLIER"
    assert body["summary"]["makloon"]["count"] == 1
    assert body["summary"]["supplier"]["count"] == 1
    assert body["summary"]["unclassified"]["count"] == 0
    assert rows["PO-SUP-A"]["vendor_type_source"] == "purchase_orders.vendor_type"


def test_ap_ledger_marks_missing_vendor_type_as_unclassified(api_client, headers, db):
    _order, _invoice = seed(db)
    if not has_column(db, "purchase_orders", "vendor_type"):
        pytest.skip("kolom purchase_orders.vendor_type belum ada di models.py")
    seed_pos(db)  # vendor_type sengaja dibiarkan kosong

    body = api_client.get("/api/cfo/ap-ledger", headers=headers("CFO_MANAGER")).json()
    assert {row["ap_kind"] for row in body["rows"]} == {"UNCLASSIFIED"}
    assert set(body["summary"]["unclassified_pos"]) == {"PO-SUP-A", "PO-MKL-A"}
    assert body["summary"]["supplier"]["count"] == 0
    assert body["summary"]["makloon"]["count"] == 0


def test_ap_payment_requires_table_and_evidence(api_client, headers, db):
    _order, _invoice = seed(db)
    seed_pos(db)
    po = db.query(m.PurchaseOrder).filter_by(po_no="PO-SUP-A").one()
    if not has_column(db, "purchase_orders", "vendor_type"):
        pytest.skip("kolom purchase_orders.vendor_type belum ada di models.py")
    po.vendor_type = "SUPPLIER"
    db.commit()

    if not ap_ready(db):
        # Tanpa tabel ap_payments, pencatatan WAJIB ditolak (503), bukan diam-diam
        # menyimpan ke tabel lain.
        response = post(api_client, headers, "CFO_MANAGER", "/cfo/ap-ledger/payments",
                        json={"po_fk": po.id, "amount": "1000000", "evidence_ref": "BCA-AP-1"})
        assert response.status_code == 503, response.text
        assert "ap_payments" in response.text
        pytest.skip("tabel ap_payments belum ada di models.py")

    # Tanpa bukti -> ditolak.
    no_evidence = post(api_client, headers, "CFO_MANAGER", "/cfo/ap-ledger/payments",
                       json={"po_fk": po.id, "amount": "1000000"})
    assert 400 <= no_evidence.status_code < 500, no_evidence.text

    ok = post(api_client, headers, "CFO_MANAGER", "/cfo/ap-ledger/payments",
              json={"po_fk": po.id, "amount": "1000000", "evidence_ref": "BCA-AP-1"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["po"]["paid"] == 1000000.0
    assert ok.json()["po"]["outstanding"] == 4000000.0

    # Melebihi sisa utang -> ditolak.
    over = post(api_client, headers, "CFO_MANAGER", "/cfo/ap-ledger/payments",
                json={"po_fk": po.id, "amount": "9999999", "evidence_ref": "BCA-AP-2"})
    assert over.status_code == 400, over.text


def test_ap_payment_rejects_unclassified_vendor_type(api_client, headers, db):
    _order, _invoice = seed(db)
    if not ap_ready(db):
        pytest.skip("tabel ap_payments / kolom vendor_type belum ada")
    seed_pos(db)
    po = db.query(m.PurchaseOrder).filter_by(po_no="PO-MKL-A").one()  # vendor_type kosong
    response = post(api_client, headers, "CFO_MANAGER", "/cfo/ap-ledger/payments",
                    json={"po_fk": po.id, "amount": "1000000", "evidence_ref": "BCA-AP-9"})
    assert response.status_code == 409, response.text


def test_ap_partial_payments_track_outstanding_and_are_audited(api_client, headers, db):
    """Ledger AP nyata: paid/outstanding dari ap_payments, bukan dari notes."""
    if not ap_ready(db):
        pytest.skip("tabel ap_payments / kolom vendor_type belum ada")
    seed(db)
    seed_pos(db)
    po = db.query(m.PurchaseOrder).filter_by(po_no="PO-SUP-A").one()
    po.vendor_type = "SUPPLIER"
    po.tax_amount = Decimal("500000")   # gross = 5.5jt
    db.commit()

    first = post(api_client, headers, "FINANCE_SUPPORT", "/cfo/ap-ledger/payments",
                 json={"po_fk": po.id, "amount": "2000000", "evidence_ref": "BCA-AP-100"})
    assert first.status_code == 201, first.text
    assert first.json()["po"]["paid"] == 2000000.0
    assert first.json()["po"]["gross_amount"] == 5500000.0
    assert first.json()["po"]["outstanding"] == 3500000.0
    assert first.json()["po"]["partial"] is True

    second = post(api_client, headers, "FINANCE_SUPPORT", "/cfo/ap-ledger/payments",
                  json={"po_no": "PO-SUP-A", "amount": "3500000", "evidence_ref": "BCA-AP-101"})
    assert second.status_code == 201, second.text
    assert second.json()["po"]["outstanding"] == 0.0
    assert second.json()["po"]["paid"] == 5500000.0
    assert second.json()["po"]["status"] == "PAID"

    # Tercatat di AP ledger dan di audit.
    body = api_client.get("/api/cfo/ap-ledger?vendor_type=SUPPLIER", headers=headers("CFO_MANAGER")).json()
    row = [r for r in body["rows"] if r["po_no"] == "PO-SUP-A"][0]
    assert row["payment_count"] == 2
    assert sorted(row["payment_evidence"]) == ["BCA-AP-100", "BCA-AP-101"]
    assert row["vendor_type_class"] == "SUPPLIER"

    logs = db.query(m.AuditLog).filter(m.AuditLog.action == "AP_PAYMENT_RECORDED").all()
    assert len(logs) == 2
    assert all(log.source_module == "cfo_payments" for log in logs)
    assert all(log.new_status == "APPROVED" for log in logs)

    # Sisa utang nol -> pembayaran berikutnya ditolak.
    assert post(api_client, headers, "CFO_MANAGER", "/cfo/ap-ledger/payments",
                json={"po_fk": po.id, "amount": "1", "evidence_ref": "BCA-AP-102"}).status_code == 400

    # Role gating pada penulisan AP.
    assert post(api_client, headers, "CEO", "/cfo/ap-ledger/payments",
                json={"po_fk": po.id, "amount": "1", "evidence_ref": "BCA-AP-103"}).status_code == 403


def test_ap_summary_and_ledger_agree_on_real_vendor_type(api_client, headers, db):
    """ap-summary (batch 1) dan ap-ledger (batch 2) harus sepakat."""
    if not ap_ready(db):
        pytest.skip("tabel ap_payments / kolom vendor_type belum ada")
    seed(db)
    seed_pos(db)
    db.query(m.PurchaseOrder).filter_by(po_no="PO-SUP-A").one().vendor_type = "SUPPLIER"
    db.query(m.PurchaseOrder).filter_by(po_no="PO-MKL-A").one().vendor_type = "MAKLOON"
    db.commit()

    summary = api_client.get("/api/cfo/ap-summary", headers=headers("CFO_MANAGER")).json()
    ledger = api_client.get("/api/cfo/ap-ledger", headers=headers("CFO_MANAGER")).json()
    for key in ("supplier", "makloon"):
        assert summary["summary"][key]["count"] == ledger["summary"][key]["count"], key
        assert summary["summary"][key]["outstanding"] == ledger["summary"][key]["outstanding"], key
    assert {r["po_no"]: r["vendor_type_class"] for r in ledger["rows"]} == {
        r["po_no"]: r["vendor_type_class"] for r in summary["rows"]}
