"""SPK preparation stays separate from manager release."""
import json
from datetime import date, timedelta

from app import models as m


def request(client, headers, role, method, path, payload=None, expected=200):
    response = client.request(method, "/api" + path, headers=headers(role), json=payload)
    assert response.status_code == expected, response.text
    return response


def test_support_generates_previews_and_prints_one_locked_version(client, headers, db):
    po = request(client, headers, "CMO_SUPPORT", "POST", "/cmo/po-intake", {
        "po_number": "PO-SPK-01", "buyer": "Buyer from order", "order_type": "REPEAT_PRODUCTION",
        "buyer_deadline": str(date.today()+timedelta(days=30)),
        "articles": [{"article_code": "JKT-01", "garment_type": "Jacket", "qty": 17,
                      "size_breakdown": "M:7,L:10", "production_route": "Cutting>Sewing>QC"}]}, expected=201).json()
    upload = client.post(f"/api/cmo/po-intake/{po['id']}/document", headers=headers("CMO_SUPPORT"),
                         files={"document": ("customer-po.pdf", b"%PDF-1.4\nPO evidence", "application/pdf")})
    assert upload.status_code == 200, upload.text
    request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/check")
    request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/submit")
    accepted = request(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review",
                       {"action": "ACCEPT", "note": "Checked customer PO"}).json()
    order = {"id": accepted["order_fk"], "order_id": accepted["order_id"]}
    spk = request(client, headers, "CMO_SUPPORT", "POST", "/cmo/spk", {
        "order_fk": order["id"], "spk_no": "SPK-REAL-01", "notes": "Use approved fabric"}).json()
    request(client, headers, "CMO_SUPPORT", "POST", "/cmo/spk", {
        "order_fk": order["id"], "spk_no": "SPK-BYPASS", "status": "RELEASED"}, expected=403)
    sid = spk["id"]
    assert spk["status"] == "DRAFT" and spk["snapshot"] is None
    request(client, headers, "CMO_SUPPORT", "GET", f"/cmo/spk/{sid}/pdf", expected=409)
    request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/spk/{sid}/print", expected=409)
    generated = request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/spk/{sid}/generate").json()
    assert generated["status"] == "GENERATED"
    frozen = json.loads(generated["snapshot"])
    assert frozen["spk_no"] == "SPK-REAL-01"
    assert frozen["order_id"] == order["order_id"] and frozen["buyer"] == "Buyer from order"
    assert frozen["articles"][0]["article_code"] == "JKT-01"
    assert frozen["articles"][0]["qty"] == 17
    assert frozen["notes"] == "Use approved fabric"

    preview = request(client, headers, "CMO_SUPPORT", "GET", f"/cmo/spk/{sid}/pdf")
    printed = request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/spk/{sid}/print")
    assert preview.headers["content-type"] == printed.headers["content-type"] == "application/pdf"
    assert preview.content.startswith(b"%PDF") and preview.content == printed.content
    latest = request(client, headers, "CMO_SUPPORT", "GET", "/cmo/spk").json()[0]
    assert latest["status"] == "PRINTED" and latest["snapshot"] == generated["snapshot"]
    assert latest["released_by"] is None and latest["released_at"] is None
    assert request(client, headers, "CMO_SUPPORT", "GET", f"/cmo/spk/{sid}/pdf").content == preview.content
    assert request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/spk/{sid}/print").content == preview.content
    request(client, headers, "CMO_SUPPORT", "PATCH", f"/cmo/spk/{sid}", {"notes": "Changed"}, expected=409)
    request(client, headers, "CMO_SUPPORT", "PATCH", f"/cmo/spk/{sid}", {"status": "RELEASED"}, expected=403)

    release_body={"version_id":sid,"reason":"Commercial gates reviewed"}
    request(client, headers, "CMO_SUPPORT", "GET", f"/cmo/spk/{sid}/release-readiness", expected=403)
    request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/spk/{sid}/release", release_body, expected=403)
    request(client, headers, "COO_MANAGER", "POST", f"/cmo/spk/{sid}/release", release_body, expected=403)
    request(client, headers, "CMO_SUPPORT", "POST", f"/cmo/spk/{sid}/void", expected=403)
    request(client, headers, "CMO_SUPPORT", "DELETE", f"/cmo/spk/{sid}", expected=403)
    readiness=request(client, headers, "CMO_MANAGER", "GET", f"/cmo/spk/{sid}/release-readiness").json()
    assert not readiness["ready"] and readiness["checks"]["printed_version"]["ok"]
    assert not readiness["checks"]["quotation_approved"]["ok"]
    request(client, headers, "CMO_MANAGER", "POST", f"/cmo/spk/{sid}/release",
            {"version_id":sid+1,"reason":"Wrong version"}, expected=409)
    request(client, headers, "CMO_MANAGER", "POST", f"/cmo/spk/{sid}/release", release_body, expected=400)
    assert db.get(m.SPK, sid).status == "PRINTED"
    denied = db.query(m.AuditLog).filter_by(entity="SPK", entity_id=sid, action="DENIED_SPK_ACTION").all()
    assert {entry.detail for entry in denied} >= {"RELEASE", "RELEASE_READINESS", "VOID", "DELETE_DRAFT", "DIRECT_STATUS_CHANGE"}
    assert db.query(m.AuditLog).filter_by(action="DENIED_SPK_ACTION", detail="CREATE_WITH_STATUS").count() == 1

    voided = request(client, headers, "CMO_MANAGER", "POST", f"/cmo/spk/{sid}/void").json()
    assert voided["status"] == "VOID"
    request(client, headers, "CMO_SUPPORT", "GET", f"/cmo/spk/{sid}/pdf", expected=409)
    request(client, headers, "CMO_SUPPORT", "PATCH", f"/cmo/spk/{sid}", {"notes": "Changed"}, expected=409)
    revision = request(client, headers, "CMO_SUPPORT", "POST", "/cmo/spk", {
        "order_fk": order["id"], "spk_no": "SPK-REAL-02"}).json()
    assert revision["version"] == 2


def test_unrelated_role_is_denied_and_audited(client, headers, db):
    request(client, headers, "FINANCE_SUPPORT", "GET", "/cmo/spk", expected=403)
    request(client, headers, "FINANCE_SUPPORT", "POST", "/cmo/spk", {"order_fk": 999, "spk_no": "X"}, expected=403)
    entries = db.query(m.AuditLog).filter_by(action="DENIED_SPK_ACTION", entity="SPK").all()
    assert {entry.detail for entry in entries} == {"LIST", "CREATE_DRAFT"}
