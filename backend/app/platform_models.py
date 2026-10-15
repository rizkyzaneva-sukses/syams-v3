"""Modul Platform: Notifications + Idempotency (PRD §6).

Menutup dua celah infrastruktur yang dipakai lintas modul:

1. **Notification** — tabel notifikasi umum. Sebelumnya setiap modul yang ingin
   "memberi tahu seseorang" tidak punya tempat tinggal bersama, sehingga tidak
   ada lonceng, tidak ada unread-count, dan tidak ada riwayat baca.
   Satu baris bisa ditujukan ke SATU user (`user_id`) ATAU ke SEMUA user dengan
   role tertentu (`role_target`, mis. 'CFO_MANAGER' -> semua CFO Manager).

2. **IdempotencyKey** — tabel idempotency umum. Modul accounting sudah punya
   `source_ref` di journal_entries untuk menjaga auto-posting tidak dobel, tapi
   itu spesifik accounting. Endpoint tulis berisiko (create payment, release
   SPK, dsb.) butuh tabel umum: cek dulu apakah (key, scope) sudah pernah
   diproses, kalau ya kembalikan respons lama tanpa mengeksekusi ulang.

Helper `notify()` sengaja ditulis di sini (bukan di router) supaya modul lain
bisa `from ..platform_models import notify` TANPA mengimpor router — menghindari
siklus impor dan membuat pemakaian dari service/seed lebih mudah.
"""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Text, Boolean, DateTime,
                        ForeignKey, Index, text)
from sqlalchemy.orm import Session
from .database import Base

# Nilai sah untuk kolom kategori & severity. Divalidasi di router (bukan Enum DB)
# supaya menambah kategori baru cukup ubah satu tempat tanpa migrasi tipe.
NOTIFICATION_CATEGORIES = ("APPROVAL", "DUE_DATE", "MATERIAL", "FINANCE", "EXCEPTION", "SYSTEM")
NOTIFICATION_SEVERITIES = ("INFO", "WARNING", "CRITICAL")


class Notification(Base):
    """Notifikasi umum milik satu user, satu role, atau broadcast ke semua.

    Tingkat baca (is_read/read_at) selalu PER-BARIS. Untuk notifikasi bertarget
    role, `role_target` menandai audiensnya; pembacaan per-user direpresentasikan
    lewat baris yang dibuat khusus dengan `user_id` terisi (dibuat oleh router),
    sehingga "sudah dibaca oleh A" tidak memaksa "sudah dibaca oleh B".
    """
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    # NULL = broadcast (tidak diarahkan ke user tertentu).
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # NULL = bukan notifikasi berbasis role. Kalau diisi, dipetakan ke semua user
    # yang role-nya sama (mis. 'CFO_MANAGER').
    role_target = Column(String(40), nullable=True, index=True)
    category = Column(String(24), nullable=False, default="SYSTEM", index=True)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    link_path = Column(String(200), nullable=True)
    severity = Column(String(16), nullable=False, default="INFO", index=True)
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    # dedup_key = kunci anti-dobel dari pemanggil (mis. f"APPROVAL:{order_id}").
    # Bila sama, baris baru tidak dibuat — lihat notify().
    dedup_key = Column(String(160), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        # Keunikan dedup_key hanya berlaku saat kuncinya terisi. Index parsial
        # (bukan UniqueConstraint biasa) dipakai karena banyak baris tanpa
        # dedup_key adalah hal yang normal, jadi NULL tidak boleh dianggap unik.
        Index("uq_notification_dedup_key", "dedup_key", unique=True,
              postgresql_where=text("dedup_key IS NOT NULL"),
              sqlite_where=text("dedup_key IS NOT NULL")),
    )


class IdempotencyKey(Base):
    """Catatan idempotency untuk endpoint tulis berisiko (PRD §6).

    Alur pemakaian: endpoint memanggil POST /platform/idempotency/check dengan
    (key, scope). Kalau `exists=True`, endpoint mengembalikan respons tersimpan
    dan BERHENTI (tidak mengeksekusi efek samping dua kali). Kalau belum ada,
    endpoint melakukan pekerjaannya lalu POST /platform/idempotency/record untuk
    menyimpan (key, scope, status, body) agar panggilan ulang aman.
    """
    __tablename__ = "idempotency_keys"
    id = Column(Integer, primary_key=True)
    key = Column(String(160), nullable=False, unique=True, index=True)
    # scope = konteks operasi, mis. 'payment-create'. (key, scope) bersama-sama
    # mengidentifikasi satu operasi logis sehingga key yang sama untuk scope
    # berbeda tidak saling menimpa.
    scope = Column(String(80), nullable=False, index=True)
    # request_hash = sidik jari payload permintaan (sha256 hex, 64 char). Dipakai
    # untuk mendeteksi pengiriman key yang sama dengan payload berbeda.
    request_hash = Column(String(64), nullable=True)
    response_status = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)


def notify(db: Session, user_id=None, role_target=None, category="SYSTEM",
           title="", body=None, link_path=None, severity="INFO", dedup_key=None,
           commit=False, audit_user=None):
    """Buat satu notifikasi, idempotent terhadap `dedup_key`.

    Mengembalikan objek Notification yang dibuat, ATAU baris yang sudah ada
    kalau `dedup_key` sudah pernah dipakai — sehingga pemanggil boleh memanggil
    ulang tanpa takut menggandakan notifikasi.

    Catatan transaksi: fungsi ini HANYA `db.add` + `db.flush` (bukan commit)
    supaya notifikasi ikut transaksi bisnis pemanggil — kalau operasi utama
    gagal dan rollback, notifikasi pun batal. Set `commit=True` bila dipanggil
    di luar transaksi (mis. dari cron).

    `severity` dinormalisasi; nilai tak dikenal jatuh ke 'INFO' agar satu typo
    tidak membuat notifikasi hilang dari daftar.
    """
    if dedup_key:
        existing = db.query(Notification).filter(Notification.dedup_key == dedup_key).first()
        if existing:
            # JANGAN buat baru: kunci yang sama berarti notifikasi ini sudah ada.
            return existing

    sev = (severity or "INFO").upper()
    if sev not in NOTIFICATION_SEVERITIES:
        sev = "INFO"
    cat = (category or "SYSTEM").upper()
    if cat not in NOTIFICATION_CATEGORIES:
        cat = "SYSTEM"

    entry = Notification(
        user_id=user_id, role_target=role_target, category=cat,
        title=title, body=body, link_path=link_path, severity=sev,
        dedup_key=dedup_key,
    )
    db.add(entry)
    try:
        db.flush()
    except Exception:
        # Balapan jarak dekat (dua request membuat dedup_key sama sekaligus):
        # unique index parsial menolak yang kedua. Ambil baris pemenang dan
        # kembalikan itu — perilaku tetap idempotent, bukan error ke pemanggil.
        db.rollback()
        if dedup_key:
            existing = db.query(Notification).filter(Notification.dedup_key == dedup_key).first()
            if existing:
                if commit:
                    db.commit()
                return existing
        raise
    if commit:
        db.commit()
    return entry
