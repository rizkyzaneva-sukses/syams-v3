"""Artwork Versioning — versi artwork per artikel + guardrail obsolete.

Menutup gap PRD §7 & BLUEPRINT §3.8/§3.6: "Artwork yang sudah diganti tidak
boleh dicetak sebagai versi aktif. Iman mencatat penerimaan versi."

Sebelumnya artwork hanya satu kolom string di ``Article``. Modul ini memberi
riwayat versi yang tidak bisa ditimpa, status eksplisit, dan — yang paling
penting — GUARDRAIL NYATA di ``GET /artwork/can-print``: produksi hanya boleh
mencetak versi berstatus ``APPROVED``. Versi ``SUPERSEDED``/``OBSOLETE`` selalu
menjawab ``boleh_cetak=false`` dengan alasan, sehingga pekerjaan tidak pernah
memakai artwork basi.

Pola role (workspace Diki):
* baca  — semua user terautentikasi (read-only).
* tulis — CMO_SUPPORT, CMO_MANAGER (kelola berkas & approve), SAMPLE_PIC
          (Diki mendukung sample), PRINTING_PIC (Iman — serah terima/penerimaan).

Endpoint:
``GET  /artwork``                       daftar artwork (filter article_id/order_fk)
``POST /artwork``                       buat kepala artwork per artikel
``GET  /artwork/can-print``             GUARDRAIL: boleh cetak atau tidak
``GET  /artwork/{id}``                  detail + semua versi
``POST /artwork/{id}/versions``         unggah versi baru (max+1, SUPERSEDED versi lama)
``POST /artwork/versions/{id}/approve`` APPROVED (tolak 409 kalau OBSOLETE/SUPERSEDED)
``POST /artwork/versions/{id}/obsolete``OBSOLETE (wajib alasan)
``POST /artwork/versions/{id}/handover``serah terima ke Iman (printed/print_register_no)
``POST /artwork/handovers/{id}/acknowledge`` Iman mencatat penerimaan versi (BLUEPRINT §3.6)
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..auth import get_current_user
from ..database import get_db
from ..workflow import role as role_of
from .. import models as m
from ..artwork_models import (Artwork, ArtworkVersion, ArtworkHandover,
                              ARTWORK_TYPES, ARTWORK_VERSION_STATUSES,
                              PRINTABLE_VERSION_STATUSES)

router = APIRouter(prefix="/artwork", tags=["artwork"])

# Semua role terautentikasi boleh membaca. Write dibagi dua: pengelola berkas
# (CMO/SAMPLE) dan penerima di Printing (Iman).
WRITE_ROLES = ("CMO_SUPPORT", "CMO_MANAGER", "SAMPLE_PIC", "PRINTING_PIC")
# Approve adalah keputusan CMO, bukan Printing — Iman menerima, tidak mengesahkan.
APPROVE_ROLES = ("CMO_SUPPORT", "CMO_MANAGER")
# Penerimaan versi dicatat oleh Iman (PRINTING_PIC), bisa juga CMO bila Iman
# tidak sempat mencatat sendiri.
ACK_ROLES = ("PRINTING_PIC", "CMO_SUPPORT", "CMO_MANAGER")
DEFAULT_RECEIVER = "Iman"


# ── Skema request ────────────────────────────────────────────────────────────
class ArtworkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: int
    artwork_type: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=200)


class VersionIn(BaseModel):
    """Unggah versi baru. version_no TIDAK diterima dari klien — dihitung server."""
    model_config = ConfigDict(extra="forbid")
    file_ref: str = Field(min_length=1, max_length=500)
    file_name: str = Field(min_length=1, max_length=255)
    buyer_reference: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=4000)


class ObsoleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)


class HandoverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_pic: Optional[str] = Field(default=None, max_length=120)
    printed: bool = False
    print_register_no: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=2000)


class AckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: Optional[str] = Field(default=None, max_length=2000)


# ── Helper ───────────────────────────────────────────────────────────────────
def _require_write(user, db: Session, *roles):
    """Role tulis; penolakan tetap dicatat sebagai DENIED_* di audit_logs."""
    if role_of(user) not in roles:
        log_audit(db, user, "DENIED_ARTWORK_WRITE", "ArtworkWrite", None,
                  detail=f"role={role_of(user)} tidak boleh menulis data artwork",
                  source_module="artwork", reason="WRITE_ROLE_FORBIDDEN")
        db.commit()
        raise HTTPException(403, "Peran ini tidak berhak mengubah data artwork.")
    return user


def _iso(value):
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _version_payload(row: ArtworkVersion) -> dict:
    return {
        "id": row.id,
        "artwork_id": row.artwork_id,
        "version_no": row.version_no,
        "file_ref": row.file_ref,
        "file_name": row.file_name,
        "buyer_reference": row.buyer_reference,
        "notes": row.notes,
        "status": row.status,
        "submitted_by_id": row.submitted_by_id,
        "approved_by_id": row.approved_by_id,
        "approved_at": _iso(row.approved_at),
        "superseded_by_id": row.superseded_by_id,
        "received_by_id": row.received_by_id,
        "received_at": _iso(row.received_at),
        "created_at": _iso(row.created_at),
        # Dua flag turunan yang dipakai UI apa adanya — tidak dihitung ulang di
        # frontend supaya UI tidak bisa "terlihat boleh cetak" padahal tidak.
        "is_printable": row.status in PRINTABLE_VERSION_STATUSES,
        "is_obsolete": row.status == "OBSOLETE",
        "is_superseded": row.status == "SUPERSEDED",
    }


def _handover_payload(row: ArtworkHandover) -> dict:
    return {
        "id": row.id,
        "artwork_version_id": row.artwork_version_id,
        "to_pic": row.to_pic,
        "handed_by_id": row.handed_by_id,
        "handover_at": _iso(row.handover_at),
        "printed": row.printed,
        "print_register_no": row.print_register_no,
        "acknowledged_by_id": row.acknowledged_by_id,
        "acknowledged_at": _iso(row.acknowledged_at),
        "acknowledged": row.acknowledged_at is not None,
        "notes": row.notes,
        "created_at": _iso(row.created_at),
    }


def _artwork_payload(db: Session, row: Artwork, with_versions: bool = False) -> dict:
    versions = (db.query(ArtworkVersion)
                .filter(ArtworkVersion.artwork_id == row.id)
                .order_by(desc(ArtworkVersion.version_no)).all())
    current = next((v for v in versions if v.version_no == row.current_version_no), None)
    if current is None and versions:
        current = versions[0]
    payload = {
        "id": row.id,
        "article_id": row.article_id,
        "artwork_type": row.artwork_type,
        "title": row.title,
        "current_version_no": row.current_version_no,
        "is_active": row.is_active,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "version_count": len(versions),
        "current_version": _version_payload(current) if current else None,
        "current_is_printable": bool(current and current.status in PRINTABLE_VERSION_STATUSES),
    }
    if with_versions:
        handovers = {}
        version_ids = [v.id for v in versions]
        if version_ids:
            for h in (db.query(ArtworkHandover)
                      .filter(ArtworkHandover.artwork_version_id.in_(version_ids))
                      .order_by(desc(ArtworkHandover.id)).all()):
                handovers.setdefault(h.artwork_version_id, []).append(_handover_payload(h))
        payload["versions"] = [
            {**_version_payload(v), "handovers": handovers.get(v.id, [])} for v in versions
        ]
    return payload


# ── GET/POST /artwork ────────────────────────────────────────────────────────
@router.get("")
def list_artworks(
    article_id: int = Query(None, description="Filter satu artikel"),
    order_fk: int = Query(None, description="Filter semua artwork pada satu Order"),
    artwork_type: str = Query(None, min_length=1),
    limit: int = Query(300, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Daftar kepala artwork (kepala + versi terkini), per artikel/order."""
    query = db.query(Artwork)
    if article_id is not None:
        query = query.filter(Artwork.article_id == article_id)
    if order_fk is not None:
        query = query.join(m.Article, m.Article.id == Artwork.article_id).filter(
            m.Article.order_fk == order_fk)
    if artwork_type:
        query = query.filter(Artwork.artwork_type == artwork_type.strip().upper())
    rows = query.order_by(desc(Artwork.updated_at), desc(Artwork.id)).limit(limit).all()
    return {
        "rows": [_artwork_payload(db, row) for row in rows],
        "total": len(rows),
        "artwork_types": list(ARTWORK_TYPES),
        "version_statuses": list(ARTWORK_VERSION_STATUSES),
        "source": "artworks + artwork_versions",
    }


@router.post("")
def create_artwork(
    payload: ArtworkIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Buat kepala artwork untuk satu artikel.

    Kalau kepala untuk (artikel, jenis) sudah ada, permintaan ditolak 409: itu
    bukan artwork baru, melainkan revisi — yang benar adalah mengunggah versi
    baru lewat ``POST /artwork/{id}/versions``.
    """
    _require_write(user, db, *WRITE_ROLES)
    artwork_type = payload.artwork_type.strip().upper()
    if artwork_type not in ARTWORK_TYPES:
        raise HTTPException(422, f"artwork_type tidak dikenal; pilih salah satu dari {list(ARTWORK_TYPES)}")
    article = db.get(m.Article, payload.article_id)
    if article is None:
        raise HTTPException(404, "Artikel tidak ditemukan")

    existing = (db.query(Artwork)
                .filter(Artwork.article_id == payload.article_id,
                        Artwork.artwork_type == artwork_type).first())
    if existing is not None:
        raise HTTPException(409, f"Artwork {artwork_type} untuk artikel ini sudah ada "
                                 f"(id={existing.id}); unggah versi baru untuk merevisi.")

    row = Artwork(article_id=payload.article_id, artwork_type=artwork_type,
                  title=payload.title.strip(), current_version_no=1, is_active=True)
    db.add(row)
    db.flush()
    log_audit(db, user, "CREATE_ARTWORK", "Artwork", row.id,
              detail=f"artwork {artwork_type} untuk artikel {article.article_code}: {row.title}",
              obj=row, source_module="artwork", new_status="CREATED", reason="ARTWORK_DIBUAT")
    db.commit()
    db.refresh(row)
    return _artwork_payload(db, row, with_versions=True)


# ── GUARDRAIL: boleh cetak atau tidak ────────────────────────────────────────
@router.get("/can-print")
def can_print(
    article_id: int = Query(..., description="Artikel yang mau dicetak"),
    artwork_type: str = Query(None, description="Kosongkan untuk semua jenis artwork"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Apakah artwork artikel ini boleh dipakai mencetak? (GUARDRAIL PRD §7)

    Hanya versi berstatus ``APPROVED`` yang ``boleh_cetak=true``. Versi
    ``SUPERSEDED`` (sudah digantikan) dan ``OBSOLETE`` (dibatalkan) SELALU
    menjawab ``false`` beserta alasannya, sehingga pekerjaan tidak pernah
    mencetak artwork basi tanpa disadari.

    Bila ada lebih dari satu jenis artwork untuk artikel, hasil keseluruhan
    ``boleh_cetak`` hanya true kalau SEMUA jenis punya versi aktif yang bisa
    dicetak — mencetak separuh artwork yang salah tetap salah.
    """
    article = db.get(m.Article, article_id)
    if article is None:
        raise HTTPException(404, "Artikel tidak ditemukan")

    query = db.query(Artwork).filter(Artwork.article_id == article_id,
                                     Artwork.is_active.is_(True))
    if artwork_type:
        query = query.filter(Artwork.artwork_type == artwork_type.strip().upper())
    artworks = query.order_by(Artwork.artwork_type.asc()).all()

    jenis = []
    for art in artworks:
        versions = (db.query(ArtworkVersion)
                    .filter(ArtworkVersion.artwork_id == art.id)
                    .order_by(desc(ArtworkVersion.version_no)).all())
        current = next((v for v in versions if v.version_no == art.current_version_no), None)
        if current is None and versions:
            current = versions[0]

        # Alasan penolakan yang spesifik — bukan sekadar tombol mati.
        if current is None:
            boleh, alasan = False, "Artwork belum punya versi sama sekali"
        elif current.status == "SUPERSEDED":
            boleh = False
            alasan = (f"Versi v{current.version_no} sudah SUPERSEDED (digantikan versi lebih baru); "
                      f"jangan dicetak sebagai versi aktif")
        elif current.status == "OBSOLETE":
            boleh = False
            alasan = f"Versi v{current.version_no} sudah OBSOLETE (dibatalkan); tidak boleh dicetak"
        elif current.status == "APPROVED":
            boleh, alasan = True, f"Versi v{current.version_no} APPROVED siap cetak"
        else:
            boleh = False
            alasan = (f"Versi v{current.version_no} masih {current.status}; "
                      f"harus APPROVED sebelum boleh dicetak")

        jenis.append({
            "artwork_id": art.id,
            "artwork_type": art.artwork_type,
            "title": art.title,
            "current_version": _version_payload(current) if current else None,
            "boleh_cetak": boleh,
            "alasan": alasan,
        })

    boleh_semua = bool(jenis) and all(item["boleh_cetak"] for item in jenis)
    if not jenis:
        alasan_semua = "Belum ada artwork yang dibuat untuk artikel ini"
    elif boleh_semua:
        alasan_semua = "Semua jenis artwork punya versi APPROVED yang berlaku"
    else:
        alasan_semua = "; ".join(f"{j['artwork_type']}: {j['alasan']}"
                                 for j in jenis if not j["boleh_cetak"])
    # OBSOLETE/SUPERSEDED = peringatan merah yang harus dibaca UI.
    ada_obsolete = any(j["current_version"] and j["current_version"]["is_obsolete"] for j in jenis)
    ada_superseded = any(j["current_version"] and j["current_version"]["is_superseded"] for j in jenis)

    return {
        "article_id": article_id,
        "article_code": article.article_code,
        "artwork_type_filter": artwork_type.strip().upper() if artwork_type else None,
        "boleh_cetak": boleh_semua,
        "alasan": alasan_semua,
        "ada_versi_obsolete": ada_obsolete,
        "ada_versi_superseded": ada_superseded,
        "jenis": jenis,
        "rule": ("Hanya artwork APPROVED yang boleh dicetak. Versi yang sudah "
                 "digantikan (SUPERSEDED) atau dibatalkan (OBSOLETE) tidak boleh "
                 "dipakai sebagai versi aktif — PRD §7 / BLUEPRINT §3.8."),
    }


# ── GET /artwork/{id} ────────────────────────────────────────────────────────
@router.get("/{artwork_id}")
def get_artwork(
    artwork_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Detail satu artwork: seluruh riwayat versi + serah terimanya."""
    row = db.get(Artwork, artwork_id)
    if row is None:
        raise HTTPException(404, "Artwork tidak ditemukan")
    article = db.get(m.Article, row.article_id)
    payload = _artwork_payload(db, row, with_versions=True)
    payload["article"] = ({
        "id": article.id,
        "article_code": article.article_code,
        "order_fk": article.order_fk,
        "garment_type": article.garment_type,
    } if article else None)
    return payload


# ── POST /artwork/{id}/versions ──────────────────────────────────────────────
@router.post("/{artwork_id}/versions")
def create_version(
    artwork_id: int,
    payload: VersionIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Unggah versi artwork baru.

    * ``version_no`` dihitung otomatis = max(version_no)+1 (bukan dari klien).
    * Versi baru berstatus ``SUBMITTED`` (menunggu keputusan CMO).
    * Versi lama yang masih ``APPROVED`` otomatis menjadi ``SUPERSEDED`` dan
      ``superseded_by_id`` menunjuk versi baru — inilah yang mematikan versi
      basi sebagai versi aktif (guardrail PRD §7).
    * ``current_version_no`` pada kepala artwork dinaikkan.
    """
    _require_write(user, db, *WRITE_ROLES)
    art = db.get(Artwork, artwork_id)
    if art is None:
        raise HTTPException(404, "Artwork tidak ditemukan")
    if not art.is_active:
        raise HTTPException(409, "Artwork sudah dinonaktifkan; tidak bisa menambah versi")

    latest = (db.query(ArtworkVersion)
              .filter(ArtworkVersion.artwork_id == artwork_id)
              .order_by(desc(ArtworkVersion.version_no)).first())
    next_no = (latest.version_no if latest else 0) + 1

    new_version = ArtworkVersion(
        artwork_id=artwork_id, version_no=next_no,
        file_ref=payload.file_ref.strip(), file_name=payload.file_name.strip(),
        buyer_reference=payload.buyer_reference, notes=payload.notes,
        status="SUBMITTED", submitted_by_id=getattr(user, "id", None),
        created_at=datetime.utcnow(),
    )
    db.add(new_version)
    db.flush()

    # Versi lama yang masih berlaku sebagai APPROVED tidak boleh tetap "aktif".
    superseded = []
    for old in (db.query(ArtworkVersion)
                .filter(ArtworkVersion.artwork_id == artwork_id,
                        ArtworkVersion.id != new_version.id,
                        ArtworkVersion.status == "APPROVED").all()):
        old.status = "SUPERSEDED"
        old.superseded_by_id = new_version.id
        superseded.append(old.version_no)

    art.current_version_no = next_no
    art.updated_at = datetime.utcnow()

    log_audit(db, user, "CREATE_ARTWORK_VERSION", "ArtworkVersion", new_version.id,
              detail=(f"artwork {art.artwork_type} v{next_no} diunggah ({payload.file_name}); "
                      f"versi lama yang di-supersede: {superseded or '-'}"),
              obj=new_version, source_module="artwork",
              previous_status="APPROVED" if superseded else None, new_status="SUBMITTED",
              reason="VERSI_BARU_DIUNGGAH")
    db.commit()
    db.refresh(new_version)
    return {
        "version": _version_payload(new_version),
        "superseded_versions": superseded,
        "artwork": _artwork_payload(db, art, with_versions=True),
        "rule": ("Versi lama APPROVED otomatis menjadi SUPERSEDED dan tidak lagi boleh "
                 "dipakai mencetak; versi baru menunggu APPROVED."),
    }


# ── POST /artwork/versions/{id}/approve ──────────────────────────────────────
@router.post("/versions/{version_id}/approve")
def approve_version(
    version_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Setujui satu versi artwork (APPROVED) — CMO_SUPPORT/CMO_MANAGER.

    GUARDRAIL PRD §7: versi yang sudah ``OBSOLETE`` atau ``SUPERSEDED`` tidak
    boleh di-approve — ditolak dengan 409. Approve versi basi akan menghidupkan
    kembali artwork yang sudah digantikan, hal yang persis dilarang.
    """
    _require_write(user, db, *APPROVE_ROLES)
    row = db.get(ArtworkVersion, version_id)
    if row is None:
        raise HTTPException(404, "Versi artwork tidak ditemukan")

    status = (row.status or "").upper()
    if status in ("OBSOLETE", "SUPERSEDED"):
        log_audit(db, user, "DENIED_ARTWORK_APPROVE", "ArtworkVersion", row.id,
                  detail=f"versi v{row.version_no} berstatus {status} tidak boleh di-approve",
                  obj=row, source_module="artwork", previous_status=status,
                  reason="VERSI_BASI_TIDAK_BOLEH_DIAPPROVE")
        db.commit()
        raise HTTPException(409, f"Versi v{row.version_no} sudah {status}; tidak boleh di-approve "
                                 f"(artwork yang sudah diganti/dibatalkan tidak boleh jadi versi aktif).")
    if status == "APPROVED":
        raise HTTPException(409, "Versi ini sudah APPROVED.")

    art = db.get(Artwork, row.artwork_id)
    # Approve versi baru berarti ia MENGGANTIKAN versi APPROVED yang lebih lama.
    superseded = []
    for old in (db.query(ArtworkVersion)
                .filter(ArtworkVersion.artwork_id == row.artwork_id,
                        ArtworkVersion.id != row.id,
                        ArtworkVersion.status == "APPROVED").all()):
        old.status = "SUPERSEDED"
        old.superseded_by_id = row.id
        superseded.append(old.version_no)

    row.status = "APPROVED"
    row.approved_by_id = getattr(user, "id", None)
    row.approved_at = datetime.utcnow()
    if art is not None:
        art.current_version_no = row.version_no
        art.updated_at = datetime.utcnow()

    log_audit(db, user, "APPROVE_ARTWORK_VERSION", "ArtworkVersion", row.id,
              detail=(f"versi v{row.version_no} disetujui; versi lama di-supersede: {superseded or '-'}"),
              obj=row, source_module="artwork", previous_status=status, new_status="APPROVED",
              reason="ARTWORK_DISETUJUI")
    db.commit()
    db.refresh(row)
    return {
        "version": _version_payload(row),
        "superseded_versions": superseded,
        "artwork": _artwork_payload(db, art, with_versions=True) if art else None,
        "rule": "Hanya versi APPROVED yang boleh dipakai mencetak (PRD §7).",
    }


# ── POST /artwork/versions/{id}/obsolete ─────────────────────────────────────
@router.post("/versions/{version_id}/obsolete")
def obsolete_version(
    version_id: int,
    payload: ObsoleteIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Tandai versi artwork OBSOLETE — WAJIB alasan.

    Versi OBSOLETE tidak lagi bisa dicetak dan tidak bisa di-approve lagi.
    Alasan disimpan di audit (PRD §7: perubahan harus punya jejak), bukan
    dititipkan pada catatan bebas.
    """
    _require_write(user, db, *WRITE_ROLES)
    row = db.get(ArtworkVersion, version_id)
    if row is None:
        raise HTTPException(404, "Versi artwork tidak ditemukan")
    status = (row.status or "").upper()
    if status == "OBSOLETE":
        raise HTTPException(409, "Versi ini sudah OBSOLETE.")

    row.status = "OBSOLETE"
    log_audit(db, user, "OBSOLETE_ARTWORK_VERSION", "ArtworkVersion", row.id,
              detail=f"versi v{row.version_no} ditandai OBSOLETE: {payload.reason}",
              obj=row, source_module="artwork", previous_status=status, new_status="OBSOLETE",
              reason=payload.reason)
    db.commit()
    db.refresh(row)
    return {"version": _version_payload(row),
            "rule": "Versi OBSOLETE tidak bisa dicetak dan tidak bisa di-approve lagi."}


# ── POST /artwork/versions/{id}/handover ─────────────────────────────────────
@router.post("/versions/{version_id}/handover")
def handover_version(
    version_id: int,
    payload: HandoverIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Catat serah terima versi artwork ke Iman (default penerima).

    Hanya versi ``APPROVED`` yang boleh diserahkan untuk dicetak — menyerahkan
    versi SUBMITTED/dibatalkan akan menciptakan cetak dengan artwork belum sah.
    ``printed``/``print_register_no`` mencatat jejak cetak (register).
    """
    _require_write(user, db, *WRITE_ROLES)
    row = db.get(ArtworkVersion, version_id)
    if row is None:
        raise HTTPException(404, "Versi artwork tidak ditemukan")
    if row.status != "APPROVED":
        raise HTTPException(409, f"Hanya versi APPROVED yang boleh diserahkan; versi ini {row.status}.")

    handover = ArtworkHandover(
        artwork_version_id=row.id,
        to_pic=(payload.to_pic or DEFAULT_RECEIVER).strip(),
        handed_by_id=getattr(user, "id", None),
        handover_at=datetime.utcnow(),
        printed=bool(payload.printed),
        print_register_no=payload.print_register_no,
        notes=payload.notes,
    )
    db.add(handover)
    db.flush()
    log_audit(db, user, "ARTWORK_HANDOVER", "ArtworkHandover", handover.id,
              detail=(f"versi v{row.version_no} diserahkan ke {handover.to_pic} "
                      f"(printed={handover.printed}, register={handover.print_register_no or '-'})"),
              obj=handover, source_module="artwork", new_status="HANDED_OVER",
              reason="SERAH_TERIMA_ARTWORK")
    db.commit()
    db.refresh(handover)
    return {"handover": _handover_payload(handover),
            "version": _version_payload(row)}


# ── POST /artwork/handovers/{id}/acknowledge ─────────────────────────────────
@router.post("/handovers/{handover_id}/acknowledge")
def acknowledge_handover(
    handover_id: int,
    payload: AckIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Iman mencatat PENERIMAAN versi artwork (BLUEPRINT §3.6).

    Penerimaan dicatat terpisah dari serah terima supaya "sudah diserahkan"
    tidak pernah disamakan dengan "sudah diterima". Versi yang diterima
    menandai awal jejak pemakaian versi itu di Printing.
    """
    _require_write(user, db, *ACK_ROLES)
    handover = db.get(ArtworkHandover, handover_id)
    if handover is None:
        raise HTTPException(404, "Serah terima artwork tidak ditemukan")
    if handover.acknowledged_at is not None:
        raise HTTPException(409, "Serah terima ini sudah ditandai diterima.")

    version = db.get(ArtworkVersion, handover.artwork_version_id)
    # Versi yang sudah dibatalkan/digantikan TIDAK boleh ditandai diterima;
    # itu akan menyamarkan pemakaian artwork basi.
    if version is not None and version.status in ("OBSOLETE", "SUPERSEDED"):
        raise HTTPException(409, f"Versi v{version.version_no} berstatus {version.status}; "
                                 f"tidak boleh ditandai diterima.")

    now = datetime.utcnow()
    handover.acknowledged_by_id = getattr(user, "id", None)
    handover.acknowledged_at = now
    if payload.notes:
        handover.notes = ((handover.notes + " | ") if handover.notes else "") + payload.notes

    if version is not None:
        version.received_by_id = getattr(user, "id", None)
        version.received_at = now

    log_audit(db, user, "ACKNOWLEDGE_ARTWORK_HANDOVER", "ArtworkHandover", handover.id,
              detail=(f"penerimaan versi v{version.version_no if version else '-'} dicatat "
                      f"oleh role={role_of(user)}"),
              obj=handover, source_module="artwork", new_status="ACKNOWLEDGED",
              reason="ARTWORK_DITERIMA")
    db.commit()
    db.refresh(handover)
    return {"handover": _handover_payload(handover),
            "version": _version_payload(version) if version else None,
            "rule": "Penerimaan versi dicatat Iman (BLUEPRINT §3.6)."}
