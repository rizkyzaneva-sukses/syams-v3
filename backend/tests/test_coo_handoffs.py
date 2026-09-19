"""Persistensi handoff + jaminan Qty Sent immutable (revisi #54, COO-S-006).

Fokus: handoff yang SUDAH DITERIMA tidak bisa diubah qty-nya (assert 4xx).
Router belum terdaftar di app/main.py (milik orkestrator), jadi tes ini
memasangnya sendiri.
"""
from datetime import date

import pytest

from app import models as m


@pytest.fixture(autouse=True)
def mount_router():
    from app.main import app
    from app.routers.coo_handoffs import router

    already = any(getattr(r, "path", "").startswith("/api/coo/handoffs") for r in app.routes)
    if not already:
        app.include_router(router, prefix="/api")
    yield


def make_order(db, number, route="Cutting>Sewing>QC", qty=100):
    order = m.Order(order_id=number, buyer="Buyer", order_type=m.OrderType.REPEAT_PRODUCTION)
    db.add(order)
    db.flush()
    article = m.Article(order_fk=order.id, article_code="A-1", qty=qty, production_route=route)
    db.add(article)
    db.commit()
    return order, article


def cutting_done(db, article, qty=100):
    mv = m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=qty,
                              qty_done=qty, status="DONE")
    db.add(mv)
    db.commit()
    return mv


def send(db, client, headers, order, article, qty=100, to="Sewing", role="COO_MANAGER", **extra):
    body = {"order_fk": order.id, "article_id": article.id,
            "from_process": "Cutting", "to_process": to, "qty_sent": qty}
    body.update(extra)
    return client.post("/api/coo/handoffs", json=body, headers=headers(role))


# ── Autentikasi & kewenangan ─────────────────────────────────────────────────
def test_endpoints_require_authentication(client):
    assert client.get("/api/coo/handoffs").status_code == 401
    assert client.post("/api/coo/handoffs", json={}).status_code == 401


def test_only_coo_manager_may_send_handoff(db, client, headers):
    order, article = make_order(db, "SO-HO-AUTH")
    cutting_done(db, article)
    # PIC lantai boleh menerima, tidak boleh memindahkan qty.
    denied = send(db, client, headers, order, article, role="PRODUCTION_PIC")
    assert denied.status_code == 403
    assert "tidak berwenang" in denied.json()["detail"]
    assert client.post("/api/coo/handoffs", json={}, headers=headers("CFO_MANAGER")).status_code == 403


# ── Persistensi nyata: batch_no/evidence/shift/location tersimpan ────────────
def test_handoff_persists_batch_evidence_shift_location(db, client, headers):
    order, article = make_order(db, "SO-HO-PERSIST")
    mv = cutting_done(db, article)
    resp = send(db, client, headers, order, article, batch_no="BATCH-77",
                evidence_ref="GD-HO-001", shift="SHIFT-2", location="LINE-A")
    assert resp.status_code == 201, resp.text
    body = resp.json()["handoff"]

    assert body["batch_no"] == "BATCH-77"
    assert body["evidence_ref"] == "GD-HO-001"
    assert body["shift"] == "SHIFT-2"
    assert body["location"] == "LINE-A"
    assert body["qty_sent"] == 100 and body["qty_received"] == 0
    assert body["status"] == "PENDING_RECEIPT"
    assert body["handoff_no"].startswith("HO-SO-HO-PERSIST-A-1-CUTTING-SEWING")
    assert body["qty_sent_locked"] is False

    # Handoff benar-benar tersimpan, bukan direkonstruksi.
    db.expire_all()
    stored = db.query(m.ProductionHandoff).one()
    assert stored.batch_no == "BATCH-77" and stored.shift == "SHIFT-2"
    # Movement pengirim terhubung ke handoff (production_movements.handoff_id).
    assert db.get(m.ProductionMovement, mv.id).handoff_id == stored.id

    listed = client.get(f"/api/coo/handoffs?order_fk={order.id}",
                        headers=headers("COO_MANAGER")).json()
    assert listed["summary"]["count"] == 1
    assert listed["handoffs"][0]["batch_no"] == "BATCH-77"
    assert listed["immutability_rule"] == "Qty Sent tidak boleh ditimpa setelah handoff diterima"


# ── Jaminan inti: QTY SENT IMMUTABLE setelah diterima ────────────────────────
def test_qty_sent_cannot_be_overwritten_after_receipt(db, client, headers):
    order, article = make_order(db, "SO-HO-LOCK")
    cutting_done(db, article)
    handoff_id = send(db, client, headers, order, article, qty=100).json()["handoff"]["id"]

    received = client.post(f"/api/coo/handoffs/{handoff_id}/receive",
                           json={"qty_received": 95}, headers=headers("PRODUCTION_PIC"))
    assert received.status_code == 200, received.text
    assert received.json()["handoff"]["qty_sent_locked"] is True
    assert received.json()["handoff"]["discrepancy"] == -5
    assert received.json()["handoff"]["status"] == "PARTIAL"

    # NEGATIF WAJIB: ubah qty_sent setelah diterima -> harus 4xx.
    tamper = client.patch(f"/api/coo/handoffs/{handoff_id}",
                          json={"qty_sent": 95}, headers=headers("COO_MANAGER"))
    assert 400 <= tamper.status_code < 500, tamper.text
    assert tamper.status_code == 409
    assert "Qty Sent tidak boleh ditimpa" in tamper.json()["detail"]

    # Nilai di database tidak berubah.
    db.expire_all()
    assert db.get(m.ProductionHandoff, handoff_id).qty_sent == 100


def test_qty_sent_change_is_refused_even_when_sent_equals_received(db, client, headers):
    """Diterima penuh pun tetap terkunci — bukan hanya saat ada discrepancy."""
    order, article = make_order(db, "SO-HO-LOCK2")
    cutting_done(db, article)
    handoff_id = send(db, client, headers, order, article, qty=60).json()["handoff"]["id"]
    assert client.post(f"/api/coo/handoffs/{handoff_id}/receive",
                       json={"qty_received": 60},
                       headers=headers("PRODUCTION_PIC")).status_code == 200

    tamper = client.patch(f"/api/coo/handoffs/{handoff_id}",
                          json={"qty_sent": 61}, headers=headers("COO_MANAGER"))
    assert tamper.status_code == 409, tamper.text
    db.expire_all()
    assert db.get(m.ProductionHandoff, handoff_id).qty_sent == 60


def test_cannot_smuggle_qty_sent_change_through_receive_endpoint(db, client, headers):
    """qty_sent tidak boleh diubah lewat endpoint penerimaan."""
    order, article = make_order(db, "SO-HO-LOCK3")
    cutting_done(db, article)
    handoff_id = send(db, client, headers, order, article, qty=100).json()["handoff"]["id"]

    resp = client.post(f"/api/coo/handoffs/{handoff_id}/receive",
                       json={"qty_received": 100, "qty_sent": 50},
                       headers=headers("PRODUCTION_PIC"))
    assert resp.status_code == 409, resp.text
    assert "terkunci" in resp.json()["detail"]
    db.expire_all()
    row = db.get(m.ProductionHandoff, handoff_id)
    assert row.qty_sent == 100 and row.qty_received == 0
    assert row.status == "PENDING_RECEIPT"


def test_double_receipt_is_refused(db, client, headers):
    order, article = make_order(db, "SO-HO-LOCK4")
    cutting_done(db, article)
    handoff_id = send(db, client, headers, order, article, qty=100).json()["handoff"]["id"]
    assert client.post(f"/api/coo/handoffs/{handoff_id}/receive",
                       json={"qty_received": 100},
                       headers=headers("PRODUCTION_PIC")).status_code == 200
    second = client.post(f"/api/coo/handoffs/{handoff_id}/receive",
                         json={"qty_received": 80},
                         headers=headers("PRODUCTION_PIC"))
    assert second.status_code == 409, second.text
    db.expire_all()
    assert db.get(m.ProductionHandoff, handoff_id).qty_received == 100


def test_qty_sent_may_change_before_receipt_and_is_auditable(db, client, headers):
    """Sebelum diterima qty_sent masih boleh dikoreksi — tapi tetap tercatat."""
    order, article = make_order(db, "SO-HO-PRE")
    cutting_done(db, article, qty=100)
    handoff_id = send(db, client, headers, order, article, qty=100).json()["handoff"]["id"]

    fix = client.patch(f"/api/coo/handoffs/{handoff_id}",
                       json={"qty_sent": 80, "reason": "salah ketik"},
                       headers=headers("COO_MANAGER"))
    assert fix.status_code == 200, fix.text
    assert fix.json()["handoff"]["qty_sent"] == 80
    assert fix.json()["handoff"]["discrepancy"] == -80
    assert "qty_sent" in fix.json()["changed"]

    logs = db.query(m.AuditLog).filter_by(action="COO_HANDOFF_UPDATED").all()
    assert logs and logs[0].source_module == "COO_EXECUTION"
    assert logs[0].reason == "salah ketik"


def test_patch_after_receipt_may_still_correct_metadata_only(db, client, headers):
    """Setelah diterima, metadata boleh dikoreksi — qty_sent tidak."""
    order, article = make_order(db, "SO-HO-META")
    cutting_done(db, article)
    handoff_id = send(db, client, headers, order, article, qty=100).json()["handoff"]["id"]
    client.post(f"/api/coo/handoffs/{handoff_id}/receive", json={"qty_received": 100},
                headers=headers("PRODUCTION_PIC"))

    ok = client.patch(f"/api/coo/handoffs/{handoff_id}",
                      json={"evidence_ref": "GD-LATE-9", "location": "GUDANG-B"},
                      headers=headers("COO_MANAGER"))
    assert ok.status_code == 200, ok.text
    assert ok.json()["handoff"]["evidence_ref"] == "GD-LATE-9"
    assert ok.json()["handoff"]["location"] == "GUDANG-B"
    assert ok.json()["handoff"]["qty_sent"] == 100


# ── Angka tidak boleh dikarang ───────────────────────────────────────────────
def test_discrepancy_is_computed_not_accepted_from_client(db, client, headers):
    order, article = make_order(db, "SO-HO-CALC")
    cutting_done(db, article)
    bad = send(db, client, headers, order, article, qty=100, discrepancy=0)
    assert bad.status_code == 400
    assert "dihitung server" in bad.json()["detail"]


def test_qty_received_cannot_be_set_at_send_time(db, client, headers):
    order, article = make_order(db, "SO-HO-RECV")
    cutting_done(db, article)
    bad = send(db, client, headers, order, article, qty=100, qty_received=100)
    assert bad.status_code == 400
    assert "endpoint penerimaan" in bad.json()["detail"]


def test_receipt_cannot_exceed_qty_sent(db, client, headers):
    order, article = make_order(db, "SO-HO-OVER")
    cutting_done(db, article)
    handoff_id = send(db, client, headers, order, article, qty=50).json()["handoff"]["id"]
    resp = client.post(f"/api/coo/handoffs/{handoff_id}/receive",
                       json={"qty_received": 80}, headers=headers("PRODUCTION_PIC"))
    assert resp.status_code == 400
    assert "melebihi qty_sent" in resp.json()["detail"]


def test_qty_sent_cannot_exceed_actual_production(db, client, headers):
    order, article = make_order(db, "SO-HO-EXCEED")
    cutting_done(db, article, qty=40)
    resp = send(db, client, headers, order, article, qty=90)
    assert resp.status_code == 400
    assert "melebihi qty_done" in resp.json()["detail"]


def test_handoff_must_follow_the_article_route(db, client, headers):
    order, article = make_order(db, "SO-HO-ROUTE", route="Cutting>Sewing>QC")
    cutting_done(db, article)
    # Cutting -> QC melompati Sewing.
    skip = send(db, client, headers, order, article, to="QC")
    assert skip.status_code == 400
    assert "harus ke SEWING" in skip.json()["detail"]
    # Proses asing.
    alien = send(db, client, headers, order, article, to="PRINTING")
    assert alien.status_code == 400


def test_handoff_from_last_process_is_refused(db, client, headers):
    order, article = make_order(db, "SO-HO-LAST", route="Cutting>Sewing", qty=60)
    db.add_all([
        m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=60,
                             qty_done=60, status="DONE"),
        m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=60,
                             qty_done=60, status="DONE"),
    ])
    db.commit()
    body = {"order_fk": order.id, "article_id": article.id, "from_process": "Sewing",
            "to_process": "PACKING", "qty_sent": 60}
    resp = client.post("/api/coo/handoffs", json=body, headers=headers("COO_MANAGER"))
    assert resp.status_code == 400
    assert "langkah terakhir" in resp.json()["detail"]


def test_unknown_order_and_article_are_rejected(db, client, headers):
    order, article = make_order(db, "SO-HO-404")
    cutting_done(db, article)
    missing_order = client.post("/api/coo/handoffs",
                                json={"order_fk": 99999, "article_id": article.id,
                                      "from_process": "Cutting", "to_process": "Sewing",
                                      "qty_sent": 10},
                                headers=headers("COO_MANAGER"))
    assert missing_order.status_code == 404

    other_order, other_article = make_order(db, "SO-HO-OTHER")
    cut_other = m.ProductionMovement(article_id=other_article.id, process="Cutting",
                                     qty_in=100, qty_done=100, status="DONE")
    db.add(cut_other)
    db.commit()
    # Artikel milik order lain tidak boleh dipakai.
    mismatch = client.post("/api/coo/handoffs",
                           json={"order_fk": order.id, "article_id": other_article.id,
                                 "from_process": "Cutting", "to_process": "Sewing",
                                 "qty_sent": 10},
                           headers=headers("COO_MANAGER"))
    assert mismatch.status_code == 400
    assert "bukan milik order" in mismatch.json()["detail"]


def test_missing_handoff_returns_404(db, client, headers):
    assert client.post("/api/coo/handoffs/999999/receive", json={"qty_received": 1},
                       headers=headers("COO_MANAGER")).status_code == 404
    assert client.patch("/api/coo/handoffs/999999", json={"batch_no": "X"},
                        headers=headers("COO_MANAGER")).status_code == 404


def test_list_filters_and_summary(db, client, headers):
    order, article = make_order(db, "SO-HO-LIST")
    cutting_done(db, article)
    first = send(db, client, headers, order, article, qty=100).json()["handoff"]["id"]
    send(db, client, headers, order, article, qty=40, to="SEWING")
    client.post(f"/api/coo/handoffs/{first}/receive", json={"qty_received": 90},
                headers=headers("PRODUCTION_PIC"))

    body = client.get(f"/api/coo/handoffs?order_fk={order.id}",
                      headers=headers("COO_MANAGER")).json()
    assert body["summary"]["count"] == 2
    assert body["summary"]["pending_receipt"] == 1
    assert body["summary"]["locked"] == 1
    assert body["summary"]["total_qty_sent"] == 140
    assert body["summary"]["total_qty_received"] == 90
    assert body["summary"]["total_discrepancy"] == -50

    only_locked = client.get(f"/api/coo/handoffs?status=partial",
                             headers=headers("COO_MANAGER")).json()
    assert only_locked["summary"]["count"] == 1
    assert only_locked["handoffs"][0]["qty_sent_locked"] is True
    # Status yang tidak ada memang kosong — bukan diam-diam mengembalikan semua.
    assert client.get("/api/coo/handoffs?status=REJECTED",
                      headers=headers("COO_MANAGER")).json()["summary"]["count"] == 0


def test_read_scope_blocks_unrelated_roles(client, headers):
    assert client.get("/api/coo/handoffs", headers=headers("HR_SUPPORT")).status_code == 403
    assert client.get("/api/coo/handoffs", headers=headers("SHIPMENT_ADMIN")).status_code == 403
