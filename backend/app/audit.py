"""Audit entries participate in the caller's business transaction.

INT-ORDER-001 poin 10 requires every status change to record source_module,
actor, timestamp, previous_status, new_status and reason. Those live in real
columns now instead of free text inside `detail`, so the trail can be filtered
and reconstructed.
"""
from sqlalchemy.orm import Session
from . import models


def status_snapshot(obj):
    """Ambil nama status dari objek apa pun yang punya konsep status.

    Model di aplikasi ini memakai nama kolom yang berbeda-beda (status,
    overall_status, release status, dsb). Urutan ini sengaja: kolom `status`
    dulu kalau ada, baru kolom status yang lebih khusus.
    """
    for key in ("status", "overall_status", "flow_step", "order_close_status",
                "finance_gate_status", "shipment_status", "customer_close_status"):
        value = getattr(obj, key, None)
        if value is None:
            continue
        # Enum (mis. OrderType) -> nilai stringnya.
        return getattr(value, "value", value)
    return None


def module_of(obj):
    """Modul sumber perubahan, diturunkan dari nama model.

    Dipakai supaya satu perubahan bisa ditelusuri berasal dari halaman/modul
    mana tanpa setiap pemanggil harus menyebutkannya.
    """
    return type(obj).__name__ if obj is not None else None


def order_ref(db: Session, obj):
    """Order ID (SO-...) yang terkait dengan objek, kalau bisa ditelusuri."""
    from . import models as m
    order = None
    if isinstance(obj, m.Order):
        return obj.order_id
    order_fk = getattr(obj, "order_fk", None)
    if order_fk:
        order = db.get(m.Order, order_fk)
    elif isinstance(obj, m.Payment):
        inv = db.query(m.Invoice).filter_by(invoice_no=obj.invoice_no).first()
        order = db.get(m.Order, inv.order_fk) if inv else None
    elif isinstance(obj, m.Article):
        order = db.get(m.Order, obj.order_fk)
    elif getattr(obj, "article_id", None):
        article = db.get(m.Article, obj.article_id)
        order = db.get(m.Order, article.order_fk) if article else None
    elif getattr(obj, "shipment_fk", None):
        shipment = db.get(m.Shipment, obj.shipment_fk)
        order = db.get(m.Order, shipment.order_fk) if shipment else None
    return order.order_id if order else None


def log_audit(db: Session, user, action: str, entity: str, entity_id: int | None = None,
              detail: str | None = None, obj=None, source_module: str | None = None,
              previous_status: str | None = None, new_status: str | None = None,
              reason: str | None = None):
    """Catat satu entri audit.

    Argumen `obj` opsional: kalau diberikan, source_module/order_id/status diisi
    otomatis dari objek, sementara pemanggil tetap bisa menimpa nilainya.
    """
    if obj is not None:
        if source_module is None:
            source_module = module_of(obj)
        if new_status is None:
            new_status = status_snapshot(obj)
    entry = models.AuditLog(
        user_id=user.id if user else None, action=action,
        entity=entity, entity_id=entity_id, detail=detail,
        source_module=source_module,
        order_id=order_ref(db, obj) if obj is not None else None,
        previous_status=previous_status, new_status=new_status, reason=reason,
    )
    db.add(entry)
    return entry
