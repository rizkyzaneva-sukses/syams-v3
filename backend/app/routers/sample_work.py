"""Sample PIC (Fahrul) work surface — Sample Today, My Sample Tasks & eligibility.

Blueprint: SMP-F-001 (#31), SMP-F-002 (#32), SMP-F-003 (#33), SMP-F-005 (#35),
SMP-F-007 (#37).

Batas mutlak yang ditegakkan di sini:

* **Pekerjaan sample != keputusan buyer.** Endpoint di modul ini hanya
  membaca. Fahrul tidak punya endpoint untuk mengubah ``SampleRecord.status``
  menjadi APPROVED/REJECTED, tidak punya ``customer-decision``, tidak bisa
  release SPK, tidak bisa menjalankan produksi, tidak bisa membuat PO/GR.
  Keputusan buyer (BUYER_APPROVE / BUYER_REJECT) tetap milik CMO_MANAGER
  melalui ``POST /cmo/samples/{id}/customer-decision`` pada
  ``/api/cmo/samples``; modul ini hanya menampilkan *status keputusan* sebagai
  informasi read-only per sample version.
* **Eligibility berasal dari data, bukan dari UI.** Sample Work (task Fahrul)
  hanya muncul untuk artikel dengan ``perlu_sample = YA`` DAN sample request
  yang sudah ada DAN versi PPM/mockup yang eligible. Order/article yang tidak
  eligible tetap dikembalikan, tetapi dengan ``eligible = false`` dan
  ``reason`` yang bisa dibaca manusia (server-side rejection, ditampilkan).
* **Lifecycle task**: OPEN → START/IN_PROGRESS → UPDATE → INSPECTION →
  SUBMIT_RESULT → DONE. Task tidak pernah ditandai DONE tanpa sample version
  submitted + seluruh required evidence (dihitung di ``_state_for``).
* **SLA berasal dari Master** (``buyer_deadline`` order), bukan angka bebas
  yang boleh diubah Fahrul.
"""
from datetime import date, datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_user
from ..database import get_db
from .. import models as m

router = APIRouter(prefix="/sample", tags=["sample-work"])

# Peran yang boleh melihat antrean kerja Sample PIC.
VIEW_ROLES = {"CEO", "CMO_MANAGER", "COO_MANAGER", "SAMPLE_PIC"}

# Aksi yang dimiliki Sample PIC (pekerjaan sample).
SAMPLE_WORK_ACTIONS = (
    "START", "UPDATE_PROGRESS", "INSPECTION", "UPLOAD_EVIDENCE",
    "SUBMIT_RESULT", "WORK_REVISION",
)

# Aksi keputusan buyer — SENGAJA tidak ada di daftar atas dan ditolak di bawah.
BUYER_DECISION_ACTIONS = ("BUYER_APPROVE", "BUYER_REJECT", "APPROVE", "REJECT")

# Status keputusan buyer pada SampleRecord (bukan pekerjaan Fahrul).
BUYER_DECISION_STATUSES = {"APPROVED", "REJECTED"}

# Tahapan lifecycle task sample (SMP-F-005). Tiap tahap punya bukti yang wajib
# ada sebelum boleh maju ke tahap berikutnya.
LIFECYCLE = ("OPEN", "IN_PROGRESS", "UPDATE", "INSPECTION", "SUBMIT_RESULT", "DONE")

# Persyaratan per tahap. `code` adalah kunci bukti/prasyarat pada `requirements`.
STEP_REQUIREMENTS = {
    "IN_PROGRESS": [
        ("sample_request", "Sample Request sudah dibuat CMO"),
    ],
    "UPDATE": [
        ("sample_request", "Sample Request sudah dibuat CMO"),
        ("ppm_version", "Versi PPM/mockup eligible"),
    ],
    "INSPECTION": [
        ("ppm_version", "Versi PPM/mockup eligible"),
        ("evidence_progress", "Bukti progres sample diunggah"),
    ],
    "SUBMIT_RESULT": [
        ("evidence_progress", "Bukti progres sample diunggah"),
        ("evidence_inspection", "Bukti hasil inspeksi diunggah"),
    ],
    "DONE": [
        ("version_submitted", "Sample version sudah submitted"),
        ("evidence_progress", "Bukti progres sample diunggah"),
        ("evidence_inspection", "Bukti hasil inspeksi diunggah"),
        ("evidence_result", "Bukti hasil akhir diunggah"),
    ],
}

# Kata kunci yang menandai bukti inspeksi / hasil akhir pada catatan evidence.
INSPECTION_HINTS = ("inspeksi", "inspection", "qc", "periksa")
RESULT_HINTS = ("hasil", "result", "final", "kirim", "submit")

# Kategori exception yang menjadi milik pekerjaan sample (SMP-F-007).
SAMPLE_EXCEPTION_HINTS = ("sample", "ppm", "mockup", "bahan sample", "artwork")

# Lead time pengingat SLA (hari) — dipakai untuk menandai "segera".
SLA_SOON_DAYS = 2


# ────────────────────────────── helpers ──────────────────────────────
def _role(user):
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def _require_view(user):
    if _role(user) not in VIEW_ROLES:
        raise HTTPException(403, "Antrean kerja Sample PIC tidak tersedia untuk peran ini.")


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _perlu_sample(article):
    """SMP-F-003: sample wajib bila Perlu Sample = YA (flag ATAU status)."""
    return bool(article.sample_required) or (article.sample_status or "").upper() in {
        "REQUIRED", "YES", "YA", "REQUESTED", "PROCESS", "IN_PROGRESS",
    }


def _ppm_versions(notes):
    """Versi PPM/mockup eligible yang tercatat pada sample request.

    Sample request (SampleRecord.notes) menyimpan ``ppm_version`` sebagai JSON:
    ``{"ppm_version": {"version": 2, "eligible": true, "submitted": true}}``.
    Bentuk lama/teks bebas tidak dianggap eligible — lebih aman menandai alasan
    daripada melepas task tanpa dasar.
    """
    if not notes:
        return None
    try:
        parsed = json.loads(notes)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    version = parsed.get("ppm_version")
    return version if isinstance(version, dict) else None


def _evidence_flags(evidence, ppm_version):
    """Kategori bukti yang sudah diunggah — dasar evidence completeness."""
    names = " ".join(
        f"{(row.file_name or '')} {(row.note or '')}".lower() for row in evidence
    )
    return {
        "evidence_progress": len(evidence) > 0,
        "evidence_inspection": any(hint in names for hint in INSPECTION_HINTS),
        "evidence_result": any(hint in names for hint in RESULT_HINTS),
        "version_submitted": bool(ppm_version and ppm_version.get("submitted")),
    }


def _requirements(state):
    return {
        key: {"code": key, "label": label, "ok": bool(state.get(key))}
        for key, label in STEP_REQUIREMENTS["DONE"]
    }


def _evidence_completeness(state):
    keys = ["evidence_progress", "evidence_inspection", "evidence_result"]
    have = sum(1 for key in keys if state.get(key))
    return {
        "uploaded": have,
        "required": len(keys),
        "complete": have == len(keys),
        "missing": [k for k in keys if not state.get(k)],
    }


def _lifecycle(status, state, has_exception):
    """Posisi task pada lifecycle; bukti menentukan boleh maju atau tidak.

    `DONE` TIDAK PERNAH otomatis: walaupun seluruh bukti lengkap, task berhenti
    di SUBMIT_RESULT dan menunggu Fahrul submit + (bila perlu) keputusan buyer.
    """
    if status in BUYER_DECISION_STATUSES:
        return "DONE"
    if has_exception:
        return "WORK_REVISION"
    if not state.get("sample_request"):
        return "OPEN"
    if not state.get("ppm_version"):
        return "IN_PROGRESS"
    if not state.get("evidence_progress"):
        return "UPDATE"
    if not state.get("evidence_inspection"):
        return "INSPECTION"
    if not state.get("evidence_result") or not state.get("version_submitted"):
        return "SUBMIT_RESULT"
    return "SUBMIT_RESULT"


def _next_action(stage, state, buyer_decided):
    if buyer_decided:
        return "Menunggu CMO_MANAGER mencatat/menindaklanjuti keputusan buyer"
    return {
        "OPEN": "Mulai kerjakan sample (START)",
        "IN_PROGRESS": "Update progres sample",
        "UPDATE": "Unggah bukti progres sample",
        "INSPECTION": "Unggah bukti inspeksi sample",
        "SUBMIT_RESULT": "Submit hasil + bukti akhir ke CMO",
        "WORK_REVISION": "Perbaiki temuan exception lalu unggah bukti ulang",
        "DONE": "Selesai — menunggu keputusan buyer CMO_MANAGER",
    }.get(stage, "Periksa sample")


def _sla(due):
    if due is None:
        return {"due": None, "remaining_days": None, "state": "NO_SLA", "label": "SLA belum ditetapkan Master"}
    remaining = (due - date.today()).days
    if remaining < 0:
        state, label = "OVERDUE", f"Terlambat {abs(remaining)} hari"
    elif remaining == 0:
        state, label = "DUE_TODAY", "Jatuh tempo hari ini"
    elif remaining <= SLA_SOON_DAYS:
        state, label = "DUE_SOON", f"{remaining} hari lagi"
    else:
        state, label = "ON_TRACK", f"{remaining} hari lagi"
    return {"due": _iso(due), "remaining_days": remaining, "state": state, "label": label}


def _sample_blocker(sample, order, ppm_version):
    """Blocker + owner-nya. Blocker bukan pekerjaan sample milik Fahrul tetap
    tugas PIC-nya, tetapi tidak boleh di-upload-ulang oleh Fahrul."""
    if sample.status in BUYER_DECISION_STATUSES:
        return None
    if not ppm_version:
        return {"blocker": "Sample Request / versi PPM-mockup belum eligible",
                "blocker_owner": "CMO_MANAGER"}
    if not _evidence_flags(sample.evidence or [], ppm_version)["evidence_progress"]:
        return {"blocker": "Bukti sample belum diunggah", "blocker_owner": "SAMPLE_PIC"}
    if order is not None and order.finance_status not in {"PAID", "CLEAR", "READY"}:
        return {"blocker": "Gate pembayaran order belum lolos", "blocker_owner": "CFO_MANAGER"}
    return None


def _sample_exceptions(db, sample_ids):
    """Exception sample milik satu kumpulan sample (source_entity='SampleRecord')."""
    ids = [i for i in sample_ids if i is not None]
    if not ids:
        return {}
    rows = (db.query(m.ExceptionItem)
            .filter(m.ExceptionItem.source_entity == "SampleRecord",
                    m.ExceptionItem.source_entity_id.in_(ids),
                    m.ExceptionItem.confidential.is_(False),
                    m.ExceptionItem.status.in_(["OPEN", "IN_PROGRESS"]))
            .order_by(m.ExceptionItem.id.asc()).all())
    result = {}
    for row in rows:
        result.setdefault(row.source_entity_id, []).append(row)
    return result


def _exception_block(row):
    category = (row.category or "").lower()
    owner = row.owner_role or "SAMPLE_PIC"
    return {
        "exception_id": row.id,
        "category": row.category,
        "severity": row.severity,
        "status": row.status,
        "problem": row.title,
        "owner": owner,
        "due": _iso(row.due_date),
        "next_action": row.next_action,
        "escalation": row.escalation_reason,
        "resolution": row.resolution_note,
        "can_edit": owner in {"SAMPLE_PIC", "SAMPLE"},
        "can_escalate": owner not in {"SAMPLE_PIC", "SAMPLE"},
        # SMP-F-007: resolve/override bukan milik Sample PIC.
        "can_resolve": False,
        "scope": "SAMPLE",
    }


def _build_rows(db, user):
    """Satu baris per (article x sample version) — dipakai kedua endpoint.

    Read-only: tidak ada satu pun penulisan di sini, sehingga Fahrul tidak bisa
    menyentuh keputusan buyer dari modul ini.
    """
    articles = (db.query(m.Article)
                .options(selectinload(m.Article.order))
                .order_by(m.Article.id.asc()).all())
    samples = (db.query(m.SampleRecord)
               .options(selectinload(m.SampleRecord.evidence))
               .order_by(m.SampleRecord.id.asc()).all())

    by_article = {}
    by_pair = {}
    for sample in samples:
        if sample.article_id is not None:
            by_article.setdefault(sample.article_id, []).append(sample)
        by_pair.setdefault((sample.order_fk, sample.article_code), []).append(sample)

    # Urutan versi sample per artikel/artikel-code: v1, v2, dst.
    versions = {}
    for sample in samples:
        key = (sample.order_fk, sample.article_id, sample.article_code)
        versions[key] = versions.get(key, 0) + 1
        sample._sample_version = versions[key]

    exception_map = _sample_exceptions(db, [s.id for s in samples])

    rows = []
    handled_samples = set()
    for article in articles:
        order = article.order
        candidates = []
        if article.id in by_article:
            candidates.extend(by_article[article.id])
        for sample in by_pair.get((article.order_fk, article.article_code), []):
            if sample.article_id is None:
                candidates.append(sample)

        needed = _perlu_sample(article)
        if not candidates:
            # SMP-F-003: artikel yang butuh sample tapi belum punya Sample Request.
            # Sistem harus MEMBUAT task CREATE SAMPLE untuk Fahrul dari routing,
            # bukan menunggu input ulang CMO; server tetap melaporkan alasannya.
            eligible = bool(needed)
            rows.append(_row(
                article=article, order=order, sample=None, sample_version=None,
                eligible=eligible, ppm_version=None, exceptions=[],
                reason=(
                    "Perlu Sample = YA, Sample Request belum dibuat — sistem membuat task CREATE SAMPLE untuk Sample PIC"
                    if eligible
                    else "Article ini tidak butuh sample (Perlu Sample = TIDAK)"
                ),
                required_action="CREATE_SAMPLE" if eligible else None,
            ))
            continue

        for sample in candidates:
            handled_samples.add(sample.id)
            ppm_version = _ppm_versions(sample.notes)
            rows.append(_row(
                article=article, order=order, sample=sample,
                sample_version=getattr(sample, "_sample_version", 1),
                eligible=bool(needed and ppm_version),
                ppm_version=ppm_version,
                exceptions=exception_map.get(sample.id, []),
                reason=(
                    "Order & Article valid, Sample Request ada, versi PPM/mockup eligible"
                    if needed and ppm_version
                    else "Article ini tidak butuh sample (Perlu Sample = TIDAK)" if not needed
                    else "Sample Request belum punya versi PPM/mockup eligible"
                ),
                required_action=None,
            ))

    # Sample Record yang artikelnya sudah tidak ada (mis. article_code yatim).
    for sample in samples:
        if sample.id in handled_samples:
            continue
        order = db.get(m.Order, sample.order_fk)
        article = m.Article(order_fk=sample.order_fk, article_code=sample.article_code,
                            qty=0, sample_required=True, sample_status="REQUIRED")
        ppm_version = _ppm_versions(sample.notes)
        rows.append(_row(
            article=article, order=order, sample=sample,
            sample_version=getattr(sample, "_sample_version", 1),
            eligible=bool(ppm_version), ppm_version=ppm_version,
            exceptions=exception_map.get(sample.id, []),
            reason=("Sample Request ada, versi PPM/mockup eligible" if ppm_version
                    else "Article ID pada Sample Request tidak ditemukan di order"),
            required_action=None,
        ))
    return rows


def _row(*, article, order, sample, sample_version, eligible, ppm_version,
         exceptions, reason, required_action):
    state = {
        "sample_request": sample is not None,
        "ppm_version": bool(ppm_version),
        "evidence_progress": False,
        "evidence_inspection": False,
        "evidence_result": False,
        "version_submitted": bool(ppm_version and ppm_version.get("submitted")),
    }
    if sample is not None:
        state.update(_evidence_flags(sample.evidence or [], ppm_version))

    status = sample.status if sample is not None else ("NOT_STARTED" if required_action else "NOT_REQUIRED")
    buyer_decided = bool(sample is not None and sample.status in BUYER_DECISION_STATUSES)
    has_exception = bool(exceptions) and not buyer_decided
    stage = _lifecycle(status, state, has_exception)
    due = order.buyer_deadline if order is not None else None
    if sample is not None and sample.completed_date is not None:
        due = sample.completed_date
    blocker = _sample_blocker(sample, order, ppm_version) if sample is not None else (
        {"blocker": "Sample Request belum dibuat", "blocker_owner": "CMO_MANAGER"}
        if eligible else None
    )
    # SMP-F-007: exception sample yang jadi milik PIC adalah blocker miliknya,
    # bukan "bukti belum diunggah" — supaya owner blocker di baris tetap benar.
    if has_exception:
        owned = [row for row in exceptions
                 if (row.owner_role or "SAMPLE_PIC") in {"SAMPLE_PIC", "SAMPLE"}]
        blame = owned[0] if owned else exceptions[0]
        blocker = {
            "blocker": f"Exception {blame.category}: {blame.title}",
            "blocker_owner": blame.owner_role or "SAMPLE_PIC",
        }

    task_id = (f"SMP-{sample.id}" if sample is not None
               else f"SMP-NEW-{article.order_fk}-{article.id}")
    requirement_state = _requirements(state)
    return {
        "task_id": task_id,
        "kind": "SAMPLE_WORK",
        "sample_id": sample.id if sample is not None else None,
        "sample_fk": sample.id if sample is not None else None,
        "sample_version": sample_version,
        "order_id": order.order_id if order is not None else None,
        "order_fk": order.id if order is not None else article.order_fk,
        "buyer": order.buyer if order is not None else None,
        "article_id": article.id,
        "article_code": article.article_code,
        "order_article_id": article.id,
        "priority": "HIGH" if (due is not None and (due - date.today()).days < 0) else "NORMAL",
        "eligible": bool(eligible),
        "eligibility_reason": reason,
        "required_action": required_action,
        "sample_work_status": status,
        "stage": stage,
        "next_action": _next_action(stage, state, buyer_decided),
        "sla": _sla(due),
        "evidence": _evidence_completeness(state) if sample is not None else
                    {"uploaded": 0, "required": 3, "complete": False,
                     "missing": ["evidence_progress", "evidence_inspection", "evidence_result"]},
        "requirements": requirement_state,
        "blocker": blocker["blocker"] if blocker else None,
        "blocker_owner": blocker["blocker_owner"] if blocker else None,
        "owner": "SAMPLE_PIC",
        "handoff": "Keputusan buyer dicatat CMO_MANAGER (BUYER_APPROVE/BUYER_REJECT)",
        # Keputusan buyer = read-only untuk Fahrul.
        "buyer_decision": {
            "decided": buyer_decided,
            "status": sample.status if sample is not None else None,
            "decided_by_id": sample.customer_approved_by_id if sample is not None else None,
            "decided_at": _iso(sample.customer_decision_at) if sample is not None else None,
            "reason": sample.customer_decision_reason if sample is not None else None,
            "readonly": True,
            "owner": "CMO_MANAGER",
        },
        "exceptions": [_exception_block(row) for row in exceptions],
        "updated_at": _iso(sample.created_at) if sample is not None
                      else _iso(order.updated_at if order is not None else None),
        # Pagar eksplisit: aksi yang boleh/tidak boleh dipanggil Fahrul.
        "allowed_actions": list(SAMPLE_WORK_ACTIONS),
        "denied_actions": list(BUYER_DECISION_ACTIONS),
    }


def _summary(rows):
    today = date.today()
    buckets = {
        "not_started": [r for r in rows if r["stage"] == "OPEN" and r["eligible"]],
        "in_progress": [r for r in rows if r["stage"] in {"IN_PROGRESS", "UPDATE", "INSPECTION"}],
        "waiting_revision": [r for r in rows if r["stage"] == "WORK_REVISION"],
        "ready_to_handoff": [r for r in rows if r["stage"] == "SUBMIT_RESULT"],
        "buyer_decided": [r for r in rows if r["buyer_decision"]["decided"]],
    }
    overdue = [r for r in rows if r["sla"]["state"] == "OVERDUE" and not r["buyer_decision"]["decided"]]
    blocked = [r for r in rows if r["blocker"]]
    eligible = [r for r in rows if r["eligible"]]
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "today": today.isoformat(),
        "buckets": {key: len(value) for key, value in buckets.items()},
        "overdue": len(overdue),
        "blocked": len(blocked),
        "total_eligible": len(eligible),
        "total_rows": len(rows),
        "my_sample_tasks": len([r for r in rows if r["sample_id"] is not None]),
        "create_sample_tasks": len([r for r in rows if r["required_action"] == "CREATE_SAMPLE"]),
    }


# ────────────────────────────── endpoints ──────────────────────────────
@router.get("/today")
def sample_today(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Landing action-first Sample PIC (SMP-F-001 / revisi #31).

    Lima bagian sesuai blueprint: belum mulai, sedang dikerjakan, menunggu
    revisi, siap diserahkan, terlambat. Setiap baris memuat Sample ID, Order ID,
    Article ID, version, prioritas, next action, SLA/due, evidence completeness,
    blocker, owner, dan handoff.
    """
    _require_view(user)
    rows = _build_rows(db, user)
    today = date.today()
    # Nama variabel sengaja bukan `sections`: pemakaian lambda di dalam
    # comprehension akan menangkap nama itu, bukan field hasil.
    buckets = [
        ("NOT_STARTED", "Belum Mulai", [r for r in rows if r["stage"] == "OPEN" and r["eligible"]]),
        # "Sedang Dikerjakan" mencakup seluruh tahap kerja aktif (IN_PROGRESS,
        # UPDATE, INSPECTION) dan SUBMIT_RESULT sengaja dipisah agar baris yang
        # sudah siap diserahkan tidak tercampur dengan yang masih dikerjakan.
        ("IN_PROGRESS", "Sedang Dikerjakan",
         [r for r in rows if r["stage"] in {"IN_PROGRESS", "UPDATE", "INSPECTION"}]),
        ("WAITING_REVISION", "Menunggu Revisi", [r for r in rows if r["stage"] == "WORK_REVISION"]),
        ("READY_TO_HANDOFF", "Siap Diserahkan", [r for r in rows if r["stage"] == "SUBMIT_RESULT"]),
        ("OVERDUE", "Terlambat", [r for r in rows if r["sla"]["state"] == "OVERDUE"
                                  and not r["buyer_decision"]["decided"]]),
    ]
    return {
        **_summary(rows),
        "sections": [{"key": key, "label": label, "rows": value} for key, label, value in buckets],
        "not_eligible": [r for r in rows if not r["eligible"]],
        # Pagar akses yang ditampilkan ke UI (ditegakkan juga di server).
        "access": _access_contract(),
    }


@router.get("/my-tasks")
def my_sample_tasks(status: str = None, order_id: str = None,
                    db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Antrean kerja sample Fahrul (SMP-F-005 / revisi #35).

    Berasal otomatis dari routing order/article yang eligible. SLA dari Master.
    Task tidak DONE tanpa sample version submitted + seluruh required evidence.
    """
    _require_view(user)
    rows = _build_rows(db, user)
    if status:
        wanted = status.upper()
        rows = [r for r in rows if r["stage"] == wanted or r["sample_work_status"] == wanted]
    if order_id:
        rows = [r for r in rows if (r["order_id"] or "").lower() == order_id.lower()]
    rows.sort(key=lambda r: (
        r["sla"]["remaining_days"] if r["sla"]["remaining_days"] is not None else 10 ** 6,
        r["order_id"] or "",
        r["article_code"] or "",
    ))
    return {
        **_summary(rows),
        "tasks": rows,
        "lifecycle": list(LIFECYCLE),
        "sla_source": "Master (buyer_deadline order / completed_date sample) — bukan input Sample PIC",
        "access": _access_contract(),
    }


def _access_contract():
    """Batas akses yang berlaku untuk Sample PIC (SMP-F-002 & SMP-F-007)."""
    return {
        "role": "SAMPLE_PIC",
        "can": list(SAMPLE_WORK_ACTIONS),
        "cannot": [
            "BUYER_APPROVE", "BUYER_REJECT",
            "RELEASE_SPK", "PRODUCTION_BULK", "PURCHASE_ORDER", "GOODS_RECEIPT",
            "FINANCE_ACTION", "DELIVERY_EXECUTION", "CLOSE_ORDER",
            "EXCEPTION_RESOLVE", "EXCEPTION_OVERRIDE",
        ],
        "buyer_decision_owner": "CMO_MANAGER",
        "sample_decision_denied": True,
        "note": ("Pekerjaan sample (start/update/inspeksi/unggah bukti/submit hasil) "
                 "milik Sample PIC. Keputusan buyer APPROVED/REJECTED milik CMO_MANAGER "
                 "dan hanya tampil read-only di sini."),
    }
