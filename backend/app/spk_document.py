"""Build a frozen SPK document from the order at generation time."""
import json
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def snapshot_spk(spk, order):
    if not order.articles:
        raise ValueError("Order has no articles")
    return {
        "spk_no": spk.spk_no,
        "version": spk.version,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "order_id": order.order_id,
        "buyer": order.buyer,
        "order_date": order.order_date.isoformat() if order.order_date else None,
        "buyer_deadline": order.buyer_deadline.isoformat() if order.buyer_deadline else None,
        "notes": spk.notes or "",
        "articles": [{"article_code": a.article_code, "garment_type": a.garment_type or "",
                      "qty": a.qty, "size_breakdown": a.size_breakdown or "",
                      "production_route": a.production_route or ""} for a in order.articles],
    }


def build_spk_pdf(spk):
    if not spk.snapshot:
        raise ValueError("SPK has no snapshot")
    data = json.loads(spk.snapshot)
    if isinstance(data, list):
        # Historical released SPKs stored just the article snapshot.
        data = {"spk_no": spk.spk_no, "version": spk.version,
                "order_id": str(spk.order_fk), "buyer": "", "articles": data,
                "notes": spk.notes or "", "generated_at": ""}
    articles = data.get("articles")
    if not isinstance(articles, list) or not articles:
        raise ValueError("SPK snapshot has no articles")

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, invariant=1, rightMargin=18*mm,
                            leftMargin=18*mm, topMargin=19*mm, bottomMargin=17*mm)
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    body.wordWrap = "CJK"

    def para(value):
        return Paragraph(escape(str(value if value not in (None, "") else "—")), body)

    story = [Paragraph("SURAT PERINTAH KERJA", styles["Title"]), Spacer(1, 8*mm)]
    details = [
        ["Nomor SPK", data.get("spk_no", spk.spk_no)],
        ["Versi", data.get("version", spk.version)],
        ["Dibuat", data.get("generated_at", "")],
        ["Order", data.get("order_id", "")],
        ["Buyer", data.get("buyer", "")],
        ["Tanggal order", data.get("order_date", "")],
        ["Deadline buyer", data.get("buyer_deadline", "")],
    ]
    table = Table([[para(a), para(b)] for a, b in details], colWidths=[37*mm, 137*mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.extend([table, Spacer(1, 8*mm), Paragraph("Artikel produksi", styles["Heading2"])])
    rows = [[para(x) for x in ("Artikel", "Jenis", "Qty", "Ukuran", "Rute produksi")]]
    for article in articles:
        rows.append([para(article.get(k)) for k in
                     ("article_code", "garment_type", "qty", "size_breakdown", "production_route")])
    article_table = Table(rows, colWidths=[31*mm, 34*mm, 13*mm, 42*mm, 54*mm], repeatRows=1)
    article_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9edf2")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c5ced8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([article_table, Spacer(1, 7*mm), Paragraph("Catatan", styles["Heading2"]),
                  para(data.get("notes", ""))])
    doc.build(story)
    return buffer.getvalue()
