"""Modul Artwork Versioning BOS SYAMS (workspace Diki — CMO Support / SAMPLE_PIC).

Melengkapi gap PRD §7 & BLUEPRINT §3.8: "Artwork yang sudah diganti tidak boleh
dicetak sebagai versi aktif. Iman mencatat penerimaan versi."

Sebelumnya artwork hanya berupa SATU kolom string (``Article.approved_artwork_version``),
sehingga tidak ada riwayat versi, tidak ada status (DRAFT/APPROVED/SUPERSEDED/
OBSOLETE), dan tidak ada peringatan saat versi lama dicoba dipakai lagi. Modul
ini menambah tiga tabel:

* ``Artwork``          — kepala artwork per (artikel, jenis). Satu artikel bisa
                         punya SABLON, BORDIR, LABEL, LAINNYA sekaligus.
* ``ArtworkVersion``   — tiap unggahan file adalah satu versi yang tidak bisa
                         ditimpa; koreksi = versi baru (immutability seperti
                         SampleRecord / SPK version).
* ``ArtworkHandover``  — serah terima versi ke Iman (PRINTING_PIC) plus catatan
                         penerimaan versi (BLUEPRINT §3.6).

Prinsip yang ditegakkan di level model + status:

1. Artwork hanya boleh dicetak dari versi berstatus ``APPROVED``. Status
   ``SUPERSEDED``/``OBSOLETE`` TIDAK PERNAH boleh dipakai mencetak — router yang
   memaksa aturan itu, model hanya menyimpan statusnya apa adanya.
2. Versi tidak dihapus/ditimpa. Versi lama yang sudah APPROVED otomatis menjadi
   ``SUPERSEDED`` dengan menunjuk ``superseded_by_id`` ke versi penggantinya,
   jadi rantai revisi bisa dibaca apa adanya.
3. ``UNIQUE(article_id, artwork_type)`` memaksa satu kepala artwork per jenis;
   ``UNIQUE(artwork_id, version_no)`` memaksa nomor versi tidak melompat/ganda.
"""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Text, Boolean, DateTime,
                        ForeignKey, UniqueConstraint)
from .database import Base


# Jenis artwork yang dikenal. ``LAINNYA`` menampung jenis yang belum terdaftar
# supaya operator tidak menulis teks bebas (yang membuat laporan tidak bisa
# difilter) sekaligus tidak memaksa migrasi tiap kali ada jenis baru.
ARTWORK_TYPES = ("SABLON", "BORDIR", "LABEL", "LAINNYA")

# Status versi artwork. Urutannya menggambarkan siklus hidup:
# DRAFT -> SUBMITTED -> APPROVED -> (SUPERSEDED | OBSOLETE).
# SUPERSEDED = digantikan versi lebih baru; OBSOLETE = dibatalkan tanpa pengganti.
ARTWORK_VERSION_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "OBSOLETE", "SUPERSEDED")

# HANYA status ini yang boleh dipakai mencetak produksi (guardrail PRD §7).
PRINTABLE_VERSION_STATUSES = ("APPROVED",)


class Artwork(Base):
    """Kepala artwork per (artikel, jenis) — wadah dari semua versi."""
    __tablename__ = "artworks"
    __table_args__ = (
        # Satu artikel hanya punya satu kepala artwork per jenis. Kalau ingin
        # artwork SABLON kedua untuk artikel yang sama, itu berarti revisi baru
        # dari kepala yang sama, bukan baris baru.
        UniqueConstraint("article_id", "artwork_type", name="uq_artwork_article_type"),
    )
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    # SABLON / BORDIR / LABEL / LAINNYA
    artwork_type = Column(String(20), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    # Versi yang sedang berlaku. Dinaikkan router setiap kali versi baru diunggah
    # supaya daftar/detail tidak perlu menghitung max() berulang.
    current_version_no = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class ArtworkVersion(Base):
    """Satu unggahan berkas artwork — immutable, koreksi lewat versi baru."""
    __tablename__ = "artwork_versions"
    __table_args__ = (
        # Nomor versi per artwork tidak boleh ganda/melompat; router yang
        # menetapkan max+1, constraint yang menjaganya kalau ada balapan.
        UniqueConstraint("artwork_id", "version_no", name="uq_artwork_version_no"),
    )
    id = Column(Integer, primary_key=True)
    artwork_id = Column(Integer, ForeignKey("artworks.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    # Referensi berkas: path di storage atau URL. Disimpan sebagai String(500)
    # supaya bisa dipakai untuk path maupun URL tanpa kolom terpisah.
    file_ref = Column(String(500), nullable=False)
    file_name = Column(String(255), nullable=False)
    # Referensi dari buyer (mis. nomor PO/buyer artwork code) bila ada.
    buyer_reference = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    # DRAFT / SUBMITTED / APPROVED / OBSOLETE / SUPERSEDED
    status = Column(String(16), default="DRAFT", nullable=False, index=True)
    submitted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    # Versi pengganti (diisi saat versi ini di-SUPERSEDE oleh versi lebih baru).
    superseded_by_id = Column(Integer, ForeignKey("artwork_versions.id"), nullable=True)
    # Penerimaan versi oleh Iman (PRINTING_PIC) — BLUEPRINT §3.6.
    received_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    received_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ArtworkHandover(Base):
    """Serah terima satu versi artwork ke Iman + jejak cetak & penerimaannya."""
    __tablename__ = "artwork_handovers"
    id = Column(Integer, primary_key=True)
    artwork_version_id = Column(Integer, ForeignKey("artwork_versions.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    # PIC tujuan serah terima (default Iman); disimpan teks karena bisa jadi
    # nama orang di luar daftar user, sama pola dengan PrintingHandoff.sender.
    to_pic = Column(String(120), nullable=False)
    handed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    handover_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    printed = Column(Boolean, default=False, nullable=False)
    print_register_no = Column(String(120), nullable=True)
    # Penerimaan oleh Iman (BLUEPRINT §3.6): dicatat terpisah dari pengiriman,
    # supaya "sudah diserahkan" dan "sudah diterima" bisa dibedakan.
    acknowledged_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
