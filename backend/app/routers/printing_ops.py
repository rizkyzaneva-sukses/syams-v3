"""Printing: task/eligibility, batas transisi status, target harian & makloon.

Revisi #41 (PRN-I-002 Task, Assignment & Eligibility), #42 (PRN-I-003 Batas
Proses & Status Transition), #46 (PRN-I-007 Internal Production & Makloon
Embroidery), #47 (PRN-I-008 Target Harian, Integrasi, Exception & Audit).

Dua endpoint baca:

``GET /printing/daily-target``
    Target harian Printing/Bordir (ditetapkan Iman lewat ``target_date`` pada
    baris ``production_movements``) dibandingkan realisasi yang dihitung dari
    output sah, per proses per hari. Termasuk blok makloon (vendor/embroidery),
    exception Printing yang sedang terbuka, dan audit perubahan status.

``GET /printing/eligibility``
    Untuk tiap job (artikel x rute) Printing/Bordir: apakah job itu boleh
    dikerjakan, oleh role apa, pada status apa, tindakan apa yang sah
    (START, UPDATE_PROGRESS, REPORT_RESULT, SUBMIT_RESULT, HANDOFF), dan
    transisinya. Termasuk ringkasan izin dan batas milik domain lain
    (rate/harga = CFO, output fisik = Printing).

Semua angka diturunkan dari transaksi yang sudah tercatat
(``production_movements``, ``qc_records``, ``articles``, ``orders``, ``spks``,
``exceptions``, ``audit_logs``) — endpoint ini tidak menulis apa pun dan tidak
menyimpan target di tabel baru. Kolom/tabel tambahan yang dibutuhkan untuk
mengubah/menetapkan target secara manual diminta lewat
``REQUESTS/printing_ops.md``.

Rute sudah boleh dibatasi (revisi #42): pilihan proses dan status tidak lagi
bebas. Batas status di sini adalah cermin baca dari aturan yang dipaksakan
``app/workflow.py`` saat write; kalau keduanya berbeda, workflow yang berlaku.
"""
import json
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

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
    jobs = _job_rows(db, order_fk=order_fk, limit=limit)
    day_rows = []
    for job in jobs:
        if not job["is_printing_stage"]:
            continue
        target = job["qty_in"] if job["target_date"] == on_date else 0
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

    Target diambil dari ``production_movements.target_date`` (ditetapkan Iman)
    pada tanggal yang diminta; realisasi dihitung HANYA dari output sah yang
    sudah tercatat (``qty_done`` baris movement yang sama). Mismatch (ada
    realisasi tanpa target, atau target terlewat) dilaporkan sebagai
    ``mismatch`` dan dipetakan ke exception Printing, bukan dibiarkan diam.

    Iman tidak bisa mengubah rate finansial CFO; batas itu dikembalikan di
    blok ``rate_boundary`` supaya UI bisa menolak lebih awal.
    """
    _require(user, *READ_ROLES)
    day = on_date or date.today()
    rows, totals = _daily_target_rows(db, day, order_fk=order_fk, limit=limit)
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
            "table": "production_movements",
            "columns": ["target_date", "qty_in", "qty_done", "qty_reject", "pic_name", "status"],
            "note": ("Target harian ditetapkan lewat target_date pada movement; angka target TIDAK "
                     "dikunci di sistem. Kolom target_value/set_by/set_at/reason/version untuk "
                     "penetapan manual diminta di REQUESTS/printing_ops.md."),
            "rate_owner": "CFO_MANAGER",
        },
        "set_by": None,
        "set_at": None,
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
        "submitted_jobs": [row["job_id"] for row in submitted],
        "source": "production_movements + qc_records + exceptions + audit_logs",
    }
