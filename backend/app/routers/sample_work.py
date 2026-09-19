"""Sample PIC (Fahrul) work surface — Sample Today, My Sample Tasks & eligibility.

Blueprint: SMP-F-001 (#31), SMP-F-002 (#32), SMP-F-003 (#33), SMP-F-005 (#35),
SMP-F-007 (#37).

Sumber kebenaran (revisi #31-#39, batch 2)
------------------------------------------
Versi sample, jenis bukti, relasi exception, dan task CREATE_SAMPLE kini
dibaca/ditulis ke kolom & tabel eksplisit bila ada:

* ``sample_versions`` / ``sample_records.sample_version`` → versi eksplisit.
* ``sample_evidence.evidence_kind`` → klasifikasi bukti tersimpan, bukan tebakan.
* ``exceptions.sample_fk`` / ``exceptions.sample_version`` → ikatan langsung ke
  sample (dan versinya bila kolomnya ada).
* ``sample_tasks`` + ``sample_task_prerequisites`` → task CREATE_SAMPLE
  dipersist sebagai baris DB.

Bila kolom/tabel itu BELUM ada (schema agent belum mendarat), modul ini
memakai fallback heuristik dan **menandainya dengan jujur**: setiap baris
membawa ``data_source`` + ``write_support`` dan setiap fallback yang terpakai
muncul di ``heuristics_active``. Tidak ada fallback yang diam-diam.

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
from sqlalchemy import inspect as sa_inspect
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
# LEGACY FALLBACK saja — dipakai HANYA untuk evidence lama yang belum punya
# `evidence_kind`, dan hasilnya ditandai `fallback` + nama file yang tidak
# terklasifikasi (mis. IMG_2231.pdf) supaya tidak menyamar sebagai data pasti.
INSPECTION_HINTS = ("inspeksi", "inspection", "qc", "periksa")
RESULT_HINTS = ("hasil", "result", "final", "kirim", "submit")

# Jenis bukti yang sah — sejajar dengan `sample_evidence.evidence_kind`.
EVIDENCE_KINDS = ("PROGRESS", "INSPECTION", "RESULT")

# Tahap lifecycle task eksplisit pada `sample_tasks.stage`, beserta aksi
# sahnya (revisi #35). Bila tabel `sample_tasks` sudah ada, tahap dibaca dari
# sana — bukan disimpulkan ulang dari kelengkapan bukti.
TASK_STAGES = ("OPEN", "IN_PROGRESS", "UPDATE", "INSPECTION", "SUBMIT_RESULT", "DONE",
               "WORK_REVISION", "CREATE_SAMPLE")

# Status task pada `sample_tasks.status`.
TASK_STATUSES = ("OPEN", "IN_PROGRESS", "DONE", "BLOCKED", "CANCELLED")

# Kolom-kolom kunci yang harus ada sebelum modul ini "berbicara eksplisit".
# Diperiksa sekali per proses lewat `schema_capabilities()`.
REQUIRED_COLUMNS = {
    "sample_records": ("sample_version", "previous_version_id", "revision_reason",
                       "submitted_by_id", "submitted_at"),
    "sample_evidence": ("evidence_kind", "sample_version"),
}
REQUIRED_TABLES = ("sample_versions", "sample_tasks", "sample_task_prerequisites")

# Kategori exception yang menjadi milik pekerjaan sample (SMP-F-007).
SAMPLE_EXCEPTION_HINTS = ("sample", "ppm", "mockup", "bahan sample", "artwork")

# Lead time pengingat SLA (hari) — dipakai untuk menandai "segera".
SLA_SOON_DAYS = 2


# ────────────────────────────── helpers ──────────────────────────────
def _role(user):
    return user.role.value if hasattr(user.role, "value") else str(user.role)


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


def _require_view(user):
    if _role(user) not in VIEW_ROLES:
        raise HTTPException(403, "Antrean kerja Sample PIC tidak tersedia untuk peran ini.")


# ─────────────────────── schema capabilities (batch 2) ───────────────────────
_CAPS_CACHE = {}


def schema_capabilities(db):
    """Kolom/tabel eksplisit mana yang BENAR-BENAR ada di schema saat ini.

    Dipakai supaya modul ini membaca kolom eksplisit begitu schema agent
    mendarat, tanpa perlu diubah lagi — dan supaya fallback heuristik bisa
    dilaporkan terbuka, bukan disembunyikan.
    """
    key = db.get_bind()
    key = (id(key), str(getattr(key, "url", key)))
    if key in _CAPS_CACHE:
        return _CAPS_CACHE[key]

    caps = {"columns": {}, "tables": {}}
    try:
        inspector = sa_inspect(db.get_bind())
        table_names = set(inspector.get_table_names())
        for table, columns in REQUIRED_COLUMNS.items():
            if table not in table_names:
                caps["columns"][table] = {column: False for column in columns}
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            caps["columns"][table] = {column: column in present for column in columns}
        for table in REQUIRED_TABLES:
            caps["tables"][table] = table in table_names
    except Exception:  # pragma: no cover — DB tak terjangkau: pakai fallback
        for table, columns in REQUIRED_COLUMNS.items():
            caps["columns"][table] = {column: False for column in columns}
        caps["tables"].update({table: False for table in REQUIRED_TABLES})

    _CAPS_CACHE[key] = caps
    return caps


def _column_present(db, table, column):
    return bool(schema_capabilities(db)["columns"].get(table, {}).get(column))


def _table_present(db, table):
    return bool(schema_capabilities(db)["tables"].get(table))


def _explicit_version(db, sample):
    """Versi eksplisit dari `sample_records.sample_version` (batch 2).

    Mengembalikan None bila kolomnya belum ada ATAU belum diisi (data lama),
    supaya pemanggil bisa memakai fallback turunan-id dan menandainya.
    """
    if not _column_present(db, "sample_records", "sample_version"):
        return None
    value = getattr(sample, "sample_version", None)
    return int(value) if value else None


def _explicit_revision_reason(db, sample):
    if not _column_present(db, "sample_records", "revision_reason"):
        return None
    return getattr(sample, "revision_reason", None)


def _explicit_submission(db, sample):
    """Submission/handoff eksplisit (#34), bukan tebakan dari completed_date."""
    if not _column_present(db, "sample_records", "submitted_at"):
        return None, None
    return getattr(sample, "submitted_at", None), getattr(sample, "submitted_by_id", None)


def _version_sources(db):
    """Dari mana versi/task/bukti/exception dibaca — untuk dilaporkan ke UI."""
    return {
        "sample_version": ("sample_records.sample_version"
                           if _column_present(db, "sample_records", "sample_version")
                           else "DERIVED_FROM_ID_ORDER"),
        "sample_versions_table": _table_present(db, "sample_versions"),
        "evidence_kind": ("sample_evidence.evidence_kind"
                          if _column_present(db, "sample_evidence", "evidence_kind")
                          else "LEGACY_SUBSTRING_HEURISTIC"),
        "evidence_version": ("sample_evidence.sample_version"
                             if _column_present(db, "sample_evidence", "sample_version")
                             else "NOT_STORED"),
        "exception_link": ("exceptions.sample_fk"
                           if _column_present(db, "exceptions", "sample_fk")
                           else "LEGACY_SOURCE_ENTITY_STRING"),
        "task_store": ("sample_tasks" if _table_present(db, "sample_tasks")
                       else "EPHEMERAL_NOT_PERSISTED"),
        "prerequisite_store": ("sample_task_prerequisites"
                               if _table_present(db, "sample_task_prerequisites")
                               else "EPHEMERAL_NOT_PERSISTED"),
        "revision_reason": ("sample_records.revision_reason"
                            if _column_present(db, "sample_records", "revision_reason")
                            else "NOT_STORED"),
        "submission": ("sample_records.submitted_at/submitted_by_id"
                       if _column_present(db, "sample_records", "submitted_at")
                       else "DERIVED_FROM_completed_date"),
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


def _legacy_kind_of(row):
    """Tebakan jenis bukti untuk data LAMA (fallback, bukan sumber kebenaran).

    Hanya menyentuh `file_name`/`note` karena kolom `evidence_kind` belum ada
    atau belum diisi. Nama file seperti ``IMG_2231.pdf`` tidak bisa
    diklasifikasikan — itu dilaporkan sebagai ``unclassified``, bukan dipaksa
    masuk salah satu keranjang.
    """
    names = f"{row.file_name or ''} {row.note or ''}".lower()
    if any(hint in names for hint in INSPECTION_HINTS):
        return "INSPECTION", True
    if any(hint in names for hint in RESULT_HINTS):
        return "RESULT", True
    return None, False


def _evidence_kinds(db, evidence):
    """Jenis tiap bukti + sumbernya: kolom eksplisit dulu, fallback ditandai.

    Mengembalikan ``(kinds, fallback_used, fallback_rows, unclassified)``:
    * ``kinds``          → {evidence_id: "PROGRESS"|"INSPECTION"|"RESULT"|None}
    * ``fallback_used``  → True bila minimal satu baris dibaca lewat tebakan nama
    * ``fallback_rows``  → daftar {evidence_id, file_name, guessed_kind} hasil tebakan
    * ``unclassified``   → nama file yang bahkan tebakan pun tidak yakin
    """
    explicit = _column_present(db, "sample_evidence", "evidence_kind")
    kinds, fallback_rows, unclassified = {}, [], []
    fallback_used = False
    for row in evidence:
        kind = getattr(row, "evidence_kind", None) if explicit else None
        source = "COLUMN"
        if kind:
            kind = str(kind).upper()
            if kind not in EVIDENCE_KINDS:
                kind, source = None, "INVALID_COLUMN_VALUE"
        if not kind:
            guessed, sure = _legacy_kind_of(row)
            source = "HEURISTIC_SUBSTRING" if sure else "UNCLASSIFIED"
            fallback_used = True
            if sure:
                kind = guessed
                fallback_rows.append({"evidence_id": row.id, "file_name": row.file_name,
                                      "guessed_kind": guessed, "source": source})
            else:
                unclassified.append(row.file_name)
        kinds[row.id] = kind
    return kinds, fallback_used, fallback_rows, unclassified


def _evidence_version_of(db, row):
    """Versi sample yang diikat sebuah bukti (kolom `sample_version`, #34)."""
    if not _column_present(db, "sample_evidence", "sample_version"):
        return None
    value = getattr(row, "sample_version", None)
    return int(value) if value else None


def _evidence_flags(db, evidence, ppm_version, version=None):
    """Kategori bukti yang sudah diunggah — dasar evidence completeness.

    Bukti dibaca dari kolom eksplisit `evidence_kind`; tebakan lama hanya
    dipakai bila kolomnya tidak ada/kosong DAN hasilnya selalu ikut dilaporkan
    lewat `_evidence_kinds()`. Bila `version` diberikan, bukti milik versi lain
    tidak dihitung (revisi #34: bukti terikat ke versi sample).
    """
    rows = list(evidence or [])
    if version is not None:
        versioned = [row for row in rows if _evidence_version_of(db, row) is not None]
        if versioned:
            rows = [row for row in rows
                    if _evidence_version_of(db, row) in (None, int(version))]
        versioned = None
    kinds, fallback_used, fallback_rows, unclassified = _evidence_kinds(db, rows)
    kind_values = set(kinds.values())
    return {
        "evidence_progress": len(rows) > 0,
        "evidence_inspection": "INSPECTION" in kind_values,
        "evidence_result": "RESULT" in kind_values,
        "version_submitted": bool(ppm_version and ppm_version.get("submitted")),
        "_kinds": kinds,
        "_fallback_used": fallback_used,
        "_fallback_rows": fallback_rows,
        "_unclassified": unclassified,
    }


def _prune_flags(flags):
    return {key: value for key, value in flags.items() if not key.startswith("_")}


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


def _sample_blocker(db, sample, order, ppm_version):
    """Blocker + owner-nya. Blocker bukan pekerjaan sample milik Fahrul tetap
    tugas PIC-nya, tetapi tidak boleh di-upload-ulang oleh Fahrul."""
    if sample.status in BUYER_DECISION_STATUSES:
        return None
    if not ppm_version:
        return {"blocker": "Sample Request / versi PPM-mockup belum eligible",
                "blocker_owner": "CMO_MANAGER"}
    if not _evidence_flags(db, sample.evidence or [], ppm_version)["evidence_progress"]:
        return {"blocker": "Bukti sample belum diunggah", "blocker_owner": "SAMPLE_PIC"}
    if order is not None and order.finance_status not in {"PAID", "CLEAR", "READY"}:
        return {"blocker": "Gate pembayaran order belum lolos", "blocker_owner": "CFO_MANAGER"}
    return None


def _sample_exceptions(db, sample_ids):
    """Exception sample milik satu kumpulan sample.

    Batch 2: bila kolom eksplisit `exceptions.sample_fk` sudah ada, ikatan
    dibaca dari sana (dan versinya dari `exceptions.sample_version`). Kalau
    belum, fallback lama `source_entity='SampleRecord' + source_entity_id`
    dipakai — dan pemakaian fallback itu ditandai di `_version_sources()`.
    """
    ids = [i for i in sample_ids if i is not None]
    if not ids:
        return {}
    query = db.query(m.ExceptionItem)
    if _column_present(db, "exceptions", "sample_fk"):
        query = query.filter(m.ExceptionItem.sample_fk.in_(ids))
    else:
        query = query.filter(m.ExceptionItem.source_entity == "SampleRecord",
                             m.ExceptionItem.source_entity_id.in_(ids))
    rows = (query
            .filter(m.ExceptionItem.confidential.is_(False),
                    m.ExceptionItem.status.in_(["OPEN", "IN_PROGRESS"]))
            .order_by(m.ExceptionItem.id.asc()).all())
    explicit = _column_present(db, "exceptions", "sample_fk")
    result = {}
    for row in rows:
        link = getattr(row, "sample_fk", None) if explicit else None
        key = link if link is not None else row.source_entity_id
        result.setdefault(key, []).append(row)
    return result


def _exception_block(row, db=None):
    category = (row.category or "").lower()
    owner = row.owner_role or "SAMPLE_PIC"
    scope = "SAMPLE"
    if db is not None and _column_present(db, "exceptions", "scope"):
        scope = getattr(row, "scope", None) or "SAMPLE"
    exception_version = getattr(row, "sample_version", None) if db is not None else None
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
        "scope": scope,
        # Revisi #37: exception bisa diikat ke VERSI sample tertentu.
        "sample_fk": getattr(row, "sample_fk", None) if db is not None else None,
        "sample_version": exception_version,
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
    #
    # Batch 2: kolom eksplisit `sample_records.sample_version` menang. Urutan
    # `id` hanya dipakai sebagai fallback untuk data lama, dan pemakaian
    # fallback itu dicatat di `heuristic_flags` supaya bisa dilaporkan.
    explicit_version = _column_present(db, "sample_records", "sample_version")
    heuristic_flags = {"version_from_id_order": False, "evidence_kind_guessed": False}
    version_chain = {}      # urutan fallback per (order, article)
    sample_version_by_id = {}

    for sample in samples:
        # Kolom eksplisit menang; urutan `id` hanya fallback data lama dan
        # pemakaiannya dicatat supaya bisa dilaporkan terbuka.
        explicit = getattr(sample, "sample_version", None) if explicit_version else None
        if explicit:
            sample_version_by_id[sample.id] = int(explicit)
            sample._sample_version_source = "COLUMN"
            continue
        heuristic_flags["version_from_id_order"] = True
        key = (sample.order_fk, sample.article_id, sample.article_code)
        version_chain[key] = version_chain.get(key, 0) + 1
        sample_version_by_id[sample.id] = version_chain[key]
        sample._sample_version_source = "DERIVED_FROM_ID_ORDER"

    exception_map = _sample_exceptions(db, [s.id for s in samples])
    heuristic_flags["exception_link_legacy"] = not _column_present(db, "exceptions", "sample_fk")

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
                db=db,
            ))
            continue

        for sample in candidates:
            handled_samples.add(sample.id)
            ppm_version = _ppm_versions(sample.notes)
            rows.append(_row(
                article=article, order=order, sample=sample,
                sample_version=_sample_version_no(sample, sample_version_by_id),
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
                db=db,
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
            sample_version=_sample_version_no(sample, sample_version_by_id),
            eligible=bool(ppm_version), ppm_version=ppm_version,
            exceptions=exception_map.get(sample.id, []),
            reason=("Sample Request ada, versi PPM/mockup eligible" if ppm_version
                    else "Article ID pada Sample Request tidak ditemukan di order"),
            required_action=None,
            db=db,
        ))
    return rows


def _row(*, article, order, sample, sample_version, eligible, ppm_version,
         exceptions, reason, required_action, db=None):
    # Panggilan lama `_row(...)` tanpa `db` tetap jalan (helper internal);
    # seluruh pemanggil di modul ini meneruskan `db` supaya kolom eksplisit
    # benar-benar dibaca.
    state = {
        "sample_request": sample is not None,
        "ppm_version": bool(ppm_version),
        "evidence_progress": False,
        "evidence_inspection": False,
        "evidence_result": False,
        "version_submitted": bool(ppm_version and ppm_version.get("submitted")),
    }
    if sample is not None and db is not None:
        state.update(_evidence_flags(db, sample.evidence or [], ppm_version,
                                     version=sample_version))
    elif sample is not None:
        state.update({key: value for key, value in
                      _evidence_flags_offline(sample.evidence or [], ppm_version).items()
                      if not key.startswith("_")})

    status = sample.status if sample is not None else ("NOT_STARTED" if required_action else "NOT_REQUIRED")
    buyer_decided = bool(sample is not None and sample.status in BUYER_DECISION_STATUSES)
    has_exception = bool(exceptions) and not buyer_decided
    stage = _lifecycle(status, state, has_exception)
    due = order.buyer_deadline if order is not None else None
    if sample is not None and sample.completed_date is not None:
        due = sample.completed_date
    blocker = _sample_blocker(db, sample, order, ppm_version) if sample is not None else (
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
    version_source = (getattr(sample, "_sample_version_source", None) if sample is not None
                      else None)

    if db is not None:
        kinds, kind_fallback, kind_guess, kind_unclassified = _evidence_kinds(
            db, sample.evidence or []) if sample is not None else ({}, False, [], [])
    else:
        kinds, kind_fallback, kind_guess, kind_unclassified = {}, True, [], []

    payload = {
        "task_id": task_id,
        "kind": "SAMPLE_WORK",
        "sample_id": sample.id if sample is not None else None,
        "sample_fk": sample.id if sample is not None else None,
        "sample_version": sample_version,
        "sample_version_source": version_source or ("NOT_STORED" if sample is not None else None),
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
        "evidence_kinds": ({str(key): value for key, value in kinds.items()}
                           if sample is not None else {}),
        "evidence_kind_source": ("sample_evidence.evidence_kind" if not kind_fallback
                                 else "LEGACY_SUBSTRING_HEURISTIC"),
        "evidence_unclassified": kind_unclassified,
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
        "exceptions": [_exception_block(row, db) for row in exceptions],
        "updated_at": _iso(sample.created_at) if sample is not None
                      else _iso(order.updated_at if order is not None else None),
        # Revisi #34/#38: alasan revisi & submission tersimpan, bukan tebakan.
        "revision_reason": (_explicit_revision_reason(db, sample)
                            if (db is not None and sample is not None) else None),
        "submitted_at": None,
        "submitted_by_id": None,
        # Pagar eksplisit: aksi yang boleh/tidak boleh dipanggil Fahrul.
        "allowed_actions": list(SAMPLE_WORK_ACTIONS),
        "denied_actions": list(BUYER_DECISION_ACTIONS),
    }

    if sample is not None and db is not None:
        submitted_at, submitted_by = _explicit_submission(db, sample)
        payload["submitted_at"] = _iso(submitted_at or sample.completed_date)
        payload["submitted_by_id"] = submitted_by
        payload["submitted_at_source"] = ("COLUMN" if submitted_at is not None
                                          else "DERIVED_FROM_completed_date")
    elif sample is not None:
        payload["submitted_at"] = _iso(sample.completed_date)
        payload["submitted_at_source"] = "DERIVED_FROM_completed_date"

    # Batch 2: task CREATE_SAMPLE dipersist ke `sample_tasks` + prasyaratnya.
    if db is not None and required_action == "CREATE_SAMPLE" and eligible:
        task = _persist_create_sample_task(db, payload)
        payload.update(task)
    return payload


def _evidence_flags_offline(evidence, ppm_version):
    """`_evidence_flags` untuk pemanggil tanpa sesi DB (fallback, ditandai)."""
    names = " ".join(f"{(row.file_name or '')} {(row.note or '')}".lower()
                     for row in evidence)
    return {
        "evidence_progress": len(evidence) > 0,
        "evidence_inspection": any(hint in names for hint in INSPECTION_HINTS),
        "evidence_result": any(hint in names for hint in RESULT_HINTS),
        "version_submitted": bool(ppm_version and ppm_version.get("submitted")),
    }


def _has_attr(model_or_class, name):
    return hasattr(model_or_class, name)


def _sample_version_no(sample, sample_version_by_id):
    """Nomor versi satu baris: kolom eksplisit dulu, fallback urutan `id`."""
    explicit = getattr(sample, "sample_version", None)
    if explicit:
        return int(explicit)
    return sample_version_by_id.get(sample.id) or getattr(sample, "_sample_version", 1)


# ─────────────────── task CREATE_SAMPLE → tabel `sample_tasks` ───────────────────
CREATE_SAMPLE_REQUIREMENTS = (
    ("sample_request", "Sample Request dibuat CMO untuk order/article ini"),
    ("ppm_version", "Versi PPM/mockup eligible tersedia"),
    ("article_routed", "Order & Article valid dan butuh sample"),
)


def _persist_create_sample_task(db, payload):
    """Tulis task CREATE_SAMPLE + prasyaratnya ke DB, idempoten.

    Dipanggil saat endpoint dibaca (routing order/article yang butuh sample
    tetapi belum punya Sample Request). Bila tabelnya belum ada, tidak ada yang
    ditulis dan fungsi mengembalikan ``persistence = NOT_PERSISTED`` apa adanya
    — bukan mengarang baris.
    """
    model = getattr(m, "SampleTask", None)
    if model is None or not _table_present(db, "sample_tasks"):
        return {
            "task_db_id": None,
            "task_no": None,
            "persistence": "BLOCKED_TABLE_ABSENT",
            "persisted_task": None,
        }

    article_id = payload.get("article_id")
    order_fk = payload.get("order_fk")
    existing = (db.query(model)
                .filter(model.order_fk == order_fk,
                        model.article_id == article_id,
                        model.required_action == "CREATE_SAMPLE")
                .order_by(model.id.asc()).first()
                if _has_attr(model, "required_action") else None)

    created = False
    if existing is None:
        values = {
            "stage": "OPEN",
            "status": "OPEN",
            "priority": payload.get("priority") or "NORMAL",
            "required_action": "CREATE_SAMPLE",
            "next_action": payload.get("next_action"),
            "handoff": payload.get("handoff"),
            "due_date": (db.get(m.Order, order_fk).buyer_deadline
                         if order_fk is not None and db.get(m.Order, order_fk) else None),
            "sla_source": "Master (buyer_deadline order)",
        }
        if _has_attr(model, "order_fk"):
            values["order_fk"] = order_fk
        if _has_attr(model, "article_id"):
            values["article_id"] = article_id
        if _has_attr(model, "article_code"):
            values["article_code"] = payload.get("article_code")
        if _has_attr(model, "sample_fk"):
            values["sample_fk"] = None
        if _has_attr(model, "sample_version"):
            values["sample_version"] = 1
        if _has_attr(model, "blocker_owner"):
            values["blocker_owner"] = "CMO_MANAGER"
        if _has_attr(model, "bottleneck_reason"):
            values["bottleneck_reason"] = "Sample Request belum dibuat CMO"
        task = model(**values)
        if _has_attr(model, "task_no"):
            task.task_no = f"SMP-NEW-{order_fk or 0}-{article_id or 0}"
        db.add(task)
        db.commit()
        db.refresh(task)
        existing = task
        created = True

    prerequisites = _persist_prerequisites(db, existing)
    return {
        "task_db_id": existing.id,
        "task_no": getattr(existing, "task_no", None),
        "persistence": "PERSISTED_CREATED" if created else "PERSISTED_EXISTING",
        "persisted_task": {
            "stage": getattr(existing, "stage", None),
            "status": getattr(existing, "status", None),
            "priority": getattr(existing, "priority", None),
            "blocker_owner": getattr(existing, "blocker_owner", None),
            "bottleneck_reason": getattr(existing, "bottleneck_reason", None),
        },
        "prerequisites": prerequisites,
    }


def _persist_prerequisites(db, task):
    """Prasyarat task CREATE_SAMPLE — jejak kapan & bukti apa yang memenuhi."""
    model = getattr(m, "SampleTaskPrerequisite", None)
    if model is None or not _table_present(db, "sample_task_prerequisites"):
        return {"store": "BLOCKED_TABLE_ABSENT", "rows": [], "satisfied": 0, "pending": 0}
    rows = []
    for key, label in CREATE_SAMPLE_REQUIREMENTS:
        row = (db.query(model)
               .filter(model.task_id == task.id, model.requirement_key == key)
               .first())
        if row is None:
            row = model(task_id=task.id, requirement_key=key, label=label,
                        satisfied=(key == "article_routed"))
            db.add(row)
            db.commit()
            db.refresh(row)
        rows.append(row)
    return {
        "store": "sample_task_prerequisites",
        "rows": [{"requirement_key": row.requirement_key, "label": row.label,
                  "satisfied": bool(row.satisfied),
                  "satisfied_at": _iso(row.satisfied_at)} for row in rows],
        "satisfied": sum(1 for row in rows if row.satisfied),
        "pending": sum(1 for row in rows if not row.satisfied),
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


def _data_source(db):
    """Laporan terbuka: mana yang tersimpan eksplisit, mana yang fallback."""
    sources = _version_sources(db)
    heuristics = [key for key, value in sources.items()
                  if isinstance(value, str) and value in {
                      "DERIVED_FROM_ID_ORDER", "LEGACY_SUBSTRING_HEURISTIC",
                      "LEGACY_SOURCE_ENTITY_STRING", "EPHEMERAL_NOT_PERSISTED",
                      "NOT_STORED", "DERIVED_FROM_completed_date"}]
    return {
        "sources": sources,
        "heuristics_active": heuristics,
        "write_support": {
            "create_sample_task": ("sample_tasks"
                                   if _table_present(db, "sample_tasks")
                                   else "BLOCKED_TABLE_ABSENT"),
            "task_prerequisites": ("sample_task_prerequisites"
                                   if _table_present(db, "sample_task_prerequisites")
                                   else "BLOCKED_TABLE_ABSENT"),
            "endpoint": "GET /api/sample/today & /api/sample/my-tasks (persist saat dibaca)",
        },
    }


def _persisted_tasks(db, rows):
    """Baca kembali task yang sudah tersimpan di `sample_tasks` (batch 2).

    Inilah bukti persistensi: baris yang punya `task_db_id` memang ada di DB,
    dan bila tabelnya sudah ada tetapi task belum tersimpan, itu dilaporkan
    sebagai `MISSING_IN_DB` — bukan didiamkan.
    """
    model = getattr(m, "SampleTask", None)
    if model is None or not _table_present(db, "sample_tasks"):
        return {"store": "BLOCKED_TABLE_ABSENT", "persisted": 0, "missing": [],
                "rows": []}
    persisted, missing, dump = 0, [], []
    for row in rows:
        if row.get("required_action") != "CREATE_SAMPLE" or not row.get("eligible"):
            continue
        task = (db.query(model)
                .filter(model.order_fk == row.get("order_fk"),
                        model.article_id == row.get("article_id"),
                        model.required_action == "CREATE_SAMPLE")
                .first())
        if task is None:
            missing.append(row.get("task_id"))
            continue
        persisted += 1
        row["task_db_id"] = task.id
        row["persistence"] = "PERSISTED"
        row["persisted_task"] = {
            "stage": getattr(task, "stage", None),
            "status": getattr(task, "status", None),
            "priority": getattr(task, "priority", None),
            "blocker_owner": getattr(task, "blocker_owner", None),
            "bottleneck_reason": getattr(task, "bottleneck_reason", None),
            "created_at": _iso(getattr(task, "created_at", None)),
        }
        prerequisites = (db.query(getattr(m, "SampleTaskPrerequisite"))
                         .filter(getattr(m, "SampleTaskPrerequisite").task_id == task.id)
                         .all()
                         if getattr(m, "SampleTaskPrerequisite", None) is not None
                         and _table_present(db, "sample_task_prerequisites") else [])
        row["prerequisites"] = {
            "store": "sample_task_prerequisites" if prerequisites else "BLOCKED_TABLE_ABSENT",
            "rows": [{"requirement_key": p.requirement_key, "label": p.label,
                      "satisfied": bool(p.satisfied), "satisfied_at": _iso(p.satisfied_at)}
                     for p in prerequisites],
        }
        dump.append({"task_db_id": task.id, "task_id": row.get("task_id"),
                     "order_id": row.get("order_id"), "article_code": row.get("article_code")})
    return {"store": "sample_tasks", "persisted": persisted, "missing": missing, "rows": dump}


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
        # Batch 2: laporan terbuka tentang sumber data & persistensi task.
        "data_source": _data_source(db),
        "task_persistence": _persisted_tasks(db, rows),
        # Pagar akses yang ditampilkan ke UI (ditegakkan juga di server).
        "access": _access_contract(),
    }


@router.get("/my-tasks")
def my_sample_tasks(status: str = None, order_id: str = None,
                    db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Antrean kerja sample Fahrul (SMP-F-005 / revisi #35).

    Berasal otomatis dari routing order/article yang eligible. SLA dari Master.
    Task tidak DONE tanpa sample version submitted + seluruh required evidence.

    Batch 2: task CREATE_SAMPLE dipersist ke `sample_tasks` (dengan prasyaratnya)
    saat endpoint ini dibaca; kolom `task_db_id`/`persistence` membuktikannya.
    """
    _require_view(user)
    rows = _build_rows(db, user)
    persisted = _persisted_tasks(db, rows)
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
        "data_source": _data_source(db),
        "task_persistence": persisted,
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
