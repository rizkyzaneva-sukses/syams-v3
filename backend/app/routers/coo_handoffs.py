"""Persistensi handoff antar proses (revisi #54, COO-S-006).

Sebelum tabel ``production_handoffs`` ada, edge handoff direkonstruksi dari
urutan ``production_movements`` — angkanya benar tapi tidak bisa menyimpan
batch_no, evidence_ref, shift, location, dan yang paling penting: tidak ada
tempat untuk MENGUNCI qty yang sudah dikirim.

Router ini menegakkan tiga hal yang menjadi inti revisi:

1. **Qty Sent immutable setelah diterima.** Begitu handoff diterima
   (``qty_received`` tercatat), ``qty_sent`` tidak bisa diubah lagi — oleh
   siapa pun, termasuk COO_MANAGER. Koreksi harus lewat handoff baru, sehingga
   jejaknya tetap ada. Ini yang mencegah angka lama ditimpa diam-diam.
2. **Discrepancy dihitung, bukan diketik.** ``discrepancy = qty_received -
   qty_sent`` dihitung server; kalau klien mengirim discrepancy, nilainya
   diabaikan dan alasan penolakan dilaporkan.
3. **Qty yang dikirim harus berasal dari produksi nyata.** ``qty_sent`` tidak
   boleh melebihi ``qty_done`` proses pengirim, dan tujuan harus proses
   berikutnya di rute artikel.

Semua penulisan menulis audit di transaksi yang sama.
"""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import coo_actions
from ..audit import log_audit
from ..auth import require_roles
from ..database import get_db
from ..models import Article, Order, ProductionHandoff, ProductionMovement, Role
from ..workflow import route_for, role as role_of

router = APIRouter(prefix="/coo", tags=["coo-handoffs"])

# Pengirim/penulis handoff: COO_MANAGER memegang kewenangan; PIC melaporkan
# penerimaan di lantai.
WRITE_ROLES = (Role.COO_MANAGER, Role.PRODUCTION_PIC, Role.PRINTING_PIC)
RECEIVE_ROLES = (Role.COO_MANAGER, Role.PRODUCTION_PIC, Role.PRINTING_PIC)
READ_ROLES = (
    Role.CEO,
    Role.COO_MANAGER,
    Role.PRODUCTION_PIC,
    Role.PRINTING_PIC,
    Role.CFO_MANAGER,
    Role.CMO_MANAGER,
)

PENDING_RECEIPT = "PENDING_RECEIPT"
RECEIVED = "RECEIVED"
PARTIAL = "PARTIAL"
REJECTED = "REJECTED"

# Status yang berarti qty_sent sudah terkunci. Ini daftar tertutup, bukan
# "tidak sama dengan PENDING_RECEIPT", supaya status tak dikenal tidak
# diam-diam membuka kunci.
LOCKED_STATUSES = frozenset({RECEIVED, PARTIAL})


def _fail(message, status=400):
    raise HTTPException(status, message)


def _norm(value):
    return (value or "").strip().upper()


def _now():
    return datetime.utcnow()


def _movement_rollup(db: Session, article_ids):
    """qty_done/qty_in per (article, process) beserta id movement-nya."""
    if not article_ids:
        return {}
    rows = (
        db.query(ProductionMovement)
        .filter(ProductionMovement.article_id.in_(sorted(article_ids)))
        .order_by(ProductionMovement.id)
        .all()
    )
    buckets = {}
    for mv in rows:
        key = (mv.article_id, _norm(mv.process))
        bucket = buckets.setdefault(key, {"qty_in": 0, "qty_done": 0, "ids": []})
        bucket["qty_in"] += int(mv.qty_in or 0)
        bucket["qty_done"] += int(mv.qty_done or 0)
        bucket["ids"].append(mv.id)
    return buckets


def _next_process(article, process):
    route = route_for(article)
    here = next((i for i, p in enumerate(route) if p == _norm(process)), None)
    if here is None or here + 1 >= len(route):
        return None
    return route[here + 1]


def _serialize(row: ProductionHandoff) -> dict:
    """Representasi handoff yang dipakai endpoint baca dan tulis.

    `qty_sent` selalu disertai alasan kenapa ia (tidak) terkunci, supaya UI
    tidak perlu menebak dari status saja.
    """
    locked = row.status in LOCKED_STATUSES
    return {
        "id": row.id,
        "handoff_no": row.handoff_no,
        "order_fk": row.order_fk,
        "article_id": row.article_id,
        "from_process": row.from_process,
        "to_process": row.to_process,
        "batch_no": row.batch_no,
        "qty_sent": int(row.qty_sent or 0),
        "qty_received": int(row.qty_received or 0),
        "discrepancy": int(row.discrepancy or 0),
        "remaining_balance": int(row.qty_sent or 0) - int(row.qty_received or 0),
        "sender_id": row.sender_id,
        "receiver_id": row.receiver_id,
        "sent_at": row.sent_at,
        "received_at": row.received_at,
        "evidence_ref": row.evidence_ref,
        "shift": row.shift,
        "location": row.location,
        "status": row.status,
        "qty_sent_locked": locked,
        "qty_sent_lock_rule": (
            "qty_sent terkunci karena handoff sudah diterima; koreksi lewat handoff baru"
            if locked
            else "qty_sent masih bisa dikoreksi selama belum ada penerimaan"
        ),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _get_handoff(db: Session, handoff_id: int) -> ProductionHandoff:
    row = db.get(ProductionHandoff, handoff_id)
    if row is None:
        _fail(f"ProductionHandoff {handoff_id} not found", 404)
    return row


def _assert_sendable(db: Session, article, order, from_process, to_process, qty_sent):
    """Validasi handoff keluar terhadap produksi nyata."""
    route = route_for(article)
    if not route:
        _fail(f"Artikel {article.article_code} belum punya rute produksi", 400)
    source = _norm(from_process)
    target = _norm(to_process)
    if source not in route:
        _fail(f"Proses {source} tidak ada di rute artikel ({' > '.join(route)})", 400)

    expected = _next_process(article, source)
    if expected is None:
        _fail(f"{source} adalah langkah terakhir rute; handoff tidak berlaku", 400)
    if expected != target:
        _fail(f"Handoff {source} harus ke {expected}, bukan {target}", 400)

    bucket = _movement_rollup(db, [article.id]).get((article.id, source))
    done = int(bucket["qty_done"]) if bucket else 0
    if int(qty_sent) > done:
        _fail(
            f"qty_sent {int(qty_sent)} melebihi qty_done {done} pada {source} "
            f"(artikel {article.article_code})",
            400,
        )
    return {"qty_done": done, "movement_ids": sorted(bucket["ids"]) if bucket else []}


def _build_handoff_no(db: Session, order, article, source, target) -> str:
    """Nomor handoff deterministik & unik: HO-<order>-<article>-<seq>."""
    prefix = f"HO-{order.order_id}-{article.article_code}-{source}-{target}"
    existing = (
        db.query(func.count(ProductionHandoff.id))
        .filter(ProductionHandoff.handoff_no.like(f"{prefix}%"))
        .scalar()
        or 0
    )
    return f"{prefix}-{int(existing) + 1}"


# ── POST /coo/handoffs — kirim qty ke proses berikutnya ──────────────────────
@router.post("/handoffs", status_code=201)
def create_handoff(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_roles(*WRITE_ROLES)),
):
    """Catat pengiriman handoff antar proses (revisi #54).

    Hanya COO_MANAGER yang boleh MENGIRIM handoff — memindahkan qty adalah
    titik sengketa kuantitas, jadi kewenangannya tunggal. PIC boleh MENERIMA.
    """
    actor_role = role_of(user)
    if not coo_actions.can_run(coo_actions.HANDOFF, actor_role):
        _fail(
            f"{actor_role} tidak berwenang mengirim handoff; hanya "
            f"{', '.join(sorted(coo_actions.roles_for(coo_actions.HANDOFF)))}",
            403,
        )

    order_fk = payload.get("order_fk")
    if order_fk is None:
        _fail("order_fk wajib diisi", 400)
    order = db.get(Order, int(order_fk))
    if order is None:
        _fail(f"Order {order_fk} not found", 404)

    article_id = payload.get("article_id")
    if article_id is None:
        _fail("article_id wajib diisi", 400)
    article = db.get(Article, int(article_id))
    if article is None:
        _fail(f"Article {article_id} not found", 404)
    if article.order_fk != order.id:
        _fail(f"Article {article_id} bukan milik order {order.order_id}", 400)

    from_process = _norm(payload.get("from_process"))
    to_process = _norm(payload.get("to_process"))
    if not from_process:
        _fail("from_process wajib diisi", 400)
    if not to_process:
        _fail("to_process wajib diisi", 400)

    try:
        qty_sent = int(payload.get("qty_sent"))
    except (TypeError, ValueError):
        _fail("qty_sent wajib berupa angka", 400)
    if qty_sent <= 0:
        _fail("qty_sent wajib > 0", 400)

    # Discrepancy adalah hasil hitung, bukan input. Cek keberadaan field, bukan
    # nilainya: `discrepancy: 0` tetap klaim klien dan tetap ditolak.
    if "discrepancy" in payload:
        _fail("discrepancy dihitung server (qty_received - qty_sent), tidak boleh dikirim", 400)
    if "qty_received" in payload:
        _fail("qty_received hanya boleh diisi lewat endpoint penerimaan", 400)

    guard = _assert_sendable(db, article, order, from_process, to_process, qty_sent)

    row = ProductionHandoff(
        order_fk=order.id,
        article_id=article.id,
        handoff_no=_build_handoff_no(db, order, article, from_process, to_process),
        from_process=from_process,
        to_process=to_process,
        batch_no=(payload.get("batch_no") or None),
        qty_sent=qty_sent,
        qty_received=0,
        discrepancy=0 - qty_sent,
        sender_id=user.id,
        receiver_id=None,
        sent_at=_now(),
        received_at=None,
        evidence_ref=(payload.get("evidence_ref") or None),
        shift=(payload.get("shift") or None),
        location=(payload.get("location") or None),
        status=PENDING_RECEIPT,
    )
    db.add(row)
    db.flush()

    # Ikat movement sumber ke handoff ini supaya hubungannya nyata, bukan
    # rekonstruksi (kolom production_movements.handoff_id, revisi #54).
    if guard["movement_ids"]:
        (
            db.query(ProductionMovement)
            .filter(ProductionMovement.id.in_(guard["movement_ids"]),
                    ProductionMovement.handoff_id.is_(None))
            .update({ProductionMovement.handoff_id: row.id}, synchronize_session=False)
        )

    log_audit(
        db, user, "COO_HANDOFF_SENT", "ProductionHandoff", row.id,
        detail=(
            f"Handoff {row.handoff_no}: {from_process} -> {to_process} "
            f"qty_sent={qty_sent} batch={row.batch_no or '-'} shift={row.shift or '-'}"
        ),
        obj=row, source_module="COO_EXECUTION",
        previous_status=None, new_status=row.status,
    )
    db.commit()
    db.refresh(row)
    return {
        "handoff": _serialize(row),
        "actor_role": actor_role,
        "quantity_source": {
            "source": "production_movements",
            "qty_done_at_sender": guard["qty_done"],
            "movement_ids": guard["movement_ids"],
        },
        "immutability": {
            "qty_sent_locked": False,
            "locks_on": "penerimaan pertama (qty_received dicatat)",
            "rule": "Qty Sent tidak boleh ditimpa setelah diterima",
        },
    }


# ── POST /coo/handoffs/{id}/receive — terima & kunci qty_sent ────────────────
@router.post("/handoffs/{handoff_id}/receive")
def receive_handoff(
    handoff_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_roles(*RECEIVE_ROLES)),
):
    """Terima handoff. Setelah ini **qty_sent tidak bisa diubah lagi**.

    Ini jaminan inti revisi #54: begitu ada penerimaan, angka kirim terkunci
    dan selisihnya menjadi discrepancy yang diaudit — bukan angka yang bisa
    ditimpa supaya laporan terlihat cocok.
    """
    row = _get_handoff(db, handoff_id)

    if row.status in LOCKED_STATUSES:
        _fail(
            f"Handoff {row.handoff_no} sudah diterima ({row.status}); "
            f"qty_sent {row.qty_sent} terkunci dan tidak boleh ditimpa",
            409,
        )

    try:
        qty_received = int(payload.get("qty_received"))
    except (TypeError, ValueError):
        _fail("qty_received wajib berupa angka", 400)
    if qty_received < 0:
        _fail("qty_received tidak boleh negatif", 400)
    if qty_received > int(row.qty_sent):
        _fail(
            f"qty_received {qty_received} melebihi qty_sent {row.qty_sent} "
            f"(penerimaan berlebih tidak sah)",
            400,
        )

    # Kalau klien ikut mengirim qty_sent, nilainya harus sama — usaha menimpa
    # angka kirim lewat endpoint penerimaan ditolak terang-terangan.
    if "qty_sent" in payload and payload.get("qty_sent") not in (None, row.qty_sent):
        _fail(
            f"qty_sent pada handoff ini terkunci di {row.qty_sent}; "
            f"permintaan mengubahnya ke {payload.get('qty_sent')} ditolak",
            409,
        )

    row.qty_received = qty_received
    row.discrepancy = qty_received - int(row.qty_sent)
    row.receiver_id = user.id
    row.received_at = _now()
    row.status = RECEIVED if row.discrepancy == 0 else PARTIAL
    if payload.get("evidence_ref"):
        row.evidence_ref = payload["evidence_ref"]
    if payload.get("batch_no"):
        row.batch_no = payload["batch_no"]
    if payload.get("location"):
        row.location = payload["location"]
    if payload.get("shift"):
        row.shift = payload["shift"]

    log_audit(
        db, user, "COO_HANDOFF_RECEIVED", "ProductionHandoff", row.id,
        detail=(
            f"Handoff {row.handoff_no} diterima: qty_sent={row.qty_sent} "
            f"qty_received={qty_received} discrepancy={row.discrepancy}"
        ),
        obj=row, source_module="COO_EXECUTION",
        previous_status=PENDING_RECEIPT, new_status=row.status,
    )
    db.commit()
    db.refresh(row)
    return {
        "handoff": _serialize(row),
        "actor_role": role_of(user),
        "immutability": {
            "qty_sent_locked": True,
            "locked_value": int(row.qty_sent),
            "rule": "Qty Sent tidak boleh ditimpa setelah diterima",
            "correction_path": "terbitkan handoff baru; handoff ini tetap tersimpan sebagai riwayat",
        },
    }


# ── PATCH /coo/handoffs/{id} — koreksi metadata selama belum diterima ────────
@router.patch("/handoffs/{handoff_id}")
def update_handoff(
    handoff_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(require_roles(Role.COO_MANAGER)),
):
    """Koreksi handoff. ``qty_sent`` hanya boleh berubah SEBELUM diterima."""
    row = _get_handoff(db, handoff_id)
    before = _serialize(row)

    # Ini penjaga intinya. Pesan sengaja menyebut nilai lama dan baru.
    if "qty_sent" in payload and payload.get("qty_sent") is not None:
        try:
            new_qty = int(payload["qty_sent"])
        except (TypeError, ValueError):
            _fail("qty_sent wajib berupa angka", 400)
        if new_qty != int(row.qty_sent):
            if row.status in LOCKED_STATUSES:
                _fail(
                    f"Qty Sent tidak boleh ditimpa: handoff {row.handoff_no} sudah "
                    f"diterima ({row.status}, qty_received={row.qty_received}). "
                    f"qty_sent terkunci di {row.qty_sent}; koreksi lewat handoff baru.",
                    409,
                )
            if new_qty <= 0:
                _fail("qty_sent wajib > 0", 400)
            guard = _assert_sendable(
                db,
                db.get(Article, row.article_id),
                db.get(Order, row.order_fk),
                row.from_process, row.to_process, new_qty,
            ) if row.article_id else {"qty_done": None, "movement_ids": []}
            row.qty_sent = new_qty
            row.discrepancy = int(row.qty_received or 0) - new_qty

    for field in ("batch_no", "evidence_ref", "shift", "location", "to_process"):
        if field in payload and payload[field] is not None:
            setattr(row, field, payload[field])

    if "qty_received" in payload and payload.get("qty_received") is not None:
        _fail("qty_received hanya boleh diisi lewat endpoint penerimaan", 400)

    changed = [f for f in ("qty_sent", "batch_no", "evidence_ref", "shift", "location", "to_process")
               if getattr(row, f) != before.get(f)]
    if not changed:
        _fail("Tidak ada perubahan yang bisa diterapkan", 400)

    log_audit(
        db, user, "COO_HANDOFF_UPDATED", "ProductionHandoff", row.id,
        detail=f"Handoff {row.handoff_no} dikoreksi: {', '.join(changed)}",
        obj=row, source_module="COO_EXECUTION",
        previous_status=before["status"], new_status=row.status,
        reason=payload.get("reason"),
    )
    db.commit()
    db.refresh(row)
    return {
        "handoff": _serialize(row),
        "changed": changed,
        "actor_role": role_of(user),
    }


# ── GET /coo/handoffs — daftar handoff nyata (bukan rekonstruksi) ────────────
@router.get("/handoffs")
def list_handoffs(
    order_fk: Optional[int] = Query(None),
    article_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(require_roles(*READ_ROLES)),
):
    """Daftar handoff tersimpan, lengkap dengan discrepancy & status kunci."""
    query = db.query(ProductionHandoff)
    if order_fk is not None:
        query = query.filter(ProductionHandoff.order_fk == order_fk)
    if article_id is not None:
        query = query.filter(ProductionHandoff.article_id == article_id)
    if status:
        query = query.filter(ProductionHandoff.status == _norm(status))
    rows = query.order_by(ProductionHandoff.id.desc()).all()

    items = [_serialize(r) for r in rows]
    discrepancies = [i for i in items if i["discrepancy"] != 0]
    pending = [i for i in items if i["status"] == PENDING_RECEIPT]
    return {
        "as_of": date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc),
        "actor_role": role_of(user),
        "handoffs": items,
        "summary": {
            "count": len(items),
            "pending_receipt": len(pending),
            "locked": sum(1 for i in items if i["qty_sent_locked"]),
            "discrepancy_count": len(discrepancies),
            "total_qty_sent": sum(i["qty_sent"] for i in items),
            "total_qty_received": sum(i["qty_received"] for i in items),
            "total_discrepancy": sum(i["discrepancy"] for i in items),
        },
        "immutability_rule": "Qty Sent tidak boleh ditimpa setelah handoff diterima",
    }
