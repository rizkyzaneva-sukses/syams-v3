"""Notifikasi otomatis: setiap proses yang masuk memberi tahu role yang menerima tugas baru.

Mesin ini membaca perubahan pada saat flush (SQLAlchemy `before_flush`), sehingga semua jalur
penyimpanan — endpoint generik, endpoint khusus, maupun skrip — otomatis terbaca tanpa harus
menambah panggilan notifikasi di tiap endpoint. Notifikasi ikut transaksi bisnis: bila operasi
utama dibatalkan, notifikasinya juga batal. Kegagalan di sini tidak boleh menggagalkan
operasi bisnis, jadi setiap aturan dibungkus try/except.

Penerima = role (`role_target`) atau user tertentu. Link selalu menunjuk halaman yang memang
boleh dibuka oleh role penerima.
"""
import logging
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from . import models as m
from .platform_models import Notification

log = logging.getLogger("bos.notifications")
ALL_ROLES = {r.value for r in m.Role}


def rupiah(value) -> str:
    return "Rp. " + f"{int(Decimal(str(value or 0))):,}".replace(",", ".")


# ───────────────────────────── deteksi perubahan ─────────────────────────────

def _is_new(obj) -> bool:
    return inspect(obj).transient or inspect(obj).pending


def became(obj, attr: str, values) -> bool:
    """True bila `attr` baru saja berubah menjadi salah satu `values` (termasuk saat objek baru dibuat)."""
    values = (values,) if isinstance(values, str) else tuple(values)
    state = inspect(obj).attrs[attr]
    history = state.history
    if not history.has_changes():
        return False
    return bool(history.added) and history.added[0] in values


def _order(session: Session, order_fk):
    return session.get(m.Order, order_fk) if order_fk else None


def _oid(session, obj) -> str:
    order = _order(session, getattr(obj, "order_fk", None))
    return order.order_id if order else "-"


def _n(roles, title, body=None, link=None, category="TASK", severity="INFO", links=None, user_id=None):
    """Satu kejadian untuk satu atau beberapa role. `links` = {role: path} menimpa `link`."""
    return {"roles": tuple(roles), "title": title, "body": body, "link": link, "links": links or {},
            "category": category, "severity": severity, "user_id": user_id}


# ───────────────────────────── aturan per entitas ─────────────────────────────

def rules_for(session: Session, obj) -> list[dict]:
    out: list[dict] = []
    new = _is_new(obj)

    if isinstance(obj, m.POIntake):
        label = obj.po_number or f"#{obj.id or 'baru'}"
        if became(obj, "status", "SUBMITTED"):
            out.append(_n(["CMO_MANAGER"], f"PO {label} menunggu review",
                          f"{obj.buyer or 'Buyer'} — periksa kelengkapan lalu terima atau tolak.",
                          "/cmo/po-inbox", "APPROVAL"))
        if became(obj, "status", "REJECTED") and not new:
            out.append(_n(["CMO_SUPPORT"], f"PO {label} ditolak — perlu revisi", obj.review_note,
                          "/cmo/po-inbox", "APPROVAL", "WARNING"))

    elif isinstance(obj, m.Order) and new:
        out.append(_n(["CFO_MANAGER"], f"Order baru {obj.order_id}",
                      f"{obj.buyer} — terbitkan invoice dan tentukan DP.", "/cfo/invoices", "FINANCE"))
        out.append(_n(["CMO_SUPPORT"], f"Order {obj.order_id} aktif",
                      f"{obj.buyer} — siapkan quotation, sample, dan SPK.", "/cmo/orders"))

    elif isinstance(obj, m.Order):
        if became(obj, "finance_gate_status", "APPROVED"):
            out.append(_n(["CMO_SUPPORT"], f"Invoice di-ACC CFO — cetak & release SPK {obj.order_id}",
                          "Cetak SPK (PDF), rilis, lalu berikan ke Cecep untuk PPM.", "/cmo/spk", "TASK"))
            out.append(_n(["CMO_MANAGER"], f"Finance Gate {obj.order_id} disetujui",
                          "SPK sedang disiapkan Deby; PPM menyusul setelah SPK dirilis.", "/cmo/orders", "FINANCE"))
        if became(obj, "finance_gate_status", "HOLD"):
            out.append(_n(["CMO_MANAGER"], f"Finance Gate {obj.order_id} ditahan", obj.finance_gate_notes,
                          "/cmo/orders", "FINANCE", "WARNING"))

    elif isinstance(obj, m.Quotation):
        oid = _oid(session, obj)
        if new:
            out.append(_n(["CFO_MANAGER"], f"Quotation {obj.quotation_no} menunggu persetujuan margin",
                          f"Order {oid}", "/cmo/quotations", "APPROVAL"))
        if became(obj, "status", "APPROVED") and not new:
            out.append(_n(["CMO_SUPPORT", "CMO_MANAGER"], f"Quotation {obj.quotation_no} disetujui CFO",
                          f"Order {oid} — kirim penawaran ke buyer.", "/cmo/quotations", "APPROVAL"))
        if became(obj, "status", "REJECTED") and not new:
            out.append(_n(["CMO_SUPPORT"], f"Quotation {obj.quotation_no} ditolak", obj.approval_reason,
                          "/cmo/quotations", "APPROVAL", "WARNING"))

    elif isinstance(obj, m.Invoice):
        if new:
            out.append(_n(["CMO_SUPPORT"], f"Invoice {obj.invoice_no} terbit",
                          f"Order {_oid(session, obj)} — tagihan {rupiah(obj.amount)}, DP {rupiah(obj.dp_amount)}. "
                          "Kirim ke customer.", "/cmo/today", "FINANCE"))
        elif became(obj, "status", "PAID"):
            out.append(_n(["CMO_MANAGER"], f"Invoice {obj.invoice_no} lunas", f"Order {_oid(session, obj)}",
                          "/cmo/orders", "FINANCE"))

    elif isinstance(obj, m.Payment) and new:
        out.append(_n(["CFO_MANAGER"], f"Pembayaran {rupiah(obj.amount)} dicatat",
                      f"Invoice {obj.invoice_no} — verifikasi dan rekonsiliasi.", "/cfo/invoices", "FINANCE"))

    elif isinstance(obj, m.SampleRecord):
        oid = _oid(session, obj)
        if new:
            out.append(_n(["SAMPLE_PIC"], f"Sample baru: {obj.article_code}", f"Order {oid} — mulai kerjakan sample.",
                          "/sample/tasks"))
        if obj.submitted_at and inspect(obj).attrs.submitted_at.history.has_changes():
            out.append(_n(["CMO_MANAGER"], f"Sample {obj.article_code} siap diputuskan buyer", f"Order {oid}",
                          "/cmo/sample-approval", "APPROVAL"))
        if not new and became(obj, "status", ("APPROVED", "REVISION", "REJECTED")):
            out.append(_n(["SAMPLE_PIC", "CMO_SUPPORT"], f"Sample {obj.article_code}: {obj.status}", f"Order {oid}",
                          "/cmo/samples", "APPROVAL", "INFO" if obj.status == "APPROVED" else "WARNING",
                          links={"SAMPLE_PIC": "/sample/tasks"}))

    elif isinstance(obj, m.SampleTask) and new and obj.assigned_to_id:
        out.append(_n([], "Tugas sample baru untuk Anda", obj.next_action, "/sample/tasks", user_id=obj.assigned_to_id))

    elif isinstance(obj, m.Task) and new and obj.assigned_to_id:
        out.append(_n([], f"Tugas baru: {obj.title}", None, "/tasks", user_id=obj.assigned_to_id))

    elif isinstance(obj, m.SPK):
        oid = _oid(session, obj)
        if became(obj, "status", "RELEASED"):
            out.append(_n(["CMO_MANAGER"], f"SPK {obj.spk_no} dirilis — lakukan PPM", f"Order {oid}: SPK hasil cetak diberikan Deby.",
                          "/cmo/samples", "TASK"))
            out.append(_n(["COO_MANAGER", "PRODUCTION_PIC", "PRINTING_PIC", "CMO_SUPPORT"],
                          f"SPK {obj.spk_no} dirilis — order {oid}",
                          "Mulai tahap BAHAN (BOM, material request, PO), lalu Rencana Produksi.",
                          "/master", "MATERIAL",
                          links={"COO_MANAGER": "/coo/planning", "PRODUCTION_PIC": "/coo/material-requests",
                                 "CMO_SUPPORT": "/cmo/today"}))

    elif isinstance(obj, m.ProductionPlan) and became(obj, "status", ("APPROVED", "RELEASED")):
        out.append(_n(["PRODUCTION_PIC", "PRINTING_PIC"], f"Rencana produksi {_oid(session, obj)} disetujui",
                      "Proses produksi boleh mulai begitu material READY.", "/coo/production", "MATERIAL"))

    elif isinstance(obj, m.MaterialRequest) and new:
        out.append(_n(["PRODUCTION_PIC"], f"Permintaan material baru: {obj.item_name}",
                      f"Order {_oid(session, obj)} — {obj.qty} {obj.unit or ''}".strip(), "/coo/material-requests", "MATERIAL"))

    elif isinstance(obj, m.PurchaseOrder):
        if new:
            out.append(_n(["CFO_MANAGER"], f"PO pembelian {obj.po_no} menunggu persetujuan anggaran",
                          f"{obj.item} — {rupiah(obj.amount)}", "/cfo/purchase-orders", "APPROVAL"))
        if became(obj, "material_status", "READY") and not new:
            out.append(_n(["COO_MANAGER", "PRODUCTION_PIC"], f"Material {obj.item or obj.po_no} READY",
                          f"Order {_oid(session, obj)}", "/master", "MATERIAL"))

    elif isinstance(obj, m.Shipment):
        oid = _oid(session, obj)
        if became(obj, "packing_status", "PACKED"):
            out.append(_n(["CFO_MANAGER"], f"Pengiriman {obj.shipment_no} siap dinilai Finance Gate", f"Order {oid}",
                          "/cfo/shipments", "FINANCE"))
        if became(obj, "status", "SHIPPED"):
            out.append(_n(["CMO_MANAGER", "CMO_SUPPORT"], f"Order {oid} dikirim", f"Shipment {obj.shipment_no}",
                          "/coo/deliveries", links={"CMO_SUPPORT": "/cmo/after-sales"}))
        if became(obj, "status", "DELIVERED"):
            out.append(_n(["CMO_MANAGER"], f"Order {oid} diterima fisik", "Konfirmasi kepuasan buyer.",
                          "/coo/deliveries", "APPROVAL"))

    elif isinstance(obj, m.OrderClosing):
        oid = _oid(session, obj)
        for attr, who, others in (("customer_close_status", "Customer", ["COO_MANAGER", "CFO_MANAGER"]),
                                  ("operational_close_status", "Operasional", ["CMO_MANAGER", "CFO_MANAGER"]),
                                  ("financial_close_status", "Finansial", ["CMO_MANAGER", "COO_MANAGER"])):
            if became(obj, attr, "CLOSED"):
                out.append(_n(others, f"Closing {who} order {oid} selesai", "Lengkapi closing bagian Anda.",
                              "/coo/closing", "APPROVAL"))

    elif isinstance(obj, m.ExceptionItem) and new:
        role = obj.owner_role if obj.owner_role in ALL_ROLES else "CEO"
        visible = ("CEO", "CMO_MANAGER", "COO_MANAGER", "CFO_MANAGER", "CHRO_MANAGER")
        severity = "CRITICAL" if (obj.severity or "").upper() == "RED" else "WARNING"
        title = "Exception rahasia baru" if obj.confidential else f"Exception: {obj.title}"
        out.append(_n([role], title, None if obj.confidential else obj.next_action,
                      "/exceptions" if role in visible else "/master", "EXCEPTION", severity))

    elif isinstance(obj, m.CEODecision) and new:
        out.append(_n(["CEO"], "Keputusan baru menunggu CEO", None, "/ceo/decisions", "APPROVAL"))

    elif isinstance(obj, m.ManpowerRequest) and new:
        out.append(_n(["CHRO_MANAGER"], "Permintaan tenaga kerja baru", None, "/chro/recruitment", "APPROVAL"))

    elif isinstance(obj, m.EmployeeIssue) and new:
        out.append(_n(["CHRO_MANAGER"], "Isu karyawan baru", None, "/chro/issues", "EXCEPTION", "WARNING"))

    return out


def materialize(session: Session, events: list[dict]) -> int:
    count = 0
    for ev in events:
        for role in ev["roles"]:
            session.add(Notification(role_target=role, category=ev["category"], title=ev["title"][:200], body=ev["body"],
                                     link_path=ev["links"].get(role, ev["link"]), severity=ev["severity"]))
            count += 1
        if ev["user_id"]:
            session.add(Notification(user_id=ev["user_id"], category=ev["category"], title=ev["title"][:200],
                                     body=ev["body"], link_path=ev["link"], severity=ev["severity"]))
            count += 1
    return count


def _before_flush(session: Session, flush_context, instances):
    try:
        with session.no_autoflush:
            events: list[dict] = []
            for obj in list(session.new) + [o for o in session.dirty if session.is_modified(o)]:
                if isinstance(obj, Notification):
                    continue
                try:
                    events.extend(rules_for(session, obj))
                except Exception:  # satu aturan rusak tidak boleh menggagalkan transaksi bisnis
                    log.exception("aturan notifikasi gagal untuk %s", type(obj).__name__)
            materialize(session, events)
    except Exception:
        log.exception("mesin notifikasi gagal")


if not event.contains(Session, "before_flush", _before_flush):
    event.listen(Session, "before_flush", _before_flush)


# ───────────────────────────── dipakai Control System ─────────────────────────────

def notify_roles(session: Session, roles, title, body=None, link="/master", category="TASK", severity="INFO",
                 links=None, user_id=None):
    """Panggilan eksplisit untuk kejadian yang bukan perubahan satu baris (mis. giliran tahap berikut)."""
    return materialize(session, [_n(roles, title, body, link, category, severity, links, user_id)])
