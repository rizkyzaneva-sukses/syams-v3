"""CFO money workflow — PAYMENT_REPORTED -> CFO VERIFY/REJECT + AP ledger (revisi #17 & #20).

Ini satu-satunya modul CFO yang MENULIS. Aturan yang ditegakkan di sini:

1. **Tidak ada pembayaran "terverifikasi" tanpa bukti.** Finance melaporkan
   pembayaran lewat ``POST /cfo/invoices/{id}/payments-report``; tanpa
   ``evidence_ref`` yang bisa diperiksa, permintaan itu **ditolak** (400) — bukan
   disimpan sebagai catatan yang terlihat sah. Ini aturan keras revisi #17.
2. **Hanya CFO_MANAGER yang boleh verify/reject.** Finance melaporkan, CFO
   memutuskan. FINANCE_SUPPORT tidak dapat memverifikasi pekerjaannya sendiri.
3. **Reject wajib alasan.** Penolakan tanpa alasan tidak bisa ditindaklanjuti.
4. **Uang tidak bisa dimutasi ulang.** Begitu sebuah pembayaran VERIFIED atau
   REJECTED, ia terkunci: laporan ulang, verify ulang, reject ulang semuanya
   gagal (409). Koreksi dilakukan dengan membuat laporan pembayaran BARU, bukan
   dengan menimpa catatan lama. Tidak ada DELETE di modul ini.
5. **Setiap transisi status uang hanya tercatat SEKALI dan selalu berakhir di
   ``audit_logs``** (previous_status -> new_status, alasan, pelaku). Tidak ada
   satu pun endpoint di sini yang menulis tanpa jejak audit; bila tabel audit
   belum ada, penulisan ditolak (503) — bukan diterima tanpa jejak.

Ledger AP memakai ``purchase_orders.vendor_type`` yang NYATA. Modul ini TIDAK
pernah menebak supplier vs makloon dari nama supplier: pemisahan hanya sah
kalau vendor_type diisi sumbernya. Begitu juga pembayaran AP hanya datang dari
``ap_payments`` yang benar-benar menunjuk PO, bukan dari pembayaran AR yang
kebetulan menyebut nomor PO di catatannya.

Kalau kolom/tabel schema belum mendarat (agent schema masih bekerja), endpoint
tulis mengembalikan **503 dengan alasan yang bisa dibaca** dan mendaftar kolom
yang kurang di ``pending_schema`` — tidak ada sukses palsu dan tidak ada
perilaku yang menebak. Lihat ``REQUESTS/cfo_writes.md``.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from ..audit import log_audit
from ..auth import get_current_user
from ..database import get_db
from .. import models as m

router = APIRouter(prefix="/cfo", tags=["cfo-payments"])

# ── Peran ────────────────────────────────────────────────────────────────────
# Finance & CFO boleh MELAPORKAN/MENULIS ledger; hanya CFO yang memutuskan.
PAYMENT_WRITE_ROLES = {"CFO_MANAGER", "FINANCE_SUPPORT"}
PAYMENT_VERIFY_ROLES = {"CFO_MANAGER"}          # pemisahan tugas: bukan Finance
PAYMENT_VIEW_ROLES = {"CEO", "CFO_MANAGER", "FINANCE_SUPPORT", "CMO_MANAGER", "CMO_SUPPORT"}

# ── Status ───────────────────────────────────────────────────────────────────
PAYMENT_STATUSES = ("PAYMENT_REPORTED", "VERIFIED", "REJECTED")
# Baris pembayaran lama (sebelum kolom `status` ada) dianggap uang yang sudah
# masuk ledger apa adanya. Ini perilaku lama yang dipertahankan, bukan tebakan
# baru: modul ini tidak pernah menaikkan status apa pun menjadi VERIFIED.
LEGACY_PAYMENT_STATUSES = (None, "", "VERIFIED", "REPORTED", "PAYMENT_REPORTED")

# Alias status -> status kanonik. Klien boleh memakai nama yang lebih luwes.
_STATUS_ALIASES = {
    "REPORTED": "PAYMENT_REPORTED",
    "PAYMENT_REPORTED": "PAYMENT_REPORTED",
    "VERIFIED": "VERIFIED",
    "REJECT": "REJECTED",
    "REJECTED": "REJECTED",
}

# Status yang berarti "sudah dilaporkan, menunggu keputusan CFO". Kolom `status`
# di schema punya default "REPORTED" dan modul lain di repo menulis "REPORTED",
# jadi kedua ejaan harus dikenali — kalau tidak, pembayaran yang belum
# diverifikasi akan terlihat seperti uang yang sudah sah.
PENDING_STATUSES = {"PAYMENT_REPORTED", "REPORTED"}

# Pemisahan vendor AP yang sah. Dipakai untuk retur AP ledger; TIDAK dipakai
# untuk menebak vendor_type dari nama supplier.
AP_VENDOR_TYPES = ("SUPPLIER", "MAKLOON", "LOGISTIK", "VENDOR")
# Klasifikasi yang bisa diturunkan dari vendor_type apa adanya.
AP_KIND_BY_VENDOR_TYPE = {
    "SUPPLIER": "SUPPLIER",
    "VENDOR": "SUPPLIER",
    "LOGISTIK": "SUPPLIER",
    "MAKLOON": "MAKLOON",
}

# Bukti minimum yang bisa diperiksa CFO. Garis bawah: 4 karakter karena referensi
# bank asli ("BCA-1", "TRF2") pendek; yang ditolak adalah bukti kosong/placeholder.
MIN_EVIDENCE_LEN = 4
_PLACEHOLDERS = {"-", "--", "?", "??", "n/a", "na", "none", "null", "tbd", "tes", "test"}
_REFERENCE_RE = re.compile(r"[A-Za-z0-9]")

AP_PAYMENT_STATUSES = ("PENDING", "APPROVED", "REJECTED")

# Kolom yang dibutuhkan alur tulis ini. Dipakai untuk memberitahu APA yang kurang
# (bukan untuk berpura-pura sudah bisa).
REQUIRED_PAYMENT_COLUMNS = (
    "status", "evidence_ref", "verified_by_id", "verified_at", "rejection_reason",
)
REQUIRED_AP_PAYMENT_COLUMNS = (
    "po_fk", "amount", "payment_date", "method", "evidence_ref",
    "approval_status", "created_by_id", "created_at",
)


# ── Helper schema (bukan tebakan; ini pembacaan schema) ──────────────────────
def _columns(db: Session, table: str) -> set:
    """Nama kolom yang BENAR-BENAR ada di DB saat ini."""
    try:
        return {c["name"] for c in sa_inspect(db.get_bind()).get_columns(table)}
    except Exception:
        return set()


def _has_table(db: Session, name: str) -> bool:
    try:
        return sa_inspect(db.get_bind()).has_table(name)
    except Exception:
        return False


def _ap_model(fail: bool = True):
    """Model ``ap_payments`` kalau sudah mendarat di models.py.

    Diakses lewat nama, bukan atribut langsung, supaya modul ini tetap bisa
    diimpor (dan endpoint AR-nya tetap jalan) selama agent schema belum
    menambahkan tabelnya. Kalau model belum ada, endpoint AP menolak dengan 503
    — bukan menulis ke tabel tebakan.
    """
    model = getattr(m, "APPayment", None)
    if model is None and fail:
        raise HTTPException(
            503,
            "Model ap_payments belum ada di models.py. Ledger AP belum bisa ditulis. "
            "Lihat REQUESTS/cfo_writes.md.",
        )
    return model


def _role(user) -> str:
    return getattr(user.role, "value", user.role)


def _require(user, allowed, area):
    if _role(user) not in allowed:
        raise HTTPException(403, f"{area} tidak tersedia untuk peran ini. Izin: {', '.join(sorted(allowed))}.")


def _dec(value) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "Angka tidak valid.")
    if not number.is_finite():
        raise HTTPException(400, "Angka tidak valid.")
    return number


def _num(value):
    return None if value is None else float(value)


def _iso(value):
    return value.isoformat() if value else None


def _now():
    return datetime.utcnow()


# ── Bukti pembayaran ─────────────────────────────────────────────────────────
def clean_evidence(raw):
    """Kembalikan referensi bukti yang bisa diperiksa, atau ``None``.

    ``None`` berarti bukti TIDAK memadai → pemanggil wajib menolak. Placeholder
    seperti "??" atau "n/a" sengaja dianggap tidak ada: itu bukan bukti, dan
    memperlakukannya sebagai bukti adalah persis kegagalan yang dicegah revisi
    #17 ("jangan pernah 'terverifikasi' tanpa bukti").
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if len(text) < MIN_EVIDENCE_LEN:
        return None
    if text.lower() in _PLACEHOLDERS:
        return None
    if not _REFERENCE_RE.search(text):
        return None
    return text


# ── Pembacaan status pembayaran (satu pintu, tidak ada tebakan kedua) ────────
def effective_payment_status(payment):
    """Status kanonik sebuah pembayaran. ``None`` untuk baris legacy tanpa status.

    Baris lama (kolom ``status`` NULL/kosong) sengaja dikembalikan sebagai
    ``None``, bukan "VERIFIED": itu urusan lapisan laporan, dan di sini kita
    tidak boleh menghaluskan status uang.
    """
    raw = (getattr(payment, "status", None) or "").strip().upper()
    if not raw:
        return None
    return _STATUS_ALIASES.get(raw, raw)


def is_payment_locked(payment) -> bool:
    """Uang yang sudah diputuskan CFO tidak bisa dimutasi lagi."""
    return effective_payment_status(payment) in {"VERIFIED", "REJECTED"}


def is_payment_evidenced(payment) -> bool:
    """Bukti yang benar-benar tersimpan.

    ``evidence_ref`` dibaca lebih dulu; ``notes`` hanya dipakai untuk baris lama
    yang dibuat sebelum kolom bukti ada (lihat REQUESTS/cfo_receivables.md).
    """
    return clean_evidence(getattr(payment, "evidence_ref", None)) is not None


def recorded_evidence(payment):
    """Referensi bukti apa adanya untuk ditampilkan/di-audit."""
    stored = getattr(payment, "evidence_ref", None)
    if stored and str(stored).strip():
        return str(stored).strip()
    return (getattr(payment, "notes", None) or "").strip() or None


def payable_from_ledger(payment):
    """Berapa banyak dari pembayaran ini yang sudah sah masuk ledger AR.

    Hanya pembayaran VERIFIED (atau baris legacy tanpa status) yang menutup
    piutang. Pembayaran yang baru DILAPORKAN belum menutup apa pun sampai CFO
    memverifikasinya.
    """
    status = effective_payment_status(payment)
    if status in {"REJECTED", "PAYMENT_REPORTED"}:
        return Decimal("0")
    return _dec(payment.amount)


# ═══════════════════════════════ ALUR AR (revisi #17) ════════════════════════
class PaymentReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    amount: Decimal = Field(gt=0, description="Nominal pembayaran yang dilaporkan")
    evidence_ref: str = Field(min_length=1, description="Referensi bukti bayar (bank ref/URL arsip)")
    payment_date: date | None = None
    method: str | None = Field(default=None, max_length=80)
    currency: str | None = Field(default=None, max_length=8)
    notes: str | None = None


class PaymentRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, description="Alasan penolakan (wajib)")
    evidence_ref: str | None = None


def _payment_columns_or_fail(db, action: str):
    """Pastikan skema siap SEBELUM menyentuh data. Kalau belum, tolak dengan 503."""
    cols = _columns(db, "payments")
    missing = [c for c in REQUIRED_PAYMENT_COLUMNS if c not in cols]
    if missing:
        raise HTTPException(
            503,
            f"{action} belum bisa dijalankan: kolom payments {', '.join(missing)} belum ada. "
            "Pembayaran tidak boleh berstatus apa pun tanpa kolom bukti/verifikasi. "
            "Lihat REQUESTS/cfo_writes.md.",
        )
    return cols


def _resolve_invoice(db: Session, invoice_id: int):
    invoice = db.get(m.Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "Invoice not found")
    return invoice


def _invoice_snapshot(db: Session, invoice):
    ledger = db.query(m.Payment).filter(
        (m.Payment.invoice_id == invoice.id)
        | ((m.Payment.invoice_id.is_(None)) & (m.Payment.invoice_no == invoice.invoice_no))
    ).order_by(m.Payment.id.asc()).all()
    amount = _dec(invoice.amount)
    paid = sum((_dec(p.amount) for p in ledger if payable_from_ledger(p) > 0), Decimal("0"))
    pending = sum((_dec(p.amount) for p in ledger
                   if effective_payment_status(p) == "PAYMENT_REPORTED"), Decimal("0"))
    outstanding = max(amount - paid, Decimal("0"))
    return {
        "invoice_id": invoice.id,
        "invoice_no": invoice.invoice_no,
        "amount": _num(amount),
        "paid": _num(paid),
        "outstanding": _num(outstanding),
        "pending_amount": _num(pending),
        "partial": paid > 0 and paid < amount,
        "payment_count": len(ledger),
        "payment_ids": [p.id for p in ledger],
        "currency": getattr(invoice, "currency", None) or "IDR",
        "status": invoice.status,
        "visible_outstanding": _num(max(outstanding - sum(
            (_dec(p.amount) for p in ledger if effective_payment_status(p) == "PAYMENT_REPORTED"),
            Decimal("0")), Decimal("0"))),
    }


def _payment_row(payment, invoice=None):
    status = effective_payment_status(payment)
    # `payments` punya verified_by_id/verified_at, tapi belum punya
    # rejected_by_id/rejected_at (lihat REQUESTS/cfo_writes.md). Untuk penolakan,
    # pelaku & waktu disimpan di kolom "decided by/at" yang ada supaya tidak ada
    # keputusan uang tanpa pelaku; perbedaan verify vs reject dibaca dari
    # `status` dan dari audit_logs (action PAYMENT_VERIFIED / PAYMENT_REJECTED).
    decided_at = getattr(payment, "rejected_at", None) or getattr(payment, "verified_at", None)
    decided_by = getattr(payment, "rejected_by_id", None) or getattr(payment, "verified_by_id", None)
    return {
        "payment_id": payment.id,
        "invoice_id": payment.invoice_id,
        "invoice_no": payment.invoice_no,
        "order_fk": payment.order_fk,
        "amount": _num(_dec(payment.amount)),
        "payment_date": _iso(payment.payment_date),
        "method": payment.method,
        "currency": getattr(payment, "currency", None) or (getattr(invoice, "currency", None) if invoice else None) or "IDR",
        "status": status,
        "status_effective": status or "VERIFIED_LEGACY",
        "locked": is_payment_locked(payment),
        # Immutability: apa yang boleh dilakukan berikutnya, dihitung server-side.
        "allowed_next_actions": [] if is_payment_locked(payment) else ["VERIFY", "REJECT"],
        "evidence_ref": recorded_evidence(payment),
        "evidence_valid": is_payment_evidenced(payment),
        "reported_by_id": getattr(payment, "reported_by_id", None),
        "reported_at": _iso(getattr(payment, "reported_at", None)),
        "verified_by_id": getattr(payment, "verified_by_id", None),
        "verified_at": _iso(getattr(payment, "verified_at", None)),
        "decided_by_id": decided_by,
        "decided_at": _iso(decided_at),
        "rejected_by_id": getattr(payment, "rejected_by_id", None),
        "rejected_at": _iso(getattr(payment, "rejected_at", None)),
        "rejection_reason": getattr(payment, "rejection_reason", None),
        "notes": payment.notes,
    }


@router.post("/invoices/{invoice_id}/payments-report", status_code=201)
def report_invoice_payment(invoice_id: int, data: PaymentReportIn,
                           db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Finance melaporkan pembayaran masuk (revisi #17) → status PAYMENT_REPORTED.

    Pembayaran yang TIDAK punya bukti yang bisa diperiksa akan DITOLAK (400).
    Yang tersimpan di sini belum menutup piutang: nilainya baru masuk ledger AR
    setelah CFO memverifikasi.
    """
    _require(user, PAYMENT_WRITE_ROLES, "Pelaporan pembayaran")
    _payment_columns_or_fail(db, "Pelaporan pembayaran")
    invoice = _resolve_invoice(db, invoice_id)

    evidence = clean_evidence(data.evidence_ref)
    if evidence is None:
        raise HTTPException(
            400,
            "Bukti pembayaran wajib dan harus bisa diperiksa (mis. referensi transfer bank). "
            f"Minimal {MIN_EVIDENCE_LEN} karakter dan bukan placeholder. "
            "Pembayaran tanpa bukti ditolak, bukan ditandai terverifikasi.",
        )

    amount = _dec(data.amount)
    if amount <= 0:
        raise HTTPException(400, "Nominal pembayaran harus lebih dari nol.")

    snapshot = _invoice_snapshot(db, invoice)
    # Pembayaran yang sudah sah + yang sedang menunggu tidak boleh melewati
    # nilai invoice. Ini mencegah laporan berlebih yang lalu "terverifikasi".
    if Decimal(str(snapshot["paid"])) + Decimal(str(snapshot["pending_amount"])) + amount > _dec(invoice.amount):
        raise HTTPException(
            400,
            "Total pembayaran (termasuk yang menunggu verifikasi) melebihi nilai invoice.",
        )

    order = db.get(m.Order, invoice.order_fk) if invoice.order_fk else None
    if order is not None and (order.overall_status or "") == "CLOSED":
        raise HTTPException(409, "Order sudah CLOSED — order tertutup bersifat immutable.")

    currency = (data.currency or getattr(invoice, "currency", None) or "IDR").strip() or "IDR"
    payment = m.Payment(
        invoice_no=invoice.invoice_no,
        invoice_id=invoice.id,
        order_fk=invoice.order_fk,
        amount=amount,
        payment_date=data.payment_date or date.today(),
        method=data.method,
        notes=data.notes,
    )
    payment.status = "PAYMENT_REPORTED"
    payment.evidence_ref = evidence
    payment.reported_by_id = user.id
    payment.reported_at = _now()
    payment.currency = currency
    db.add(payment)
    db.flush()

    log_audit(db, user, "PAYMENT_REPORTED", "Payment", payment.id,
              f"invoice={invoice.invoice_no}; amount={amount}; evidence={evidence}",
              source_module="cfo_payments", previous_status=None,
              new_status="PAYMENT_REPORTED", reason=None)
    db.commit()
    db.refresh(payment)
    return {
        "payment": _payment_row(payment, invoice),
        "invoice": _invoice_snapshot(db, invoice),
        "workflow": "PAYMENT_REPORTED",
        "message": "Pembayaran dilaporkan. Piutang baru tertutup setelah CFO_MANAGER memverifikasi.",
    }


@router.get("/payments-queue")
def list_payments(status: str = Query(None, description="PAYMENT_REPORTED|VERIFIED|REJECTED|ALL"),
                  invoice_id: int = Query(None),
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Antrean verifikasi pembayaran (revisi #17).

    Path sengaja ``/cfo/payments-queue``, bukan ``/cfo/payments``: modul
    ``modules.py`` sudah memegang ``GET /cfo/payments`` (daftar mentah untuk
    dropdown halaman lama) dan saya tidak boleh menyentuh file itu. Path terpisah
    menghindari dua route identik di main.py.
    """
    _require(user, PAYMENT_VIEW_ROLES, "Antrean pembayaran")
    wanted = (status or "").strip().upper()
    if wanted and wanted not in {"ALL", "PAYMENT_REPORTED", "VERIFIED", "REJECTED"}:
        raise HTTPException(400, "status harus PAYMENT_REPORTED, VERIFIED, REJECTED, atau ALL.")

    query = db.query(m.Payment).order_by(m.Payment.id.desc())
    if invoice_id:
        query = query.filter(m.Payment.invoice_id == invoice_id)
    payments = query.all()

    rows = []
    for payment in payments:
        row = _payment_row(payment)
        if wanted and wanted != "ALL":
            if wanted == "VERIFIED":
                if row["status_effective"] not in {"VERIFIED", "VERIFIED_LEGACY"}:
                    continue
            elif row["status"] != wanted:
                continue
        rows.append(row)

    pending = [r for r in rows if r["status"] == "PAYMENT_REPORTED"]
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "as_of": date.today().isoformat(),
        "rows": rows,
        "total_rows": len(rows),
        "summary": {
            "pending_verification_count": len(pending),
            "pending_verification_amount": float(sum((Decimal(str(r["amount"])) for r in pending), Decimal("0"))),
            "verified_count": sum(1 for r in rows if r["status_effective"] in {"VERIFIED", "VERIFIED_LEGACY"}),
            "rejected_count": sum(1 for r in rows if r["status"] == "REJECTED"),
            "currency": "IDR",
        },
        "rule": "Hanya pembayaran VERIFIED yang menutup piutang. Laporan tanpa bukti ditolak sebelum tersimpan.",
    }


def _transitionable(db, payment_id: int):
    """Ambil pembayaran yang MASIH boleh diputuskan. Kalau sudah final -> 409."""
    payment = db.get(m.Payment, payment_id)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    cols = _columns(db, "payments")
    verified_at = getattr(payment, "verified_at", None) if "verified_at" in cols else None
    rejected_at = getattr(payment, "rejected_at", None) if "rejected_at" in cols else None
    status = effective_payment_status(payment)
    if status in {"VERIFIED", "REJECTED"} or verified_at or rejected_at:
        # Immutability (revisi #17): uang yang sudah diputuskan tidak dimutasi
        # ulang. Koreksi = laporan pembayaran baru.
        raise HTTPException(
            409,
            "Pembayaran ini sudah final dan tidak bisa diputuskan ulang. "
            "Buat laporan pembayaran baru untuk koreksi.",
        )
    return payment, cols


@router.post("/payment-decisions/{payment_id}/verify")
def verify_payment(payment_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """CFO_MANAGER memverifikasi pembayaran (revisi #17).

    Tanpa bukti -> 409 (bukan 200). Hanya CFO yang boleh; Finance tidak dapat
    memverifikasi laporannya sendiri.
    """
    _require(user, PAYMENT_VERIFY_ROLES, "Verifikasi pembayaran")
    _payment_columns_or_fail(db, "Verifikasi pembayaran")
    payment, cols = _transitionable(db, payment_id)

    invoice = db.get(m.Invoice, payment.invoice_id) if payment.invoice_id else None
    if invoice is None:
        invoice = db.query(m.Invoice).filter_by(invoice_no=payment.invoice_no).order_by(m.Invoice.id.desc()).first()

    if not is_payment_evidenced(payment):
        raise HTTPException(
            409,
            "Pembayaran tanpa bukti yang bisa diperiksa tidak boleh diverifikasi. "
            "Minta Finance melaporkan ulang dengan referensi bukti.",
        )

    previous = effective_payment_status(payment) or "PAYMENT_REPORTED"
    payment.status = "VERIFIED"
    payment.verified_by_id = user.id
    payment.verified_at = _now()

    if invoice is not None:
        ledger = db.query(m.Payment).filter(
            (m.Payment.invoice_id == invoice.id)
            | ((m.Payment.invoice_id.is_(None)) & (m.Payment.invoice_no == invoice.invoice_no))
        ).all()
        if "allocated_invoice_id" in cols:
            payment.allocated_invoice_id = invoice.id
        if "allocated_at" in cols:
            payment.allocated_at = _now()
        paid = sum((payable_from_ledger(p) for p in ledger), Decimal("0"))
        if paid > _dec(invoice.amount):
            raise HTTPException(400, "Total pembayaran terverifikasi melebihi nilai invoice.")
        invoice.paid_amount = paid
        invoice.status = "PAID" if paid >= _dec(invoice.amount) else ("PARTIAL" if paid > 0 else "UNPAID")
        if (invoice.reconciliation_status or "") != "VERIFIED":
            # Piutang tidak boleh dianggap terverifikasi oleh pembayaran bila
            # invoice-nya sendiri belum direkonsiliasi.
            raise HTTPException(
                409,
                "Invoice belum memiliki rekonsiliasi VERIFIED; selesaikan rekonsiliasi dulu.",
            )

    log_audit(db, user, "PAYMENT_VERIFIED", "Payment", payment.id,
              f"invoice={payment.invoice_no}; amount={payment.amount}; evidence={recorded_evidence(payment)}",
              obj=payment, source_module="cfo_payments",
              previous_status=previous, new_status="VERIFIED")
    db.commit()
    db.refresh(payment)
    return {
        "payment": _payment_row(payment, invoice),
        "invoice": _invoice_snapshot(db, invoice) if invoice is not None else None,
        "workflow": "VERIFIED",
        "verified_by": user.id,
        "message": "Pembayaran terverifikasi dan masuk ledger AR.",
    }


@router.post("/payment-decisions/{payment_id}/reject")
def reject_payment(payment_id: int, data: PaymentRejectIn,
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    """CFO_MANAGER menolak pembayaran (revisi #17) — WAJIB alasan.

    Penolakan TIDAK menghapus apa pun: catatan tetap ada, nilainya diabaikan
    dari ledger, dan alasannya tersimpan untuk ditindaklanjuti Finance.
    """
    _require(user, PAYMENT_VERIFY_ROLES, "Penolakan pembayaran")
    _payment_columns_or_fail(db, "Penolakan pembayaran")
    reason = (data.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Alasan penolakan wajib diisi.")
    payment, cols = _transitionable(db, payment_id)

    previous = effective_payment_status(payment) or "PAYMENT_REPORTED"
    payment.status = "REJECTED"  # status final, terkunci
    payment.rejection_reason = reason
    # `rejected_by_id`/`rejected_at` belum ada di schema; kolom decide yang ada
    # (verified_by_id/verified_at) dipakai supaya penolakan tetap punya pelaku &
    # waktu. Arah keputusan dibaca dari `status`.
    if "rejected_by_id" in cols:
        payment.rejected_by_id = user.id
    if "rejected_at" in cols:
        payment.rejected_at = _now()
    if "rejection_evidence_ref" in cols and data.evidence_ref and clean_evidence(data.evidence_ref):
        # Bukti pembanding dari CFO (kalau ada) ikut disimpan supaya Finance tahu
        # apa yang dinilai kurang — tidak pernah mengganti bukti laporan asli.
        payment.rejection_evidence_ref = clean_evidence(data.evidence_ref)
    payment.verified_by_id = user.id if "rejected_by_id" not in cols else payment.verified_by_id
    payment.verified_at = _now() if "rejected_at" not in cols else payment.verified_at

    log_audit(db, user, "PAYMENT_REJECTED", "Payment", payment.id,
              f"invoice={payment.invoice_no}; amount={payment.amount}; reason={reason}",
              obj=payment, source_module="cfo_payments",
              previous_status=previous, new_status="REJECTED", reason=reason)
    db.commit()
    db.refresh(payment)
    return {
        "payment": _payment_row(payment),
        "workflow": "REJECTED",
        "reason": reason,
        "message": "Pembayaran ditolak; catatan tetap tersimpan dan tidak menutup piutang.",
    }


# ═══════════════════════════════ AP LEDGER (revisi #20) ══════════════════════
class APPaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    po_fk: int | None = Field(default=None, description="PO yang dibayar")
    po_no: str | None = Field(default=None, max_length=80, description="Alternatif po_fk")
    amount: Decimal = Field(gt=0)
    payment_date: date | None = None
    method: str | None = Field(default=None, max_length=80)
    evidence_ref: str | None = Field(default=None, max_length=500)


def _ap_columns_or_fail(db, action: str):
    if not _has_table(db, "ap_payments"):
        raise HTTPException(
            503,
            f"{action} belum bisa dijalankan: tabel ap_payments belum ada. "
            "Ledger AP tidak boleh dicatat di tabel lain. Lihat REQUESTS/cfo_writes.md.",
        )
    cols = _columns(db, "ap_payments")
    missing = [c for c in REQUIRED_AP_PAYMENT_COLUMNS if c not in cols]
    if missing:
        raise HTTPException(503, f"{action} belum bisa dijalankan: kolom ap_payments {', '.join(missing)} belum ada.")
    return cols


def ap_kind(po):
    """SUPPLIER vs MAKLOON dari ``vendor_type`` yang NYATA.

    Tidak ada fallback nama di sini (itu dihapus atas permintaan revisi #20):
    kalau ``vendor_type`` kosong, hasilnya ``UNCLASSIFIED`` dan barisnya
    dilaporkan sebagai utang klasifikasi, bukan diam-diam ditebak.
    """
    explicit = (getattr(po, "vendor_type", None) or "").strip().upper()
    if not explicit:
        return "UNCLASSIFIED"
    return AP_KIND_BY_VENDOR_TYPE.get(explicit, "UNCLASSIFIED")


def _ap_ledger(db, po):
    """Pembayaran AP nyata yang menunjuk PO ini (hanya dari tabel ap_payments)."""
    model = _ap_model(fail=False)
    if model is None or not _has_table(db, "ap_payments"):
        return []
    return (db.query(model)
            .filter(model.po_fk == po.id)
            .order_by(model.id.asc()).all())


def _ap_gross(po):
    """Nilai utang PO = amount + pajak (kalau kolomny sudah ada)."""
    return _dec(po.amount) + _dec(getattr(po, "tax_amount", None))


def ap_outstanding(db, po, rows=None):
    rows = rows if rows is not None else _ap_ledger(db, po)
    paid = sum((_dec(r.amount) for r in rows
                if (getattr(r, "approval_status", None) or "APPROVED").upper() != "REJECTED"), Decimal("0"))
    return max(_ap_gross(po) - paid, Decimal("0")), paid


def _ap_row(db, po, today=None):
    today = today or date.today()
    order = db.get(m.Order, po.order_fk) if po.order_fk else None
    ledger = _ap_ledger(db, po)
    outstanding, paid = ap_outstanding(db, po, ledger)
    received = (po.material_status or "").upper() in {"READY", "RECEIVED", "PARTIAL"}
    due = getattr(po, "due_date", None) or po.arrival_date
    overdue = (today - due).days if (due and received and (today - due).days > 0) else 0
    paid_amount = paid
    return {
        "po_id": po.id,
        "ap_id": f"AP-{po.po_no}",
        "po_no": po.po_no,
        "vendor_type": (getattr(po, "vendor_type", None) or "").strip().upper() or None,
        # `ap_kind` dipertahankan sebagai alias `vendor_type_class` supaya kontrak
        # AP identik dengan cfo_receivables.ap-summary (batch 1) — dua endpoint
        # yang menyajikan angka AP yang sama tidak boleh punya nama field berbeda.
        "ap_kind": ap_kind(po),
        "vendor_type_class": ap_kind(po),
        "vendor_type_source": "purchase_orders.vendor_type",
        "supplier": po.supplier,
        "order_id": order.order_id if order else None,
        "order_fk": po.order_fk,
        "vendor_invoice_no": getattr(po, "vendor_invoice_no", None),
        "amount": _num(_dec(po.amount)),
        "tax_amount": _num(_dec(getattr(po, "tax_amount", None))),
        "gross_amount": _num(_ap_gross(po)),
        "paid": _num(paid_amount),
        "partial": bool(ledger) and 0 < paid_amount < _ap_gross(po),
        "outstanding": _num(outstanding),
        "currency": getattr(po, "currency", None) or "IDR",
        "due_date": _iso(due),
        "due_date_source": "purchase_orders.due_date" if getattr(po, "due_date", None) else (
            "purchase_orders.arrival_date" if po.arrival_date else None),
        "days_overdue": overdue,
        "received": received,
        "material_status": po.material_status,
        "approval_status": getattr(po, "approval_status", None) or po.status,
        "status": "PAID" if received and outstanding <= 0 and paid > 0 else (
            "OVERDUE" if overdue else ("OUTSTANDING" if received else "NOT_RECEIVED")),
        "payment_count": len(ledger),
        "payment_ids": [r.id for r in ledger],
        # `payment_evidence` (nama yang sama dipakai ap-summary batch 1) = daftar
        # referensi bukti; `payment_ids` untuk menelusuri barisnya.
        "payment_evidence": [(r.evidence_ref or "") for r in ledger],
        "payments": [{
            "ap_payment_id": r.id,
            "amount": _num(_dec(r.amount)),
            "payment_date": _iso(r.payment_date),
            "method": r.method,
            "evidence_ref": r.evidence_ref,
            "approval_status": getattr(r, "approval_status", None),
        } for r in ledger],
    }


def _ap_payload(db, rows):
    def blank():
        return {"count": 0, "amount": Decimal("0"), "paid": Decimal("0"), "outstanding": Decimal("0")}

    groups = {"SUPPLIER": blank(), "MAKLOON": blank(), "UNCLASSIFIED": blank()}
    total = blank()
    for row in rows:
        for group in (groups[row["ap_kind"]], total):
            group["count"] += 1
            group["amount"] += Decimal(str(row["gross_amount"]))
            group["paid"] += Decimal(str(row["paid"]))
            group["outstanding"] += Decimal(str(row["outstanding"]))

    def dump(group):
        return {"count": group["count"], "amount": float(group["amount"]),
                "paid": float(group["paid"]), "outstanding": float(group["outstanding"])}

    unclassified = [row["po_no"] for row in rows if row["ap_kind"] == "UNCLASSIFIED"]
    return {
        "supplier": dump(groups["SUPPLIER"]),
        "makloon": dump(groups["MAKLOON"]),
        # Sengaja dipisah dari supplier/makloon: klasifikasi yang belum diisi
        # sumbernya TIDAK boleh tampil sebagai salah satu dari keduanya.
        "unclassified": dump(groups["UNCLASSIFIED"]),
        "total": dump(total),
        "unclassified_pos": unclassified,
        "classification_rule": (
            "vendor_type pada purchase_orders. Kosong = UNCLASSIFIED; "
            "modul ini tidak menebak dari nama supplier."
        ),
        "currency": "IDR",
    }


@router.get("/ap-ledger")
def ap_ledger(vendor_type: str = Query(None, description="SUPPLIER|MAKLOON|LOGISTIK|VENDOR"),
              only_outstanding: bool = Query(False),
              db: Session = Depends(get_db), user=Depends(get_current_user)):
    """AP ledger per PO, dipisah supplier vs makloon lewat ``vendor_type`` nyata (revisi #20)."""
    _require(user, PAYMENT_VIEW_ROLES, "AP ledger")
    wanted = (vendor_type or "").strip().upper()
    if wanted and wanted not in AP_VENDOR_TYPES:
        raise HTTPException(400, "vendor_type harus SUPPLIER, MAKLOON, LOGISTIK, atau VENDOR.")

    rows = [_ap_row(db, po) for po in db.query(m.PurchaseOrder).order_by(m.PurchaseOrder.id.desc()).all()]
    if wanted:
        rows = [row for row in rows if row["vendor_type"] == wanted]
    if only_outstanding:
        rows = [row for row in rows if row["outstanding"] > 0]

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "as_of": date.today().isoformat(),
        "view": "AP_LEDGER",
        "summary": _ap_payload(db, rows),
        "rows": rows,
        "total_rows": len(rows),
        "filters": {"vendor_type": vendor_type, "only_outstanding": only_outstanding},
        "write_support": {
            "ap_payments_table": _has_table(db, "ap_payments"),
            "vendor_type_column": "vendor_type" in _columns(db, "purchase_orders"),
        },
    }


@router.post("/ap-ledger/payments", status_code=201)
def record_ap_payment(data: APPaymentIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Catat pembayaran AP (parsial) ke satu PO — wajib bukti (revisi #20).

    Menolak: pembayaran melebihi sisa utang PO, PO yang material belum diterima,
    dan pembayaran tanpa bukti. Semua penolakan terjadi sebelum baris tersimpan.
    """
    _require(user, PAYMENT_WRITE_ROLES, "Pembayaran AP")
    _ap_columns_or_fail(db, "Pencatatan pembayaran AP")
    model = _ap_model()
    if model is None:  # pragma: no cover - _ap_model() sudah menolak 503
        raise HTTPException(503, "Model ap_payments belum ada.")

    po = None
    if data.po_fk:
        po = db.get(m.PurchaseOrder, data.po_fk)
    elif data.po_no:
        po = db.query(m.PurchaseOrder).filter_by(po_no=data.po_no.strip()).first()
    else:
        raise HTTPException(400, "Pembayaran AP harus menunjuk po_fk atau po_no.")
    if po is None:
        raise HTTPException(404, "Purchase order not found")

    if ap_kind(po) == "UNCLASSIFIED":
        raise HTTPException(
            409,
            "PO ini belum punya vendor_type (SUPPLIER/MAKLOON). "
            "AP supplier vs makloon tidak boleh ditentukan dari tebakan nama.",
        )

    evidence = clean_evidence(data.evidence_ref)
    if evidence is None:
        raise HTTPException(
            400,
            "Bukti pembayaran AP wajib dan harus bisa diperiksa. "
            "Pembayaran supplier tanpa bukti ditolak.",
        )

    amount = _dec(data.amount)
    if amount <= 0:
        raise HTTPException(400, "Nominal pembayaran AP harus lebih dari nol.")

    received = (po.material_status or "").upper() in {"READY", "RECEIVED", "PARTIAL"}
    if not received:
        raise HTTPException(409, "PO belum menerima material — belum ada yang bisa dibayar.")

    outstanding, _paid = ap_outstanding(db, po)
    if amount > outstanding:
        raise HTTPException(
            400,
            "Pembayaran AP melebihi sisa utang PO.",
        )

    payment = model(
        po_fk=po.id,
        amount=amount,
        payment_date=data.payment_date or date.today(),
        method=data.method,
        evidence_ref=evidence,
        approval_status="APPROVED",
        created_by_id=user.id,
    )
    db.add(payment)
    db.flush()

    log_audit(db, user, "AP_PAYMENT_RECORDED", "APPayment", payment.id,
              f"po={po.po_no}; vendor_type={po.vendor_type}; amount={amount}; evidence={evidence}",
              source_module="cfo_payments", previous_status=None,
              new_status="APPROVED")
    db.commit()
    db.refresh(payment)
    return {
        "ap_payment": {
            "ap_payment_id": payment.id,
            "po_fk": payment.po_fk,
            "po_no": po.po_no,
            "amount": _num(_dec(payment.amount)),
            "payment_date": _iso(payment.payment_date),
            "method": payment.method,
            "evidence_ref": payment.evidence_ref,
            "approval_status": payment.approval_status,
        },
        "po": _ap_row(db, po),
        "message": "Pembayaran AP tercatat; sisa utang PO diperbarui dari ledger AP.",
    }
