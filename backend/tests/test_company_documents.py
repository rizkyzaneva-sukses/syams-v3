"""Gambar unggahan, profil perusahaan (logo oleh CEO), dokumen SPK baru, dan Proforma Invoice (PDF)."""
import json
from datetime import date, timedelta
from io import BytesIO

import pytest
from PIL import Image

from app import models as m
from app.cfo_models import StoredImage
from app.invoice_document import build_invoice_pdf, invoice_lines, money
from app.spk_document import build_spk_pdf, parse_sizes, snapshot_spk


def png_bytes(size=(120, 80), color=(200, 30, 30), mode="RGB"):
    out = BytesIO()
    Image.new(mode, size, color).save(out, format="PNG")
    return out.getvalue()


def upload(client, headers, role, kind, raw, name="a.png", mime="image/png"):
    return client.post("/api/files/images", headers=headers(role), data={"kind": kind}, files={"file": (name, raw, mime)})


# ───────────────────────────── unggah gambar ─────────────────────────────

def test_only_ceo_uploads_the_logo_and_teams_upload_designs(client, headers):
    for role in ("CMO_MANAGER", "CMO_SUPPORT", "CFO_MANAGER", "COO_MANAGER"):
        assert upload(client, headers, role, "LOGO", png_bytes()).status_code == 403, role
    ok = upload(client, headers, "CEO", "LOGO", png_bytes())
    assert ok.status_code == 201 and ok.json()["kind"] == "LOGO" and ok.json()["mime"] == "image/png"
    assert upload(client, headers, "CMO_SUPPORT", "DESIGN", png_bytes()).status_code == 201
    assert upload(client, headers, "SAMPLE_PIC", "SIZE_CHART", png_bytes()).status_code == 201
    assert upload(client, headers, "CFO_MANAGER", "DESIGN", png_bytes()).status_code == 403
    assert upload(client, headers, "CEO", "BANNER", png_bytes()).status_code == 422


def test_uploads_must_be_real_images_and_are_shrunk(client, headers, db):
    assert upload(client, headers, "CMO_SUPPORT", "DESIGN", b"%PDF-1.4 bukan gambar", "x.png").status_code == 422
    assert upload(client, headers, "CMO_SUPPORT", "DESIGN", b"", "x.png").status_code == 422
    assert upload(client, headers, "CMO_SUPPORT", "DESIGN", b"\0" * (8 * 1024 * 1024 + 10), "big.png").status_code == 413
    big = upload(client, headers, "CMO_SUPPORT", "DESIGN", png_bytes((3600, 2400)))
    assert big.status_code == 201 and max(big.json()["width"], big.json()["height"]) == 1800
    stored = db.get(StoredImage, big.json()["id"])
    assert stored.mime == "image/jpeg" and Image.open(BytesIO(stored.data)).size == (1800, 1200)
    logo = upload(client, headers, "CEO", "LOGO", png_bytes((2000, 1000), mode="RGBA", color=(0, 0, 0, 0)))
    assert logo.json()["width"] == 800 and logo.json()["mime"] == "image/png"


def test_images_are_served_only_to_signed_in_users(client, headers):
    image = upload(client, headers, "CMO_SUPPORT", "DESIGN", png_bytes()).json()
    assert client.get(f"/api/files/images/{image['id']}").status_code == 401
    got = client.get(f"/api/files/images/{image['id']}", headers=headers("COO_MANAGER"))
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg" and got.content[:2] == b"\xff\xd8"
    assert client.get("/api/files/images/99999", headers=headers("COO_MANAGER")).status_code == 404


# ───────────────────────────── profil perusahaan ─────────────────────────────

def test_company_profile_defaults_and_ceo_only_edit(client, headers):
    default = client.get("/api/company/profile", headers=headers("CMO_SUPPORT")).json()
    assert default["name"] == "SYAMS Manufacturing" and default["logo_image_id"] is None and "Screen printing" in default["tagline"]
    logo = upload(client, headers, "CEO", "LOGO", png_bytes()).json()
    design = upload(client, headers, "CMO_SUPPORT", "DESIGN", png_bytes()).json()
    body = {"name": "SYAMS Manufacturing", "tagline": "Screen printing", "phone": "0811", "email": "a@b.co", "address": "Bandung",
            "logo_image_id": logo["id"]}
    assert client.put("/api/company/profile", headers=headers("CMO_MANAGER"), json=body).status_code == 403
    assert client.put("/api/company/profile", headers=headers("CEO"), json={**body, "logo_image_id": design["id"]}).status_code == 422
    assert client.put("/api/company/profile", headers=headers("CEO"), json={**body, "logo_image_id": 424242}).status_code == 422
    saved = client.put("/api/company/profile", headers=headers("CEO"), json=body)
    assert saved.status_code == 200 and saved.json()["logo_image_id"] == logo["id"] and saved.json()["address"] == "Bandung"
    assert client.get("/api/company/profile", headers=headers("CFO_MANAGER")).json()["phone"] == "0811"


# ───────────────────────────── PO → order membawa spesifikasi & gambar ─────────────────────────────

def accepted_po(client, headers, design_id=None, chart_id=None, number="PO-DOC-1"):
    po = client.post("/api/cmo/po-intake", headers=headers("CMO_SUPPORT"), json={
        "po_number": number, "buyer": "WARCHIEVE", "order_type": "REPEAT_PRODUCTION",
        "buyer_deadline": str(date.today() + timedelta(days=15)),
        "articles": [{"article_code": "ANGEL RED", "garment_type": "T-SHIRT", "qty": 100, "size_breakdown": "S:15, M:25, L:20, XL:25, XXL:15",
                      "design_image_id": design_id, "size_chart_image_id": chart_id, "fabric_type": "16S CKP",
                      "print_type": "PLASTISOL", "embroidery_type": "-", "material_color": "BLACK", "packaging": "OPP",
                      "label_note": "LABEL LEHER", "zipper_note": "", "finishing_note": "Hangtag"}]}).json()
    client.post(f"/api/cmo/po-intake/{po['id']}/document", headers=headers("CMO_SUPPORT"),
                files={"document": ("po.pdf", b"%PDF-1.4\n1 0 obj\n", "application/pdf")})
    client.post(f"/api/cmo/po-intake/{po['id']}/check", headers=headers("CMO_SUPPORT"))
    client.post(f"/api/cmo/po-intake/{po['id']}/submit", headers=headers("CMO_SUPPORT"))
    return client.post(f"/api/cmo/po-intake/{po['id']}/review", headers=headers("CMO_MANAGER"), json={"action": "ACCEPT"}).json()


def test_article_spec_and_images_flow_from_po_to_order(client, headers):
    design = upload(client, headers, "CMO_SUPPORT", "DESIGN", png_bytes()).json()
    chart = upload(client, headers, "CMO_SUPPORT", "SIZE_CHART", png_bytes((60, 40))).json()
    accepted = accepted_po(client, headers, design["id"], chart["id"])
    order = client.get("/api/orders/" + accepted["order_id"], headers=headers("COO_MANAGER")).json()
    article = order["articles"][0]
    assert article["design_image_id"] == design["id"] and article["size_chart_image_id"] == chart["id"]
    assert (article["fabric_type"], article["print_type"], article["material_color"], article["packaging"]) == ("16S CKP", "PLASTISOL", "BLACK", "OPP")
    assert article["label_note"] == "LABEL LEHER" and article["finishing_note"] == "Hangtag"


# ───────────────────────────── dokumen SPK ─────────────────────────────

def test_spk_pdf_follows_the_syams_form_with_logo_and_design(client, headers, db):
    logo = upload(client, headers, "CEO", "LOGO", png_bytes((300, 100), (10, 120, 160))).json()
    client.put("/api/company/profile", headers=headers("CEO"), json={"name": "SYAMS Manufacturing", "logo_image_id": logo["id"]})
    design = upload(client, headers, "CMO_SUPPORT", "DESIGN", png_bytes((400, 500))).json()
    accepted = accepted_po(client, headers, design["id"], None)
    customer = db.query(m.Customer).filter_by(name="WARCHIEVE").one()
    customer.phone, customer.shipping_carrier, customer.address = "0812-1111", "JNE Trucking", "Jl. Merdeka 1, Bandung"
    db.commit()
    spk = client.post("/api/cmo/spk", headers=headers("CMO_SUPPORT"), json={"order_fk": accepted["order_fk"], "spk_no": "SPK-DOC-1", "notes": "Pakai plastisol"}).json()
    generated = client.post(f"/api/cmo/spk/{spk['id']}/generate", headers=headers("CMO_SUPPORT")).json()
    snap = json.loads(generated["snapshot"])
    assert snap["buyer_info"] == {"name": "WARCHIEVE", "phone": "0812-1111", "shipping_carrier": "JNE Trucking", "address": "Jl. Merdeka 1, Bandung"}
    assert snap["order_type"] == "REPEAT_PRODUCTION" and snap["articles"][0]["design_image_id"] == design["id"]
    assert snap["articles"][0]["fabric_type"] == "16S CKP" and snap["articles"][0]["packaging"] == "OPP"

    pdf = client.get(f"/api/cmo/spk/{spk['id']}/pdf", headers=headers("CMO_SUPPORT"))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    for label in (b"BUYER INFORMATION", b"ALUR PRODUKSI", b"SPESIFIKASI", b"FINISHING & ACCESORIES", b"NOTES", b"SIZE CHART",
                  b"ANGEL RED", b"WARCHIEVE", b"JNE Trucking", b"16S CKP", b"PLASTISOL", b"LABEL LEHER", b"REPEAT", b"Pakai plastisol"):
        assert label in pdf.content, label
    printed = client.post(f"/api/cmo/spk/{spk['id']}/print", headers=headers("CMO_SUPPORT"))
    assert printed.content == pdf.content                       # PDF deterministik
    readiness = client.get(f"/api/cmo/spk/{spk['id']}/release-readiness", headers=headers("CMO_SUPPORT")).json()
    assert readiness["checks"]["document_current"]["ok"] is True   # snapshot baru sama dengan isi order


def test_spk_pdf_has_one_page_per_article_and_works_without_images(db):
    order = m.Order(order_id="SYM-2610-001", buyer="Kyan", order_type=m.OrderType.SAMPLE_PRODUCTION, buyer_deadline=date.today() + timedelta(days=9))
    order.articles.append(m.Article(article_code="A1", garment_type="HOODIE", qty=30, size_breakdown="XXL:10, XXXXL:5, S:15"))
    order.articles.append(m.Article(article_code="A2", garment_type="TEE", qty=10, size_breakdown="M:10"))
    db.add(order)
    db.flush()
    spk = m.SPK(order_fk=order.id, spk_no="SPK-X", status="GENERATED", version=1)
    spk.snapshot = json.dumps(snapshot_spk(spk, order, None))
    pdf = build_spk_pdf(spk, None, {"name": "SYAMS Manufacturing", "logo_image_id": None})
    assert pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 2 and b"A1" in pdf and b"A2" in pdf and b"4XL" in pdf
    assert parse_sizes("XXL:10, XXXL:2, xs:3, junk, M:x") == {"2XL": 10, "3XL": 2, "XS": 3}


# ───────────────────────────── Proforma Invoice ─────────────────────────────

def test_money_formats_like_the_proforma_sample():
    assert money(3800, "USD") == "3.800,00" and money(9, "USD") == "9,00" and money(900, "USD") == "900,00"
    assert money(1234567, "IDR") == "1.234.567" and money(0, "IDR") == "0" and money(None) == "0"
    assert money("2500.5", "EUR") == "2.500,50"


def make_invoice(db, currency="USD", amount=3800, dp=0, paid=0, priced=True):
    order = m.Order(order_id="SYM-2610-005", buyer="WARCHIVE", order_type=m.OrderType.REPEAT_PRODUCTION, overall_status="ACTIVE")
    for code, kind, qty in (("ANGEL TEE", "TEE", 100), ("GUARD SWEATPANTS", "PANTS", 100), ("WIDOW TEE", "TEE", 100)):
        order.articles.append(m.Article(article_code=code, garment_type=kind, qty=qty))
    db.add(order)
    db.flush()
    quotation = None
    if priced:
        prices = [9, 20, 9]
        quotation = m.Quotation(order_fk=order.id, quotation_no="Q-1", currency=currency, status="APPROVED",
                                pricing_breakdown=json.dumps([{"article_id": a.id, "unit_price": p, "unit_hpp": 3} for a, p in zip(order.articles, prices)]))
        db.add(quotation)
    invoice = m.Invoice(invoice_no="141026/WRC/OKT 2", order_fk=order.id, amount=amount, dp_amount=dp, paid_amount=paid,
                        currency=currency, due_date=date(2026, 10, 15))
    db.add(invoice)
    db.commit()
    return invoice, order, quotation


def test_invoice_lines_come_from_the_quotation_or_split_by_qty(db):
    invoice, order, quotation = make_invoice(db)
    lines = invoice_lines(invoice, order, quotation)
    assert [(l["article"], l["qty"], float(l["price"]), float(l["total"])) for l in lines] == [
        ("ANGEL TEE", 100, 9.0, 900.0), ("GUARD SWEATPANTS", 100, 20.0, 2000.0), ("WIDOW TEE", 100, 9.0, 900.0)]
    fallback = invoice_lines(invoice, order, None)
    assert sum(float(l["total"]) for l in fallback) == pytest.approx(3800, abs=0.001) and {l["qty"] for l in fallback} == {100}


def test_invoice_pdf_endpoint_renders_the_proforma(client, headers, db):
    invoice, order, quotation = make_invoice(db, dp=1000)
    logo = upload(client, headers, "CEO", "LOGO", png_bytes((300, 100))).json()
    client.put("/api/company/profile", headers=headers("CEO"), json={"name": "SYAMS Manufacturing", "tagline": "Screen printing, Sewing", "phone": "0821", "email": "x@y.id", "logo_image_id": logo["id"]})
    response = client.get(f"/api/cfo/invoices/{invoice.id}/pdf", headers=headers("CFO_MANAGER"))
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    for label in (b"Proforma Invoice", b"WARCHIVE", b"Billed To", b"TOTAL QTY", b"SUBTOTAL", b"INVOICE TOTAL", b"ANGEL TEE",
                  b"3.800,00", b"2.000,00", b"15/10/2026", b"SISA TAGIHAN", b"2.800,00", b"Screen printing, Sewing", b"Telp. 0821"):
        assert label in response.content, label
    assert client.get(f"/api/cfo/invoices/{invoice.id}/pdf", headers=headers("CMO_SUPPORT")).status_code == 200
    assert client.get(f"/api/cfo/invoices/{invoice.id}/pdf", headers=headers("COO_MANAGER")).status_code == 403
    assert client.get("/api/cfo/invoices/99999/pdf", headers=headers("CFO_MANAGER")).status_code == 404


def test_invoice_total_shows_outstanding_and_dash_when_settled(db):
    invoice, order, quotation = make_invoice(db, currency="IDR", amount=5_000_000, paid=5_000_000, priced=False)
    paid = build_invoice_pdf(invoice, order, quotation, {"name": "SYAMS"}, None)
    assert b"INVOICE TOTAL" in paid and b"(-)" in paid
    invoice.paid_amount = 1_000_000
    owing = build_invoice_pdf(invoice, order, quotation, {"name": "SYAMS"}, None)
    assert b"4.000.000" in owing and b"Rp" in owing
