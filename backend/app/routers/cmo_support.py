"""CMO Support (Deby) work queues — Revisi #9 poin 2, 3, 5, 8, 9, 10.

Deby's "Hari Ini" is a work list, not an analysis dashboard: what she must
prepare, what is missing, and which divisi is waiting on her. Every row carries
the mandatory queue contract (revisi #9 poin 3): Task ID, Buyer ID, Order ID,
Article ID, tahap proses, status, data/bukti kurang, next action, owner, due/SLA,
source/evidence, updated_at dan status handoff.

Read-only. Deby may not verify payment, take final commercial decisions, release
SPK, run batch release, change production/inventory/QC, execute delivery or close
orders (poin 12) — those actions are never offered here.
"""
from datetime import date, datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from .. import models as m

router = APIRouter(prefix="/cmo", tags=["cmo-support"])

VIEW_ROLES = {"CEO", "CMO_MANAGER", "CMO_SUPPORT"}


def _require_view(user):
    if user.role.value not in VIEW_ROLES:
        raise HTTPException(403, "Antrean kerja CMO Support tidak tersedia untuk peran ini.")


def _iso(value):
    return value.isoformat() if value is not None else None


def _row(*, task_id, kind, order=None, buyer=None, article=None, status=None,
         missing=None, action=None, owner="CMO_SUPPORT", due=None, source=None,
         handoff=None, updated=None):
    return {
        "task_id": task_id,
        "decision_type": kind,
        "buyer": buyer or (order.buyer if order is not None else None),
        "order_id": order.order_id if order is not None else None,
        "order_fk": order.id if order is not None else None,
        "article_code": article,
        "status": status,
        "missing": missing,
        "next_action": action,
        "owner": owner,
        "due": _iso(due),
        "source": source,
        "handoff": handoff,
        "updated_at": _iso(updated),
    }


def _confirmations_for(db, order):
    rows = []
    for shipment in db.query(m.Shipment).filter(m.Shipment.order_fk == order.id).all():
        rows.extend(db.query(m.DeliveryConfirmation)
                    .filter(m.DeliveryConfirmation.shipment_fk == shipment.id).all())
    return rows


@router.get("/deby-today")
def deby_today(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Deby's action-first work list (revisi #9 poin 2)."""
    _require_view(user)
    queues = []

    # 1. PO masuk yang masih perlu dilengkapi / dikirim Deby (poin 4).
    po_rows = []
    for po in db.query(m.POIntake).order_by(m.POIntake.id.asc()).all():
        if po.status not in {"DRAFT", "NEEDS_INFO", "READY"}:
            continue
        try:
            missing = json.loads(po.missing_items_json or "[]")
        except (TypeError, ValueError):
            missing = []
        po_rows.append(_row(
            task_id=f"PO-{po.id}", kind="PO_INTAKE", buyer=po.buyer,
            status=po.status,
            missing=", ".join(missing) if missing else "Lengkap",
            action=("Periksa kelengkapan lalu kirim ke Cecep" if po.status == "READY"
                    else "Lengkapi data & dokumen PO"),
            due=po.buyer_deadline, source="Dokumen PO buyer",
            handoff="Cecep review & aktifkan Order",
            updated=po.updated_at))
    queues.append({"key": "PO_INTAKE", "label": "PO Masuk — perlu dilengkapi",
                   "owner": "CMO_SUPPORT", "handoff": "Cecep review & aktifkan Order",
                   "rows": po_rows})

    # 2. PO yang sudah dikirim, menunggu keputusan Cecep (read-only untuk Deby).
    waiting = []
    for po in (db.query(m.POIntake).filter(m.POIntake.status == "SUBMITTED")
               .order_by(m.POIntake.id.asc()).all()):
        waiting.append(_row(
            task_id=f"PO-{po.id}", kind="PO_WAITING_REVIEW", buyer=po.buyer,
            status=po.status, missing="—",
            action="Menunggu review Cecep — tidak ada aksi Deby",
            owner="CMO_MANAGER", due=po.buyer_deadline, source="Draft PO terkirim",
            handoff="Order aktif setelah diterima Cecep",
            updated=po.updated_at))
    queues.append({"key": "PO_WAITING", "label": "Menunggu Review Cecep",
                   "owner": "CMO_MANAGER", "handoff": "Order aktif setelah diterima",
                   "rows": waiting})

    # 3. Bukti Sample/PPM yang belum lengkap (poin 8). Deby hanya input bukti.
    sample_rows = []
    for sample in db.query(m.SampleRecord).order_by(m.SampleRecord.id.asc()).all():
        evidence = len(sample.evidence) if sample.evidence else 0
        decided = sample.customer_approved_by_id is not None
        if evidence and decided:
            continue
        order = db.get(m.Order, sample.order_fk)
        sample_rows.append(_row(
            task_id=f"SMP-{sample.id}", kind="SAMPLE_EVIDENCE", order=order,
            article=sample.article_code, status=sample.status,
            missing="Bukti belum diunggah" if not evidence else "Keputusan Cecep belum dicatat",
            action=("Unggah foto/PDF bukti Sample/PPM" if not evidence
                    else "Menunggu keputusan Cecep"),
            owner="CMO_SUPPORT" if not evidence else "CMO_MANAGER",
            due=sample.completed_date, source="Bukti Sample/PPM",
            handoff="Cecep catat keputusan buyer → SPK",
            updated=sample.created_at))
    queues.append({"key": "SAMPLE_EVIDENCE", "label": "Bukti Sample/PPM belum lengkap",
                   "owner": "CMO_SUPPORT", "handoff": "Cecep catat keputusan buyer",
                   "rows": sample_rows})

    # 4. SPK yang siap di-Generate/Preview/Print oleh Deby (poin 9).
    spk_rows = []
    for spk in db.query(m.SPK).order_by(m.SPK.id.asc()).all():
        if spk.status not in {"DRAFT", "GENERATED"}:
            continue
        order = db.get(m.Order, spk.order_fk)
        spk_rows.append(_row(
            task_id=f"SPK-{spk.id}", kind="SPK_PREPARE", order=order,
            status=spk.status,
            missing=("Perlu di-Generate" if spk.status == "DRAFT" else "Perlu di-Print"),
            action=("Generate lalu Preview PDF" if spk.status == "DRAFT" else "Print SPK"),
            due=order.buyer_deadline if order else None,
            source=f"SPK v{spk.version}", handoff="Print bukan Release — Cecep yang release",
            updated=spk.created_at))
    queues.append({"key": "SPK_PREPARE", "label": "SPK siap Generate / Print",
                   "owner": "CMO_SUPPORT",
                   "handoff": "Print bukan Release — Cecep yang release",
                   "rows": spk_rows})

    # 5. After-sales & komunikasi delivery (poin 10). Eksekusi milik COO.
    delivery_rows = []
    for order in db.query(m.Order).all():
        if order.overall_status == "CLOSED":
            continue
        if order.shipment_status not in {"SHIPPED", "DELIVERED"}:
            continue
        if any(conf.status == "CONFIRMED" for conf in _confirmations_for(db, order)):
            continue
        delivery_rows.append(_row(
            task_id=f"AS-{order.id}", kind="AFTER_SALES", order=order,
            status=order.shipment_status,
            missing="Konfirmasi penerimaan buyer",
            action="Hubungi buyer & catat konfirmasi penerimaan",
            owner="CMO_SUPPORT", due=order.buyer_deadline,
            source="Komunikasi delivery", handoff="Closing customer & operasional",
            updated=order.updated_at))
    queues.append({"key": "AFTER_SALES", "label": "After Sales & komunikasi delivery",
                   "owner": "CMO_SUPPORT", "handoff": "Delivery execution milik COO",
                   "rows": delivery_rows})

    # 6. Follow-up buyer yang jatuh tempo (poin 5).
    today = date.today()
    follow_rows = []
    for order in db.query(m.Order).all():
        if order.overall_status == "CLOSED" or order.buyer_deadline is None:
            continue
        if order.buyer_deadline > today:
            continue
        follow_rows.append(_row(
            task_id=f"FU-{order.id}", kind="FOLLOW_UP", order=order,
            status=order.overall_status,
            missing="Follow-up buyer jatuh tempo",
            action="Hubungi buyer & catat hasil",
            owner="CMO_SUPPORT", due=order.buyer_deadline,
            source="Deadline buyer", handoff="Peluang repeat order",
            updated=order.updated_at))
    queues.append({"key": "FOLLOW_UP", "label": "Follow-up jatuh tempo",
                   "owner": "CMO_SUPPORT", "handoff": "Peluang repeat order",
                   "rows": follow_rows})

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "queues": queues,
        "totals": {q["key"]: len(q["rows"]) for q in queues},
        "total_tasks": sum(len(q["rows"]) for q in queues),
    }