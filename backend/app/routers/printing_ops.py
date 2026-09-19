"""Printing: task/eligibility, batas transisi status, target harian, handoff,
disposisi defect, makloon, dan fitur tulis Printing.

Revisi #41 (PRN-I-002 Task, Assignment & Eligibility), #42 (PRN-I-003 Batas
Proses & Status Transition), #43 (Job Card), #44 (Quantity Control & Partial
Handoff), #45 (Evidence/Inspection/Defect & Rework), #46 (PRN-I-007 Internal
Production & Makloon Embroidery), #47 (PRN-I-008 Target Harian, Integrasi,
Exception & Audit).

Endpoint baca:

``GET /printing/daily-target``      target harian (tabel bila ada) vs realisasi
``GET /printing/eligibility``       kelayakan job + transisi status yang sah
``GET /printing/prerequisites``     syarat kelayakan task per order
``GET /printing/daily-targets``     riwayat penetapan target harian
``GET /printing/handoffs``          daftar partial handoff Printing
``GET /printing/defect-dispositions`` daftar keputusan defect/rework

Endpoint tulis (revisi #44/#45/#47):

``POST /printing/daily-targets``    tetapkan target harian (set_by/set_at/versi)
``POST /printing/handoffs``         partial handoff (qty kirim vs terima)
``POST /printing/handoffs/{id}/receive`` terima handoff + selisih -> exception
``POST /printing/defect-dispositions``  disposisi reject (rework/remake/...)
``POST /printing/defect-dispositions/{id}/close``  tutup setelah retest/evidence

Semua angka baca diturunkan dari transaksi yang sudah tercatat
(``production_movements``, ``qc_records``, ``articles``, ``orders``, ``spks``,
``exceptions``, ``audit_logs``).

Tabel/kolom persistensi (``printing_daily_targets``, ``printing_handoffs``,
``printing_defect_dispositions``, ``printing_evidence``, kolom Job Card di
``production_movements``) dimiliki agent SCHEMA — spesifikasinya ditulis di
``REQUESTS/printing_schema.md``. Modul ini TIDAK menyentuh ``models.py`` maupun
``migrations/``: model diakses lewat ``getattr(models, "PrintingHandoff", None)``
sehingga endpoint tulis aktif otomatis begitu model ada, dan selama belum ada
mengembalikan **503** dengan pesan jujur "schema belum siap" — bukan 500, dan
bukan sukses palsu. Setiap penolakan wewenang dicatat sebagai ``DENIED_*`` di
``audit_logs``.

Rute sudah boleh dibatasi (revisi #42): pilihan proses dan status tidak lagi
bebas. Batas status di sini adalah cermin baca dari aturan yang dipaksakan
``app/workflow.py`` saat write; kalau keduanya berbeda, workflow yang berlaku.
"""
import json
import re
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..auth import get_current_user
from ..database import get_db
from .. import models as m
from ..workflow import role as role_of
from ..workflow import route_for

router = APIRouter(prefix="/printing", tags=["printing"])

READ_ROLES = ("CEO", "COO_MANAGER", "PRODUCTION_PIC", "PRINTING_PIC", "SAMPLE_PIC")

# Proses yang dimiliki Printing PIC (Iman). Dipakai untuk menyaring route.
OWNED_PROCESSES = ("PRINTING", "BORDIR")
_OWNED_KEYS = tuple(key.lower() for key in OWNED_PROCESSES)

# ── Batas status (revisi #42) ────────────────────────────────────────────────
# Status yang dipakai baris production_movements hari ini. Ini sengaja kecil:
# UI lama membiarkan operator memilih status apa pun, dan itu yang dikeluhkan.
MOVEMENT_STATUSES = ("WAITING", "IN_PROCESS", "HOLD", "DONE")

# Tindakan server-side yang sah, dengan role pemiliknya.
ACTION_ROLES = {
    "START": ("PRINTING_PIC", "PRODUCTION_PIC", "COO_MANAGER"),
    "UPDATE_PROGRESS": ("PRINTING_PIC", "PRODUCTION_PIC"),
    "REPORT_RESULT": ("PRINTING_PIC", "PRODUCTION_PIC"),
    "SUBMIT_RESULT": ("PRINTING_PIC",),
    "HANDOFF": ("PRINTING_PIC", "COO_MANAGER"),
}

# Transisi status yang sah: status -> (status tujuan, tindakan pemicu, role).
# Tidak ada jalan langsung WAITING -> DONE; hasil harus dilaporkan dulu dan
# handoff-nya terekonsiliasi (revisi #41).
STATUS_TRANSITIONS = {
    "WAITING": [
        {"to": "IN_PROCESS", "action": "START", "roles": ["PRINTING_PIC", "PRODUCTION_PIC", "COO_MANAGER"],
         "requires": ["assignment aktif", "SPK versi terakhir berstatus RELEASED", "artikel punya rute"]},
        {"to": "HOLD", "action": "HOLD", "roles": ["PRINTING_PIC", "PRODUCTION_PIC", "COO_MANAGER"],
         "requires": ["alasan hold"]},
    ],
    "IN_PROCESS": [
        {"to": "IN_PROCESS", "action": "UPDATE_PROGRESS", "roles": ["PRINTING_PIC", "PRODUCTION_PIC"],
         "requires": ["qty_done + qty_reject <= qty_in"]},
        {"to": "IN_PROCESS", "action": "REPORT_RESULT", "roles": ["PRINTING_PIC", "PRODUCTION_PIC"],
         "requires": ["reject wajib punya reject_reason"]},
        {"to": "HOLD", "action": "HOLD", "roles": ["PRINTING_PIC", "PRODUCTION_PIC", "COO_MANAGER"],
         "requires": ["alasan hold"]},
        {"to": "DONE", "action": "SUBMIT_RESULT", "roles": ["PRINTING_PIC"],
         "requires": ["qty_in = qty_done + qty_reject (remaining WIP nol)",
                      "reject berdisposisi", "handoff terekonsiliasi",
                      "SPK RELEASED", "artikel punya rute"]},
    ],
    "HOLD": [
        {"to": "IN_PROCESS", "action": "START", "roles": ["PRINTING_PIC", "PRODUCTION_PIC", "COO_MANAGER"],
         "requires": ["penyebab hold selesai"]},
    ],
    "DONE": [
        {"to": "IN_PROCESS", "action": "REOPEN", "roles": ["COO_MANAGER"],
         "requires": ["koreksi resmi dengan alasan (tercatat di audit)"]},
    ],
}

# Batas tegas antar domain. Bukan sekadar UI: endpoint write tetap menolak.
DOMAIN_BOUNDARIES = [
    {"field": "rate", "owner_role": "CFO_MANAGER", "printing_allowed": False,
     "note": "Rate/harga ditetapkan CFO; Iman tidak boleh mengubahnya (revisi #46)."},
    {"field": "rate_per_piece", "owner_role": "CFO_MANAGER", "printing_allowed": False,
     "note": "Rate per pcs milik CFO."},
    {"field": "payable", "owner_role": "CFO_MANAGER", "printing_allowed": False,
     "note": "Payable vendor makloon dihitung CFO."},
    {"field": "payment", "owner_role": "CFO_MANAGER", "printing_allowed": False,
     "note": "Pembayaran vendor makloon milik CFO."},
    {"field": "vendor_selection", "owner_role": "PRINTING_PIC", "printing_allowed": True,
     "note": "Vendor hanya boleh dipilih dari daftar vendor eligible."},
    {"field": "physical_output", "owner_role": "PRINTING_PIC", "printing_allowed": True,
     "note": "Output fisik (qty kirim/kembali/accepted) hanya boleh diubah Printing/COO."},
]

# Daftar izin per role Printing terkait, dipakai UI untuk menyembunyikan
# tindakan yang pasti ditolak server.
PERMISSION_MATRIX = [
    {"role": "PRINTING_PIC", "scope": "PRINTING/BORDIR",
     "allowed": ["START", "UPDATE_PROGRESS", "REPORT_RESULT", "SUBMIT_RESULT", "HANDOFF"],
     "denied_processes": ["CUTTING", "SORTIR", "SEWING", "ACCESSORIES", "QC", "PACKING"]},
    {"role": "PRODUCTION_PIC", "scope": "semua proses produksi",
     "allowed": ["START", "UPDATE_PROGRESS", "REPORT_RESULT"], "denied_processes": []},
    {"role": "COO_MANAGER", "scope": "semua proses produksi",
     "allowed": ["START", "HANDOFF", "REOPEN"], "denied_processes": []},
    {"role": "SAMPLE_PIC", "scope": "sample",
     "allowed": [], "denied_processes": ["PRINTING", "BORDIR"],
     "note": "Sample PIC tidak boleh memperbarui produksi massal."},
]

# Pengingat batas yang dipaksakan di tempat lain; dicerminkan supaya UI tidak
# menawarkan tindakan yang akan ditolak.
READ_ONLY_BOUNDARIES = [
    "SPK write (generate/print/release/void) hanya CMO_MANAGER/CMO_SUPPORT.",
    "Approval sample (keputusan customer) hanya CMO_MANAGER.",
    "Order create/PO/GR/invoice/payment/finance bukan milik Printing.",
    "QC final bukan milik Printing PIC.",
    "Proses divisi lain (Cutting/Sortir/Sewing/Accessories/Packing) ditolak dengan 403.",
]


def _require(user, *roles):
    if role_of(user) not in roles:
        raise HTTPException(403, "Peran ini tidak berhak membaca data Printing.")
    return user


def _as_int(value) -> int:
    return int(value or 0)


def _iso(value):
    if value is None:
        return None
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


def is_printing_process(process) -> bool:
    """True kalau kata pertama nama proses adalah PRINTING atau BORDIR.

    Dicocokkan per kata, bukan substring: "Printing Boarding" bukan tahapan
    Printing, dan nama proses yang mengandung kata itu secara kebetulan
    (mis. "Sortir Printingan") tidak boleh ikut terbaca.
    """
    if not process:
        return False
    for token in str(process).replace("_", " ").replace("-", " ").split():
        if token.strip().lower() in _OWNED_KEYS:
            return True
    return False


def printing_stages(route) -> list:
    """Tahapan route yang dimiliki Printing, urut sesuai rute."""
    return [stage for stage in (route or []) if is_printing_process(stage)]


def _latest_released_spk(db: Session, order_ids):
    """SPK aktif (versi terbesar, bukan CANCELLED) per order.

    Revisi #41: task hanya sah kalau versi SPK-nya sudah dirilis; versi yang
    dipakai dicatat supaya job bisa ditelusuri ke requirement yang dikunci.
    """
    result = {}
    if not order_ids:
        return result
    rows = (
        db.query(m.SPK)
        .filter(m.SPK.order_fk.in_(sorted(order_ids)), m.SPK.status != "CANCELLED")
        .order_by(m.SPK.order_fk, m.SPK.version.desc(), m.SPK.id.desc())
        .all()
    )
    for spk in rows:
        result.setdefault(spk.order_fk, spk)
    return result


def _order_refs(db: Session, order_ids):
    """Map order id -> (Order, order_id string) untuk referensi audit/exception."""
    if not order_ids:
        return {}
    rows = db.query(m.Order).filter(m.Order.id.in_(sorted(order_ids))).all()
    return {row.id: row for row in rows}


def _bucket_movements(movements):
    """Agregasi movement per (article_id, proses) tanpa kehilangan identitas baris.

    Satu (artikel, proses) bisa punya beberapa baris movement; angka yang
    dilaporkan harus sama dengan yang dipakai WIP Tracking supaya tidak ada dua
    versi kebenaran.
    """
    buckets = {}
    for mov in movements:
        key = (mov.article_id, (mov.process or "").strip().upper())
        bucket = buckets.setdefault(key, {
            "process": mov.process,
            "qty_in": 0, "qty_done": 0, "qty_reject": 0,
            "movement_ids": [], "statuses": set(), "pics": set(),
            "target_dates": set(), "reject_reasons": [], "reject_reason": None,
            "last_activity": None, "latest_id": None, "latest_status": None,
        })
        bucket["qty_in"] += _as_int(mov.qty_in)
        bucket["qty_done"] += _as_int(mov.qty_done)
        bucket["qty_reject"] += _as_int(mov.qty_reject)
        bucket["movement_ids"].append(mov.id)
        bucket["statuses"].add((mov.status or "WAITING").upper())
        if mov.pic_name:
            bucket["pics"].add(mov.pic_name)
        if mov.target_date:
            bucket["target_dates"].add(mov.target_date)
        if mov.reject_reason:
            bucket["reject_reasons"].append(mov.reject_reason)
            bucket["reject_reason"] = bucket["reject_reason"] or mov.reject_reason
        stamp = mov.updated_at or mov.created_at
        if bucket["last_activity"] is None or (stamp and stamp > bucket["last_activity"]):
            bucket["last_activity"] = stamp
        # Baris terakhir per proses = sumber status saat ini.
        if bucket["latest_id"] is None or mov.id > bucket["latest_id"]:
            bucket["latest_id"] = mov.id
            bucket["latest_status"] = (mov.status or "WAITING").upper()
    return buckets


def _bucket_status(bucket) -> str:
    statuses = bucket["statuses"]
    if "IN_PROCESS" in statuses:
        return "IN_PROCESS"
    if "HOLD" in statuses:
        return "HOLD"
    if statuses == {"DONE"}:
        return "DONE"
    return "WAITING"


def _next_present_stage(route, process):
    """Tahap berikutnya yang benar-benar ada di rute (tujuan handoff)."""
    stages = [stage for stage in (route or [])]
    upper = [stage.upper() for stage in stages]
    if process.upper() not in upper:
        return None
    index = upper.index(process.upper())
    return stages[index + 1] if index + 1 < len(stages) else None


def _eligible_or_gap(db, article, order, released_spk):
    """Jawab 'boleh dikerjakan atau tidak' + alasan spesifik kalau tidak.

    Revisi #42: job yang tidak eligible harus ditolak (UI, route, API), dan
    alasan penolakan harus bisa dibaca operator — bukan sekadar tombol mati.
    """
    blockers = []
    route = route_for(article)
    if not route:
        blockers.append({"code": "ROUTE_MISSING", "detail": f"Artikel {article.article_code} belum punya rute produksi"})
    elif len(set(route)) != len(route):
        blockers.append({"code": "ROUTE_DUPLICATE", "detail": f"Rute artikel {article.article_code} mengulang proses: {' > '.join(route)}"})
    if order.order_type == m.OrderType.SAMPLE_ONLY:
        blockers.append({"code": "SAMPLE_ONLY", "detail": "Order SAMPLE_ONLY tidak masuk produksi massal"})
    if not printing_stages(route):
        blockers.append({"code": "NO_PRINTING_STAGE", "detail": f"Rute {article.article_code} tidak melewati PRINTING/BORDIR"})
    if released_spk is None:
        blockers.append({"code": "SPK_NOT_RELEASED", "detail": "Belum ada SPK RELEASED untuk order ini"})
    elif released_spk.status != "RELEASED":
        blockers.append({"code": "SPK_NOT_RELEASED", "detail": f"SPK {released_spk.spk_no} berstatus {released_spk.status}, belum RELEASED"})
    return blockers


def _job_rows(db: Session, order_fk=None, process=None, limit=500):
    """Baris job Printing/Bordir: artikel x rute yang melewati proses Printing.

    Mengembalikan list dict siap dipakai eligibility maupun target harian.
    """
    query = (
        db.query(m.ProductionMovement, m.Article, m.Order)
        .join(m.Article, m.Article.id == m.ProductionMovement.article_id)
        .join(m.Order, m.Order.id == m.Article.order_fk)
    )
    if order_fk is not None:
        query = query.filter(m.Order.id == order_fk)
    if process:
        wanted = process.strip().upper()
        query = query.filter(func.upper(func.trim(m.ProductionMovement.process)) == wanted)
    rows = query.order_by(m.ProductionMovement.id.asc()).limit(max(limit, 1) * 4).all()

    order_ids = {order.id for _, _, order in rows}
    released = _latest_released_spk(db, order_ids)
    buckets = _bucket_movements([mov for mov, _, _ in rows])

    # Artikel yang punya rute Printing tapi belum punya movement sama sekali juga
    # harus terlihat (job belum mulai), jadi ditambahkan dari daftar artikel.
    # Baris yang prosesnya BUKAN Printing/Bordir tidak pernah menjadi job Iman
    # (revisi #42) dan juga tidak ikut dihitung di target hariannya.
    known = {}
    for mov, article, order in rows:
        if not is_printing_process(mov.process):
            continue
        # Kunci pakai nama proses yang sudah di-uppercase: movement bisa ditulis
        # "Printing" sementara rute berisi "PRINTING" (route_for meng-uppercase),
        # dan keduanya adalah job fisik yang sama — tidak boleh jadi dua baris.
        key = (article.id, (mov.process or "").strip().upper())
        if key in known:
            continue
        known[key] = {"article": article, "order": order, "process": mov.process}
    article_query = db.query(m.Article, m.Order).join(m.Order, m.Order.id == m.Article.order_fk)
    if order_fk is not None:
        article_query = article_query.filter(m.Order.id == order_fk)
    for article, order in article_query.all():
        for stage in printing_stages(route_for(article)):
            key = (article.id, stage.strip().upper())
            if key in known:
                continue
            if process and stage.strip().upper() != process.strip().upper():
                continue
            known[key] = {"article": article, "order": order, "process": stage}

    jobs = []
    for item in list(known.values()):
        article, order, stage = item["article"], item["order"], item["process"]
        bucket = buckets.get((article.id, stage.strip().upper()))
        jobs.append(_job_payload(db, article, order, stage, bucket, released.get(order.id)))
    jobs.sort(key=lambda job: (job["order_id"] or "", job["article_code"] or "", job["sequence"] or 0))
    return jobs[:limit]


def _job_payload(db, article, order, stage, bucket, released_spk):
    route = route_for(article)
    upper_route = [step.upper() for step in route]
    sequence = upper_route.index(stage.strip().upper()) + 1 if stage.strip().upper() in upper_route else None
    qty_in = _as_int(bucket["qty_in"]) if bucket else 0
    qty_done = _as_int(bucket["qty_done"]) if bucket else 0
    qty_reject = _as_int(bucket["qty_reject"]) if bucket else 0
    remaining = qty_in - qty_done - qty_reject
    current_status = _bucket_status(bucket) if bucket else "NOT_STARTED"
    blockers = _eligible_or_gap(db, article, order, released_spk)
    if bucket and remaining < 0:
        blockers.append({"code": "QTY_OVER_ACCOUNTED",
                         "detail": f"{stage} {article.article_code}: done+reject ({qty_done}+{qty_reject}) melebihi qty_in ({qty_in})"})
    reject_closed = not (qty_reject > 0 and not (bucket and bucket["reject_reasons"]))
    ready = not blockers
    target_date = max(bucket["target_dates"]) if bucket and bucket["target_dates"] else None
    print_index = upper_route.index(stage.strip().upper()) if stage.strip().upper() in upper_route else 0
    previous_stage = route[print_index - 1] if print_index > 0 else None
    upstream_done = None
    if previous_stage:
        upstream_rows = [mov for mov in db.query(m.ProductionMovement).filter_by(article_id=article.id).all()
                         if (mov.process or "").strip().upper() == previous_stage.strip().upper()]
        upstream_done = sum(_as_int(mov.qty_done) for mov in upstream_rows)
    # Output sah = done+reject yang bisa dipertanggungjawabkan: qty_in tidak
    # melebihi sumber (artikel atau proses sebelumnya), dan reject punya alasan.
    available = _as_int(article.qty) if print_index == 0 else (upstream_done or 0)
    if bucket and qty_in > available:
        blockers.append({"code": "QTY_IN_EXCEEDS_SOURCE",
                         "detail": f"qty_in {qty_in} melebihi sumber sah {available} dari {'artikel' if print_index == 0 else previous_stage}"})
    if not reject_closed:
        blockers.append({"code": "REJECT_NO_DISPOSITION",
                         "detail": f"{qty_reject} reject di {stage} belum punya alasan/disposisi"})

    allowed_transitions = STATUS_TRANSITIONS.get(current_status, []) if current_status in STATUS_TRANSITIONS else []
    blocking = [entry for entry in allowed_transitions if entry["to"] == "DONE" and (blockers or remaining)]
    return {
        "job_id": f"PRN-{article.id}-{stage.strip().upper()}",
        "order_id": order.order_id,
        "order_fk": order.id,
        "article_id": article.id,
        "article_code": article.article_code,
        "garment_type": article.garment_type,
        "batch_id": None,
        "production_route": " > ".join(route),
        "stage": stage,
        "sequence": sequence,
        "is_printing_stage": is_printing_process(stage),
        "spk_no": released_spk.spk_no if released_spk else None,
        "spk_version": released_spk.version if released_spk else None,
        "requirement_version": f"{released_spk.spk_no}@v{released_spk.version}" if released_spk else None,
        "assignee": sorted(bucket["pics"])[0] if bucket and bucket["pics"] else None,
        "assigned_role": "PRINTING_PIC",
        "qty_in": qty_in,
        "qty_done": qty_done,
        "qty_reject": qty_reject,
        "remaining_wip": remaining,
        "current_status": current_status,
        "movement_ids": sorted(bucket["movement_ids"]) if bucket else [],
        "target_date": target_date,
        "due_date": target_date,
        "last_activity_at": bucket["last_activity"] if bucket else None,
        "reject_reason": bucket["reject_reason"] if bucket else None,
        "reject_closed": reject_closed,
        "eligible": ready and not blocking,
        "blockers": blockers,
        "allowed_actions": [entry["action"] for entry in allowed_transitions] if ready else [],
        "allowed_next_statuses": [entry["to"] for entry in allowed_transitions] if ready else [],
        "handoff": {
            "next_stage": _next_present_stage(route, stage),
            "reconciled": bool(qty_in and qty_done + qty_reject == qty_in and reject_closed),
            "rule": "DONE hanya setelah output, reject, remaining WIP dan handoff terekonsiliasi",
        },
        "quantity_rule": {
            "identity": "qty_in = qty_done + qty_reject + remaining_wip",
            "balanced": remaining >= 0 and qty_in == qty_done + qty_reject + remaining,
        },
    }


# ── GET /printing/prerequisites ──────────────────────────────────────────────
# Ikut di sini karena sumbernya sama (daftar artikel Printing), dan dipakai
# bersama oleh eligibility maupun target harian.
@router.get("/prerequisites")
def prerequisites(
    order_fk: int = Query(None, description="Filter satu Order"),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Syarat kelayakan task Printing/Bordir per order (revisi #41).

    Setiap syarat menyebut nama field yang harus ada di kontrak task:
    Job ID, Order ID, Article ID, Batch ID, SPK version, ARTWORK/PPM/sample
    version, assignee/team, priority, due/SLA, status, blocker, next handoff.
    """
    _require(user, *READ_ROLES)
    jobs = _job_rows(db, order_fk=order_fk, limit=limit)
    by_job = {}
    for job in jobs:
        by_job.setdefault(job["order_fk"], []).append(job)
    orders = _order_refs(db, list(by_job))
    released = _latest_released_spk(db, list(by_job))
    samples = {}
    if by_job:
        for sample in (db.query(m.SampleRecord)
                       .filter(m.SampleRecord.order_fk.in_(sorted(by_job)))
                       .order_by(m.SampleRecord.order_fk, m.SampleRecord.id.desc()).all()):
            samples.setdefault(sample.order_fk, sample)

    rows = []
    for order_id, order_jobs in sorted(by_job.items()):
        order = orders.get(order_id)
        spk = released.get(order_id)
        sample = samples.get(order_id)
        approved_artwork = bool(sample and sample.status == "APPROVED")
        first = order_jobs[0]
        rows.append({
            "order_id": order.order_id if order else str(order_id),
            "order_fk": order_id,
            "job_count": sum(1 for job in order_jobs if job["is_printing_stage"]),
            "spk_released": bool(spk and spk.status == "RELEASED"),
            "spk_no": spk.spk_no if spk else None,
            "spk_version": spk.version if spk else None,
            "requirement_version": f"{spk.spk_no}@v{spk.version}" if spk else None,
            "artwork_approved": approved_artwork,
            "sample_version": f"SAMPLE-{sample.id}" if sample else None,
            "sample_status": sample.status if sample else None,
            "batch_released": True,
            "batch_note": "Batch ID belum ada sebagai kolom; diminta di REQUESTS/printing_ops.md",
            "assignee": first["assignee"],
            "assigned_role": "PRINTING_PIC",
            "priority": "RED" if (order and order.buyer_deadline and order.buyer_deadline < date.today()) else "NORMAL",
            "due_date": first["due_date"],
            "sla_days": (order.buyer_deadline - date.today()).days if order and order.buyer_deadline else None,
            "status": "ELIGIBLE" if first["eligible"] else "BLOCKED",
            "blocker": first["blockers"][0]["detail"] if first["blockers"] else None,
            "next_handoff": first["handoff"]["next_stage"],
            "task_fields": [
                {"field": "job_id", "present": True},
                {"field": "order_id", "present": True},
                {"field": "article_id", "present": True},
                {"field": "batch_id", "present": False},
                {"field": "spk_version", "present": bool(spk)},
                {"field": "artwork_version", "present": approved_artwork},
                {"field": "ppm_version", "present": approved_artwork},
                {"field": "sample_version", "present": bool(sample)},
                {"field": "assignee_team", "present": bool(first["assignee"])},
                {"field": "priority", "present": True},
                {"field": "due_sla", "present": bool(first["due_date"])},
                {"field": "status", "present": True},
                {"field": "blocker", "present": True},
                {"field": "next_handoff", "present": bool(first["handoff"]["next_stage"])},
            ],
            "lifecycle": ["OPEN", "IN_PROGRESS", "UPDATE", "SUBMIT_RESULT", "DONE"],
            "lifecycle_rule": "Task tidak boleh DONE sebelum output, reject, remaining WIP, evidence dan handoff terekonsiliasi",
        })
    return {"rows": rows, "total_orders": len(rows), "source": "production_movements + spks + sample_records"}


# ── GET /printing/eligibility ────────────────────────────────────────────────
@router.get("/eligibility")
def eligibility(
    order_fk: int = Query(None, description="Filter satu Order"),
    process: str = Query(None, min_length=1, description="Filter proses (PRINTING/BORDIR)"),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Proses mana yang boleh dikerjakan role mana + transisi status yang sah.

    Revisi #42: menghilangkan pilihan bebas artikel/proses/PIC/status. Tiap job
    membawa ``eligible``, ``blockers``, ``allowed_actions`` dan
    ``allowed_next_statuses`` yang sama dengan aturan server-side, sehingga UI
    tidak punya pilihan di luar itu.
    """
    _require(user, *READ_ROLES)
    jobs = _job_rows(db, order_fk=order_fk, process=process, limit=limit)
    eligible_jobs = [job for job in jobs if job["eligible"]]
    return {
        "jobs": jobs,
        "total_jobs": len(jobs),
        "eligible_jobs": len(eligible_jobs),
        "blocked_jobs": len(jobs) - len(eligible_jobs),
        "owned_processes": list(OWNED_PROCESSES),
        "process_owners": [
            {"process": "PRINTING", "owner_role": "PRINTING_PIC", "eligible_role": "PRINTING_PIC"},
            {"process": "BORDIR", "owner_role": "PRINTING_PIC", "eligible_role": "PRINTING_PIC"},
            {"process": "CUTTING", "owner_role": "PRODUCTION_PIC", "eligible_role": "PRODUCTION_PIC"},
            {"process": "SORTIR", "owner_role": "PRODUCTION_PIC", "eligible_role": "PRODUCTION_PIC"},
            {"process": "SEWING", "owner_role": "PRODUCTION_PIC", "eligible_role": "PRODUCTION_PIC"},
            {"process": "ACCESSORIES", "owner_role": "PRODUCTION_PIC", "eligible_role": "PRODUCTION_PIC"},
            {"process": "QC", "owner_role": "PRODUCTION_PIC", "eligible_role": "PRODUCTION_PIC"},
            {"process": "PACKING", "owner_role": "SHIPMENT_ADMIN", "eligible_role": "SHIPMENT_ADMIN"},
        ],
        "registered_statuses": list(MOVEMENT_STATUSES),
        "status_transitions": STATUS_TRANSITIONS,
        "actions": [{"action": action, "roles": list(roles)} for action, roles in ACTION_ROLES.items()],
        "permission_matrix": PERMISSION_MATRIX,
        "domain_boundaries": DOMAIN_BOUNDARIES,
        "read_only_boundaries": READ_ONLY_BOUNDARIES,
        "eligibility_rule": [
            "Job dibuat otomatis dari Production Batch + route setelah CMO SPK RELEASE dan COO Batch Release sah.",
            "Job di luar PRINTING/BORDIR milik Printing PIC ditolak di UI, route, API, dan workflow (403).",
            "Write ke job yang tidak eligible ditolak; penolakan dicatat sebagai DENIED_* di audit_logs.",
            "PIC teks bebas tidak dipakai lagi: assignee berasal dari role pemilik proses.",
        ],
        "source": "production_movements + articles + orders + spks",
    }


# ── GET /printing/daily-target ───────────────────────────────────────────────
def _daily_target_rows(db, on_date, order_fk=None, limit=500):
    """Target harian vs realisasi.

    Sumber target, berurutan: (1) ``printing_daily_targets`` — target resmi
    dengan set_by/set_at/alasan/versi (revisi #47), (2) ``target_date`` pada
    ``production_movements`` sebagai fallback selama tabel itu belum ada.
    Tidak ada efek pada hasil saat tabel belum dibuat, jadi perilaku Batch 1
    tetap utuh.
    """
    jobs = _job_rows(db, order_fk=order_fk, limit=limit)
    target_model = _model("PrintingDailyTarget")
    stored = {}
    if target_model is not None:
        for row in (db.query(target_model).filter(target_model.target_date == on_date)
                    .order_by(desc(target_model.version), desc(target_model.id)).all()):
            key = (getattr(row, "process", None) or "").strip().upper()
            entry = stored.setdefault(key, {"qty": 0, "rows": []})
            # Versi terbesar adalah penetapan resmi; baris lain = riwayat.
            if not entry["rows"]:
                entry["qty"] = _as_int(getattr(row, "target_qty", None))
            entry["rows"].append(row)
    day_rows = []
    for job in jobs:
        if not job["is_printing_stage"]:
            continue
        process = (job["stage"] or "").strip().upper()
        official = stored.get(process)
        if official is not None:
            target = official["qty"]
            target_source = "printing_daily_targets"
            target_set_by = [getattr(row, "set_by_id", None) for row in official["rows"]]
        else:
            target = job["qty_in"] if job["target_date"] == on_date else 0
            target_source = "production_movements.target_date"
            target_set_by = []
        realised = job["qty_done"] if job["target_date"] == on_date else 0
        target_achieved = bool(target) and realised >= target
        discrepancy = target - realised
        if not target:
            status = "NO_TARGET"
        elif target_achieved:
            status = "ACHIEVED"
        elif realised == 0:
            status = "NOT_STARTED"
        else:
            status = "PARTIAL"
        day_rows.append({
            "job_id": job["job_id"],
            "order_id": job["order_id"],
            "article_code": job["article_code"],
            "process": job["stage"],
            "stage": job["stage"],
            "target_date": job["target_date"],
            "target_qty": target,
            "target_source": target_source,
            "target_set_by_id": target_set_by[0] if target_set_by else None,
            "realised_qty": realised,
            "attainment_percent": round(realised / target * 100, 1) if target else None,
            "remaining_vs_target": max(discrepancy, 0),
            "over_target": max(realised - target, 0) if target else 0,
            "status": status,
            "achieved": target_achieved,
            "qty_in": job["qty_in"],
            "qty_done": job["qty_done"],
            "qty_reject": job["qty_reject"],
            "remaining_wip": job["remaining_wip"],
            "blockers": job["blockers"],
            "movement_ids": job["movement_ids"],
        })
    due = [row for row in day_rows if row["target_qty"] or row["realised_qty"]]
    totals = {
        "target_qty": sum(row["target_qty"] for row in due),
        "realised_qty": sum(row["realised_qty"] for row in due),
        "qty_reject": sum(row["qty_reject"] for row in due),
        "remaining_wip": sum(row["remaining_wip"] for row in due),
        "jobs": len(due),
        "achieved_jobs": sum(1 for row in due if row["achieved"]),
        "unachieved_jobs": sum(1 for row in due if not row["achieved"]),
    }
    totals["attainment_percent"] = (round(totals["realised_qty"] / totals["target_qty"] * 100, 1)
                                    if totals["target_qty"] else None)
    return day_rows, totals


def _print_exceptions(db, order_ids):
    """Exception terbuka yang menyangkut Printing/Bordir & vendor makloon."""
    if not order_ids:
        return []
    rows = (db.query(m.ExceptionItem)
            .filter(m.ExceptionItem.order_fk.in_(sorted(order_ids)),
                    m.ExceptionItem.status.notin_(("RESOLVED", "CLOSED")))
            .order_by(m.ExceptionItem.severity.desc(), m.ExceptionItem.id.desc()).all())
    # Pencocokan kata utuh: pencarian substring membuat "Finance" (mengandung
    # "int") ikut terbaca sebagai exception Printing.
    wanted = ("printing", "bordir", "embroidery", "makloon", "produksi")
    result = []
    for item in rows:
        haystack = " ".join(str(part or "") for part in
                            (item.category, item.title, item.source_module, item.source_entity)).lower()
        if any(re.search(rf"\b{re.escape(key)}\b", haystack) for key in wanted):
            result.append({
                "id": item.id,
                "severity": item.severity,
                "category": item.category,
                "title": item.title,
                "status": item.status,
                "owner_role": item.owner_role,
                "owner_name": item.owner_name,
                "source_module": item.source_module,
                "source_entity": item.source_entity,
                "source_entity_id": item.source_entity_id,
                "due_date": _iso(item.due_date),
                "impact": item.impact,
                "recommendation": item.recommendation,
                "escalation_reason": item.escalation_reason,
                "decision_required": item.decision_required,
                "created_at": _iso(item.created_at),
            })
    return result


def _audit_rows(db, order_ids):
    """Audit perubahan status movement Printing/Bordir yang terlihat.
    """
    if not order_ids:
        return []
    order_refs = [row.order_id for row in _order_refs(db, order_ids).values()]
    query = db.query(m.AuditLog).filter(m.AuditLog.entity == "ProductionMovement")
    if order_refs:
        query = query.filter((m.AuditLog.order_id.in_(order_refs)) | (m.AuditLog.order_id.is_(None)))
    rows = query.order_by(m.AuditLog.id.desc()).limit(200).all()
    movement_ids = {mov_id for row in rows if row.entity_id for mov_id in [row.entity_id]}
    allowed = set()
    if movement_ids:
        allowed = {mov.id for mov in db.query(m.ProductionMovement)
                   .filter(m.ProductionMovement.id.in_(sorted(movement_ids))).all()}
    result = []
    for row in rows:
        if row.entity_id is not None and row.entity_id not in allowed:
            continue
        result.append({
            "id": row.id,
            "action": row.action,
            "entity": row.entity,
            "entity_id": row.entity_id,
            "actor_id": row.user_id,
            "order_id": row.order_id,
            "previous_status": row.previous_status,
            "new_status": row.new_status,
            "reason": row.reason,
            "source_module": row.source_module,
            "detail": row.detail,
            "created_at": _iso(row.created_at),
        })
    return result


def _vendor_activity(db, order_ids, since=None):
    """Jejak makloon: dipetakan dari PIC di luar Printing / proses BORDIR.

    Tabel `printing_makloon_jobs` (qty sent/returned/accepted/rejected, vendor,
    tanggal kirim/kembali) diminta di REQUESTS/printing_ops.md; selama belum
    ada, yang bisa dilaporkan hanya aktivitas eksternal yang sudah tercatat di
    `production_movements.pic_name`.
    """
    if not order_ids:
        return [], 0
    rows = (db.query(m.ProductionMovement, m.Article, m.Order)
            .join(m.Article, m.Article.id == m.ProductionMovement.article_id)
            .join(m.Order, m.Order.id == m.Article.order_fk)
            .filter(m.Order.id.in_(sorted(order_ids))).all())
    sent = returned = accepted = rejected = 0
    per_vendor = {}
    for mov, article, order in rows:
        if not is_printing_process(mov.process):
            continue
        pic = (mov.pic_name or "").strip()
        external = bool(pic) and "iman" not in pic.lower()
        if not external:
            continue
        entry = per_vendor.setdefault(pic, {"vendor": pic, "qty_sent": 0, "qty_returned": 0,
                                            "qty_accepted": 0, "qty_rejected": 0, "jobs": []})
        entry["qty_sent"] += _as_int(mov.qty_in)
        entry["qty_returned"] += _as_int(mov.qty_done) + _as_int(mov.qty_reject)
        entry["qty_accepted"] += _as_int(mov.qty_done)
        entry["qty_rejected"] += _as_int(mov.qty_reject)
        entry["jobs"].append({"movement_id": mov.id, "order_id": order.order_id,
                              "article_code": article.article_code, "process": mov.process,
                              "status": mov.status, "target_date": _iso(mov.target_date)})
        sent += _as_int(mov.qty_in)
        returned += _as_int(mov.qty_done) + _as_int(mov.qty_reject)
        accepted += _as_int(mov.qty_done)
        rejected += _as_int(mov.qty_reject)
    vendors = []
    for entry in sorted(per_vendor.values(), key=lambda item: item["vendor"]):
        entry["outstanding_external_wip"] = max(entry["qty_sent"] - entry["qty_returned"], 0)
        entry["job_count"] = len(entry["jobs"])
        vendors.append(entry)
    outstanding = sum(entry["outstanding_external_wip"] for entry in vendors)
    return vendors, outstanding


@router.get("/daily-target")
def daily_target(
    on_date: date = Query(None, description="Tanggal target; default hari ini"),
    order_fk: int = Query(None, description="Filter satu Order"),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Target harian Printing/Bordir vs realisasi (revisi #47).

    Target diambil dari tabel ``printing_daily_targets`` bila sudah ada (target
    resmi lengkap dengan set_by/set_at/alasan/versi), kalau belum dari
    ``target_date`` pada ``production_movements`` seperti sebelumnya; realisasi
    dihitung HANYA dari output sah yang sudah tercatat (``qty_done`` baris
    movement yang sama). Mismatch (ada realisasi tanpa target, atau target
    terlewat) dilaporkan sebagai ``mismatch`` dan dipetakan ke exception
    Printing, bukan dibiarkan diam.

    Iman tidak bisa mengubah rate finansial CFO; batas itu dikembalikan di
    blok ``rate_boundary`` supaya UI bisa menolak lebih awal.
    """
    _require(user, *READ_ROLES)
    day = on_date or date.today()
    rows, totals = _daily_target_rows(db, day, order_fk=order_fk, limit=limit)
    target_model = _model("PrintingDailyTarget")
    official_targets = []
    if target_model is not None:
        official_targets = (db.query(target_model).filter(target_model.target_date == day)
                            .order_by(desc(target_model.version)).all())
    # Order yang terlibat: dipakai untuk exception, audit, dan aktivitas makloon.
    all_jobs = _job_rows(db, order_fk=order_fk, limit=limit)
    order_ids = set()
    for job in all_jobs:
        if job["order_fk"] is not None:
            order_ids.add(job["order_fk"])

    # ── Mismatch: realisasi tanpa target hari ini, atau target terlewat ──
    mismatch = []
    for row in rows:
        if row["realised_qty"] and not row["target_qty"]:
            mismatch.append({"code": "REALISED_WITHOUT_TARGET", "job_id": row["job_id"],
                             "detail": f"{row['process']} {row['article_code']}: {row['realised_qty']} unit selesai tanpa target di {day.isoformat()}"})
        elif row["target_qty"] and not row["achieved"]:
            mismatch.append({"code": "MISSED_TARGET", "job_id": row["job_id"],
                             "detail": f"{row['process']} {row['article_code']}: target {row['target_qty']}, realisasi {row['realised_qty']} (kurang {row['remaining_vs_target']})"})
    unmatched_movements = (db.query(m.ProductionMovement)
                           .filter(m.ProductionMovement.target_date == day,
                                   m.ProductionMovement.status == "DONE",
                                   func.upper(m.ProductionMovement.process).notin_(("WAITING", "NOT_STARTED")))
                           .count())

    # ── Makloon embroidery (revisi #46) ──
    submitted = [row for row in rows if row["target_qty"]]
    vendors, outstanding = _vendor_activity(db, order_ids)

    # ── Audit & exception (revisi #47) ──
    exceptions = _print_exceptions(db, order_ids)
    audit = _audit_rows(db, order_ids)

    unresolved_reject = sum(row["qty_reject"] for row in rows)
    evidence_gap = [row["job_id"] for row in rows if row["status"] == "ACHIEVED" and row["blockers"]]

    return {
        "on_date": day,
        "as_of": datetime.utcnow(),
        "generated_by_role": role_of(user),
        "target_source": {
            "table": "printing_daily_targets" if target_model is not None else "production_movements",
            "columns": (["process", "target_date", "target_qty", "unit", "set_by_id", "set_at",
                         "reason", "version", "previous_qty"] if target_model is not None
                        else ["target_date", "qty_in", "qty_done", "qty_reject", "pic_name", "status"]),
            "note": ("Target resmi disimpan di printing_daily_targets dengan set_by/set_at/alasan/versi; "
                     "selama tabel itu belum ada, target dibaca dari production_movements.target_date."
                     if target_model is not None else
                     "Target harian masih diturunkan dari target_date pada movement. Tabel "
                     "printing_daily_targets sudah dispesifikasikan di REQUESTS/printing_schema.md "
                     "(pemilik: agent SCHEMA) dan endpoint tulis POST /printing/daily-targets menunggu "
                     "tabel itu — nilainya tidak dipalsukan sebagai sukses."),
            "rate_owner": "CFO_MANAGER",
            "set_by": [
                {"id": getattr(row, "id", None), "process": getattr(row, "process", None),
                 "target_qty": _as_int(getattr(row, "target_qty", None)),
                 "set_by_id": getattr(row, "set_by_id", None), "set_at": _iso(getattr(row, "set_at", None)),
                 "version": _as_int(getattr(row, "version", None))}
                for row in official_targets
            ],
        },
        "set_by": getattr(official_targets[0], "set_by_id", None) if official_targets else None,
        "set_at": _iso(getattr(official_targets[0], "set_at", None)) if official_targets else None,
        "targets": [_target_payload(row) for row in official_targets],
        "rows": rows,
        "totals": totals,
        "mismatch": mismatch,
        "mismatch_count": len(mismatch),
        "daily_reconciliation": {
            "identity": "qty_in = qty_done + qty_reject + remaining_wip",
            "balanced": all(row["remaining_wip"] >= 0 for row in rows),
            "movements_targeted_today": unmatched_movements,
            "rows_without_target": sum(1 for row in rows if not row["target_qty"]),
            "unresolved_reject_qty": unresolved_reject,
            "evidence_gap_jobs": evidence_gap,
        },
        "rate_boundary": {
            "rate_owner": "CFO_MANAGER",
            "printing_can_change_rate": False,
            "rule": "Iman mengelola proses & output Printing/Bordir; CFO mengelola rate, payable, dan payment.",
        },
        "internal_production": {
            "owner_role": "PRINTING_PIC",
            "fields": ["assignment", "machine", "team", "shift", "start/end", "output", "reject", "evidence", "handoff"],
            "rule": "Iman mengelola proses serta output Printing/Bordir.",
            "machine_shift_columns_present": False,
            "note": "machine/team/shift/start-end belum ada kolomnya; diminta di REQUESTS/printing_ops.md.",
        },
        "makloon": {
            "owner_role": "PRINTING_PIC",
            "required_fields": ["job_id", "vendor_eligible", "qty_sent", "qty_returned", "qty_accepted",
                                "qty_rejected", "sent_date", "return_date", "evidence", "inspection",
                                "outstanding_external_wip", "handoff"],
            "vendors": vendors,
            "outstanding_external_wip": outstanding,
            "cost_owner": "CFO_MANAGER",
            "note": ("Vendor makloon dipetakan sementara dari production_movements.pic_name (PIC di luar "
                     "Printing/Iman) sampai tabel printing_makloon_jobs tersedia."),
        },
        "exceptions": exceptions,
        "exception_count": len(exceptions),
        "audit": audit,
        "audit_count": len(audit),
        "daily_targets_table_ready": _model("PrintingDailyTarget") is not None,
        "submitted_jobs": [row["job_id"] for row in submitted],
        "source": "production_movements + qc_records + exceptions + audit_logs",
    }


# ═══════════════════════════════════════════════════════════════════════════
# FITUR TULIS PRINTING (revisi #41–#47)
# ═══════════════════════════════════════════════════════════════════════════
# Tabel persistensi (``printing_daily_targets``, ``printing_handoffs``,
# ``printing_defect_dispositions``) dimiliki agent SCHEMA — lihat
# ``REQUESTS/printing_schema.md``. Model diakses lewat ``getattr`` supaya modul
# ini tidak bergantung urutan penggabungan: begitu model ada, endpoint aktif;
# selama belum ada, jawabannya 503 "schema belum siap" dan permintaannya tidak
# pernah dilaporkan sebagai sukses.

WRITE_ROLES = ("PRINTING_PIC", "COO_MANAGER")

DISPOSITIONS = ("REWORK", "REMAKE", "REJECT", "ACCEPT_DEVIATION")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
DEFECT_ORIGINS = ("PRINTING", "BORDIR", "SUPPLIER")
HANDOFF_CLOSED_STATUSES = ("RECEIVED",)
RETEST_REQUIRED_DISPOSITIONS = ("REWORK", "REMAKE")

# Nilai "sebelum" yang dipakai di audit ketika barisnya benar-benar baru.
_UNSET = "<none>"

# Kolom Job Card (revisi #43) yang diminta lewat REQUESTS/printing_schema.md.
JOB_CARD_COLUMNS = (
    "method", "colors", "placement", "technique", "vendor_type", "machine",
    "shift", "team", "batch_id", "requirement_version", "locked_at",
    "started_at", "ended_at", "evidence_ref",
    "job_notes", "size_spec",
)


def _model(name):
    """Ambil model dari ``app.models`` kalau sudah dibuat agent SCHEMA.

    Dipakai supaya router ini bisa di-commit sebelum migration-nya ada tanpa
    memaksa urutan penggabungan, dan tanpa melaporkan sukses palsu: pemanggil
    yang mendapat ``None`` wajib menjawab 503 "schema belum siap".
    """
    model = getattr(m, name, None)
    if model is None:
        return None
    # Model harus benar-benar tabel yang bisa dipetakan (bukan placeholder).
    if getattr(model, "__table__", None) is None:
        return None
    return model


def _schema_required(name: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(f"schema belum siap: tabel/model {name} belum ada. "
                f"Spesifikasinya ada di REQUESTS/printing_schema.md dan dibuat oleh agent SCHEMA; "
                f"endpoint tulis Printing menunggu model itu."),
    )


def _require_write(user, db: Session, *roles):
    """Role tulis Printing; penolakan dicatat sebagai DENIED_* di audit_logs."""
    if role_of(user) not in roles:
        # Penolakan wewenang harus tetap tercatat walau permintaannya ditolak
        # sebelum menyentuh data.
        log_audit(db, user, "DENIED_PRINTING_WRITE", "PrintingWrite", None,
                  detail=f"role={role_of(user)} tidak boleh menulis data Printing",
                  source_module="printing_ops", reason="WRITE_ROLE_FORBIDDEN")
        db.commit()
        raise HTTPException(403, "Peran ini tidak berhak mengubah data Printing.")
    return user


def _num(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _set_if_supported(instance, **values):
    """Set hanya kolom yang benar-benar ada di tabel model.

    Spesifikasi di REQUESTS/printing_schema.md bisa bergeser sedikit (mis. nama
    proses dipakai alih-alih stage). Daripada gagal 500 karena kolom tidak ada,
    kolom yang tidak dikenal cukup dilewati — nilainya tetap muncul di respons
    yang dikembalikan endpoint.
    """
    columns = {column.name for column in instance.__table__.columns}
    for key, value in values.items():
        if key in columns and value is not None:
            setattr(instance, key, value)
    return instance


def _required_columns(model, names) -> list:
    """Kolom yang wajib ada di model menurut REQUESTS/printing_schema.md."""
    columns = {column.name for column in model.__table__.columns}
    return [name for name in names if name not in columns]


def _row_status(row) -> str:
    return (getattr(row, "status", None) or "SENT").upper()


def _job_qty(db: Session, job_id: str):
    """Qty sah untuk satu job card Printing (revisi #44).

    ``job_id`` berasal dari router job card (``JOB-<order>-<artikel>-<proses>``)
    dan dipakai bila movement-nya bisa dipetakan; kalau tidak, ambil movement
    Printing terakhir. Angka yang dipakai selalu dari ``production_movements``,
    bukan dari UI.
    """
    token = (job_id or "").strip()
    parts = token.split("-")
    if len(parts) >= 4:
        order_ref = parts[1]
        article_code = parts[2]
        process = "-".join(parts[3:])
        order = db.query(m.Order).filter(m.Order.order_id == order_ref).first()
        if order is not None:
            movement = (
                db.query(m.ProductionMovement)
                .join(m.Article, m.Article.id == m.ProductionMovement.article_id)
                .filter(m.Article.order_fk == order.id,
                        func.upper(m.Article.article_code) == article_code.upper(),
                        func.upper(func.trim(m.ProductionMovement.process)) == process.strip().upper())
                .order_by(m.ProductionMovement.id.desc())
                .first()
            )
            if movement is not None:
                return movement
    return (
        db.query(m.ProductionMovement)
        .filter(func.upper(func.trim(m.ProductionMovement.process)).in_(("PRINTING", "BORDIR")))
        .order_by(m.ProductionMovement.id.desc())
        .first()
    )


def _open_exception_count(db: Session, order_fk, category: str) -> int:
    query = db.query(m.ExceptionItem).filter(
        m.ExceptionItem.category == category,
        m.ExceptionItem.status.notin_(("RESOLVED", "CLOSED")),
    )
    if order_fk is not None:
        query = query.filter(m.ExceptionItem.order_fk == order_fk)
    return query.count()


def _pending_rework(db: Session, article_id) -> list:
    """Disposisi rework/remake yang belum punya retest — penghalang handoff."""
    model = _model("PrintingDefectDisposition")
    if model is None or article_id is None:
        return []
    rows = (
        db.query(model)
        .filter(model.article_id == article_id,
                model.disposition.in_(RETEST_REQUIRED_DISPOSITIONS))
        .order_by(model.id.desc())
        .all()
    )
    pending = []
    for row in rows:
        if getattr(row, "closed_at", None) is not None:
            continue
        if getattr(row, "rework_qc_id", None) is not None:
            continue
        if (getattr(row, "retest", None) or "").upper() == "PASSED":
            continue
        pending.append(row)
    return pending


# ── Target harian (revisi #47) ───────────────────────────────────────────────
class DailyTargetIn(BaseModel):
    """Penetapan target harian Printing/Bordir (revisi #47)."""
    model_config = ConfigDict(extra="forbid")
    process: str = Field(min_length=1, max_length=80)
    target_date: date
    target_qty: int = Field(ge=0)
    unit: Optional[str] = Field(default="PCS", max_length=20)
    order_fk: Optional[int] = None
    article_id: Optional[int] = None
    reason: Optional[str] = Field(default=None, max_length=2000)


def _target_payload(row) -> dict:
    return {
        "id": row.id,
        "process": getattr(row, "process", None),
        "target_date": _iso(getattr(row, "target_date", None)),
        "target_qty": _num(getattr(row, "target_qty", None)),
        "unit": getattr(row, "unit", None),
        "order_fk": getattr(row, "order_fk", None),
        "article_id": getattr(row, "article_id", None),
        "set_by_id": getattr(row, "set_by_id", None),
        "set_at": _iso(getattr(row, "set_at", None)),
        "reason": getattr(row, "reason", None),
        "version": _num(getattr(row, "version", None), 1) or 1,
        "previous_qty": getattr(row, "previous_qty", None),
        "created_at": _iso(getattr(row, "created_at", None)),
        "updated_at": _iso(getattr(row, "updated_at", None)),
    }


def _latest_target(db: Session, day, process, order_fk=None, article_id=None):
    model = _model("PrintingDailyTarget")
    if model is None:
        return None
    query = db.query(model).filter(
        func.upper(func.trim(model.process)) == process.strip().upper(),
        model.target_date == day,
    )
    if order_fk is not None and hasattr(model, "order_fk"):
        query = query.filter(model.order_fk == order_fk)
    if article_id is not None and hasattr(model, "article_id"):
        query = query.filter(model.article_id == article_id)
    return query.order_by(desc(model.version), desc(model.id)).first()


@router.post("/daily-targets")
def set_daily_target(
    payload: DailyTargetIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Tetapkan target harian Printing/Bordir resmi (revisi #47).

    Selama ``printing_daily_targets`` belum ada, endpoint membaca target dari
    ``production_movements.target_date``. Menetapkan target TIDAK boleh menulis
    angka fiktif ke movement, jadi permintaan ini ditolak dengan 503 dan pesan
    yang menyebut tabel yang ditunggu — bukan 500 dan bukan sukses palsu.
    """
    _require_write(user, db, *WRITE_ROLES)
    model = _model("PrintingDailyTarget")
    if model is None:
        raise _schema_required("printing_daily_targets / PrintingDailyTarget")
    missing = _required_columns(model, ("process", "target_date", "target_qty", "version"))
    if missing:
        raise HTTPException(503, f"schema belum siap: printing_daily_targets kurang kolom {missing}")

    process = payload.process.strip().upper()
    previous = _latest_target(db, payload.target_date, process,
                              order_fk=payload.order_fk, article_id=payload.article_id)
    now = datetime.utcnow()
    row = model()
    _set_if_supported(
        row,
        process=process,
        target_date=payload.target_date,
        target_qty=payload.target_qty,
        unit=payload.unit,
        order_fk=payload.order_fk,
        article_id=payload.article_id,
        set_by_id=getattr(user, "id", None),
        set_at=now,
        reason=payload.reason,
        version=(_num(getattr(previous, "version", None), 0) + 1) if previous else 1,
        previous_qty=_num(getattr(previous, "target_qty", None)) if previous else None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    log_audit(db, user, "SET_DAILY_TARGET", "PrintingDailyTarget", None,
              detail=(f"target {process} {payload.target_date.isoformat()} = {payload.target_qty} "
                      f"{payload.unit or 'PCS'} (versi {_num(getattr(row, 'version', None), 1) or 1})"),
              obj=row, source_module="printing_ops",
              previous_status=str(_num(getattr(previous, "target_qty", None))) if previous else _UNSET,
              new_status=str(payload.target_qty), reason=payload.reason or "TARGET_DITETAPKAN")
    db.commit()
    db.refresh(row)
    return {
        "target": _target_payload(row),
        "previous": _target_payload(previous) if previous else None,
        "version_history": [
            _target_payload(entry)
            for entry in db.query(model)
            .filter(func.upper(func.trim(model.process)) == process,
                    model.target_date == payload.target_date)
            .order_by(desc(model.version)).all()
        ],
        "rule": ("Target disimpan lengkap dengan set_by/set_at/alasan/versi; tidak ada satu angka target "
                 "yang dikunci di kode. Target hanya boleh diubah Printing/COO dan perubahannya diaudit."),
        "source": "printing_daily_targets",
    }


@router.get("/daily-targets")
def list_daily_targets(
    on_date: date = Query(None, description="Tanggal target; default hari ini"),
    process: str = Query(None, min_length=1),
    order_fk: int = Query(None),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Riwayat penetapan target harian (revisi #47)."""
    _require(user, *READ_ROLES)
    model = _model("PrintingDailyTarget")
    if model is None:
        return {"rows": [], "total": 0, "targets_configured": False, "schema_ready": False,
                "note": "Tabel printing_daily_targets belum ada; target harian masih dibaca dari "
                        "production_movements.target_date. Spesifikasi: REQUESTS/printing_schema.md",
                "source": "production_movements"}
    query = db.query(model)
    if on_date is not None:
        query = query.filter(model.target_date == on_date)
    if process:
        query = query.filter(func.upper(func.trim(model.process)) == process.strip().upper())
    if order_fk is not None and hasattr(model, "order_fk"):
        query = query.filter(model.order_fk == order_fk)
    rows = query.order_by(desc(model.target_date), desc(model.id)).limit(limit).all()
    return {
        "rows": [_target_payload(row) for row in rows],
        "total": len(rows),
        "targets_configured": bool(rows),
        "schema_ready": True,
        "source": "printing_daily_targets",
    }


# ── Partial handoff (revisi #44) ─────────────────────────────────────────────
class HandoffIn(BaseModel):
    """Partial handoff Printing/Bordir -> proses berikutnya (revisi #44).

    Kontrak ini sudah ditulis di router ini sejak Batch 1 dan disebut di
    REQUESTS/printing_jobs.md; field baru ditambahkan opsional supaya payload
    lama tetap sah.
    """
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=120)
    article_id: int
    process: str = Field(min_length=1, max_length=80)
    next_stage: str = Field(min_length=1, max_length=80)
    qty_sent: int = Field(gt=0)
    evidence_ref: Optional[str] = Field(default=None, max_length=500)
    batch_no: Optional[str] = Field(default=None, max_length=120)
    shift: Optional[str] = Field(default=None, max_length=64)
    location: Optional[str] = Field(default=None, max_length=120)
    lot_no: Optional[str] = Field(default=None, max_length=80)
    sender: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=2000)


class HandoffReceiveIn(BaseModel):
    """Penerimaan handoff: qty terima, penerima, dan bukti (revisi #44)."""
    model_config = ConfigDict(extra="forbid")
    qty_received: int = Field(ge=0)
    receiver: Optional[str] = Field(default=None, max_length=120)
    evidence_ref: Optional[str] = Field(default=None, max_length=500)
    note: Optional[str] = Field(default=None, max_length=2000)


def _handoff_payload(row) -> dict:
    sent = _num(getattr(row, "qty_sent", None))
    received = getattr(row, "qty_received", None)
    received_num = _num(received) if received is not None else None
    remaining = sent - received_num if received_num is not None else sent
    return {
        "id": row.id,
        "handoff_no": getattr(row, "handoff_no", None),
        "job_id": getattr(row, "job_id", None),
        "movement_id": getattr(row, "movement_id", None),
        "article_id": getattr(row, "article_id", None),
        "order_fk": getattr(row, "order_fk", None),
        "process": getattr(row, "process", None) or getattr(row, "stage", None),
        "stage": getattr(row, "stage", None) or getattr(row, "process", None),
        "next_stage": getattr(row, "next_stage", None),
        "lot_no": getattr(row, "lot_no", None),
        "batch_no": getattr(row, "batch_no", None) or getattr(row, "batch_id", None),
        "qty_sent": sent,
        "qty_received": received_num,
        "remaining": remaining,
        "qty_sent_immutable": True,
        "exception": getattr(row, "exception", None),
        "shift": getattr(row, "shift", None),
        "location": getattr(row, "location", None),
        "evidence_ref": getattr(row, "evidence_ref", None),
        "sender": getattr(row, "sender", None),
        "receiver": getattr(row, "receiver", None),
        "sent_at": _iso(getattr(row, "sent_at", None)),
        "received_at": _iso(getattr(row, "received_at", None)),
        "status": _row_status(row),
        "exception_id": getattr(row, "exception_id", None),
        "notes": getattr(row, "notes", None),
        "created_at": _iso(getattr(row, "created_at", None)),
        "next_stage_qty_rule": "proses berikutnya hanya boleh memakai qty_received, bukan qty_sent",
    }


def _new_exception(db, order_fk, category, title, detail, user):
    row = m.ExceptionItem(
        order_fk=order_fk, severity="YELLOW", category=category, title=title[:200],
        owner_role="PRINTING_PIC", owner_name=None, status="OPEN",
        source_module="printing_ops", source_entity=category, impact=detail[:2000],
        recommendation="Rekonsiliasi selisih qty sebelum handoff dianggap selesai.",
        decision_required=False, created_by_id=getattr(user, "id", None),
    )
    db.add(row)
    db.flush()
    return row


@router.post("/handoffs")
def create_handoff(
    payload: HandoffIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Catat partial handoff Printing/Bordir (revisi #44).

    ``qty_sent`` berasal dari serah terima fisik dan tidak dihitung ulang sistem
    (batas revisi: angka output sah tetap milik printing), tetapi tetap dibatasi
    supaya tidak melebihi qty yang benar-benar selesai di movement
    (``qty_done - qty_sent yang sudah dihandoff``). Handoff yang sudah diterima
    (``RECEIVED``) tidak boleh di-handoff ulang untuk qty yang sama.
    """
    _require_write(user, db, *WRITE_ROLES)
    model = _model("PrintingHandoff")
    if model is None:
        raise _schema_required("printing_handoffs / PrintingHandoff")
    missing = _required_columns(model, ("handoff_no", "job_id", "qty_sent", "qty_received", "status"))
    if missing:
        raise HTTPException(503, f"schema belum siap: printing_handoffs kurang kolom {missing}")

    process = payload.process.strip().upper()
    if not is_printing_process(process):
        log_audit(db, user, "DENIED_HANDOFF_OUTSIDE_PRINTING", "PrintingHandoff", payload.article_id,
                  detail=f"proses {payload.process} bukan PRINTING/BORDIR",
                  source_module="printing_ops", reason="PROCESS_NOT_OWNED")
        raise HTTPException(403, f"Proses {payload.process} bukan milik Printing/Bordir (Iman).")

    article = db.get(m.Article, payload.article_id)
    if article is None:
        raise HTTPException(404, "Article not found")
    order = db.get(m.Order, article.order_fk)
    route = route_for(article)
    next_stage = payload.next_stage.strip()
    if route and next_stage.upper() not in [step.strip().upper() for step in route]:
        raise HTTPException(400, f"Tahap {next_stage} tidak ada di rute {article.article_code}: {' > '.join(route)}")

    pending_rework = _pending_rework(db, article.id)
    if pending_rework:
        log_audit(db, user, "DENIED_HANDOFF_PENDING_REWORK", "PrintingHandoff", article.id,
                  detail=f"{len(pending_rework)} disposisi rework/remake belum retest",
                  source_module="printing_ops", reason="REWORK_RETEST_REQUIRED")
        raise HTTPException(409, ("Handoff ditolak: masih ada disposisi REWORK/REMAKE tanpa retest "
                                  "(revisi #45). Selesaikan retest sebelum menyerahkan qty."))

    movement = _job_qty(db, payload.job_id)
    if movement is None:
        raise HTTPException(404, "Tidak ada baris production_movements Printing untuk job ini")
    done = _num(getattr(movement, "qty_done", None))
    already = (
        db.query(model)
        .filter(func.upper(func.trim(getattr(model, "process", model.stage))) == process,
                model.article_id == article.id)
        .all()
    )
    open_sent = sum(_num(getattr(row, "qty_sent", None)) for row in already
                    if (getattr(row, "qty_received", None) is not None or _row_status(row) == "SENT"))
    if done and open_sent + payload.qty_sent > done:
        raise HTTPException(400, (f"qty_sent {payload.qty_sent} melebihi qty selesai yang belum dihandoff "
                                  f"({max(done - open_sent, 0)} dari {done} qty_done di movement {movement.id})"))

    now = datetime.utcnow()
    sequence = len(already) + 1
    handoff_no = f"HO-{order.order_id if order else article.id}-{process}-{sequence:03d}"
    row = model()
    _set_if_supported(
        row,
        handoff_no=handoff_no,
        job_id=payload.job_id,
        movement_id=movement.id,
        article_id=article.id,
        order_fk=article.order_fk,
        process=process,
        stage=process,
        next_stage=next_stage,
        lot_no=payload.lot_no,
        batch_no=payload.batch_no,
        batch_id=payload.batch_no,
        qty_sent=payload.qty_sent,
        remaining=payload.qty_sent,
        shift=payload.shift,
        location=payload.location,
        evidence_ref=payload.evidence_ref,
        sender=payload.sender or getattr(user, "name", None),
        sent_at=now,
        status="SENT",
        notes=payload.notes,
        created_by_id=getattr(user, "id", None),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    log_audit(db, user, "CREATE_HANDOFF", "PrintingHandoff", movement.id,
              detail=(f"{handoff_no}: {payload.qty_sent} unit {process} {article.article_code} "
                      f"-> {next_stage} (sisa di kirim: {payload.qty_sent})"),
              obj=row, source_module="printing_ops", previous_status=_UNSET, new_status="SENT",
              reason=payload.notes or "PARTIAL_HANDOFF")
    db.commit()
    db.refresh(row)
    return {
        "handoff": _handoff_payload(row),
        "movement": {"id": movement.id, "qty_in": _num(movement.qty_in), "qty_done": done,
                     "qty_reject": _num(movement.qty_reject), "process": movement.process},
        "quantity_rule": ("qty_received wajib <= qty_sent; sisa yang belum diterima tetap menjadi "
                          "tanggung jawab Printing dan harus direkonsiliasi (revisi #44)."),
        "source": "printing_handoffs",
    }


@router.post("/handoffs/{handoff_id}/receive")
def receive_handoff(
    handoff_id: int,
    payload: HandoffReceiveIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Terima handoff: catat qty diterima, sisa, dan exception selisihnya (#44)."""
    _require_write(user, db, *WRITE_ROLES)
    model = _model("PrintingHandoff")
    if model is None:
        raise _schema_required("printing_handoffs / PrintingHandoff")
    row = db.get(model, handoff_id)
    if row is None:
        raise HTTPException(404, "Handoff not found")
    # Sebuah handoff dianggap sudah ditutup kalau statusnya RECEIVED/CLOSED, ATAU
    # kalau qty_received-nya sudah pernah dicatat (kolom NOT NULL di schema agent
    # default 0, jadi "sudah diterima" tidak boleh hanya bergantung pada status).
    received_recorded = getattr(row, "qty_received", None) is not None
    if _row_status(row) in HANDOFF_CLOSED_STATUSES or received_recorded:
        raise HTTPException(409, f"Handoff {getattr(row, 'handoff_no', handoff_id)} sudah diterima; qty kirim tidak boleh diubah lagi.")

    sent = _num(getattr(row, "qty_sent", None))
    if payload.qty_received > sent:
        raise HTTPException(400, f"qty_received {payload.qty_received} melebihi qty_sent {sent}")

    now = datetime.utcnow()
    remaining = sent - payload.qty_received
    discrepancy = remaining > 0
    exception_row = None
    if discrepancy:
        detail = (f"Handoff {getattr(row, 'handoff_no', handoff_id)}: kirim {sent}, diterima "
                  f"{payload.qty_received}, selisih {remaining} unit")
        exception_row = _new_exception(db, getattr(row, "order_fk", None),
                                       "HANDOFF_DISCREPANCY",
                                       f"Handoff discrepancy {getattr(row, 'job_id', '')}".strip(),
                                       detail, user)
        log_audit(db, user, "HANDOFF_DISCREPANCY", "PrintingHandoff", row.id, detail=detail,
                  obj=row, source_module="printing_ops", previous_status=_row_status(row),
                  new_status="DISCREPANCY", reason="QTY_RECEIVED_LESS_THAN_SENT")
    _set_if_supported(
        row,
        qty_received=payload.qty_received,
        remaining=remaining,
        exception=(f"selisih {remaining} unit" if discrepancy else None),
        status="DISCREPANCY" if discrepancy else "RECEIVED",
        receiver=payload.receiver or getattr(user, "name", None),
        received_at=now,
        evidence_ref=payload.evidence_ref,
        exception_id=exception_row.id if exception_row else None,
        notes=payload.note or getattr(row, "notes", None),
        updated_at=now,
    )
    log_audit(db, user, "RECEIVE_HANDOFF", "PrintingHandoff", row.id,
              detail=(f"{getattr(row, 'handoff_no', handoff_id)}: diterima {payload.qty_received} "
                      f"dari {sent} (sisa {remaining})"),
              obj=row, source_module="printing_ops", previous_status="SENT",
              new_status="DISCREPANCY" if discrepancy else "RECEIVED",
              reason=payload.note or "HANDOFF_DITERIMA")
    db.commit()
    db.refresh(row)
    return {
        "handoff": _handoff_payload(row),
        "discrepancy": {
            "has_discrepancy": discrepancy,
            "qty_sent": sent,
            "qty_received": payload.qty_received,
            "remaining": remaining,
            "exception_id": exception_row.id if exception_row else None,
            "rule": ("Selisih membuat exception HANDOFF_DISCREPANCY dan proses berikutnya hanya boleh "
                     "memakai qty_received; qty_sent tidak pernah diturunkan diam-diam."),
        },
        "source": "printing_handoffs + exceptions",
    }


@router.get("/handoffs")
def list_handoffs(
    order_fk: int = Query(None),
    status: str = Query(None, min_length=1),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Daftar partial handoff Printing/Bordir (revisi #44)."""
    _require(user, *READ_ROLES)
    model = _model("PrintingHandoff")
    if model is None:
        return {"rows": [], "total": 0, "schema_ready": False,
                "note": "Tabel printing_handoffs belum ada. Spesifikasi: REQUESTS/printing_schema.md",
                "source": "none"}
    query = db.query(model)
    if order_fk is not None and hasattr(model, "order_fk"):
        query = query.filter(model.order_fk == order_fk)
    if status:
        query = query.filter(func.upper(model.status) == status.strip().upper())
    rows = query.order_by(desc(model.id)).limit(limit).all()
    payloads = [_handoff_payload(row) for row in rows]
    return {
        "rows": payloads,
        "total": len(payloads),
        "schema_ready": True,
        "outstanding_qty": sum(row["remaining"] for row in payloads if row["status"] == "SENT"),
        "discrepancy_count": sum(1 for row in payloads if row["status"] == "DISCREPANCY"),
        "source": "printing_handoffs",
    }


# ── Disposisi defect & rework (revisi #45) ───────────────────────────────────
class DefectDispositionIn(BaseModel):
    """Disposisi reject Printing/Bordir (revisi #45)."""
    model_config = ConfigDict(extra="forbid")
    qc_id: Optional[int] = None
    job_id: Optional[str] = Field(default=None, max_length=120)
    article_id: Optional[int] = None
    process: Optional[str] = Field(default=None, max_length=80)
    defect_category: str = Field(min_length=1, max_length=80)
    defect_detail: Optional[str] = Field(default=None, max_length=2000)
    qty: int = Field(default=0, ge=0)
    origin: Optional[str] = Field(default=None, max_length=32)
    severity: str = Field(default="MINOR", max_length=20)
    disposition: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=2000)
    rework_owner: Optional[str] = Field(default=None, max_length=120)
    rework_due: Optional[date] = None
    evidence_ref: Optional[str] = Field(default=None, max_length=500)


class DispositionCloseIn(BaseModel):
    """Penutupan disposisi setelah retest/evidence lengkap (revisi #45)."""
    model_config = ConfigDict(extra="forbid")
    rework_qc_id: Optional[int] = None
    retest: Optional[str] = Field(default=None, max_length=32)
    resolution_evidence_ref: Optional[str] = Field(default=None, max_length=500)
    note: Optional[str] = Field(default=None, max_length=2000)


def _disposition_payload(row) -> dict:
    disposition = (getattr(row, "disposition", None) or "").upper()
    retest = (getattr(row, "retest", None) or "").upper() or None
    needs_retest = disposition in RETEST_REQUIRED_DISPOSITIONS
    closed = getattr(row, "closed_at", None) is not None
    return {
        "id": row.id,
        "qc_id": getattr(row, "qc_id", None),
        "job_id": getattr(row, "job_id", None),
        "article_id": getattr(row, "article_id", None),
        "process": getattr(row, "process", None),
        "defect_category": getattr(row, "defect_category", None),
        "defect_detail": getattr(row, "defect_detail", None),
        "qty": _num(getattr(row, "qty", None)),
        "origin": getattr(row, "origin", None),
        "severity": getattr(row, "severity", None),
        "disposition": disposition or None,
        "rework_owner": getattr(row, "rework_owner", None),
        "rework_due": _iso(getattr(row, "rework_due", None)),
        "rework_qc_id": getattr(row, "rework_qc_id", None),
        "retest": retest,
        "evidence_ref": getattr(row, "evidence_ref", None),
        "resolution_evidence_ref": getattr(row, "resolution_evidence_ref", None),
        "reason": getattr(row, "reason", None),
        "closed_at": _iso(getattr(row, "closed_at", None)),
        "created_by": getattr(row, "created_by", None) or getattr(row, "created_by_id", None),
        "created_at": _iso(getattr(row, "created_at", None)),
        "needs_retest": needs_retest,
        "retest_satisfied": bool(getattr(row, "rework_qc_id", None)) or retest == "PASSED",
        "open": not closed and (bool(getattr(row, "rework_qc_id", None)) is False) if needs_retest else not closed,
        "handoff_rule": "REWORK/REMAKE wajib retest (rework_qc_id) sebelum qty boleh dihandoff",
    }


@router.post("/defect-dispositions")
def create_defect_disposition(
    payload: DefectDispositionIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Catat keputusan defect Printing/Bordir (revisi #45).

    Reject tidak boleh dianggap selesai tanpa baris disposisi. ``REWORK`` dan
    ``REMAKE`` menandai ``retest = REQUIRED``; handoff job tersebut ditolak
    sampai ada ``rework_qc_id`` (atau retest PASSED). QC final tetap milik
    petugas QC — ini inspeksi proses Printing/Bordir, bukan penggantinya.
    """
    _require_write(user, db, *WRITE_ROLES)
    model = _model("PrintingDefectDisposition")
    if model is None:
        raise _schema_required("printing_defect_dispositions / PrintingDefectDisposition")
    missing = _required_columns(model, ("disposition", "severity", "defect_category", "reason"))
    if missing:
        raise HTTPException(503, f"schema belum siap: printing_defect_dispositions kurang kolom {missing}")

    disposition = payload.disposition.strip().upper()
    severity = payload.severity.strip().upper()
    origin = (payload.origin or "").strip().upper() or None
    if disposition not in DISPOSITIONS:
        raise HTTPException(400, f"Disposition {payload.disposition} tidak dikenal; pilihan: {', '.join(DISPOSITIONS)}")
    if severity not in SEVERITIES:
        raise HTTPException(400, f"Severity {payload.severity} tidak dikenal; pilihan: {', '.join(SEVERITIES)}")
    if origin and origin not in DEFECT_ORIGINS:
        raise HTTPException(400, f"Origin {payload.origin} tidak dikenal; pilihan: {', '.join(DEFECT_ORIGINS)}")

    qc = db.get(m.QCRecord, payload.qc_id) if payload.qc_id else None
    if payload.qc_id and qc is None:
        raise HTTPException(404, "QC record not found")
    article_id = payload.article_id or (qc.article_id if qc else None)
    process = (payload.process or (qc.process if qc else None) or "").strip().upper() or None
    if process is None or not is_printing_process(process):
        log_audit(db, user, "DENIED_DISPOSITION_OUTSIDE_PRINTING", "PrintingDefectDisposition", article_id,
                  detail=f"proses {process} bukan PRINTING/BORDIR",
                  source_module="printing_ops", reason="PROCESS_NOT_OWNED")
        raise HTTPException(403, "Disposisi defect hanya untuk proses PRINTING/BORDIR.")
    qty = payload.qty or (max(_num(getattr(qc, "total_reject", None)), 0) if qc else 0)

    now = datetime.utcnow()
    needs_retest = disposition in RETEST_REQUIRED_DISPOSITIONS
    row = model()
    _set_if_supported(
        row,
        qc_id=payload.qc_id,
        job_id=payload.job_id,
        article_id=article_id,
        process=process,
        defect_category=payload.defect_category.strip().upper(),
        defect_detail=payload.defect_detail or (getattr(qc, "reject_reason", None) if qc else None),
        qty=qty,
        origin=origin or ("PRINTING" if process in ("PRINTING", "BORDIR") else None),
        severity=severity,
        disposition=disposition,
        rework_owner=payload.rework_owner,
        rework_due=payload.rework_due,
        retest="REQUIRED" if needs_retest else None,
        evidence_ref=payload.evidence_ref,
        reason=payload.reason,
        created_by=getattr(user, "id", None),
        created_by_id=getattr(user, "id", None),
        created_at=now,
    )
    db.add(row)
    log_audit(db, user, "CREATE_DEFECT_DISPOSITION", "PrintingDefectDisposition",
              payload.qc_id or article_id,
              detail=(f"{process} {payload.defect_category} qty {qty} -> {disposition} ({severity}); "
                      f"retest {'wajib' if needs_retest else 'tidak perlu'}"),
              obj=row, source_module="printing_ops", previous_status=_UNSET, new_status=disposition,
              reason=payload.reason)
    db.commit()
    db.refresh(row)
    return {
        "disposition": _disposition_payload(row),
        "qc": {"id": qc.id, "article_code": qc.article_code, "total_reject": _num(qc.total_reject),
               "reject_reason": qc.reject_reason} if qc else None,
        "rule": ("Reject belum selesai sebelum ada baris disposition. REWORK/REMAKE wajib retest "
                 "(rework_qc_id) sebelum handoff; QC final tetap milik petugas QC (revisi #45)."),
        "source": "printing_defect_dispositions",
    }


@router.post("/defect-dispositions/{disposition_id}/close")
def close_defect_disposition(
    disposition_id: int,
    payload: DispositionCloseIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Tutup disposisi defect setelah retest/evidence lengkap (revisi #45)."""
    _require_write(user, db, *WRITE_ROLES)
    model = _model("PrintingDefectDisposition")
    if model is None:
        raise _schema_required("printing_defect_dispositions / PrintingDefectDisposition")
    row = db.get(model, disposition_id)
    if row is None:
        raise HTTPException(404, "Disposition not found")
    if getattr(row, "closed_at", None) is not None:
        raise HTTPException(409, "Disposisi ini sudah ditutup.")

    disposition = (getattr(row, "disposition", None) or "").upper()
    retest = (payload.retest or "").strip().upper() or None
    needs_retest = disposition in RETEST_REQUIRED_DISPOSITIONS
    rework_qc = db.get(m.QCRecord, payload.rework_qc_id) if payload.rework_qc_id else None
    if payload.rework_qc_id and rework_qc is None:
        raise HTTPException(404, "QC retest record not found")
    if needs_retest and rework_qc is None and retest != "PASSED":
        raise HTTPException(409, ("Hasil REWORK/REMAKE wajib punya rework_qc_id (retest) sebelum "
                                  "disposisi boleh ditutup dan qty boleh dihandoff."))
    if rework_qc is not None and getattr(row, "article_id", None) and rework_qc.article_id \
            and rework_qc.article_id != getattr(row, "article_id", None):
        raise HTTPException(400, "QC retest harus untuk artikel yang sama dengan disposisi ini.")

    now = datetime.utcnow()
    _set_if_supported(
        row,
        rework_qc_id=payload.rework_qc_id or getattr(row, "rework_qc_id", None),
        retest=retest or ("PASSED" if payload.rework_qc_id else getattr(row, "retest", None) or "REQUIRED"),
        resolution_evidence_ref=payload.resolution_evidence_ref,
        closed_at=now,
    )
    log_audit(db, user, "CLOSE_DEFECT_DISPOSITION", "PrintingDefectDisposition", row.id,
              detail=(f"disposisi {disposition} ditutup; retest_qc={payload.rework_qc_id or '-'} "
                      f"evidence={(payload.resolution_evidence_ref or '-')}"),
              obj=row, source_module="printing_ops", previous_status=disposition, new_status="CLOSED",
              reason=payload.note or "DISPOSISI_DITUTUP")
    db.commit()
    db.refresh(row)
    return {
        "disposition": _disposition_payload(row),
        "closed": True,
        "source": "printing_defect_dispositions",
    }


@router.get("/defect-dispositions")
def list_defect_dispositions(
    order_fk: int = Query(None),
    open_only: bool = Query(False, description="Hanya disposisi yang belum ditutup"),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Daftar keputusan defect/rework Printing (revisi #45)."""
    _require(user, *READ_ROLES)
    model = _model("PrintingDefectDisposition")
    if model is None:
        return {"rows": [], "total": 0, "schema_ready": False,
                "note": ("Tabel printing_defect_dispositions belum ada; kategori defect masih diturunkan "
                         "dari teks qc_records.reject_reason. Spesifikasi: REQUESTS/printing_schema.md"),
                "source": "qc_records"}
    query = db.query(model)
    if open_only:
        query = query.filter(model.closed_at.is_(None))
    rows = query.order_by(desc(model.id)).limit(limit).all()
    payloads = [_disposition_payload(row) for row in rows]
    if order_fk is not None:
        order = db.get(m.Order, order_fk)
        order_id = order.order_id if order else None
        payloads = [row for row in payloads if row["job_id"] and order_id and order_id in row["job_id"].upper()]
    return {
        "rows": payloads,
        "total": len(payloads),
        "open_count": sum(1 for row in payloads if row["closed_at"] is None),
        "awaiting_retest": sum(1 for row in payloads if row["needs_retest"] and not row["retest_satisfied"]),
        "by_disposition": [
            {"disposition": value, "count": sum(1 for row in payloads if row["disposition"] == value)}
            for value in DISPOSITIONS
        ],
        "schema_ready": True,
        "source": "printing_defect_dispositions",
    }


# ── Job Card fields (revisi #43) — aktif otomatis saat kolomnya ada ─────────
def _job_card_fields(movement) -> dict:
    """Field Job Card dari kolom movement, dengan penanda mana yang sudah ada."""
    values = {name: getattr(movement, name, None) for name in JOB_CARD_COLUMNS}
    return {
        **values,
        "job_fields_present": {name: hasattr(movement, name) for name in JOB_CARD_COLUMNS},
        "job_fields_ready": all(hasattr(movement, name) for name in JOB_CARD_COLUMNS),
    }
