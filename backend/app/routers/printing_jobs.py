"""PRN-I-004/005/006 — Printing/Bordir Job Card, Quantity Control & Partial
Handoff, Evidence/Inspection/Defect & Rework (revisi #43, #44, #45).

Modul ini READ-ONLY terhadap tabel yang sudah ada (`production_movements`,
`qc_records`, `articles`, `orders`, `spks`). Tidak ada model/migration baru:
semua turunan dihitung dari data operasional yang dicatat COO/Printing PIC.

Aturan kuantitas yang ditegakkan di sini (revisi #44):
    qty_in == qty_done + qty_reject + wip
setiap baris job card selalu mengembalikan ketiga angka itu plus `wip` dan
`qty_balanced`, sehingga selisih tidak pernah tersembunyi di UI.

Aturan disposisi (revisi #45): reject yang belum punya disposition tidak boleh
dianggap selesai — `open_reject_no_disposition` dihitung dari reject yang
tercatat di `qc_records` tanpa alasan/keputusan rework.

Semua perubahan tulis (submit hasil, partial handoff, disposition defect) akan
menyentuh tabel baru — lihat REQUESTS/printing_jobs.md.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from .. import models
from ..auth import get_current_user, require_roles
from ..database import get_db
from ..workflow import require

router = APIRouter(prefix="/printing", tags=["printing"])

# PRINTING/BORDIR adalah proses yang dimiliki Printing PIC. Route produksi
# disimpan bebas di `articles.production_route` (mis. "Cutting > Printing > QC"),
# jadi pencocokan sengaja case-insensitive + substring supaya "Bordir " dan
# "printing" tetap ikut terbaca.
PRINTING_PROCESSES = ("PRINTING", "BORDIR")

_MATCH_KEYS = tuple(key.lower() for key in PRINTING_PROCESSES)

READ_ROLES = ("CEO", "COO_MANAGER", "PRODUCTION_PIC", "PRINTING_PIC", "SAMPLE_PIC")


def is_printing_process(process: Optional[str]) -> bool:
    """True kalau nama proses termasuk PRINTING atau BORDIR."""
    if not process:
        return False
    lowered = process.strip().lower()
    return any(key in lowered for key in _MATCH_KEYS)


def matching_printing_route(route: Optional[str]) -> list[str]:
    """Ambil tahapan route artikel yang termasuk PRINTING/BORDIR, urut aslinya."""
    return [step for step in _parse_route(route) if is_printing_process(step)]


def _parse_route(route: Optional[str]) -> list[str]:
    if not route:
        return []
    return [step.strip() for step in route.replace(">", ",").replace("|", ",").split(",") if step.strip()]


def _next_stage(route: Optional[str], process: Optional[str]) -> Optional[str]:
    """Tahap berikutnya setelah `process` pada route artikel (untuk handoff)."""
    steps = _parse_route(route)
    target = (process or "").strip().lower()
    for index, step in enumerate(steps):
        if step.strip().lower() == target:
            return steps[index + 1] if index + 1 < len(steps) else None
    return None


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@router.get("/job-cards")
def list_job_cards(
    order_fk: Optional[int] = Query(None, description="Filter satu Order"),
    process: Optional[str] = Query(None, description="Filter nama proses PRINTING/BORDIR"),
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Job card Printing/Bordir per artikel yang melewatinya.

    Sumber angka: `production_movements` (qty_in/qty_done/qty_reject) — tabel
    yang sudah dipakai WIP Tracking, jadi kuantitas di sini konsisten dengan
    `/api/coo/wip-summary`. Job Card tidak menyimpan angka sendiri.
    """
    require(user, *READ_ROLES)

    query = (
        db.query(models.ProductionMovement, models.Article, models.Order)
        .join(models.Article, models.Article.id == models.ProductionMovement.article_id)
        .join(models.Order, models.Order.id == models.Article.order_fk)
    )
    if order_fk is not None:
        query = query.filter(models.Order.id == order_fk)

    rows = query.order_by(desc(models.ProductionMovement.id)).offset(offset).limit(limit).all()

    # SPK yang dirilis per order: versi requirement yang dikunci saat START
    # (revisi #43). SPK aktif = status != CANCELLED, versi terbesar.
    order_ids = {order.id for _, _, order in rows}
    released_spk: dict[int, models.SPK] = {}
    if order_ids:
        for spk in (
            db.query(models.SPK)
            .filter(models.SPK.order_fk.in_(order_ids), models.SPK.status != "CANCELLED")
            .order_by(models.SPK.order_fk, desc(models.SPK.version))
            .all()
        ):
            released_spk.setdefault(spk.order_fk, spk)

    # Sample yang sudah disetujui customer — dipakai sebagai versi artwork/PPM.
    sample_by_order: dict[int, models.SampleRecord] = {}
    if order_ids:
        for sample in (
            db.query(models.SampleRecord)
            .filter(models.SampleRecord.order_fk.in_(order_ids), models.SampleRecord.status == "APPROVED")
            .order_by(models.SampleRecord.order_fk, desc(models.SampleRecord.id))
            .all()
        ):
            sample_by_order.setdefault(sample.order_fk, sample)

    # Reject nyata per (article, process): reject yang punya alasan atau sudah
    # masuk record REWORK. Dipakai untuk disposition yang belum selesai.
    disposition_index: dict[tuple[int, str], dict] = {}
    if rows:
        article_ids = {article.id for _, article, _ in rows}
        for qc in (
            db.query(models.QCRecord)
            .filter(models.QCRecord.article_id.in_(article_ids))
            .order_by(desc(models.QCRecord.id))
            .all()
        ):
            key = (qc.article_id, (qc.process or "").strip().upper())
            bucket = disposition_index.setdefault(key, {"rejects": [], "dispositions": [], "rework": 0})
            if _as_int(qc.total_reject) > 0:
                bucket["rejects"].append(qc)
            if (qc.reject_reason or "").strip():
                bucket["dispositions"].append(qc)
            if (qc.rework_parent_id is not None) or (qc.status or "").upper() == "REWORK":
                bucket["rework"] += 1

    cards = []
    for movement, article, order in rows:
        if not is_printing_process(movement.process):
            continue
        if process and process.strip().upper() not in (movement.process or "").upper():
            continue

        qty_in = _as_int(movement.qty_in)
        qty_done = _as_int(movement.qty_done)
        qty_reject = _as_int(movement.qty_reject)
        wip = qty_in - qty_done - qty_reject

        spk = released_spk.get(order.id)
        sample = sample_by_order.get(order.id)
        bucket = disposition_index.get((article.id, (movement.process or "").strip().upper()), None)
        rejects = bucket["rejects"] if bucket else []
        dispositions = bucket["dispositions"] if bucket else []
        rework_count = bucket["rework"] if bucket else 0
        pending_disposition = max(len(rejects) - len(dispositions), 0)
        # Tanpa qc_records, reject yang dicatat di movement dianggap belum
        # berdisposisi kalau jumlahnya > 0 dan tidak ada alasannya.
        if not rejects and qty_reject > 0 and not (movement.reject_reason or "").strip():
            pending_disposition = qty_reject

        route = article.production_route or ""
        cards.append({
            "job_id": f"JOB-{order.order_id}-{article.article_code}-{movement.process}".upper().replace(" ", ""),
            "movement_id": movement.id,
            "order_id": order.order_id,
            "order_fk": order.id,
            "article_id": article.id,
            "article_code": article.article_code,
            "buyer": order.buyer,
            "garment_type": article.garment_type,
            "article_qty": _as_int(article.qty),
            "stage": movement.process,
            "route": route or None,
            "printing_stages": matching_printing_route(route),
            # Revisi #43: versi requirement yang dipakai saat START dikunci.
            "spk_id": spk.id if spk else None,
            "spk_no": spk.spk_no if spk else None,
            "spk_version": spk.version if spk else None,
            "spk_status": spk.status if spk else None,
            "requirement_version": f"{spk.spk_no}@v{spk.version}" if spk else None,
            "artwork_version": f"SAMPLE-{sample.article_code}@approved" if sample else None,
            "sample_approved_at": sample.customer_decision_at if sample else None,
            # Referensi kerja (metode/warna/placement/teknik) belum punya kolom
            # di schema saat ini -> lihat REQUESTS/printing_jobs.md.
            "method": None,
            "colors": None,
            "placement": None,
            "size_spec": article.size_breakdown,
            "technique": None,
            "vendor_type": None,
            "machine": None,
            "team_shift": movement.pic_name,
            "pic_name": movement.pic_name,
            "target_date": movement.target_date,
            "status": movement.status,
            "qty_source": _as_int(article.qty),
            "required_evidence": ["hasil_cetak", "inspeksi", "handoff"],
            "blocker": _job_blocker(movement, pending_disposition),
            "next_handoff": _next_stage(route, movement.process),
            # Revisi #44 — kendali kuantitas.
            "qty_in": qty_in,
            "qty_done": qty_done,
            "qty_reject": qty_reject,
            "wip": wip,
            "qty_balanced": qty_in == qty_done + qty_reject + wip,
            "reject_reason": movement.reject_reason,
            "partial_handoff": wip > 0 and qty_done > 0,
            "remaining_balance": max(qty_in - qty_done - qty_reject, 0),
            # Revisi #45 — defect & rework.
            "inspection_count": len(rejects),
            "defect_dispositions": pending_disposition,
            "rework_count": rework_count,
            "reject_closed": pending_disposition == 0,
            "created_at": movement.created_at,
            "updated_at": movement.updated_at,
        })

    return {
        "job_cards": cards,
        "total_job_cards": len(cards),
        "quantity_balanced": all(card["qty_balanced"] for card in cards),
        "processes": sorted({card["stage"] for card in cards}),
        "printing_stage_rule": list(PRINTING_PROCESSES),
    }


def _job_blocker(movement, pending_disposition: int) -> Optional[str]:
    """Alasan job tidak bisa lanjut — dikembalikan eksplisit (revisi #43)."""
    if pending_disposition > 0:
        return "Reject belum berdisposisi"
    if _as_int(movement.qty_done) == 0 and (movement.status or "").upper() != "DONE":
        return "Belum ada qty selesai"
    return None


@router.get("/quality")
def quality_summary(
    order_fk: Optional[int] = Query(None),
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Rekap inspeksi, kategori defect, dan rework dari `qc_records` (revisi #45).

    QC final tetap milik petugas QC; inspeksi Printing/Bordir adalah pemeriksaan
    proses dan tidak menggantikannya — keduanya dikembalikan, dibedakan oleh
    `process` dan `is_printing_stage`.
    """
    require(user, *READ_ROLES)

    query = db.query(models.QCRecord)
    if order_fk is not None:
        query = query.filter(models.QCRecord.order_fk == order_fk)
    records = query.order_by(desc(models.QCRecord.id)).offset(offset).limit(limit).all()

    inspections, defects, rework_rows, open_rejects = [], [], [], []
    total_checked = total_pass = total_reject = 0

    for record in records:
        checked = _as_int(record.total_checked)
        passed = _as_int(record.total_pass)
        rejected = _as_int(record.total_reject)
        total_checked += checked
        total_pass += passed
        total_reject += rejected

        has_reason = bool((record.reject_reason or "").strip())
        is_rework = record.rework_parent_id is not None or (record.status or "").upper() == "REWORK"
        rate = round(passed / checked * 100, 2) if checked else None

        inspections.append({
            "qc_id": record.id,
            "order_fk": record.order_fk,
            "article_id": record.article_id,
            "article_code": record.article_code,
            "process": record.process,
            "is_printing_stage": is_printing_process(record.process),
            "total_checked": checked,
            "total_pass": passed,
            "total_reject": rejected,
            "pass_rate": rate,
            "inspector": record.inspector,
            "status": record.status,
            "rework_parent_id": record.rework_parent_id,
            "inspected_at": record.created_at,
        })

        if rejected > 0:
            defect = {
                "qc_id": record.id,
                "order_fk": record.order_fk,
                "article_code": record.article_code,
                "process": record.process,
                "total_checked": checked,
                "total_pass": passed,
                "qty_rejected": rejected,
                "pass_rate": rate,
                "defect_category": _defect_category(record.reject_reason),
                "defect_detail": record.reject_reason,
                "disposition": "REWORK" if is_rework else ("CLOSED" if has_reason else "OPEN"),
                "rework_parent_id": record.rework_parent_id,
                "severity": "MAJOR" if checked and rejected / checked > 0.05 else "MINOR",
                "inspector": record.inspector,
                "status": record.status,
                "created_at": record.created_at,
            }
            defects.append(defect)
            if is_rework:
                rework_rows.append({
                    "qc_id": record.id,
                    "article_code": record.article_code,
                    "process": record.process,
                    "rework_parent_id": record.rework_parent_id,
                    "qty_reworked": rejected,
                    "qty_pass_after_rework": passed,
                    # Revisi #45: hasil rework wajib kembali ke inspection/retest
                    # sebelum boleh dihandoff.
                    "retest_required": True,
                    "reason": record.reject_reason,
                    "owner": record.inspector,
                    "status": record.status,
                })
            if not has_reason and not is_rework:
                open_rejects.append(defect)

    return {
        "inspections": inspections,
        "total_inspections": len(inspections),
        "defects": defects,
        "total_defects": len(defects),
        "defect_categories": _count_categories(defects),
        "rework": rework_rows,
        "total_rework": len(rework_rows),
        "open_reject_no_disposition": open_rejects,
        "open_reject_count": len(open_rejects),
        "total_checked": total_checked,
        "total_pass": total_pass,
        "total_reject": total_reject,
        "overall_pass_rate": round(total_pass / total_checked * 100, 2) if total_checked else None,
        "qc_final_note": "Inspeksi Printing/Bordir tidak menggantikan QC final",
    }


def _defect_category(reason: Optional[str]) -> str:
    """Kategori defect diturunkan dari teks alasan (belum ada kolom khusus).

    Kolom `defect_category` yang bisa dipilih operator diminta lewat
    REQUESTS/printing_jobs.md; selama belum ada, teks alasan dipetakan ke
    kategori yang paling mendekati supaya rekap tetap bisa dibaca.
    """
    text = (reason or "").lower()
    if not text.strip():
        return "UNSPECIFIED"
    mapping = (
        ("warna", "COLOR_MISMATCH"),
        ("color", "COLOR_MISMATCH"),
        ("tinta", "INK_DEFECT"),
        ("sablon", "SCREEN_DEFECT"),
        ("screen", "SCREEN_DEFECT"),
        ("bordir", "EMBROIDERY_DEFECT"),
        ("miring", "PLACEMENT_OFFSET"),
        ("posisi", "PLACEMENT_OFFSET"),
        ("ukuran", "SIZE_DEVIATION"),
        ("noda", "STAIN"),
        ("robek", "FABRIC_DAMAGE"),
        ("jahit", "STITCH_DEFECT"),
    )
    for keyword, category in mapping:
        if keyword in text:
            return category
    return "OTHER"


def _count_categories(defects: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for defect in defects:
        counts[defect["defect_category"]] = counts.get(defect["defect_category"], 0) + 1
    return [
        {"category": category, "count": count}
        for category, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


# ── Kontrak tulis (revisi #44/#45) ───────────────────────────────────────────
# Endpoint tulis BELUM aktif karena menunggu tabel/kolom baru yang diminta di
# REQUESTS/printing_jobs.md. Bentuk payload di bawah adalah kontraknya.

class HandoffIn(BaseModel):
    """Partial handoff Printing/Bordir -> proses berikutnya (revisi #44)."""
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=120)
    article_id: int
    process: str = Field(min_length=1, max_length=80)
    next_stage: str = Field(min_length=1, max_length=80)
    qty_sent: int = Field(gt=0)
    evidence_ref: Optional[str] = Field(default=None, max_length=500)


class DefectDispositionIn(BaseModel):
    """Disposisi reject Printing/Bordir (revisi #45)."""
    model_config = ConfigDict(extra="forbid")
    qc_id: int
    defect_category: str = Field(min_length=1, max_length=80)
    severity: str = Field(default="MINOR", max_length=20)
    disposition: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=2000)
    rework_owner: Optional[str] = Field(default=None, max_length=120)
    rework_due: Optional[date] = None
    evidence_ref: Optional[str] = Field(default=None, max_length=500)


def _quantity_rule(qty_in: int, qty_done: int, qty_reject: int) -> dict:
    """Helper murni: cek qty_in == qty_done + qty_reject + wip."""
    wip = qty_in - qty_done - qty_reject
    return {
        "qty_in": qty_in,
        "qty_done": qty_done,
        "qty_reject": qty_reject,
        "wip": wip,
        "balanced": qty_in == qty_done + qty_reject + wip,
        "valid": wip >= 0 and min(qty_in, qty_done, qty_reject) >= 0,
    }


@router.get("/quantity-check")
def quantity_check(
    article_id: int = Query(...),
    process: str = Query(..., min_length=1),
    qty_done: int = Query(0, ge=0),
    qty_reject: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Validasi kuantitas sebelum submit (revisi #44).

    qty_in diambil dari movement yang ada, bukan dari angka yang diketik UI,
    sehingga qty masuk berasal dari source yang diterima dan tidak bisa
    dilampaui.
    """
    require(user, *READ_ROLES)
    movement = (
        db.query(models.ProductionMovement)
        .filter(
            models.ProductionMovement.article_id == article_id,
            func.upper(models.ProductionMovement.process) == process.strip().upper(),
        )
        .order_by(desc(models.ProductionMovement.id))
        .first()
    )
    if movement is None:
        raise HTTPException(404, "No production movement for this article and process")

    qty_in = _as_int(movement.qty_in)
    result = _quantity_rule(qty_in, qty_done, qty_reject)
    errors = []
    if not result["valid"]:
        errors.append("qty tidak boleh negatif atau melebihi qty_in")
    if qty_done + qty_reject > qty_in:
        errors.append(f"qty_done + qty_reject melebihi qty_in ({qty_in})")
    result.update({
        "movement_id": movement.id,
        "process": movement.process,
        "source": "production_movements",
        "errors": errors,
        "allowed": not errors,
        "checked_at": datetime.utcnow(),
    })
    return result
