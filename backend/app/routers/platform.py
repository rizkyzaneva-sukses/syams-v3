"""Router platform — Notifications + Idempotency (PRD §6).

Dua kelompok endpoint:

* **Notifications** — setiap user terautentikasi hanya boleh MELIHAT notifikasi
  miliknya sendiri ATAU notifikasi bertarget role-nya. Hanya user terkait yang
  boleh menandai sudah dibaca; admin lintas-user sengaja tidak dibuka di sini.
* **Idempotency** — pasangan check/record supaya endpoint tulis berisiko dapat
  memastikan operasi (key, scope) belum pernah dieksekusi sebelum menjalankan
  efek sampingnya.

Helper `notify()` diekspor dari `..platform_models` agar bisa dipakai modul lain
tanpa mengimpor router ini (mencegah siklus impor).
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user
from ..audit import log_audit
from .. import models
from ..platform_models import (Notification, IdempotencyKey, notify,
                               NOTIFICATION_CATEGORIES, NOTIFICATION_SEVERITIES)

router = APIRouter(prefix="/platform", tags=["platform"])


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Skema ────────────────────────────────────────────────────────────────────
class NotificationIn(BaseModel):
    """Payload pembuatan notifikasi oleh modul lain (atau UI)."""
    user_id: Optional[int] = None
    role_target: Optional[str] = Field(default=None, max_length=40)
    category: str = "SYSTEM"
    title: str = Field(min_length=1, max_length=200)
    body: Optional[str] = None
    link_path: Optional[str] = Field(default=None, max_length=200)
    severity: str = "INFO"
    # Kalau diisi dan sudah pernah ada, notifikasi baru TIDAK dibuat.
    dedup_key: Optional[str] = Field(default=None, max_length=160)


class IdempotencyCheckIn(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    scope: str = Field(min_length=1, max_length=80)


class IdempotencyRecordIn(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    scope: str = Field(min_length=1, max_length=80)
    request_hash: Optional[str] = Field(default=None, max_length=64)
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    expires_at: Optional[datetime] = None


# ── Serialisasi ──────────────────────────────────────────────────────────────
def _serialize(n: Notification):
    return {
        "id": n.id,
        "user_id": n.user_id,
        "role_target": n.role_target,
        "category": n.category,
        "title": n.title,
        "body": n.body,
        "link_path": n.link_path,
        "severity": n.severity,
        "is_read": bool(n.is_read),
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "dedup_key": n.dedup_key,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def _visible_filter(user):
    """Kondisi baris yang boleh dilihat `user`.

    Aturan: milik user sendiri, ATAU broadcast (user_id NULL tanpa role_target),
    ATAU ditargetkan ke role user. Role disimpan sebagai string di DB, jadi
    dibandingkan dengan `user.role.value`.
    """
    role_value = getattr(user.role, "value", user.role)
    return or_(
        Notification.user_id == user.id,
        Notification.role_target == role_value,
        # broadcast murni: tanpa penerima spesifik maupun role.
        (Notification.user_id.is_(None)) & (Notification.role_target.is_(None)),
    )


# ── Notifications ────────────────────────────────────────────────────────────
@router.get("/notifications")
def list_notifications(is_read: Optional[bool] = None, category: Optional[str] = None,
                       limit: int = Query(default=50, ge=1, le=200),
                       db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Daftar notifikasi milik user / role-nya / broadcast, terbaru dulu."""
    query = db.query(Notification).filter(_visible_filter(user))
    if is_read is not None:
        query = query.filter(Notification.is_read.is_(is_read))
    if category:
        query = query.filter(Notification.category == category.upper())
    rows = query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    return [_serialize(n) for n in rows]


@router.get("/notifications/unread-count")
def unread_count(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Jumlah notifikasi belum dibaca — dipakai badge lonceng di topbar."""
    total = db.query(func.count(Notification.id)).filter(
        _visible_filter(user), Notification.is_read.is_(False)).scalar() or 0
    return {"count": int(total)}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Tandai SATU notifikasi sudah dibaca. Hanya jika notifikasi ini milik user."""
    row = db.get(Notification, notification_id)
    if not row:
        raise HTTPException(404, "Notifikasi tidak ditemukan.")
    if not _can_mark(user, row):
        raise HTTPException(403, "Notifikasi ini bukan milik Anda.")
    if not row.is_read:
        row.is_read = True
        row.read_at = datetime.utcnow()
        log_audit(db, user, "READ", "Notification", entity_id=row.id, detail=f"Notifikasi #{row.id} dibaca")
        db.commit()
    return _serialize(row)


@router.post("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Tandai semua notifikasi yang terlihat oleh user sebagai sudah dibaca."""
    rows = db.query(Notification).filter(_visible_filter(user), Notification.is_read.is_(False)).all()
    now = datetime.utcnow()
    for row in rows:
        row.is_read = True
        row.read_at = now
    if rows:
        log_audit(db, user, "READ_ALL", "Notification", detail=f"{len(rows)} notifikasi dibaca")
        db.commit()
    return {"updated": len(rows)}


@router.post("/notifications", status_code=201)
def create_notification(data: NotificationIn, db: Session = Depends(get_db),
                        user=Depends(get_current_user)):
    """Buat notifikasi untuk dipakai modul lain (atau UI).

    `dedup_key` menjamin tidak dobel: bila sudah ada, baris existing dikembalikan
    dengan status 201 (idempotent), bukan dibuat baru.
    """
    if data.category.upper() not in NOTIFICATION_CATEGORIES:
        raise HTTPException(400, f"Kategori tidak dikenal. Pilihan: {', '.join(NOTIFICATION_CATEGORIES)}.")
    if data.severity.upper() not in NOTIFICATION_SEVERITIES:
        raise HTTPException(400, f"Severity tidak dikenal. Pilihan: {', '.join(NOTIFICATION_SEVERITIES)}.")
    if data.user_id is None and not data.role_target:
        raise HTTPException(400, "Isi minimal user_id atau role_target (untuk broadcast keduanya kosong).")

    before = db.query(Notification).filter(Notification.dedup_key == data.dedup_key).first() if data.dedup_key else None
    row = notify(db, user_id=data.user_id, role_target=data.role_target,
                 category=data.category, title=data.title, body=data.body,
                 link_path=data.link_path, severity=data.severity, dedup_key=data.dedup_key)
    # Hanya catat audit bila baris benar-benar baru dibuat (bukan dedup hit).
    if before is None:
        log_audit(db, user, "CREATE", "Notification", entity_id=row.id,
                  detail=f"{data.category} -> {data.title}")
    db.commit()
    db.refresh(row)
    return _serialize(row)


def _can_mark(user, row: Notification) -> bool:
    """Apakah `user` berhak menandai baris ini dibaca?

    Milik sendiri atau broadcast selalu boleh (broadcast = dibaca oleh siapa pun
    yang melihatnya). Notifikasi role_target boleh ditandai oleh user dengan role
    tersebut. Notifikasi milik user lain: tidak boleh.
    """
    role_value = getattr(user.role, "value", user.role)
    if row.user_id == user.id:
        return True
    if row.user_id is None and row.role_target is None:
        return True
    if row.role_target == role_value:
        return True
    return False


# ── Idempotency ──────────────────────────────────────────────────────────────
@router.post("/idempotency/check")
def idempotency_check(data: IdempotencyCheckIn, db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    """Cek apakah operasi (key, scope) sudah pernah diproses.

    Mengembalikan `exists` + respons tersimpan (kalau ada). Endpoint tulis
    berisiko memanggil ini DULU; bila `exists=True`, cukup kembalikan
    `response` dan lewati efek samping.
    """
    row = db.query(IdempotencyKey).filter_by(key=data.key, scope=data.scope).first()
    if not row:
        return {"exists": False, "response": None}
    return {
        "exists": True,
        "response": {
            "response_status": row.response_status,
            "response_body": row.response_body,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        },
    }


@router.post("/idempotency/record", status_code=201)
def idempotency_record(data: IdempotencyRecordIn, db: Session = Depends(get_db),
                       user=Depends(get_current_user)):
    """Simpan (key, scope) + respons agar panggilan ulang tidak mengeksekusi dobel.

    Idempotent sendiri: kalau key sudah tercatat, catatan lama diperbarui
    (kecuali scope berbeda, yang akan tetap menimpa bila key sama karena key
    unik global — lihat catatan di bawah) dan tidak membuat baris ganda.
    """
    row = db.query(IdempotencyKey).filter_by(key=data.key).first()
    if row:
        # Sudah ada: perbarui respons dengan hasil terbaru, jangan gandakan baris.
        row.scope = data.scope
        row.request_hash = data.request_hash
        row.response_status = data.response_status
        row.response_body = data.response_body
        if data.expires_at:
            row.expires_at = data.expires_at
    else:
        row = IdempotencyKey(
            key=data.key, scope=data.scope, request_hash=data.request_hash,
            response_status=data.response_status, response_body=data.response_body,
            user_id=user.id, expires_at=data.expires_at,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "key": row.key, "scope": row.scope}
