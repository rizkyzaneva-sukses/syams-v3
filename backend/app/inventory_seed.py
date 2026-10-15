"""Seed data awal modul Inventory/Purchasing (workspace Riadi).

Idempotent: aman dijalankan berulang. Kalau kode sudah ada, baris dilewati —
tidak menimpa data yang mungkin sudah disesuaikan Riadi. Hanya master data
(lokasi, supplier, material) yang di-seed; stok TIDAK di-seed karena saldo
adalah turunan dari stock_movements (tidak boleh ada angka stok yang diketik).
"""
from decimal import Decimal

from sqlalchemy.orm import Session

from .inventory_models import Supplier, InventoryLocation, Material

# (code, name, location_type)
LOCATIONS = [
    ("GD-UTAMA", "Gudang Utama", "WAREHOUSE"),
    ("GD-STAGING", "Staging Produksi", "STAGING"),
    ("GD-KARANTINA", "Karantina QC", "QUARANTINE"),
    ("GD-PRODUKSI", "Lantai Produksi", "PRODUCTION"),
]

# (code, name, vendor_type, contact, phone, lead_time_days, payment_terms)
SUPPLIERS = [
    ("SUP-KAIN01", "PT Sumber Kain Utama", "SUPPLIER", "Budi", "0812-1111-2222", 7, "NET 30"),
    ("SUP-BENANG1", "CV Benang Nusantara", "SUPPLIER", "Sari", "0812-3333-4444", 5, "NET 30"),
    ("SUP-AKSES01", "Toko Aksesoris Jaya", "SUPPLIER", "Andi", "0812-5555-6666", 3, "COD"),
    ("MK-MAKLOON1", "Makloon Jahit Sejahtera", "MAKLOON", "Hendra", "0812-7777-8888", 14, "NET 45"),
]

# (code, name, category, unit, min_stock, reorder_point, standard_cost, supplier_code)
MATERIALS = [
    ("M-KAIN-CTN30H", "Kain Katun Combed 30s Hitam", "KAIN", "kg", 50, 100, 85000, "SUP-KAIN01"),
    ("M-KAIN-CTN30P", "Kain Katun Combed 30s Putih", "KAIN", "kg", 50, 100, 85000, "SUP-KAIN01"),
    ("M-KAIN-RIB", "Rib Leher Katun", "KAIN", "kg", 20, 40, 92000, "SUP-KAIN01"),
    ("M-BENANG-HITAM", "Benang Jahit Hitam", "BENANG", "roll", 30, 60, 15000, "SUP-BENANG1"),
    ("M-BENANG-PUTIH", "Benang Jahit Putih", "BENANG", "roll", 30, 60, 15000, "SUP-BENANG1"),
    ("M-KANCING-18L", "Kancing 18L", "AKSESORIS", "pcs", 1000, 2000, 250, "SUP-AKSES01"),
    ("M-LABEL-WOVEN", "Label Woven Brand", "AKSESORIS", "pcs", 500, 1000, 400, "SUP-AKSES01"),
    ("M-TINTA-SCR", "Tinta Sablon Hitam", "TINTA", "kg", 5, 10, 120000, "SUP-AKSES01"),
    ("M-KEMAS-POLY", "Plastik Kemas Polybag", "KEMASAN", "pcs", 2000, 5000, 100, "SUP-AKSES01"),
]


def seed_inventory(db: Session) -> dict:
    """Isi lokasi/supplier/material awal. Mengembalikan jumlah yang dibuat."""
    created = {"locations": 0, "suppliers": 0, "materials": 0}

    for code, name, ltype in LOCATIONS:
        if db.query(InventoryLocation).filter_by(code=code).first():
            continue
        db.add(InventoryLocation(code=code, name=name, location_type=ltype))
        created["locations"] += 1
    db.flush()

    sup_map = {}
    for code, name, vtype, contact, phone, lead, terms in SUPPLIERS:
        existing = db.query(Supplier).filter_by(code=code).first()
        if existing:
            sup_map[code] = existing
            continue
        s = Supplier(code=code, name=name, vendor_type=vtype, contact_person=contact,
                     phone=phone, lead_time_days=lead, payment_terms=terms)
        db.add(s)
        db.flush()
        sup_map[code] = s
        created["suppliers"] += 1

    default_loc = db.query(InventoryLocation).filter_by(code="GD-UTAMA").first()
    for code, name, cat, unit, mins, rop, cost, sup_code in MATERIALS:
        if db.query(Material).filter_by(code=code).first():
            continue
        sup = sup_map.get(sup_code)
        db.add(Material(code=code, name=name, category=cat, unit=unit,
                        min_stock=Decimal(mins), reorder_point=Decimal(rop),
                        standard_cost=Decimal(cost),
                        default_supplier_id=sup.id if sup else None,
                        default_location_id=default_loc.id if default_loc else None))
        created["materials"] += 1

    db.flush()
    return created
