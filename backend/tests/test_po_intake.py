"""CMO Support PO preparation and CMO Manager Order activation."""
import re
from datetime import date, timedelta

from app import models as m


def request(client, headers, role, method, path, body=None, expected=200):
    response = client.request(method, "/api" + path, headers=headers(role), json=body)
    assert response.status_code == expected, response.text
    return response.json() if response.content else None


def complete_draft(client, headers, number="PO-001"):
    po = request(client, headers, "CMO_SUPPORT", "POST", "/cmo/po-intake", {
        "po_number": number, "buyer": "Customer A", "order_type": "SAMPLE_PRODUCTION",
        "buyer_deadline": str(date.today() + timedelta(days=30)),
        "articles": [{"article_code": "A", "qty": 10, "sample_required": True,
                      "production_route": "Cutting > QC > Packing"}],
    }, expected=201)
    uploaded = client.post(f"/api/cmo/po-intake/{po['id']}/document",
                           headers=headers("CMO_SUPPORT"),
                           files={"document": ("buyer-po.pdf", b"%PDF-1.4\n1 0 obj\n", "application/pdf")})
    assert uploaded.status_code == 200, uploaded.text
    return uploaded.json()


def test_po_intake_requires_completeness_and_manager_acceptance(client, headers, db):
    for role in ("CMO_SUPPORT", "CMO_MANAGER", "CEO"):
        request(client, headers, role, "POST", "/orders", {"buyer": "Bypass"}, expected=403)
    po = request(client, headers, "CMO_SUPPORT", "POST", "/cmo/po-intake", {}, expected=201)
    assert po["status"] == "DRAFT" and po["order_id"] is None
    request(client, headers, "COO_MANAGER", "GET", "/cmo/po-intake", expected=403)
    assert request(client, headers, "CMO_MANAGER", "GET", "/cmo/po-intake")[0]["id"] == po["id"]
    checked = request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/check")
    assert checked["status"] == "NEEDS_INFO"
    assert "Dokumen PO (PDF/JPG/PNG)" in checked["missing_items"]
    request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/submit", expected=409)
    request(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "ACCEPT"}, expected=409)
    updated = request(client, headers, "CMO_SUPPORT", "PATCH", f"/cmo/po-intake/{po['id']}", {
        "po_number": "PO-101", "buyer": "Customer A", "order_type": "SAMPLE_PRODUCTION",
        "buyer_deadline": str(date.today() + timedelta(days=30)),
        "articles": [{"article_code": "A", "qty": 10, "sample_required": True,
                      "production_route": "Cutting > QC > Packing"}],
        "follow_up_note": "Buyer sent signed PO and deadline",
    })
    assert updated["status"] == "DRAFT" and updated["follow_up_note"]
    upload = client.post(f"/api/cmo/po-intake/{po['id']}/document",
                         headers=headers("CMO_SUPPORT"),
                         files={"document": ("buyer-po.pdf", b"%PDF-1.4\n1 0 obj\n", "application/pdf")})
    assert upload.status_code == 200, upload.text
    document = client.get(f"/api/cmo/po-intake/{po['id']}/document", headers=headers("CMO_MANAGER"))
    assert document.status_code == 200 and document.content.startswith(b"%PDF-")
    assert request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/check")["status"] == "READY"
    submitted = request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/submit")
    assert submitted["status"] == "SUBMITTED"
    request(client, headers, "CMO_SUPPORT", "PATCH", f"/cmo/po-intake/{po['id']}", {"buyer": "Tampered"}, expected=409)
    request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "ACCEPT"}, expected=403)
    accepted = request(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "ACCEPT", "note": "PO matches buyer request"})
    assert accepted["status"] == "ACCEPTED" and re.fullmatch(r"SYM-\d{4}-\d{3}", accepted["order_id"])
    order = request(client, headers, "CMO_SUPPORT", "GET", "/orders/" + accepted["order_id"])
    assert order["id"] == accepted["order_fk"] and order["buyer"] == "Customer A"
    request(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "ACCEPT"}, expected=409)
    assert db.query(m.Order).count() == 1
    assert db.query(m.AuditLog).filter_by(entity="POIntake", action="ACCEPT").count() == 1


def test_rejected_po_retains_document_and_never_activates_order(client, headers, db):
    po = complete_draft(client, headers, "PO-REJECT")
    request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/check")
    request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/submit")
    request(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "REJECT"}, expected=422)
    rejected = request(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "REJECT", "note": "Buyer signature missing"})
    assert rejected["status"] == "REJECTED" and rejected["order_fk"] is None
    assert db.query(m.Order).count() == 0
    assert client.delete(f"/api/cmo/po-intake/{po['id']}", headers=headers("CMO_MANAGER")).status_code == 405
    assert client.get(f"/api/cmo/po-intake/{po['id']}/document", headers=headers("CMO_MANAGER")).status_code == 200
    request(client, headers, "CMO_SUPPORT", "PATCH", f"/cmo/po-intake/{po['id']}", {"buyer": "Changed"}, expected=409)


def test_po_without_production_route_is_complete_and_gets_default_route(client, headers, db):
    """Permintaan Bos 16 Okt 2026: form PO Draft tidak lagi meminta rute
    produksi. PO tanpa production_route harus dianggap lengkap (bukan
    'Rute produksi setiap article'), dan Order yang lahir dari accept
    otomatis memakai rute standar supaya papan COO tidak kosong."""
    po = request(client, headers, "CMO_SUPPORT", "POST", "/cmo/po-intake", {
        "po_number": "PO-NOROUTE", "buyer": "Customer B", "order_type": "SAMPLE_PRODUCTION",
        "buyer_deadline": str(date.today() + timedelta(days=30)),
        "articles": [{"article_code": "B", "qty": 5, "sample_required": True}],
    }, expected=201)
    client.post(f"/api/cmo/po-intake/{po['id']}/document",
                headers=headers("CMO_SUPPORT"),
                files={"document": ("buyer-po.pdf", b"%PDF-1.4\n1 0 obj\n", "application/pdf")})
    checked = request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/check")
    assert checked["status"] == "READY", checked
    assert "Rute produksi setiap article" not in checked["missing_items"]
    request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/submit")
    accepted = request(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review",
                       {"action": "ACCEPT"})
    assert accepted["status"] == "ACCEPTED"
    order = request(client, headers, "CMO_SUPPORT", "GET", "/orders/" + accepted["order_id"])
    assert order["articles"][0]["production_route"] == "Cutting > Sewing > QC"
