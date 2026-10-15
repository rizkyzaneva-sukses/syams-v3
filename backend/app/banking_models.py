"""Modul Bank Reconciliation + Treasury BOS SYAMS.

Melengkapi Finance (PRD §5): rekonsiliasi mutasi bank terhadap jurnal akuntansi
yang sudah POSTED. Modul ini TIDAK membuat jurnal sendiri — ia hanya MENCOCOKKAN
mutasi bank (dari statement) dengan baris jurnal atau payment yang sudah ada,
supaya saldo bank menurut statement bisa dibuktikan sama dengan saldo menurut
buku besar.

Prinsip yang ditegakkan di level model + router:
1. Mutasi bank disimpan apa adanya dari import (debit = uang masuk, credit =
   uang keluar) dan diberi status rekonsiliasi terpisah — TIDAK PERNAH menimpa
   jurnal. Rekonsiliasi adalah tindakan pencocokan, bukan posting baru.
2. Satu mutasi yang sudah RECONCILED terkunci: reconcile ulang ditolak (409).
   Koreksi dilakukan dengan unreconcile (dengan jejak audit), bukan timpa diam-diam.
3. Pencocokan hanya boleh menunjuk ke target yang NYATA (journal_line/payment
   yang ada). Target kosong = ditolak (400), bukan "reconciled tanpa lawan".
4. Treasury dihitung dari jurnal POSTED untuk akun COA yang is_cash_account=True
   — tidak ada tabel posisi terpisah yang bisa drift dari buku besar.
"""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Text, Boolean, Date, DateTime,
                        Numeric, ForeignKey, Index)
from .database import Base


# Status rekonsiliasi yang sah untuk satu mutasi bank.
RECON_STATUSES = ("UNRECONCILED", "MATCHED", "RECONCILED", "IGNORED")


class BankAccount(Base):
    """Akun bank/cash milik perusahaan (rekening riil), ditaut ke akun COA."""
    __tablename__ = "bank_accounts"
    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False, index=True)
    bank_name = Column(String(120), nullable=False)
    account_no = Column(String(64), nullable=True)
    account_name = Column(String(160), nullable=True)
    currency = Column(String(8), nullable=False, default="IDR")
    # Saldo awal menurut statement bank saat mulai direkonsiliasi.
    opening_balance = Column(Numeric(18, 2), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    # Tautan ke akun buku besar (kas/bank). Boleh NULL kalau akun COA belum
    # ditentukan, tetapi rekonsiliasi saldo hanya mungkin kalau terisi.
    gl_account_id = Column(Integer, ForeignKey("chart_of_accounts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BankTransaction(Base):
    """Satu baris mutasi dari statement bank yang diimport.

    debit = uang MASUK ke rekening; credit = uang KELUAR dari rekening. Konvensi
    ini sengaja mengikuti sisi debit/kredit akun bank di buku besar, sehingga
    pencocokan nominal tidak perlu membalik tanda.
    """
    __tablename__ = "bank_transactions"
    id = Column(Integer, primary_key=True)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    txn_date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)
    debit = Column(Numeric(18, 2), nullable=False, default=0)   # uang masuk
    credit = Column(Numeric(18, 2), nullable=False, default=0)  # uang keluar
    reference = Column(String(120), nullable=True)
    # Saldo setelah mutasi menurut statement (opsional, untuk cek berjalan).
    balance_after = Column(Numeric(18, 2), nullable=True)
    # Penanda batch import supaya satu set import bisa ditelusuri/dibatalkan.
    import_batch = Column(String(60), nullable=True, index=True)
    reconciliation_status = Column(String(16), nullable=False, default="UNRECONCILED",
                                   index=True)  # UNRECONCILED/MATCHED/RECONCILED/IGNORED
    matched_journal_line_id = Column(Integer, ForeignKey("journal_lines.id"), nullable=True)
    matched_payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    matched_at = Column(DateTime, nullable=True)
    matched_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Indeks gabungan: query daftar mutasi per akun dalam rentang tanggal adalah
    # akses terpanas di modul ini (UI selalu memfilter per akun + periode).
    __table_args__ = (Index("ix_bank_txn_account_date", "bank_account_id", "txn_date"),)
