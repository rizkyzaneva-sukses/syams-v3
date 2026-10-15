"""Modul Purchasing, Material & Inventory — workspace Riadi.

Menutup gap terbesar terhadap BLUEPRINT §3.4 & PRD §6 (Supply): sebelumnya
tidak ada master material, stok, lokasi, supplier, purchase request, goods
receipt, maupun Material Gate — hanya `material_requests`, `purchase_orders`,
dan BOM yang berdiri sendiri.

Prinsip yang ditegakkan:
1. **Stok adalah turunan, bukan angka yang diketik.** Saldo stok = jumlah
   `stock_movements` per material per lokasi. Tidak ada kolom "stok" yang bisa
   ditimpa diam-diam (PRD §2: "status turunan dihitung dari transaksi nyata").
2. **Stok tidak boleh negatif.** Movement keluar yang melebihi saldo ditolak,
   kecuali penyesuaian (ADJUSTMENT) yang wajib beralasan dan tercatat.
3. **Material Gate** menggantikan tebakan: artikel hanya boleh masuk produksi
   bila materialnya sudah teralokasi cukup, dan keputusan gate selalu punya
   pelaku + waktu.
4. **Penerimaan barang (Goods Receipt) memposting stok**, bukan sekadar status.
"""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Text, Boolean, Date, DateTime,
                        Numeric, ForeignKey, UniqueConstraint, Index)
from .database import Base


# Movement yang menambah stok (+) dan mengurangi stok (-).
INBOUND_TYPES = ("RECEIPT", "RETURN", "ADJUSTMENT_IN", "TRANSFER_IN", "PRODUCTION_RETURN")
OUTBOUND_TYPES = ("ISSUE", "ALLOCATION_ISSUE", "TRANSFER_OUT", "SCRAP", "ADJUSTMENT_OUT")
ALL_MOVEMENT_TYPES = INBOUND_TYPES + OUTBOUND_TYPES


class Supplier(Base):
    """Master supplier/makloon. Menggantikan teks bebas `purchase_orders.supplier`."""
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False, index=True)
    name = Column(String(180), nullable=False)
    vendor_type = Column(String(24), nullable=False, default="SUPPLIER", index=True)  # SUPPLIER/MAKLOON/LOGISTIK
    contact_person = Column(String(120), nullable=True)
    phone = Column(String(60), nullable=True)
    email = Column(String(160), nullable=True)
    address = Column(Text, nullable=True)
    payment_terms = Column(String(120), nullable=True)
    lead_time_days = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class InventoryLocation(Base):
    """Lokasi penyimpanan (gudang, staging, karantina)."""
    __tablename__ = "inventory_locations"
    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False, index=True)
    name = Column(String(180), nullable=False)
    location_type = Column(String(24), nullable=False, default="WAREHOUSE")  # WAREHOUSE/STAGING/QUARANTINE/PRODUCTION
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Material(Base):
    """Master material/bahan baku + titik pesan ulang."""
    __tablename__ = "materials"
    id = Column(Integer, primary_key=True)
    code = Column(String(60), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    category = Column(String(80), nullable=True, index=True)   # KAIN, BENANG, AKSESORIS, KEMASAN, TINTA
    unit = Column(String(40), nullable=False, default="pcs")
    min_stock = Column(Numeric(14, 4), nullable=False, default=0)        # batas aman
    reorder_point = Column(Numeric(14, 4), nullable=False, default=0)    # titik pesan ulang
    standard_cost = Column(Numeric(18, 2), nullable=False, default=0)    # harga standar terakhir
    default_supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    default_location_id = Column(Integer, ForeignKey("inventory_locations.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class StockMovement(Base):
    """SATU-SATUNYA sumber kebenaran saldo stok.

    Saldo = sum(qty_in) - sum(qty_out) per material per lokasi. Tidak ada kolom
    saldo yang bisa ditimpa; setiap perubahan stok wajib lewat baris di sini.
    """
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("inventory_locations.id"), nullable=False, index=True)
    movement_type = Column(String(24), nullable=False, index=True)
    qty = Column(Numeric(14, 4), nullable=False)          # selalu positif; arah ditentukan movement_type
    unit_cost = Column(Numeric(18, 2), nullable=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, index=True)
    # Jejak dokumen sumber (PO/GR/SPK) supaya aliran bisa ditelusuri dua arah.
    reference_type = Column(String(32), nullable=True)     # GOODS_RECEIPT/PURCHASE_ORDER/ALLOCATION/ADJUSTMENT
    reference_id = Column(Integer, nullable=True)
    reference_no = Column(String(80), nullable=True)
    reason = Column(Text, nullable=True)                   # wajib untuk ADJUSTMENT
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    __table_args__ = (Index("ix_stock_material_location", "material_id", "location_id"),)


class PurchaseRequest(Base):
    """Permintaan pembelian (PR) — formal, sebelum PO (BLUEPRINT §3.4)."""
    __tablename__ = "purchase_requests"
    id = Column(Integer, primary_key=True)
    pr_no = Column(String(40), unique=True, nullable=False, index=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    required_date = Column(Date, nullable=True)
    status = Column(String(24), nullable=False, default="DRAFT", index=True)
    # DRAFT -> SUBMITTED -> APPROVED -> CONVERTED_TO_PO | REJECTED | CANCELLED
    priority = Column(String(16), nullable=False, default="NORMAL")  # LOW/NORMAL/URGENT
    notes = Column(Text, nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    converted_po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PurchaseRequestLine(Base):
    __tablename__ = "purchase_request_lines"
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False, index=True)
    qty = Column(Numeric(14, 4), nullable=False)
    estimated_unit_cost = Column(Numeric(18, 2), nullable=True)
    notes = Column(Text, nullable=True)


class GoodsReceipt(Base):
    """Penerimaan barang dari supplier. Posting-nya menambah stok + stock movement."""
    __tablename__ = "goods_receipts"
    id = Column(Integer, primary_key=True)
    gr_no = Column(String(40), unique=True, nullable=False, index=True)
    po_fk = Column(Integer, ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    received_date = Column(Date, nullable=True)
    status = Column(String(24), nullable=False, default="DRAFT", index=True)  # DRAFT/POSTED/CANCELLED
    received_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    posted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    evidence_ref = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"
    id = Column(Integer, primary_key=True)
    receipt_id = Column(Integer, ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("inventory_locations.id"), nullable=False)
    qty_ordered = Column(Numeric(14, 4), nullable=False, default=0)
    qty_received = Column(Numeric(14, 4), nullable=False, default=0)
    qty_rejected = Column(Numeric(14, 4), nullable=False, default=0)
    unit_cost = Column(Numeric(18, 2), nullable=True)
    notes = Column(Text, nullable=True)


class MaterialGate(Base):
    """Gate kesiapan material per artikel — prasyarat masuk produksi (BLUEPRINT §3.4 & §6).

    Satu baris per artikel. `allocated_qty` adalah material yang sudah di-issue/
    dialokasikan ke artikel ini; `READY` hanya bila semua kebutuhan BOM terpenuhi.
    """
    __tablename__ = "material_gates"
    id = Column(Integer, primary_key=True)
    order_fk = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    # NOT_REQUESTED -> PENDING -> PARTIAL -> READY -> RELEASED | BLOCKED
    status = Column(String(24), nullable=False, default="NOT_REQUESTED", index=True)
    required_qty = Column(Numeric(14, 4), nullable=False, default=0)
    allocated_qty = Column(Numeric(14, 4), nullable=False, default=0)
    shortage_qty = Column(Numeric(14, 4), nullable=False, default=0)
    block_reason = Column(Text, nullable=True)
    evaluated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    evaluated_at = Column(DateTime, nullable=True)
    released_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    released_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
