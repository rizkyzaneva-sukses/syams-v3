"""SMP-F-004 / SMP-F-006 / SMP-F-008 — Versioned Sample Lifecycle, Evidence &
Immutability (revisi #34, #36, #38).

Blueprint revision #34 asks for a provable sample lifecycle
(`Sample Request → Requirement & PPM → Work Version → Inspection & Evidence →
Submission & Handoff → Buyer Decision → Revision`), #36 asks that Sample, Task,
Order Flow and Master read the *same* event, and #38 asks that an APPROVED
sample version is immutable — corrections go through a new revision, never a
hard edit/delete.

Data model reality (no new tables): a `sample_records` row *is* one sample
version. Ordering by `id` gives the version sequence, exactly like SPK versions
in `workflow.py` and the "latest record per article" rule that
`workflow.py::samples_ready()` already applies for the Order Flow gate. So this
module never invents a second source of truth; it *derives* the versioned view
from the same tables the gate reads, which is what revision #36 demands.

Contract of the read endpoints
------------------------------
`GET /cmo/samples-version-summary`
    Per article: latest version, status, evidence count/names, completeness,
    buyer decision, actor, timestamp, next action, immutability flag, and any
    cross-module mismatch (sample approved but Order Flow gate still closed).

`GET /cmo/samples/{sample_id}/versions`
    The version chain of one article: every version with its evidence (uploader
    + timestamp) and buyer decision, plus which version the gate consumes.

`GET /cmo/samples-version-decisions`
    Immutable-version register: which versions must not be edited or deleted,
    and the only legal way to change them.

`GET /cmo/samples-version-audit`
    Change log of every sample version sourced from `audit_logs`
    (actor, action, previous/new status, reason, timestamp).

Strictly read-only: nothing here mutates a SampleRecord. Immutability itself is
enforced inside `workflow.py::validate` (approved sample, and approved/released
sample history), and the audit trail is written by the mutation endpoints through
`audit.log_audit`. The gap this module closes is *visibility*: the UI could still
offer Edit/Delete on a submitted or approved version, and nothing told the user
which version the Order Flow gate had consumed.

Lifecycle stage is a projection, not a stored field: it is derived from status +
evidence + decision, so it can never drift from the record.
"""
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from .. import models as m

router = APIRouter(prefix="/cmo", tags=["cmo-samples"])

# Same readership as the Sample/PPM screens plus Sample PIC. Mirrors
# `modules.py::list_samples` so this view never widens access by accident.
VIEW_ROLES = {"CEO", "CMO_MANAGER", "CMO_SUPPORT", "COO_MANAGER", "SAMPLE_PIC"}

# Roles allowed to *change* a sample version. Used only to document who may act;
# enforcement stays in workflow.py.
MUTATE_ROLES = {"CMO_MANAGER", "SAMPLE_PIC"}

# Lifecycle stages from revision #34, in order.
STAGES = ["SAMPLE_REQUEST", "REQUIREMENT_PPM", "WORK_VERSION", "INSPECTION_EVIDENCE",
          "SUBMISSION_HANDOFF", "BUYER_DECISION", "CLOSED"]

STAGE_LABELS = {
    "SAMPLE_REQUEST": "Sample Request",
    "REQUIREMENT_PPM": "Requirement & PPM",
    "WORK_VERSION": "Work Version",
    "INSPECTION_EVIDENCE": "Inspection & Evidence",
    "SUBMISSION_HANDOFF": "Submission & Handoff",
    "BUYER_DECISION": "Buyer Decision",
    "CLOSED": "Selesai",
}

# A sample version is final once the buyer decided. From that point the record is
# a proof, not a draft (revisi #38).
FINAL_STATUSES = {"APPROVED", "REJECTED"}

# `REVISION` is the third buyer outcome: the version was submitted, the buyer
# sent it back. The record itself is already a decision artefact, so it must not
# be re-edited in place — the correction happens on the next version.
DECIDED_STATUSES = FINAL_STATUSES | {"REVISION"}


def _has_decision(sample):
    """Did a buyer decision land on this exact version?

    `workflow.py::decide_sample_customer` only writes APPROVED/REJECTED, but
    historical and seeded rows carry a decision timestamp/reason while sitting in
    REVISION. Treating those as open drafts is exactly the hole revisi #38
    describes, so a recorded decision wins over the status label.
    """
    if sample.status in DECIDED_STATUSES:
        return True
    return bool(sample.customer_decision_at or sample.customer_decision_reason)

# The Order Flow gate requires buyer approval *and* an approving actor
# (`workflow.py::samples_ready`).
GATE_SATISFIED_STATUSES = {"APPROVED"}

# SPK states that already reference the released sample history.
SPK_CONSUMING_STATUSES = {"GENERATED", "PRINTED", "RELEASED"}


def _require_view(user):
    if user.role.value not in VIEW_ROLES:
        raise HTTPException(403, "Riwayat versi Sample / PPM tidak tersedia untuk peran ini.")


def _iso(value):
    return value.isoformat() if value is not None else None


def _aware(value):
    """Timestamps are stored naive-UTC; normalise before comparing."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _latest(values):
    """Latest timestamp of a collection; naive/aware values never mix."""
    stamps = [value for value in (_aware(v) for v in values) if value is not None]
    return max(stamps) if stamps else None


def _user_names(db, ids):
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = db.query(m.User).filter(m.User.id.in_(wanted)).all()
    return {row.id: row.name for row in rows}


def _evidence_rows(record, names):
    return [{
        "evidence_id": item.id,
        "file_name": item.file_name,
        "file_mime": item.file_mime,
        "note": item.note,
        "uploaded_by_id": item.uploaded_by_id,
        "uploaded_by": names.get(item.uploaded_by_id),
        "created_at": _iso(item.created_at),
    } for item in sorted(record.evidence, key=lambda e: (e.id or 0))]


def _evidence_gap(status, evidence, decided=False):
    """Evidence the blueprint requires before a version may be finalised.

    Approval is the only transition that demands proof
    (`workflow.py::validate`: "Customer approval requires uploaded evidence").
    """
    count = len(evidence)
    required = 1 if status in FINAL_STATUSES or (decided and status == "APPROVED") else 0
    if required and count < required:
        return {
            "required": required,
            "present": count,
            "complete": False,
            "missing": required - count,
            "file_names": [item["file_name"] for item in evidence],
            "next_action": "Unggah bukti approval buyer sebelum versi ini disahkan.",
        }
    if not count:
        return {
            "required": required,
            "present": 0,
            "complete": False,
            "missing": 0,
            "file_names": [],
            "next_action": "Belum ada evidence; lampirkan foto sample atau PDF PPM.",
        }
    return {"required": required, "present": count, "complete": True, "missing": 0,
            "file_names": [item["file_name"] for item in evidence], "next_action": None}


def _stage_of(status, evidence_count, decided):
    """Derive the revision #34 lifecycle stage. Projection, never stored."""
    if decided and status == "APPROVED":
        return "CLOSED"
    if status in {"REJECTED", "REVISION"}:
        # A rejected version goes back to requirement/PPM work as a new draft.
        return "REQUIREMENT_PPM"
    if decided:
        return "BUYER_DECISION"
    if evidence_count:
        return "SUBMISSION_HANDOFF"
    if status in {"IN_PROCESS", "PENDING"}:
        return "WORK_VERSION"
    return "SAMPLE_REQUEST"


def _immutability(status, gate_consumed, approved_handler_id, decided=False):
    """Verdict for revisi #38: may this version still be edited or deleted?"""
    final = status in FINAL_STATUSES
    if not final and not gate_consumed and not decided:
        return {
            "immutable": False,
            "state": "OPEN",
            "reason": "Versi masih berjalan; perbaikan biasa boleh dilakukan oleh pemilik peran.",
            "locked_fields": [],
            "allowed_actions": ["EDIT", "UPLOAD_EVIDENCE", "REVISE", "VOID"],
            "requires_new_version": False,
            "next_action": "Lengkapi proses dan bukti pada versi ini.",
        }
    if not final and gate_consumed:
        # SPK sudah jalan atas versi ini — riwayatnya sudah dipakai modul lain.
        return {
            "immutable": True,
            "state": "LOCKED_BY_SPK",
            "reason": "SPK sudah dibuat/dirilis atas versi ini; riwayat sample dibekukan.",
            "locked_fields": ["status", "notes", "requested_date", "completed_date"],
            "allowed_actions": ["CREATE_NEW_VERSION", "CORRECT"],
            "requires_new_version": True,
            "next_action": "Koreksi lewat versi baru (CREATE NEW VERSION), bukan edit langsung.",
        }
    reason = ("Versi ini sudah disetujui buyer; bukti approval tidak boleh berubah."
              if status == "APPROVED" else
              "Versi ini sudah diputuskan buyer (revisi diminta); catatan keputusan bersifat final.")
    if status == "APPROVED" and approved_handler_id is None:
        reason += " Belum ada aktor approval tercatat — perbaiki lewat revisi baru, bukan edit."
    return {
        "immutable": True,
        "state": "IMMUTABLE_APPROVED" if status == "APPROVED" else "IMMUTABLE_DECIDED",
        "reason": reason,
        "locked_fields": ["status", "notes", "requested_date", "completed_date",
                          "article_code", "customer_decision_reason"],
        "allowed_actions": ["CREATE_NEW_VERSION", "REVISE", "VOID", "CORRECT"],
        "requires_new_version": True,
        "next_action": ("Buat versi sample baru untuk perubahan PPM/artwork; versi ini tetap "
                        "tersimpan sebagai bukti approval buyer."),
    }


def _load_context(db):
    """One pass over the tables involved, so every row sees the same snapshot."""
    samples = db.query(m.SampleRecord).order_by(m.SampleRecord.id.asc()).all()
    order_ids = {s.order_fk for s in samples if s.order_fk is not None}
    orders = ({o.id: o for o in db.query(m.Order).filter(m.Order.id.in_(order_ids)).all()}
              if order_ids else {})
    articles = db.query(m.Article).all()
    article_by_id = {a.id: a for a in articles}
    article_by_key = {(a.order_fk, a.article_code): a for a in articles}
    spks = {}
    for spk in db.query(m.SPK).order_by(m.SPK.version.asc(), m.SPK.id.asc()).all():
        spks[spk.order_fk] = spk
    names = _user_names(db, [s.customer_approved_by_id for s in samples]
                        + [e.uploaded_by_id for s in samples for e in s.evidence])
    return samples, orders, article_by_id, article_by_key, names, spks


def _article_of(sample, article_by_id, article_by_key):
    if sample.article_id is not None and sample.article_id in article_by_id:
        return article_by_id[sample.article_id]
    return article_by_key.get((sample.order_fk, sample.article_code))


def _article_key(sample, article):
    """Identity of the (order, article) pair a version belongs to.

    Mirrors the match used by `workflow.py::samples_ready`: explicit
    `article_id` first, then the `(order_fk, article_code)` fallback used by
    sample rows created before article_id was populated.
    """
    if sample.article_id is not None:
        return sample.order_fk, sample.article_id
    if article is not None:
        return sample.order_fk, article.id
    return sample.order_fk, sample.article_code


def _spk_consumed(order, spks):
    """Has another module already consumed the released sample of this order?

    Only the latest version of an article can be the one an SPK references —
    the same "latest sample per article" rule the gate applies.
    """
    if order is None:
        return False
    spk = spks.get(order.id)
    return bool(spk is not None and spk.status in SPK_CONSUMING_STATUSES)


def _next_action(status, decided, evidence_count, state):
    if state == "LOCKED_BY_SPK":
        return "SPK aktif atas versi ini; perubahan sample harus lewat versi baru."
    if state != "OPEN":
        return "Versi final. Perubahan PPM/artwork hanya lewat revisi atau versi baru."
    if not evidence_count:
        return "Unggah evidence (foto sample / PDF PPM) sebagai dasar keputusan buyer."
    if status == "REVISION":
        return "Perbaiki sesuai alasan revisi buyer, lalu unggah evidence baru."
    if not decided:
        return "Ajukan keputusan buyer (keputusan hanya boleh oleh CMO Manager)."
    return "Siap lanjut ke gate Order Flow."


def _version_payload(sample, version_no, names, order=None, article=None,
                     gate_consumed=False, latest=False, previous_id=None):
    evidence = _evidence_rows(sample, names)
    decided = _has_decision(sample)
    stage = _stage_of(sample.status, len(evidence), decided)
    verdict = _immutability(sample.status, gate_consumed, sample.customer_approved_by_id, decided)
    handler = sample.customer_approved_by_id
    return {
        # ── identity (revisi #34: Sample ID, Order ID, Article ID) ──
        "sample_id": sample.id,
        "sample_version": version_no,
        "previous_version": version_no - 1 if version_no > 1 else None,
        "previous_version_sample_id": previous_id,
        "is_latest_version": latest,
        "order_fk": sample.order_fk,
        "order_id": order.order_id if order is not None else None,
        "buyer": order.buyer if order is not None else None,
        "article_id": sample.article_id,
        "matched_article_id": article.id if article is not None else None,
        "article_code": sample.article_code,
        "order_type": (order.order_type.value
                       if order is not None and hasattr(order.order_type, "value") else None),
        "sample_required": bool(article.sample_required) if article is not None else None,
        # ── lifecycle ──
        "status": sample.status,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "current_owner": "CMO_MANAGER" if decided else "SAMPLE_PIC",
        "due_date": _iso(sample.requested_date),
        "completed_date": _iso(sample.completed_date),
        "blocker": ("Evidence missing" if not evidence else
                    "Buyer decision pending" if not decided else None),
        "notes": sample.notes,
        # ── evidence (revisi #34: pelaku + waktu) ──
        "evidence_count": len(evidence),
        "evidence": evidence,
        "evidence_gap": _evidence_gap(sample.status, evidence, decided),
        # ── submission & buyer decision ──
        "submitted_at": _iso(sample.completed_date) if sample.completed_date else None,
        "buyer_decision": sample.status if decided else None,
        "buyer_decision_status": sample.status if decided else None,
        "decision_at": _iso(sample.customer_decision_at),
        "decision_by_id": handler,
        "decision_by": names.get(handler),
        "decision_reason": sample.customer_decision_reason,
        "approval_reference": (sample.customer_decision_reason
                               if sample.status == "APPROVED" else None),
        # ── immutability (revisi #38) ──
        "immutable": verdict["immutable"],
        "immutability_state": verdict["state"],
        "immutability_reason": verdict["reason"],
        "locked_fields": verdict["locked_fields"],
        "allowed_actions": verdict["allowed_actions"],
        "requires_new_version": verdict["requires_new_version"],
        # ── cross-module sync (revisi #36) ──
        "gate_satisfied": bool(sample.status in GATE_SATISFIED_STATUSES and handler is not None),
        "gate_consumed_by_spk": gate_consumed,
        "next_action": _next_action(sample.status, decided, len(evidence), verdict["state"]),
        "created_at": _iso(sample.created_at),
        "updated_at": _iso(sample.created_at),
    }


@router.get("/samples-version-summary")
def samples_version_summary(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Rekap per artikel: versi terakhir, status, evidence, keputusan buyer.

    Revision #36 asks the same event to update Sample, Task, Order Flow and
    Master exactly once. This endpoint therefore reports the *gate verdict* next
    to the sample verdict, and raises a mismatch row when the two disagree.
    """
    _require_view(user)
    samples, orders, article_by_id, article_by_key, names, spks = _load_context(db)

    grouped = {}
    for sample in samples:
        article = _article_of(sample, article_by_id, article_by_key)
        grouped.setdefault(_article_key(sample, article), []).append((sample, article))

    rows = []
    for key, chain in grouped.items():
        order = orders.get(key[0])
        article = chain[-1][1]
        spk_open = _spk_consumed(order, spks)
        versions = []
        previous_id = None
        for number, (sample, _article) in enumerate(chain, start=1):
            is_latest = sample is chain[-1][0]
            versions.append(_version_payload(
                sample, number, names, order=order, article=article,
                gate_consumed=spk_open and is_latest, latest=is_latest,
                previous_id=previous_id))
            previous_id = sample.id
        latest = versions[-1]
        # Cross-module mismatch (revisi #36): Master/Article says the sample is
        # approved but the Order Flow gate still refuses to advance.
        master_status = article.sample_status if article is not None else None
        mismatch = []
        if master_status == "APPROVED" and not latest["gate_satisfied"]:
            mismatch.append({
                "code": "MASTER_APPROVED_GATE_CLOSED",
                "detail": "Master/Article menandai sample APPROVED tetapi gate Order Flow "
                          "masih tertutup (aktor approval tidak tercatat).",
            })
        if latest["status"] == "APPROVED" and latest["decision_by_id"] is None:
            mismatch.append({
                "code": "APPROVED_WITHOUT_ACTOR",
                "detail": "Versi APPROVED tanpa aktor approval; gate akan tetap tertutup.",
            })
        rows.append({
            "article_id": latest["matched_article_id"] or latest["article_id"],
            "matched_article_id": latest["matched_article_id"],
            "article_code": latest["article_code"],
            "order_fk": latest["order_fk"],
            "order_id": latest["order_id"],
            "buyer": latest["buyer"],
            "order_type": latest["order_type"],
            "sample_required": latest["sample_required"],
            "master_sample_status": master_status,
            "version_count": len(versions),
            "latest_version": latest["sample_version"],
            "latest_sample_id": latest["sample_id"],
            "previous_version": latest["previous_version"],
            "previous_version_sample_id": latest["previous_version_sample_id"],
            "status": latest["status"],
            "stage": latest["stage"],
            "stage_label": latest["stage_label"],
            "evidence_count": latest["evidence_count"],
            "evidence_file_names": latest["evidence_gap"]["file_names"],
            "evidence_complete": latest["evidence_gap"]["complete"],
            "evidence_gap": latest["evidence_gap"],
            "buyer_decision": latest["buyer_decision"],
            "buyer_decision_status": latest["buyer_decision_status"],
            "decision_by": latest["decision_by"],
            "decision_by_id": latest["decision_by_id"],
            "decision_at": latest["decision_at"],
            "decision_reason": latest["decision_reason"],
            "submitted_at": latest["submitted_at"],
            "current_owner": latest["current_owner"],
            "due_date": latest["due_date"],
            "completed_date": latest["completed_date"],
            "blocker": latest["blocker"],
            "immutable": latest["immutable"],
            "immutability_state": latest["immutability_state"],
            "immutability_reason": latest["immutability_reason"],
            "locked_fields": latest["locked_fields"],
            "allowed_actions": latest["allowed_actions"],
            "requires_new_version": latest["requires_new_version"],
            "gate_satisfied": latest["gate_satisfied"],
            "gate_consumed_by_spk": latest["gate_consumed_by_spk"],
            "open_version_count": sum(1 for v in versions if not v["immutable"]),
            "next_action": latest["next_action"],
            "mismatch": mismatch,
            "has_mismatch": bool(mismatch),
            "updated_at": latest["updated_at"],
        })

    rows.sort(key=lambda row: (not row["has_mismatch"], row["order_id"] or "",
                               row["article_code"] or ""))
    return {
        "rows": rows,
        "totals": {
            "articles": len(rows),
            "versions": sum(row["version_count"] for row in rows),
            "immutable_articles": sum(1 for row in rows if row["immutable"]),
            "open_articles": sum(1 for row in rows if not row["immutable"]),
            "awaiting_buyer": sum(1 for row in rows if not row["buyer_decision"]),
            "evidence_incomplete": sum(1 for row in rows if not row["evidence_complete"]),
            "mismatch": sum(1 for row in rows if row["has_mismatch"]),
        },
        "stages": STAGES,
    }


@router.get("/samples-version-decisions")
def samples_version_decisions(status: str = None, db: Session = Depends(get_db),
                              user=Depends(get_current_user)):
    """Register versi yang tidak boleh diubah lagi (revisi #38).

    For every immutable version this returns *why* it is frozen, which fields are
    locked, and the only legal alternatives for the UI (CREATE NEW VERSION /
    REVISE / VOID / CORRECT) so the page can stop offering Edit and Delete.
    """
    _require_view(user)
    samples, orders, article_by_id, article_by_key, names, spks = _load_context(db)

    rows = []
    for sample in samples:
        if status and sample.status != status:
            continue
        article = _article_of(sample, article_by_id, article_by_key)
        order = orders.get(sample.order_fk)
        verdict = _immutability(sample.status, _spk_consumed(order, spks),
                                sample.customer_approved_by_id, _has_decision(sample))
        if not verdict["immutable"]:
            continue
        rows.append({
            "sample_id": sample.id,
            "order_fk": sample.order_fk,
            "order_id": order.order_id if order is not None else None,
            "buyer": order.buyer if order is not None else None,
            "article_id": sample.article_id or (article.id if article is not None else None),
            "article_code": sample.article_code,
            "status": sample.status,
            "immutability_state": verdict["state"],
            "reason": verdict["reason"],
            "locked_fields": verdict["locked_fields"],
            "allowed_actions": verdict["allowed_actions"],
            "requires_new_version": verdict["requires_new_version"],
            "next_action": verdict["next_action"],
            "evidence_count": len(sample.evidence),
            "decision_by_id": sample.customer_approved_by_id,
            "decision_by": names.get(sample.customer_approved_by_id),
            "decision_at": _iso(sample.customer_decision_at),
            "can_delete": False,
            "can_edit": False,
            "created_at": _iso(sample.created_at),
        })
    rows.sort(key=lambda row: (row["order_id"] or "", row["article_code"] or "", row["sample_id"]))
    return {
        "rows": rows,
        "totals": {"immutable_versions": len(rows),
                   "mutating_roles": sorted(MUTATE_ROLES),
                   "supported_actions": ["CREATE_NEW_VERSION", "REVISE", "VOID", "CORRECT"]},
    }


@router.get("/samples/{sample_id}/versions")
def sample_versions(sample_id: int, db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    """Seluruh versi dari satu artikel: evidence, keputusan, dan status kunci."""
    _require_view(user)
    anchor = db.query(m.SampleRecord).filter(m.SampleRecord.id == sample_id).first()
    if anchor is None:
        raise HTTPException(404, "Sample not found")

    samples, orders, article_by_id, article_by_key, names, spks = _load_context(db)
    article = _article_of(anchor, article_by_id, article_by_key)
    anchor_key = _article_key(anchor, article)
    order = orders.get(anchor.order_fk)

    chain = [row for row in samples
             if _article_key(row, _article_of(row, article_by_id, article_by_key)) == anchor_key]
    if not chain:
        chain = [anchor]

    spk_open = _spk_consumed(order, spks)
    versions = []
    previous_id = None
    for number, sample in enumerate(chain, start=1):
        is_latest = sample is chain[-1]
        versions.append(_version_payload(sample, number, names, order=order, article=article,
                                         gate_consumed=spk_open and is_latest, latest=is_latest,
                                         previous_id=previous_id))
        previous_id = sample.id

    latest = versions[-1]
    current = next((v for v in versions if v["sample_id"] == sample_id), latest)
    history = [{
        "sample_version": v["sample_version"],
        "sample_id": v["sample_id"],
        "status": v["status"],
        "previous_version": v["previous_version"],
        "evidence_count": v["evidence_count"],
        "decision_at": v["decision_at"],
        "decision_by": v["decision_by"],
        "immutable": v["immutable"],
        "immutability_state": v["immutability_state"],
        "created_at": v["created_at"],
    } for v in versions]

    return {
        "sample_id": anchor.id,
        "order_fk": anchor.order_fk,
        "order_id": latest["order_id"],
        "buyer": latest["buyer"],
        "article_id": latest["article_id"],
        "article_code": latest["article_code"],
        "is_latest_version": current["sample_id"] == latest["sample_id"],
        "current_version": current["sample_version"],
        "latest_version": latest["sample_version"],
        "latest_sample_id": latest["sample_id"],
        "version_count": len(versions),
        "versions": versions,
        "current": current,
        "history": history,
        "requires_new_version": current["requires_new_version"],
        "allowed_actions": current["allowed_actions"],
        "immutability": {
            "immutable": current["immutable"],
            "state": current["immutability_state"],
            "reason": current["immutability_reason"],
            "locked_fields": current["locked_fields"],
        },
        "next_action": current["next_action"],
    }


@router.get("/samples-version-audit")
def samples_version_audit(limit: int = 100, db: Session = Depends(get_db),
                          user=Depends(get_current_user)):
    """Jejak audit perubahan sample: pelaku, aksi, status lama/baru, alasan."""
    _require_view(user)
    if limit < 1 or limit > 500:
        raise HTTPException(422, "limit must be between 1 and 500")

    logs = (db.query(m.AuditLog)
            .filter(m.AuditLog.entity == "SampleRecord")
            .order_by(m.AuditLog.id.desc())
            .limit(limit).all())
    names = _user_names(db, [log.user_id for log in logs])
    sample_ids = {log.entity_id for log in logs if log.entity_id is not None}
    samples = ({s.id: s for s in
                db.query(m.SampleRecord).filter(m.SampleRecord.id.in_(sample_ids)).all()}
               if sample_ids else {})
    return {
        "rows": [{
            "audit_id": log.id,
            "sample_id": log.entity_id,
            "article_code": (samples[log.entity_id].article_code
                             if log.entity_id in samples else None),
            "action": log.action,
            "actor_id": log.user_id,
            "actor": names.get(log.user_id),
            "previous_status": log.previous_status,
            "new_status": log.new_status,
            "reason": log.reason,
            "detail": log.detail,
            "source_module": log.source_module,
            "order_id": log.order_id,
            "created_at": _iso(log.created_at),
        } for log in logs],
        "totals": {"entries": len(logs), "limit": limit},
    }
