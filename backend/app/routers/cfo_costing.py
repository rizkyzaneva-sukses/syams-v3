"""CFO Actual Cost vs HPP + Operational Cost — Revisi #21 (CFO-007) & #24 (CFO-010).

Two read-only views for Lutfi (CFO_MANAGER):

1. ``GET /cfo/actual-cost-variance``
   Estimated (quotation/HPP versi terkunci di quotation) vs Actual HPP per Order
   ID + Article ID. Angka aktual diambil dari fakta operasional yang sudah
   dicatat divisi lain — ``material_consumptions`` (pemakaian material nyata,
   bukan kuantitas BOM) dan ``production_cost_entries`` (upah/overhead aktual) —
   bukan dari angka quotation. Setiap baris membawa ``variance`` (nominal),
   ``variance_percent``, arah (OVER/UNDER/ON_TRACK), penyebab yang bisa
   ditelusuri, owner, evidence/source, dan status review.

2. ``GET /cfo/operational-cost``
   Ringkasan biaya operasional per periode/kategori, DIPISAH dari HPP produksi:
   material + labor/overhead adalah HPP produksi (direct), sedangkan pembelian
   material (purchase orders) dan biaya operasional registrasi berada di luar HPP
   dan tidak pernah otomatis masuk HPP.

Batas peran (revisi #21): CFO mengklasifikasi, merekonsiliasi, dan mengunci nilai
finansial — router ini murni baca dan tidak pernah mengubah fakta produksi fisik
(kuantitas, output, rework, pemakaian material). Koreksi tetap lewat
adjustment/version di modul operasional, bukan ditimpa di sini.

Tabel ``operational_cost_entries`` (register biaya operasional formal: Cost ID,
vendor/employee, cost center, currency/FX, approval, payment status, accounting
period, klasifikasi direct/OPEX/asset/advance/reimbursement) belum ada di
``models.py``. Spesifikasinya ditulis di ``REQUESTS/cfo_costing.md``; selama
tabel itu belum ada, endpoint mengembalikan struktur kosong yang tetap valid
(``available: false`` + ``register: []``) dan tetap menyajikan klasifikasi yang
bisa dihitung hari ini tanpa tabel baru.
"""
from collections import OrderedDict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from .. import models as m

router = APIRouter(prefix="/cfo", tags=["cfo-costing"])

VIEW_ROLES = {"CEO", "CFO_MANAGER", "FINANCE_SUPPORT"}
FILTER_ROLES = {"CFO_MANAGER", "CEO"}


def _require_view(user):
    if user.role.value not in VIEW_ROLES:
        raise HTTPException(403, "Laporan biaya aktual & biaya operasional tidak tersedia untuk peran ini.")


def _require_filter(user):
    if user.role.value not in FILTER_ROLES:
        raise HTTPException(403, "Filter tanggal pada laporan biaya hanya tersedia untuk CFO dan CEO.")


# --- angka ------------------------------------------------------------------
# Semua nominal dirender sebagai string desimal 2 angka di belakang koma. JSON
# float biner (mis. 9999999.999999998) tidak boleh muncul di laporan keuangan,
# jadi konversi dilakukan sekali di sini dan tidak pernah lewat float.


def _dec(value):
    if value is None:
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def _num(value):
    return str(_dec(value).quantize(Decimal("0.01")))


def _qty(value):
    """Kuantitas tanpa notasi ilmiah dan tanpa nol ekor (60, 12.5, 0.25)."""
    decimal_value = _dec(value)
    rendered = format(decimal_value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _pct(part, base):
    base = _dec(base)
    if base == 0:
        return None
    return str((_dec(part) / base * Decimal(100)).quantize(Decimal("0.01")))


def _iso(value):
    return value.isoformat() if value is not None else None


def _day(value):
    """Tanggal saja dari datetime/date, untuk menghitung umur bukti."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


# --- klasifikasi biaya ------------------------------------------------------
# HPP produksi = biaya direct yang menempel pada order/artikel. Yang BUKAN HPP:
# a.l. pembelian material (purchase order), aset/capex, advance, reimbursement,
# dan biaya operasional perusahaan. Daftar ini dipakai di kedua endpoint supaya
# pemisahan HPP vs non-HPP konsisten dan bisa diaudit, bukan tersebar di UI.

PRODUCTION_CATEGORIES = ("LABOR", "OVERHEAD", "MATERIAL", "MAKLOON", "WASTE", "REWORK")

NON_HPP_PREFIXES = ("OPEX", "OPERATIONAL", "OPERASIONAL", "ASSET", "CAPEX", "ADVANCE", "REIMBURSE")

NON_HPP_HINTS = ("SELLING", "MARKETING", "PROMOSI", "GAJI_OFFICE", "SALARY_OFFICE", "RENT", "SEWA",
                 "UTILITAS", "INSURANCE", "ASURANSI", "TAX", "PAJAK", "TRAVEL", "TRANSPORT",
                 "ENTERTAIN", "DEPRECIATION", "DEPRESIASI", "AMORT")

OTHER_PRODUCTION_CATEGORIES = ("OTHER", "")

CATEGORY_LABELS = OrderedDict([
    ("MATERIAL", "Material aktual (pemakaian nyata)"),
    ("LABOR", "Upah langsung"),
    ("OVERHEAD", "Overhead produksi"),
    ("OTHER", "Biaya produksi lain (belum diklasifikasi)"),
    ("MAKLOON", "Makloon / subkontrak"),
    ("WASTE", "Waste & reject"),
    ("REWORK", "Rework"),
])

OPERATIONAL_DEPARTMENTS = {
    "COO_MANAGER": "Produksi & Operasional",
    "PRODUCTION_PIC": "Produksi & Operasional",
    "PRINTING_PIC": "Printing",
    "SHIPMENT_ADMIN": "Pengiriman",
    "CMO_MANAGER": "Commercial",
    "CMO_SUPPORT": "Commercial Support",
    "CFO_MANAGER": "Finance & Purchasing",
    "FINANCE_SUPPORT": "Finance Support",
    "CHRO_MANAGER": "HR",
    "HR_SUPPORT": "HR Support",
    "CEO": "Executive",
    "SAMPLE_PIC": "Sample & PPM",
}


def classify_category(raw):
    """Kembalikan (bucket, normalized, alasan) untuk kolom kategori bebas teks.

    Bucket: ``HPP_PRODUCTION``, ``NON_HPP`` atau ``UNCLASSIFIED``. Kategori yang
    tidak dikenali sengaja TIDAK diam-diam masuk HPP — biaya itu dilaporkan
    sebagai belum terklasifikasi supaya CFO memutuskannya secara eksplisit.
    """
    value = (raw or "").strip().upper()
    if value in PRODUCTION_CATEGORIES:
        return "HPP_PRODUCTION", value, "Kategori produksi: masuk HPP aktual."
    if value.startswith(NON_HPP_PREFIXES) or any(hint in value for hint in NON_HPP_HINTS):
        return "NON_HPP", value, "Kategori operasional/aset: TIDAK masuk HPP aktual."
    if value in OTHER_PRODUCTION_CATEGORIES:
        return "HPP_PRODUCTION" if value == "OTHER" else "UNCLASSIFIED", value, \
            "Kategori 'OTHER' dianggap biaya produksi direct (perilaku lama), perlu ditinjau CFO."
    return "UNCLASSIFIED", value, "Kategori belum dipetakan — ditahan di luar HPP sampai CFO mengklasifikasi."


def build_classification(cost_rows):
    """Peta kategori -> bucket + kategori hasil normalisasi, dari data nyata."""
    buckets = OrderedDict()
    for row in cost_rows:
        raw = (row.category or "").strip()
        bucket, normalized, reason = classify_category(raw)
        key = normalized or "(kosong)"
        if key not in buckets:
            buckets[key] = {
                "category": key,
                "bucket": bucket,
                "reason": reason,
                "entry_count": 0,
                "amount": Decimal(0),
            }
        buckets[key]["entry_count"] += 1
        buckets[key]["amount"] += _dec(row.amount)
    ordered = sorted(buckets.values(), key=lambda item: (item["bucket"], -item["amount"]))
    for item in ordered:
        item["amount"] = _num(item["amount"])
    return ordered


# --- data operasional -------------------------------------------------------


def _approved_quote(db, order_fk):
    return (db.query(m.Quotation)
            .filter(m.Quotation.order_fk == order_fk, m.Quotation.status == "APPROVED")
            .order_by(m.Quotation.id.desc()).first())


def _quote_lines(quote):
    """Baris harga per artikel dari quotation. ``{}`` bila tidak bisa dibaca."""
    if quote is None or not quote.pricing_breakdown:
        return {}
    import json

    try:
        payload = json.loads(quote.pricing_breakdown)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, list):
        return {}
    lines = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        article_id = raw.get("article_id")
        if article_id is None:
            continue
        lines[int(article_id)] = raw
    return lines


def _consumption_rows(db, order):
    """Pemakaian material nyata untuk satu order, dikelompokkan per artikel.

    Sumber ``material_consumptions`` — fakta fisik yang dicatat COO/PIC, bukan
    kebutuhan BOM. BOM hanya dipakai sebagai nilai rencana/estimasi.
    """
    grouped = {}
    rows = (db.query(m.MaterialConsumption, m.BOMItem, m.Article)
            .join(m.BOMItem, m.BOMItem.id == m.MaterialConsumption.bom_item_id)
            .join(m.Article, m.Article.id == m.BOMItem.article_id)
            .filter(m.Article.order_fk == order.id)
            .order_by(m.MaterialConsumption.id.asc()).all())
    for usage, item, article in rows:
        grouped.setdefault(article.id, []).append((usage, item))
    return grouped


def _actual_for_article(db, article, consumptions, cost_rows):
    """Baris aktual per artikel + jejak selisihnya."""
    waste = Decimal(0)
    material = Decimal(0)
    evidence = []
    for usage, item in consumptions:
        qty = _dec(usage.qty)
        material += qty * _dec(usage.actual_unit_cost)
        planned_qty = _dec(item.qty_per_unit) * Decimal(int(article.qty or 0))
        if planned_qty and qty > planned_qty:
            waste += qty - planned_qty
        evidence.append({
            "entry_id": usage.id,
            "source": "material_consumptions",
            "entry_category": "MATERIAL",
            "material_name": item.material_name,
            "unit": item.unit,
            "qty": _qty(qty),
            "actual_unit_cost": _num(usage.actual_unit_cost),
            "planned_unit_cost": _num(item.planned_unit_cost),
            "amount": _num(qty * _dec(usage.actual_unit_cost)),
            "source_ref": usage.evidence_ref,
            "recorded_at": _iso(usage.created_at),
        })

    breakdown = OrderedDict()
    for entry in cost_rows:
        bucket, normalized, _ = classify_category(entry.category)
        if bucket != "HPP_PRODUCTION":
            continue
        key = normalized or "(kosong)"
        breakdown[key] = breakdown.get(key, Decimal(0)) + _dec(entry.amount)
        evidence.append({
            "entry_id": entry.id,
            "source": "production_cost_entries",
            "entry_category": key,
            "material_name": None,
            "unit": None,
            "qty": None,
            "actual_unit_cost": None,
            "planned_unit_cost": None,
            "amount": _num(entry.amount),
            "source_ref": entry.evidence_ref,
            "recorded_at": _iso(entry.created_at),
        })

    # Rencana material dari BOM (kuantitas terjadwal x harga rencana). Ini murni
    # estimasi operasional; HPP quotation tetap dipakai sebagai pembanding utama.
    consumed_bom_ids = {item.id for _usage, item in consumptions}
    planned_material = Decimal(0)
    material_complete = True
    for item in db.query(m.BOMItem).filter_by(article_id=article.id).all():
        planned_material += Decimal(int(article.qty or 0)) * _dec(item.qty_per_unit) * _dec(item.planned_unit_cost)
        material_complete = material_complete and item.id in consumed_bom_ids

    actual_total = material + sum(breakdown.values(), Decimal(0))
    return {
        "article_id": article.id,
        "article_code": article.article_code,
        "qty": int(article.qty or 0),
        "planned_material_cost": _num(planned_material),
        "actual_material_cost": _num(material),
        "waste_qty": _qty(waste),
        "actual_labor_overhead_cost": _num(sum(breakdown.values(), Decimal(0))),
        "cost_breakdown": {key: _num(value) for key, value in breakdown.items()},
        "actual_total_cost": _num(actual_total),
        "material_usage_complete": material_complete,
        "evidence": evidence,
    }


def _variance(actual, estimated, higher_is_worse=True):
    estimated = _dec(estimated)
    actual = _dec(actual)
    diff = actual - estimated
    if diff == 0:
        direction = "ON_TRACK"
    elif (diff > 0) == higher_is_worse:
        direction = "OVER"
    else:
        direction = "UNDER"
    return {
        "estimated": _num(estimated),
        "actual": _num(actual),
        "variance": _num(diff),
        "variance_percent": _pct(diff, estimated) if estimated != 0 else None,
        "direction": direction,
    }


def _next_action(direction, reviewed):
    if reviewed:
        return "Terkunci — koreksi hanya lewat adjustment/version dengan alasan."
    if direction == "OVER":
        return "Telusuri pemicu biaya dan kunci review CFO."
    if direction == "UNDER":
        return "Pastikan tidak ada biaya produksi yang belum tercatat."
    return "Cocok dengan rencana — kunci review CFO."


def build_variance_order(db, order, *, status, has_data, reviewed, review, date_from, date_to):
    consumptions = _consumption_rows(db, order)
    quote = _approved_quote(db, order.id)
    lines = _quote_lines(quote)
    quote_hpp = _dec(quote.hpp_total) if quote else Decimal(0)

    cost_rows = (db.query(m.ProductionCostEntry)
                 .join(m.Article, m.Article.id == m.ProductionCostEntry.article_id)
                 .filter(m.Article.order_fk == order.id)
                 .order_by(m.ProductionCostEntry.id.asc()).all())

    quotation_total = Decimal(0)
    actual_total = Decimal(0)
    actual_material = Decimal(0)
    planned_material = Decimal(0)
    articles = []
    evidence_refs = []
    material_complete = True
    for article in order.articles:
        line = lines.get(article.id)
        unit_hpp = _dec(line.get("unit_hpp")) if line else Decimal(0)
        estimated = unit_hpp * Decimal(int(article.qty or 0))
        quotation_total += estimated
        article_costs = [row for row in cost_rows if row.article_id == article.id]
        row = _actual_for_article(db, article, consumptions.get(article.id, []), article_costs)
        row["quotation_hpp"] = _num(estimated)
        row["unit_hpp_quotation"] = _num(unit_hpp)
        variance = _variance(row["actual_total_cost"], estimated)
        row.update(variance)
        row["next_action"] = _next_action(variance["direction"], reviewed)
        row["hpp_source"] = "quotation.pricing_breakdown" if line else "unavailable"
        articles.append(row)
        actual_total += _dec(row["actual_total_cost"])
        actual_material += _dec(row["actual_material_cost"])
        planned_material += _dec(row["planned_material_cost"])
        material_complete = material_complete and row["material_usage_complete"]
        evidence_refs.extend(
            ref for ref in (row["evidence"] and [e["source_ref"] for e in row["evidence"]]) or [] if ref)

    # Selisih tingkat order: pakai hpp_total quotation bila ada, supaya tidak ada
    # selisih yang hilang ketika pricing_breakdown tidak memuat artikel tertentu.
    estimated_order = quote_hpp if quote_hpp else quotation_total
    order_variance = _variance(actual_total, estimated_order)
    revenue = _dec(quote.amount) if quote else None

    causes = _variance_causes(articles, order_variance, quote, reviewed)

    return {
        "order_id": order.order_id,
        "order_fk": order.id,
        "buyer": order.buyer,
        "overall_status": order.overall_status,
        "order_date": _iso(order.order_date),
        "cut_off": _iso(date.today()),
        "status": status,
        "has_actual_data": has_data,
        "quotation_no": quote.quotation_no if quote else None,
        "quotation_version": quote.id if quote else None,
        "currency": quote.currency if quote else "IDR",
        "hpp_source": "quotation.hpp_total" if quote_hpp else (
            "quotation.pricing_breakdown" if quotation_total else "unavailable"),
        **order_variance,
        "quotation_hpp": _num(estimated_order),
        "actual_material_cost": _num(actual_material),
        "planned_material_cost": _num(planned_material),
        "material_usage_complete": bool(articles) and material_complete,
        "revenue": _num(revenue) if revenue is not None else None,
        "actual_margin": _num(revenue - actual_total) if revenue is not None else None,
        "actual_margin_percent": _pct(revenue - actual_total, revenue) if revenue not in (None, 0) else None,
        "review": {
            "reviewed": reviewed,
            "reviewed_total": _num(review.reviewed_total) if review else None,
            "reviewed_at": _iso(review.reviewed_at) if review else None,
            "reviewed_by_id": review.reviewed_by_id if review else None,
            "matches_actual": bool(review and _dec(review.reviewed_total) == actual_total),
            "evidence_ref": review.evidence_ref if review else None,
            "status": "LOCKED" if reviewed else ("OVER" if order_variance["direction"] == "OVER" else "OPEN"),
        },
        "owner": "CFO_MANAGER",
        "evidence_refs": sorted(set(evidence_refs)),
        "causes": causes,
        "articles": articles,
        "data_window": {"date_from": _iso(date_from), "date_to": _iso(date_to)},
    }


def _variance_causes(articles, order_variance, quote, reviewed):
    """Penyebab selisih yang bisa ditelusuri ke bukti, bukan tebakan bebas."""
    causes = []
    if quote is None:
        causes.append({
            "cause": "Quotation belum disetujui",
            "detail": "Tidak ada quotation APPROVED sehingga HPP quotation belum tersedia untuk dibandingkan.",
            "owner": "CMO_MANAGER",
            "evidence": [],
            "traceable": True,
        })
    material_gap = sum((_dec(a["actual_material_cost"]) - _dec(a["planned_material_cost"]) for a in articles), Decimal(0))
    if material_gap != 0:
        heavy = [a for a in articles if _dec(a["actual_material_cost"]) > _dec(a["planned_material_cost"])]
        causes.append({
            "cause": "Selisih pemakaian/harga material aktual vs rencana BOM",
            "detail": f"Total selisih material {_num(material_gap)}. Pemicu pada artikel: " +
                      (", ".join(f"{a['article_code']} ({_num(_dec(a['actual_material_cost']) - _dec(a['planned_material_cost']))})"
                                 for a in heavy) if heavy else "— (pemakaian di bawah rencana)"),
            "owner": "COO_MANAGER",
            "evidence": sorted({e["source_ref"] for a in articles for e in a["evidence"]
                                if e["source"] == "material_consumptions"}),
        })
    labor = sum((_dec(a["actual_labor_overhead_cost"]) for a in articles), Decimal(0))
    if labor:
        causes.append({
            "cause": "Upah langsung & overhead produksi aktual",
            "detail": f"Total {_num(labor)} dari production_cost_entries; tidak ada padanannya di quotation "
                      "sehingga masuk sebagai selisih yang harus diklasifikasi CFO.",
            "owner": "CFO_MANAGER",
            "evidence": sorted({e["source_ref"] for a in articles for e in a["evidence"]
                                if e["source"] == "production_cost_entries"}),
        })
    missing = [a["article_code"] for a in articles if not a["material_usage_complete"]]
    if missing:
        causes.append({
            "cause": "Pemakaian material belum lengkap",
            "detail": "Artikel belum memiliki pemakaian untuk seluruh item BOM: " + ", ".join(missing),
            "owner": "COO_MANAGER",
            "evidence": [],
            "traceable": False,
        })
    if order_variance["direction"] == "OVER" and not reviewed:
        causes.append({
            "cause": "Biaya aktual melebihi HPP quotation",
            "detail": f"Selisih {order_variance['variance']} ({order_variance['variance_percent'] or '—'}%). "
                      "Wajib ditelusuri sebelum nilai finansial dikunci.",
            "owner": "CFO_MANAGER",
            "evidence": [],
            "traceable": True,
        })
    for cause in causes:
        cause.setdefault("traceable", True)
    return causes


# --- endpoint 1: actual cost vs HPP ----------------------------------------


@router.get("/actual-cost-variance")
def actual_cost_variance(
    status: str = Query("ALL", pattern="^(ALL|OVER|UNDER|ON_TRACK|NO_DATA)$"),
    order_fk: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Estimated (HPP quotation) vs HPP aktual per Order ID + Article ID.

    HPP aktual = pemakaian material nyata + upah/overhead produksi nyata. Angka
    quotation hanya dipakai sebagai pembanding, tidak pernah sebagai nilai aktual.
    """
    _require_view(user)
    if date_from or date_to:
        _require_filter(user)
    if order_fk is not None:
        order = db.get(m.Order, order_fk)
        if order is None:
            raise HTTPException(404, "Order not found")
        orders = [order]
    else:
        orders = db.query(m.Order).order_by(m.Order.id.asc()).all()

    reviews = {row.order_fk: row for row in db.query(m.CostReview).all()}
    rows = []
    for order in orders:
        costs = sum(1 for a in order.articles
                    for _ in db.query(m.ProductionCostEntry).filter_by(article_id=a.id).all())
        quote = _approved_quote(db, order.id)
        article_hpp = _quote_lines(quote)
        consumptions = 0
        for article in order.articles:
            consumptions += (db.query(m.MaterialConsumption)
                             .join(m.BOMItem, m.BOMItem.id == m.MaterialConsumption.bom_item_id)
                             .filter(m.BOMItem.article_id == article.id).count())
        has_data = bool(order.articles) and (consumptions > 0 or costs > 0)
        review = reviews.get(order.id)
        reviewed = bool(review and (not has_data or _dec(review.reviewed_total) == _dec(_actual_total_of(db, order))))
        row = build_variance_order(
            db, order,
            status="REVIEWED" if reviewed else ("OPEN" if has_data else "NO_DATA"),
            has_data=has_data, reviewed=reviewed, review=review,
            date_from=date_from, date_to=date_to)
        row["quotation_lines_matched"] = len(article_hpp)
        rows.append(row)

    if status != "ALL":
        rows = [row for row in rows if row["status"] == status or row["direction"] == status]
    if date_from is not None:
        rows = [row for row in rows if row["order_date"] and row["order_date"] >= date_from.isoformat()]
    if date_to is not None:
        rows = [row for row in rows if row["order_date"] and row["order_date"] <= date_to.isoformat()]
    rows = rows[:limit]

    totals = {
        "orders": len(rows),
        "orders_with_actual": sum(1 for row in rows if row["has_actual_data"]),
        "orders_without_actual": sum(1 for row in rows if not row["has_actual_data"]),
        "quotation_hpp": _num(sum((_dec(row["quotation_hpp"]) for row in rows), Decimal(0))),
        "actual_total_cost": _num(sum((_dec(row["actual"]) for row in rows), Decimal(0))),
        "actual_material_cost": _num(sum((_dec(row["actual_material_cost"]) for row in rows), Decimal(0))),
        "variance": _num(sum((_dec(row["variance"]) for row in rows), Decimal(0))),
        "over_count": sum(1 for row in rows if row["direction"] == "OVER"),
        "under_count": sum(1 for row in rows if row["direction"] == "UNDER"),
        "on_track_count": sum(1 for row in rows if row["direction"] == "ON_TRACK"),
        "reviewed_count": sum(1 for row in rows if row["review"]["reviewed"]),
    }
    totals["variance_percent"] = _pct(totals["variance"], totals["quotation_hpp"])

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "basis": {
            "actual_source": ["material_consumptions", "production_cost_entries"],
            "estimated_source": "quotations (status APPROVED)",
            "rule": "HPP aktual dihitung dari pemakaian & biaya nyata; angka quotation hanya pembanding.",
            "cfo_boundary": "CFO mengklasifikasi, merekonsiliasi, mengunci nilai — tidak mengubah fakta produksi.",
            "correction": "Koreksi lewat adjustment/version dengan alasan di modul operasional, bukan menimpa riwayat.",
        },
        "filters": {"status": status, "order_fk": order_fk,
                    "date_from": _iso(date_from), "date_to": _iso(date_to), "limit": limit},
        "totals": totals,
        "orders": rows,
    }


def _actual_total_of(db, order):
    """Total HPP aktual satu order tanpa membangun baris penuh (dipakai status)."""
    total = Decimal(0)
    rows = (db.query(m.MaterialConsumption, m.BOMItem)
            .join(m.BOMItem, m.BOMItem.id == m.MaterialConsumption.bom_item_id)
            .join(m.Article, m.Article.id == m.BOMItem.article_id)
            .filter(m.Article.order_fk == order.id).all())
    for usage, _item in rows:
        total += _dec(usage.qty) * _dec(usage.actual_unit_cost)
    entries = (db.query(m.ProductionCostEntry)
               .join(m.Article, m.Article.id == m.ProductionCostEntry.article_id)
               .filter(m.Article.order_fk == order.id).all())
    for entry in entries:
        bucket, _normalized, _reason = classify_category(entry.category)
        if bucket == "HPP_PRODUCTION":
            total += _dec(entry.amount)
    return total


# --- endpoint 2: operational cost ------------------------------------------


def _bucket_rows(rows, key_fn, label_fn=None):
    """Kelompokkan baris ledger (dict) atau ORM menjadi beberapa keranjang nominal."""
    buckets = OrderedDict()
    for row in rows:
        key = key_fn(row)
        if key not in buckets:
            buckets[key] = {"key": key, "label": label_fn(row) if label_fn else key,
                            "entry_count": 0, "amount": Decimal(0)}
        buckets[key]["entry_count"] += 1
        buckets[key]["amount"] += row["amount"] if isinstance(row, dict) else _dec(row.amount)
    ordered = sorted(buckets.values(), key=lambda item: item["key"])
    for item in ordered:
        item["amount"] = _num(item["amount"])
    return ordered


@router.get("/operational-cost")
def operational_cost(
    period: str = Query("month", pattern="^(month|quarter|year|all)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Ringkasan biaya operasional per periode & kategori, terpisah dari HPP.

    HPP produksi (material aktual + upah/overhead direct) dihitung ulang dari
    fakta operasional. Biaya di luar HPP: pembelian material (purchase orders),
    biaya non-produksi yang tercatat di production_cost_entries, dan register
    biaya operasional formal bila tabelnya sudah tersedia.
    """
    _require_view(user)
    if date_from or date_to:
        _require_filter(user)

    def in_window(value):
        day = _day(value)
        if day is None:
            return False
        if date_from is not None and day < date_from:
            return False
        if date_to is not None and day > date_to:
            return False
        return True

    def period_key(value):
        day = _day(value)
        if isinstance(value, str) and value:
            try:
                day = date.fromisoformat(value[:10])
            except ValueError:
                day = None
        if day is None:
            return "UNKNOWN"
        if period == "all":
            return "ALL"
        if period == "year":
            return f"{day.year}"
        if period == "quarter":
            return f"{day.year}-Q{(day.month - 1) // 3 + 1}"
        return f"{day.year}-{day.month:02d}"

    def default_window():
        """Periode berjalan bila CFO tidak memilih rentang."""
        today = date.today()
        if period == "month":
            return date(today.year, today.month, 1), today
        if period == "quarter":
            start_month = (today.month - 1) // 3 * 3 + 1
            return date(today.year, start_month, 1), today
        if period == "year":
            return date(today.year, 1, 1), today
        return None, None

    if date_from is None and date_to is None:
        win_start, win_end = default_window()
    else:
        win_start, win_end = date_from, date_to

    def within_effective(value):
        day = _day(value)
        if day is None:
            return False
        if win_start is not None and day < win_start:
            return False
        if win_end is not None and day > win_end:
            return False
        return True

    # 1. HPP produksi: pemakaian material nyata.
    material_entries = []
    consumption_rows = (db.query(m.MaterialConsumption, m.BOMItem, m.Article, m.Order)
                        .join(m.BOMItem, m.BOMItem.id == m.MaterialConsumption.bom_item_id)
                        .join(m.Article, m.Article.id == m.BOMItem.article_id)
                        .join(m.Order, m.Order.id == m.Article.order_fk)
                        .order_by(m.MaterialConsumption.id.asc()).all())
    for usage, item, article, order in consumption_rows:
        if not within_effective(usage.created_at):
            continue
        material_entries.append({
            "kind": "PRODUCTION_COST",
            "category": "MATERIAL",
            "bucket": "HPP_PRODUCTION",
            "order_id": order.order_id,
            "article_code": article.article_code,
            "department": OPERATIONAL_DEPARTMENTS.get("COO_MANAGER", "Produksi & Operasional"),
            "description": f"Pemakaian {item.material_name} ({_qty(usage.qty)} {item.unit})",
            "amount": _dec(usage.qty) * _dec(usage.actual_unit_cost),
            "currency": "IDR",
            "source": "material_consumptions",
            "source_id": usage.id,
            "source_ref": usage.evidence_ref,
            "recorded_by_id": usage.recorded_by_id,
            "incurred_at": _iso(usage.created_at),
        })

    # 2. HPP produksi: upah/overhead direct + biaya non-produksi (dipisah).
    production_entries = (db.query(m.ProductionCostEntry, m.Article, m.Order, m.User)
                          .join(m.Article, m.Article.id == m.ProductionCostEntry.article_id)
                          .join(m.Order, m.Order.id == m.Article.order_fk)
                          .outerjoin(m.User, m.User.id == m.ProductionCostEntry.recorded_by_id)
                          .order_by(m.ProductionCostEntry.id.asc()).all())
    ledger = list(material_entries)
    unclassified = []
    for entry, article, order, recorder in production_entries:
        bucket, normalized, _reason = classify_category(entry.category)
        if not within_effective(entry.created_at):
            continue
        row = {
            "kind": "PRODUCTION_COST",
            "category": normalized or "(kosong)",
            "bucket": bucket,
            "order_id": order.order_id,
            "article_code": article.article_code,
            "department": OPERATIONAL_DEPARTMENTS.get(recorder.role.value if recorder else "COO_MANAGER",
                                                      "Produksi & Operasional"),
            "description": f"Biaya {normalized or 'tanpa kategori'} artikel {article.article_code}",
            "amount": _dec(entry.amount),
            "currency": "IDR",
            "source": "production_cost_entries",
            "source_id": entry.id,
            "source_ref": entry.evidence_ref,
            "recorded_by_id": entry.recorded_by_id,
            "incurred_at": _iso(entry.created_at),
        }
        ledger.append(row)
        if bucket == "UNCLASSIFIED":
            unclassified.append(row)

    # 3. Pembelian material (purchase orders) — di luar HPP; biaya dikenali saat
    #    PO diakui, bukan saat material dipakai. Hanya untuk kontrol, tidak
    #    pernah ditambahkan ke HPP aktual.
    po_rows = (db.query(m.PurchaseOrder)
               .filter(m.PurchaseOrder.status != "CANCELLED")
               .order_by(m.PurchaseOrder.id.asc()).all())
    purchase_rows = []
    for po in po_rows:
        if not within_effective(po.created_at):
            continue
        purchase_rows.append({
            "signal": "PURCHASE_ORDER_NOT_HPP",
            "po_no": po.po_no,
            "order_id": (db.get(m.Order, po.order_fk).order_id if po.order_fk else None),
            "supplier": po.supplier,
            "item": po.item,
            "status": po.status,
            "amount": _num(po.amount),
            "currency": "IDR",
            "incurred_at": _iso(po.created_at),
        })

    # 4. Register biaya operasional formal — tabel belum ada (lihat REQUESTS).
    register_available = hasattr(m, "OperationalCostEntry")
    register_rows = []
    if register_available:  # pragma: no cover - aktif otomatis setelah tabel dibuat
        for entry in db.query(m.OperationalCostEntry).order_by(m.OperationalCostEntry.id.asc()).all():
            if not within_effective(getattr(entry, "incurred_at", entry.created_at)):
                continue
            register_rows.append({
                "kind": "OPERATIONAL_COST_ENTRY",
                "category": entry.category,
                "bucket": "NON_HPP",
                "order_id": None,
                "article_code": None,
                "department": getattr(entry, "department", None),
                "description": getattr(entry, "description", None),
                "amount": _dec(entry.amount),
                "currency": getattr(entry, "currency", "IDR"),
                "source": "operational_cost_entries",
                "source_id": entry.id,
                "source_ref": getattr(entry, "evidence_ref", None),
                "recorded_by_id": None,
                "incurred_at": _iso(getattr(entry, "incurred_at", entry.created_at)),
            })
        ledger.extend(register_rows)

    hpp_rows = [row for row in ledger if row["bucket"] == "HPP_PRODUCTION"]
    non_hpp_rows = [row for row in ledger if row["bucket"] != "HPP_PRODUCTION"]

    hpp_total = sum((row["amount"] for row in hpp_rows), Decimal(0))
    hpp_material = sum((row["amount"] for row in hpp_rows if row["category"] == "MATERIAL"), Decimal(0))
    non_hpp_total = sum((row["amount"] for row in non_hpp_rows), Decimal(0))
    purchases_total = sum((_dec(row["amount"]) for row in purchase_rows), Decimal(0))

    periods = []
    by_period = OrderedDict()
    for row in ledger:
        by_period.setdefault(period_key(row["incurred_at"]), []).append(row)
    for key in sorted(by_period):
        rows = by_period[key]
        periods.append({
            "period": key,
            "hpp_total": _num(sum((r["amount"] for r in rows if r["bucket"] == "HPP_PRODUCTION"), Decimal(0))),
            "non_hpp_total": _num(sum((r["amount"] for r in rows if r["bucket"] != "HPP_PRODUCTION"), Decimal(0))),
            "entry_count": len(rows),
            "categories": _bucket_rows([r for r in rows if r["bucket"] != "HPP_PRODUCTION"],
                                       lambda r: r["category"]),
            "orders": sorted({r["order_id"] for r in rows if r["order_id"]}),
        })

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "window": {"date_from": _iso(win_start), "date_to": _iso(win_end)},
        "separation_rule": {
            "HPP_PRODUCTION": "Biaya direct yang menempel pada Order/Artikel (material terpakai, upah langsung, overhead produksi).",
            "NON_HPP": "OPEX perusahaan, aset/capex, advance, reimbursement, dan pembelian material (purchase order). Tidak pernah otomatis masuk HPP.",
            "UNCLASSIFIED": "Kategori belum dipetakan — ditahan di luar HPP sampai CFO mengklasifikasi.",
        },
        "totals": {
            "hpp_material": _num(hpp_material),
            "hpp_labor_overhead": _num(hpp_total - hpp_material),
            "hpp_total": _num(hpp_total),
            "non_hpp_total": _num(non_hpp_total),
            "operational_total": _num(non_hpp_total),
            "purchase_orders_not_hpp": _num(purchases_total),
            "unclassified_total": _num(sum((row["amount"] for row in unclassified), Decimal(0))),
            "entry_count": len(ledger),
        },
        "hpp_by_category": _bucket_rows(hpp_rows, lambda r: r["category"]),
        "operational_by_category": _bucket_rows(non_hpp_rows, lambda r: r["category"]),
        "operational_by_department": _bucket_rows(
            [row for row in non_hpp_rows if row["department"]],
            lambda r: r["department"],
            lambda r: r["department"]),
        "periods": periods,
        "classification": build_classification(
            db.query(m.ProductionCostEntry).order_by(m.ProductionCostEntry.id.asc()).all()),
        "operational_cost_register": {
            "available": register_available,
            "table": "operational_cost_entries",
            "required": not register_available,
            "request_ref": "REQUESTS/cfo_costing.md",
            "fields_supported": [
                "category", "department", "cost_center", "vendor_or_employee", "description",
                "amount", "currency", "fx_rate", "evidence_ref", "approval_status",
                "payment_status", "accounting_period", "classification",
                "order_fk", "article_id", "incurred_at", "reversal_of_id", "version",
            ],
            "entries": register_rows,
        },
        "purchase_orders_not_hpp": purchase_rows,
        "unclassified_entries": [
            {
                "source": row["source"], "source_id": row["source_id"], "category": row["category"],
                "order_id": row["order_id"], "amount": _num(row["amount"]),
                "source_ref": row["source_ref"], "incurred_at": row["incurred_at"],
            } for row in unclassified
        ],
        "ledger": [
            {**row, "amount": _num(row["amount"])} for row in ledger
        ],
    }
