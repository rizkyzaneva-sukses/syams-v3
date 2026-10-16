"""SPK (Surat Perintah Kerja): isi dibekukan saat generate, PDF mengikuti form SPK Syams Manufacturing.

Satu halaman A4 landscape per artikel: tanggal, buyer information, alur produksi, gambar desain,
size & size chart, spesifikasi, finishing & aksesoris, dan notes. Logo perusahaan diambil dari
profil perusahaan (diunggah CEO); gambar desain dan size chart dari gambar yang diunggah di PO.
"""
import json
import re
from datetime import date, datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = landscape(A4)
SIZE_COLUMNS = ["XS", "S", "M", "L", "XL", "2XL", "3XL"]
SIZE_ALIAS = {"XXL": "2XL", "XXXL": "3XL", "XXXXL": "4XL"}
FLOW_ROW_1 = ["BAHAN", "CUTTING", "SORTIR", "SABLON/\nBORDIR", "QC SABLON", "JAHIT"]
FLOW_ROW_2 = ["SHIPPING", "PACKING", "QC", "DISTRESS", "WASHING", "SPRAY"]
ORDER_TYPE_TAG = {"REPEAT_PRODUCTION": "REPEAT", "SAMPLE_PRODUCTION": "SAMPLE + PRODUKSI", "SAMPLE_ONLY": "SAMPLE"}
ARTICLE_FIELDS = ("article_code", "garment_type", "qty", "size_breakdown", "production_route", "extra_size",
                  "design_image_id", "size_chart_image_id", "fabric_type", "print_type", "embroidery_type",
                  "material_color", "packaging", "label_note", "zipper_note", "finishing_note")
BLACK = colors.HexColor("#111111")


def article_snapshot(a) -> dict:
    """Satu-satunya definisi isi artikel di SPK; dipakai saat generate DAN saat memeriksa 'dokumen sesuai order'."""
    out = {}
    for key in ARTICLE_FIELDS:
        value = getattr(a, key, None)
        if key in ("design_image_id", "size_chart_image_id"):
            out[key] = value
        else:
            out[key] = value if key == "qty" else (value or "")
    return out


def snapshot_spk(spk, order, customer=None):
    if not order.articles:
        raise ValueError("Order has no articles")
    return {
        "spk_no": spk.spk_no,
        "version": spk.version,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "order_id": order.order_id,
        "order_type": getattr(order.order_type, "value", order.order_type),
        "buyer": order.buyer,
        "buyer_info": {"name": order.buyer,
                       "phone": getattr(customer, "phone", None) or "",
                       "shipping_carrier": getattr(customer, "shipping_carrier", None) or "",
                       "address": getattr(customer, "address", None) or ""},
        "order_date": order.order_date.isoformat() if order.order_date else None,
        "buyer_deadline": order.buyer_deadline.isoformat() if order.buyer_deadline else None,
        "notes": spk.notes or "",
        "articles": [article_snapshot(a) for a in order.articles],
    }


# ───────────────────────────── helpers gambar ─────────────────────────────

def parse_sizes(text: str) -> dict:
    sizes = {}
    for part in re.split(r"[,;\n]", text or ""):
        name, _, qty = part.partition(":")
        name = SIZE_ALIAS.get(name.strip().upper(), name.strip().upper())
        if name and qty.strip().isdigit():
            sizes[name] = sizes.get(name, 0) + int(qty.strip())
    return sizes


def _fmt_date(value, fallback=""):
    if not value:
        return fallback
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def _image(loader, image_id):
    if not image_id or loader is None:
        return None
    try:
        data = loader(image_id)
        return ImageReader(BytesIO(data)) if data else None
    except Exception:
        return None


class Sheet:
    """Kanvas dengan koordinat dari kiri-atas dalam mm."""

    def __init__(self, c):
        self.c = c

    def y(self, top, h=0):
        return PAGE_H - (top + h) * mm

    def rect(self, x, top, w, h, fill=None, stroke=True, width=1.1):
        c = self.c
        c.setLineWidth(width)
        if fill is not None:
            c.setFillColor(fill)
        c.rect(x * mm, self.y(top, h), w * mm, h * mm, stroke=1 if stroke else 0, fill=1 if fill is not None else 0)
        c.setFillColor(BLACK)

    def text(self, x, top, value, size=8, bold=False, align="left", color=BLACK, italic=False):
        c = self.c
        font = "Helvetica-BoldOblique" if bold and italic else "Helvetica-Bold" if bold else "Helvetica-Oblique" if italic else "Helvetica"
        c.setFont(font, size)
        c.setFillColor(color)
        value = "" if value is None else str(value)
        px, py = x * mm, PAGE_H - top * mm
        if align == "center":
            c.drawCentredString(px, py, value)
        elif align == "right":
            c.drawRightString(px, py, value)
        else:
            c.drawString(px, py, value)
        c.setFillColor(BLACK)

    def bar(self, x, top, w, h, label, size=10):
        self.rect(x, top, w, h, fill=BLACK)
        self.text(x + w / 2, top + h * 0.68, label, size=size, bold=True, align="center", color=colors.white)

    def underline(self, x1, x2, top, width=0.8):
        self.c.setLineWidth(width)
        self.c.line(x1 * mm, PAGE_H - top * mm, x2 * mm, PAGE_H - top * mm)

    def checkbox(self, x, top, checked=False, size=4.2):
        self.rect(x, top, size, size, stroke=True, width=1.0)
        if checked:
            self.c.setLineWidth(1.4)
            self.c.setStrokeColor(colors.HexColor("#d62828"))
            self.c.line((x + 0.6) * mm, self.y(top + size * 0.5), (x + size * 0.4) * mm, self.y(top + size - 0.6))
            self.c.line((x + size * 0.4) * mm, self.y(top + size - 0.6), (x + size + 0.8) * mm, self.y(top - 0.6))
            self.c.setStrokeColor(BLACK)

    def image(self, reader, x, top, w, h):
        if reader is not None:
            self.c.drawImage(reader, x * mm, self.y(top, h), w * mm, h * mm, preserveAspectRatio=True, anchor="c", mask="auto")

    def fit_text(self, x, top, value, max_w, size=8, bold=False):
        """Teks satu baris yang dipotong bila melebihi lebar."""
        value = "" if value is None else str(value)
        font = "Helvetica-Bold" if bold else "Helvetica"
        while value and self.c.stringWidth(value, font, size) > max_w * mm:
            value = value[:-1]
        self.text(x, top, value, size=size, bold=bold)

    def wrapped(self, x, top, value, max_w, size=8, leading=4.2, lines=6):
        words, line, out = str(value or "").split(), "", []
        for word in words:
            trial = (line + " " + word).strip()
            if self.c.stringWidth(trial, "Helvetica", size) <= max_w * mm:
                line = trial
            else:
                out.append(line)
                line = word
        if line:
            out.append(line)
        for i, row in enumerate(out[:lines]):
            self.text(x, top + i * leading, row, size=size)


def _draw_header(s, loader, profile, data):
    s.c.setFillColor(BLACK)
    path = s.c.beginPath()
    path.moveTo(0, PAGE_H)
    path.lineTo(105 * mm, PAGE_H)
    path.lineTo(92 * mm, PAGE_H - 28 * mm)
    path.lineTo(0, PAGE_H - 28 * mm)
    path.close()
    s.c.drawPath(path, stroke=0, fill=1)
    logo = _image(loader, (profile or {}).get("logo_image_id"))
    if logo is not None:
        s.rect(6, 4, 70, 20, fill=colors.white, stroke=False)
        s.image(logo, 8, 5, 66, 18)
    else:
        name = (profile or {}).get("name") or "Syams Manufacturing"
        head, _, tail = name.partition(" ")
        s.text(10, 17, head, size=24, bold=True, color=colors.white)
        s.text(11, 23, tail or "Manufacturing", size=9, bold=True, color=colors.white)
    for i, (label, value) in enumerate((("TODAY'S DATE :", date.today().strftime("%d/%m/%Y")),
                                        ("DUE DATE :", _fmt_date(data.get("buyer_deadline"))),
                                        ("FILE DESIGN :", ""))):
        top = 11 + i * 8
        s.text(232, top, label, size=10, bold=True, align="right")
        s.text(236, top, value, size=11)


def _draw_buyer(s, data):
    info = data.get("buyer_info") or {}
    s.rect(10, 36, 96, 44, stroke=True)
    s.bar(10, 36, 96, 8, "BUYER INFORMATION")
    rows = (("Nama", info.get("name") or data.get("buyer")), ("Nomor Ponsel", info.get("phone")),
            ("Ekspedisi Pengiriman", info.get("shipping_carrier")), ("Alamat", info.get("address")))
    for i, (label, value) in enumerate(rows):
        top = 52 + i * 8
        s.text(12, top, label, size=8, bold=True)
        s.fit_text(46, top - 0.6, value, 58, size=9)
        s.underline(46, 104, top + 1.2, width=0.6)


def _draw_flow(s):
    s.rect(110, 36, 177, 44, stroke=True)
    s.bar(110, 36, 177, 8, "ALUR PRODUKSI")
    xs = [118 + i * 28.5 for i in range(6)]
    s.c.setLineWidth(1.0)
    s.c.line(xs[0] * mm, s.y(54), xs[-1] * mm, s.y(54))
    s.c.line(xs[0] * mm, s.y(69), xs[-1] * mm, s.y(69))
    for x, label in zip(xs, FLOW_ROW_1):
        s.rect(x, 50, 4.2, 4.2, fill=colors.white)
        for n, part in enumerate(label.split("\n")):
            s.text(x + 2.1, 59 + n * 3, part, size=5.5, bold=False, align="center")
    for x, label in zip(xs, FLOW_ROW_2):          # arus kembali ke kiri: SPRAY di kanan → SHIPPING di kiri
        s.rect(x, 65, 4.2, 4.2, fill=colors.white)
        s.text(x + 2.1, 74, label, size=5.5, align="center")
    # kurva penghubung baris 1 -> baris 2 di sisi kanan
    s.c.setLineWidth(1.0)
    s.c.bezier((xs[-1] + 4.2) * mm, s.y(52.1), (xs[-1] + 11) * mm, s.y(52.1), (xs[-1] + 11) * mm, s.y(67.1), (xs[-1] + 4.2) * mm, s.y(67.1))


def _draw_article(s, loader, data, article):
    # nama artikel + gambar desain
    s.rect(10, 84, 28, 14)
    s.text(24, 90.5, "NAMA", size=9, align="center")
    s.text(24, 95, "ARTIKEL", size=9, align="center")
    s.rect(38, 84, 96, 14)
    s.fit_text(42, 93, article.get("article_code"), 90, size=12)
    s.rect(10, 98, 124, 102)
    s.image(_image(loader, article.get("design_image_id")), 12, 100, 120, 98)

    # size
    sizes = parse_sizes(article.get("size_breakdown"))
    columns = SIZE_COLUMNS + (["4XL"] if sizes.get("4XL") else [])
    s.rect(136, 84, 82, 14)
    s.text(177, 93, "SIZE", size=11, align="center")
    s.rect(136, 98, 82, 8)
    width = 82 / (len(columns) + 1)
    for i, name in enumerate(columns + ["TOTAL"]):
        x = 136 + i * width
        s.rect(x, 98, width, 8, stroke=True, width=0.6)
        s.text(x + width / 2, 103.4, name, size=6.5, align="center")
        value = sum(sizes.values()) if name == "TOTAL" else sizes.get(name, "")
        s.rect(x, 106, width, 12, stroke=True, width=0.6)
        s.text(x + width / 2, 113.4, value or "", size=9, align="center")
    s.rect(136, 118, 82, 8)
    s.text(177, 123.6, "SIZE CHART", size=7.5, align="center")
    s.rect(136, 126, 82, 74)
    chart = _image(loader, article.get("size_chart_image_id"))
    s.image(chart, 138, 128, 78, 70)
    tag = ORDER_TYPE_TAG.get(data.get("order_type"), "")
    if chart is None and tag:
        s.text(177, 166, tag, size=13, align="center", color=colors.HexColor("#d62828"))

    # spesifikasi
    s.rect(221, 84, 66, 50)
    s.bar(221, 84, 66, 8, "SPESIFIKASI", size=9)
    spec = (("JENIS PRODUK", article.get("garment_type")), ("JENIS KAIN", article.get("fabric_type")),
            ("JENIS SABLON", article.get("print_type")), ("JENIS BORDIR", article.get("embroidery_type")),
            ("WARNA MATERIAL", article.get("material_color")))
    for i, (label, value) in enumerate(spec):
        top = 98 + i * 7.6
        s.text(223, top, label, size=5.8)
        s.fit_text(250, top - 0.4, value or "-", 35, size=7.2)
        s.underline(250, 285, top + 1.0, width=0.5)

    # finishing
    s.rect(221, 138, 66, 36)
    s.bar(221, 138, 66, 8, "FINISHING & ACCESORIES", size=8.5)
    s.text(223, 152, "PACKAGING", size=5.8)
    packaging = (article.get("packaging") or "").upper()
    s.checkbox(251, 148.6, checked=packaging == "OPP", size=4.2)
    s.text(256.5, 152, "OPP", size=6)
    s.checkbox(265, 148.6, checked=packaging == "ZIPLOCK", size=4.2)
    s.text(270.5, 152, "ZIPLOCK", size=6)
    for i, (label, value) in enumerate((("LABEL / HANTAG", article.get("label_note")),
                                        ("ZIPPER / HEADZIP", article.get("zipper_note")),
                                        ("LAINNYA", article.get("finishing_note")))):
        top = 158 + i * 5.2
        s.text(223, top, label, size=5.8)
        s.fit_text(250, top - 0.4, value or "", 35, size=7)
        s.underline(250, 285, top + 1.0, width=0.5)

    # notes
    s.rect(221, 178, 66, 22)
    s.bar(221, 178, 66, 7, "NOTES", size=9)
    notes = data.get("notes") or ""
    extra = article.get("extra_size")
    if extra:
        notes = (notes + "  " if notes else "") + f"Extra size: {extra}"
    s.wrapped(223, 190, notes, 62, size=7, leading=3.6, lines=3)


def build_spk_pdf(spk, image_loader=None, profile=None):
    if not spk.snapshot:
        raise ValueError("SPK has no snapshot")
    data = json.loads(spk.snapshot)
    if isinstance(data, list):
        # SPK lama hanya menyimpan daftar artikel.
        data = {"spk_no": spk.spk_no, "version": spk.version, "order_id": str(spk.order_fk), "buyer": "",
                "articles": data, "notes": spk.notes or ""}
    articles = data.get("articles")
    if not isinstance(articles, list) or not articles:
        raise ValueError("SPK snapshot has no articles")
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4), invariant=1, pageCompression=0)
    c.setTitle(f"SPK {data.get('spk_no', spk.spk_no)} v{data.get('version', spk.version)}")
    s = Sheet(c)
    for index, article in enumerate(articles):
        _draw_header(s, image_loader, profile, data)
        s.text(10, 33, f"SPK {data.get('spk_no', spk.spk_no)} · v{data.get('version', spk.version)} · {data.get('order_id', '')}",
               size=7, color=colors.HexColor("#555555"))
        _draw_buyer(s, data)
        _draw_flow(s)
        _draw_article(s, image_loader, data, article)
        s.text(287, 205, f"Halaman {index + 1}/{len(articles)}", size=6.5, align="right", color=colors.HexColor("#555555"))
        c.showPage()
    c.save()
    return buffer.getvalue()
