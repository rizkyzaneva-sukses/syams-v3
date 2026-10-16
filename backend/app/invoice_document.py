"""Proforma Invoice (PDF) mengikuti format invoice Syams Manufacturing.

Baris tabel diambil dari baris harga quotation (artikel × qty × harga). Bila quotation tidak punya baris harga,
jumlah tagihan dibagi ke artikel sesuai porsi qty-nya. Mata uang mengikuti mata uang invoice.
"""
import json
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = A4
SYMBOL = {"IDR": "Rp", "USD": "$", "EUR": "€", "AUSD": "A$", "SGD": "S$", "MYR": "RM"}
GRAY = colors.HexColor("#808080")
DARK = colors.HexColor("#1b1b1b")
RED = colors.HexColor("#d62828")


def money(value, currency="IDR") -> str:
    """IDR tanpa desimal ("1.000.000"); mata uang lain 2 desimal gaya Indonesia ("3.800,00")."""
    amount = Decimal(str(value or 0))
    if (currency or "IDR").upper() == "IDR":
        return f"{int(amount.quantize(Decimal('1'))):,}".replace(",", ".")
    text = f"{amount.quantize(Decimal('0.01')):,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _date_en(d) -> str:
    return d.strftime("%d %B %Y") if d else ""


def invoice_lines(invoice, order, quotation) -> list[dict]:
    """[{article, description, qty, price, total}] untuk tabel proforma."""
    by_id = {a.id: a for a in order.articles}
    lines = []
    try:
        priced = json.loads(quotation.pricing_breakdown) if quotation and quotation.pricing_breakdown else []
    except ValueError:
        priced = []
    for row in priced:
        article = by_id.get(row.get("article_id"))
        if not article:
            continue
        price = Decimal(str(row.get("unit_price") or 0))
        lines.append({"article": article.article_code, "description": article.garment_type or "", "qty": article.qty,
                      "price": price, "total": price * article.qty})
    if lines:
        return lines
    total_qty = sum(a.qty for a in order.articles) or 1
    amount = Decimal(str(invoice.amount or 0))
    allocated = Decimal(0)
    for index, a in enumerate(order.articles):
        last = index == len(order.articles) - 1
        share = (amount - allocated) if last else (amount * a.qty / total_qty).quantize(Decimal("0.01"))
        allocated += share
        lines.append({"article": a.article_code, "description": a.garment_type or "", "qty": a.qty,
                      "price": (share / a.qty).quantize(Decimal("0.01")) if a.qty else Decimal(0), "total": share})
    return lines


def build_invoice_pdf(invoice, order, quotation, profile, logo_bytes=None, billed_to=None, po_number=None) -> bytes:
    currency = (invoice.currency or "IDR").upper()
    sym = SYMBOL.get(currency, currency)
    lines = invoice_lines(invoice, order, quotation)
    subtotal = sum((l["total"] for l in lines), Decimal(0))
    amount = Decimal(str(invoice.amount or 0))
    dp = Decimal(str(invoice.dp_amount or 0))
    paid = Decimal(str(invoice.paid_amount or 0))
    outstanding = max(Decimal(0), amount - paid)

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4, invariant=1, pageCompression=0)
    c.setTitle(f"Proforma Invoice {invoice.invoice_no}")
    left, right = 14 * mm, PAGE_W - 14 * mm

    def txt(x, y, value, size=10, bold=False, align="left", color=colors.black, italic=False):
        font = "Helvetica-BoldOblique" if bold and italic else "Helvetica-Bold" if bold else "Helvetica-Oblique" if italic else "Helvetica"
        c.setFont(font, size)
        c.setFillColor(color)
        {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align](x, y, str(value))
        c.setFillColor(colors.black)

    # kop surat
    top = PAGE_H - 14 * mm
    if logo_bytes:
        try:
            c.drawImage(ImageReader(BytesIO(logo_bytes)), left, top - 24 * mm, 62 * mm, 24 * mm, preserveAspectRatio=True,
                        anchor="nw", mask="auto")
        except Exception:
            txt(left, top - 12 * mm, profile.get("name", ""), size=20, bold=True)
    else:
        txt(left, top - 12 * mm, profile.get("name", ""), size=20, bold=True)
    txt(right, top - 3 * mm, profile.get("tagline") or "", size=10, italic=True, align="right")
    if profile.get("phone"):
        txt(right, top - 10 * mm, f"Telp. {profile['phone']}", size=10, italic=True, align="right")
    if profile.get("email"):
        txt(right, top - 17 * mm, f"Email. {profile['email']}", size=10, italic=True, align="right")

    # billed to
    y = top - 36 * mm
    txt(left, y, "Billed To :", size=10, bold=True)
    txt(left, y - 7 * mm, billed_to or order.buyer, size=10)
    txt(left, y - 14 * mm, f"No{invoice.invoice_no}", size=10)
    if po_number:
        txt(left, y - 20 * mm, f"PO : {po_number}", size=9, color=colors.HexColor("#444444"))
    txt(right - 52 * mm, y, "Proforma Invoice", size=10, bold=True, align="right")
    txt(right - 49 * mm, y, ":  " + (billed_to or order.buyer).upper(), size=10)
    txt(right - 52 * mm, y - 7 * mm, "Date", size=10, bold=True, align="right")
    created = invoice.created_at.date() if getattr(invoice, "created_at", None) else date.today()
    txt(right - 49 * mm, y - 7 * mm, ":  " + _date_en(created), size=10)

    # tabel
    cols = [10 * mm, 40 * mm, 46 * mm, 15 * mm, 36 * mm, 35 * mm]
    xs = [left]
    for w in cols:
        xs.append(xs[-1] + w)
    row_h = 7.4 * mm
    ty = y - 32 * mm
    c.setLineWidth(2)
    c.setFillColor(GRAY)
    c.rect(xs[0], ty - row_h, xs[-1] - xs[0], row_h, stroke=1, fill=1)
    c.setFillColor(colors.black)
    for i, name in enumerate(["NO", "Article", "Description", "Qty", "Price", "Total"]):
        txt((xs[i] + xs[i + 1]) / 2, ty - row_h + 2.4 * mm, name, size=10, bold=True, align="center", color=colors.white)
    cy = ty - row_h
    c.setLineWidth(1.6)
    for n, line in enumerate(lines, 1):
        c.rect(xs[0], cy - row_h, xs[-1] - xs[0], row_h, stroke=1, fill=0)
        for x in xs[1:-1]:
            c.line(x, cy, x, cy - row_h)
        base = cy - row_h + 2.4 * mm
        txt((xs[0] + xs[1]) / 2, base, n, align="center")
        txt(xs[1] + 1.5 * mm, base, str(line["article"])[:24])
        txt(xs[2] + 1.5 * mm, base, str(line["description"])[:28])
        txt(xs[4] - 2 * mm, base, line["qty"], bold=True, align="right")
        txt(xs[4] + 2 * mm, base, sym, size=9)
        txt(xs[5] - 2 * mm, base, money(line["price"], currency), align="right")
        txt(xs[5] + 2 * mm, base, sym, size=9)
        txt(xs[6] - 2 * mm, base, money(line["total"], currency), align="right")
        cy -= row_h

    def summary(label_l, value_l, label_r, value_r, fill_label=GRAY):
        nonlocal cy
        c.setLineWidth(1.8)
        c.setFillColor(fill_label)
        c.rect(xs[2], cy - row_h, xs[3] - xs[2], row_h, stroke=1, fill=1)
        c.setFillColor(colors.white)
        c.rect(xs[3], cy - row_h, xs[4] - xs[3], row_h, stroke=1, fill=1)
        c.setFillColor(colors.black)
        c.rect(xs[4], cy - row_h, xs[5] - xs[4], row_h, stroke=1, fill=0)
        c.rect(xs[5], cy - row_h, xs[6] - xs[5], row_h, stroke=1, fill=0)
        base = cy - row_h + 2.4 * mm
        txt((xs[2] + xs[3]) / 2, base, label_l, bold=True, align="center", color=colors.white, size=9)
        txt((xs[3] + xs[4]) / 2, base, value_l, bold=True, align="center")
        txt((xs[4] + xs[5]) / 2, base, label_r, bold=True, align="center", color=colors.black, size=9)
        txt(xs[5] + 2 * mm, base, sym, bold=True, size=9)
        txt(xs[6] - 2 * mm, base, value_r, bold=True, align="right")
        cy -= row_h

    total_qty = sum(l["qty"] for l in lines)
    summary("TOTAL QTY", total_qty, "SUBTOTAL", money(subtotal, currency))
    if abs(subtotal - amount) > Decimal("0.01"):
        summary("", "", "JUMLAH TAGIHAN", money(amount, currency), fill_label=colors.white)
    if dp > 0:
        summary("", "", "DP", money(dp, currency), fill_label=colors.white)
        summary("", "", "SISA TAGIHAN", money(max(Decimal(0), amount - dp), currency), fill_label=colors.white)
    due = invoice.due_date
    if due:
        txt(xs[4] + 2 * mm, cy - 5 * mm, due.strftime("%d/%m/%Y"), bold=True, color=RED)
        txt(xs[5] + 2 * mm, cy - 5 * mm, sym, bold=True, size=9, color=RED)
        txt(xs[6] - 2 * mm, cy - 5 * mm, money(amount, currency), bold=True, align="right", color=RED)

    # total akhir
    by = cy - 24 * mm
    c.setLineWidth(2.2)
    c.setFillColor(GRAY)
    c.rect(xs[4] - 6 * mm, by, 36 * mm + 6 * mm, 8.4 * mm, stroke=1, fill=1)
    c.setFillColor(DARK)
    c.rect(xs[5], by, xs[6] - xs[5], 8.4 * mm, stroke=1, fill=1)
    c.setFillColor(colors.black)
    c.rect(xs[4] - 6 * mm, by - 10 * mm, xs[6] - xs[4] + 6 * mm, 10 * mm, stroke=1, fill=0)
    txt(xs[4] + 15 * mm, by + 2.6 * mm, "INVOICE TOTAL", bold=True, align="center", color=colors.white)
    txt(xs[5] + 2 * mm, by + 2.6 * mm, sym, bold=True, size=9, color=colors.white)
    txt(xs[6] - 2 * mm, by + 2.6 * mm, money(outstanding, currency) if outstanding > 0 else "-", bold=True, align="right",
        color=colors.white)
    c.showPage()
    c.save()
    return buffer.getvalue()
