#!/usr/bin/env python3
"""Isi database LOKAL dengan 12 order contoh supaya papan Control System bisa dilihat langsung.

Hanya untuk pengembangan: menulis ke database lewat ORM (bukan API), jadi dikunci ke
APP_ENV=development dan menolak jalan bila sudah ada order (kecuali --append).

    cd backend
    python ../scripts/seed_control_demo.py            # pakai DATABASE_URL dari environment / backend/.env
    python ../scripts/seed_control_demo.py --append

Data dibuat relatif terhadap hari ini, jadi ada yang PROGRES, PERHATIAN, URGENT, dan SELESAI.
"""
import argparse
import json
import sys
from io import BytesIO
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import settings  # noqa: E402
from app.control_models import OrderBlock, OrderStage  # noqa: E402
from app.control_service import ensure_control_defaults, next_order_id  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app import models as m  # noqa: E402
from app import notifications  # noqa: E402,F401  (agar order contoh ikut membuat notifikasi seperti di aplikasi)
from app.cfo_models import CashEntry, DailyWorker, ProductionResult, StoredImage  # noqa: E402
from app.inventory_models import (GoodsReceipt, GoodsReceiptLine, InventoryLocation, Material, StockMovement, Supplier)  # noqa: E402
from app.routers.cfo_workspace import CashIn, add_cash  # noqa: E402
from app.models import SystemConfig  # noqa: E402

NOW = datetime.utcnow()


def picture(kind, label, size, bg, fg):
    """Gambar contoh (logo / desain / size chart) supaya dokumen SPK & invoice terlihat nyata saat demo."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(image)
    w, h = size
    if kind == "LOGO":
        draw.ellipse((w * 0.04, h * 0.1, w * 0.3, h * 0.9), fill=fg)
        draw.text((w * 0.36, h * 0.38), label, fill=(60, 60, 60))
    elif kind == "SIZE_CHART":
        for i in range(6):
            draw.line((w * 0.1, h * (0.15 + i * 0.13), w * 0.9, h * (0.15 + i * 0.13)), fill=fg, width=2)
        draw.text((w * 0.4, h * 0.02), label, fill=fg)
    else:
        draw.rounded_rectangle((w * 0.2, h * 0.12, w * 0.8, h * 0.9), radius=40, fill=fg)
        draw.text((w * 0.38, h * 0.48), label, fill=(255, 255, 255))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def store(db, kind, data, user_id, size):
    row = StoredImage(kind=kind, filename=f"demo-{kind.lower()}.png", mime="image/png", width=size[0], height=size[1], data=data, created_by_id=user_id)
    db.add(row)
    db.flush()
    return row.id
O = m.OrderType

# buyer, article, jenis, qty, extra, tipe, flow_step, SPK dirilis N hari lalu (None = belum), deadline +hari, invoice (total, dibayar)
ORDERS = [
    ("Kyan", "Agape Brown", "T-SHIRT", 100, "S+1/M+2", O.SAMPLE_PRODUCTION, "PRODUCTION", 6, 40, (50_000_000, 50_000_000)),
    ("HRVD", "Heavy Hoodie", "HOODIE", 80, "XL+2", O.REPEAT_PRODUCTION, "PRODUCTION", 4, 30, (40_000_000, 15_000_000)),
    ("SVXS", "World Tee", "T-SHIRT", 96, "M+2/L+1", O.REPEAT_PRODUCTION, "PRODUCTION", 0, 35, (30_000_000, 30_000_000)),
    ("Framster", "Atlanta Zip", "JACKET", 115, "", O.SAMPLE_PRODUCTION, "SAMPLE", None, 45, (60_000_000, 20_000_000)),
    ("Noir Dept", "Boxy Sweat", "SWEATSHIRT", 60, "L+3", O.REPEAT_PRODUCTION, "INVOICE", None, 30, (25_000_000, 0)),
    ("Crown Lab", "Varsity", "JACKET", 60, "", O.SAMPLE_PRODUCTION, "SPK", None, 38, (35_000_000, 35_000_000)),
    ("DSTRKT", "Cargo Pants", "PANTS", 40, "M+1/L+1", O.REPEAT_PRODUCTION, "PRODUCTION", 14, 12, (18_000_000, 18_000_000)),
    ("Blackroom", "Graphic Tee", "T-SHIRT", 130, "S+2/M+2", O.SAMPLE_PRODUCTION, "PRODUCTION", 9, 28, (45_000_000, 45_000_000)),
    ("Maison 44", "Oversize Shirt", "SHIRT", 55, "", O.REPEAT_PRODUCTION, "PRODUCTION", 2, 14, (22_000_000, 8_000_000)),
    ("Rogue Kids", "Kids Jersey", "JERSEY", 70, "L+2", O.REPEAT_PRODUCTION, "PRODUCTION", 20, 10, (20_000_000, 20_000_000)),
    ("Vanta", "Logo Tee", "T-SHIRT", 280, "", O.SAMPLE_ONLY, "FOLLOW_UP", None, 20, (9_000_000, 9_000_000)),
    ("Northstar", "Core Hoodie", "HOODIE", 6000, "", O.REPEAT_PRODUCTION, "PRODUCTION", 1, 50, (900_000_000, 450_000_000)),
]

# order ke-N (1-based): tahap manual yang sudah selesai {kode: berapa hari lalu}, tahap dilewati, bahan diterima N hari lalu
PROGRESS = {
    1: ({"CUTTING": 3, "SORTIR": 2}, [], 4),
    7: ({"CUTTING": 10, "SORTIR": 9, "PRINTING": 5, "QC_SB": 4}, ["BORDIR"], 12),
    8: ({"CUTTING": 5, "SORTIR": 4}, [], 8),
    10: ({"CUTTING": 16, "SORTIR": 15, "PRINTING": 10, "QC_SB": 9, "SEWING": 6, "ACC": 0}, ["BORDIR"], 18),
    12: ({}, [], 0),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--append", action="store_true", help="tambah order meski sudah ada order")
    args = parser.parse_args()
    if settings.app_env != "development":
        sys.exit("Ditolak: skrip ini hanya untuk APP_ENV=development.")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(m.Order).first() and not args.append:
            sys.exit("Sudah ada order di database ini. Pakai --append bila memang ingin menambah.")
        ensure_control_defaults(db)
        manager = db.query(m.User).filter_by(role=m.Role.CMO_MANAGER).first()
        created = []
        for n, (buyer, article, garment, qty, extra, otype, step, spk_days, deadline, (billed, paid)) in enumerate(ORDERS, start=1):
            order = m.Order(order_id=next_order_id(db), buyer=buyer, order_type=otype, flow_step=step,
                            overall_status="COMPLETED" if step == "FOLLOW_UP" else "ACTIVE",
                            buyer_deadline=date.today() + timedelta(days=deadline),
                            finance_status="PAID" if paid >= billed else "PARTIAL" if paid else "UNPAID",
                            created_by_id=manager.id if manager else None)
            needs_sample = otype in (O.SAMPLE_ONLY, O.SAMPLE_PRODUCTION)
            order.articles.append(m.Article(article_code=article, garment_type=garment, qty=qty, extra_size=extra or None,
                                            mockup_url=f"https://drive.google.com/mockup/{article.replace(' ', '-')}",
                                            sample_required=needs_sample, production_route="Cutting > Sewing > QC"))
            db.add(order)
            db.flush()
            article_row = order.articles[0]
            article_row.mockup_url = None
            article_row.design_image_id = store(db, "DESIGN", picture("DESIGN", article, (600, 700), (25, 25, 25), (150 + n * 7 % 90, 25, 40)), manager.id if manager else None, (600, 700))
            article_row.size_chart_image_id = store(db, "SIZE_CHART", picture("SIZE_CHART", "SIZE CHART", (600, 500), (250, 250, 250), (90, 90, 90)), manager.id if manager else None, (600, 500))
            article_row.size_breakdown = f"S:{qty // 5}, M:{qty // 4}, L:{qty // 4}, XL:{qty // 4}, XXL:{qty - qty // 5 - 3 * (qty // 4)}"
            article_row.fabric_type, article_row.print_type, article_row.material_color = "16S CKP", "PLASTISOL", "BLACK"
            article_row.embroidery_type, article_row.packaging, article_row.label_note = "-", "OPP", "LABEL LEHER"
            customer = db.query(m.Customer).filter_by(name=buyer).first() or m.Customer(name=buyer)
            customer.phone, customer.shipping_carrier, customer.address = f"0812-{1000 + n}-2026", "JNE Trucking", f"Jl. Contoh No. {n}, Bandung"
            db.add(customer)
            db.flush()
            order.customer_id = customer.id
            db.add(m.Quotation(order_fk=order.id, quotation_no=f"Q-{order.order_id}", status="APPROVED", amount=billed, currency="IDR",
                               pricing_breakdown=json.dumps([{"article_id": article_row.id, "unit_price": round(billed / qty), "unit_hpp": round(billed / qty * 0.7)}])))
            created.append(order)
            db.add(m.POIntake(po_number=f"PO-{buyer.split()[0].upper()[:4]}-{n:03d}", buyer=buyer, order_type=otype.value,
                              buyer_deadline=order.buyer_deadline, articles_json="[]", status="ACCEPTED",
                              created_by_id=manager.id if manager else 1, order_fk=order.id))
            db.add(m.Invoice(invoice_no=f"INV-{order.order_id}", order_fk=order.id, amount=billed, dp_amount=billed * 0.4,
                             paid_amount=paid,
                             status="PAID" if paid >= billed else "PARTIAL" if paid else "UNPAID"))
            if spk_days is not None:
                db.add(m.SPK(order_fk=order.id, spk_no=f"SPK-{order.order_id}", status="RELEASED", snapshot="{}",
                             released_at=NOW - timedelta(days=spk_days)))
            if needs_sample:
                sample_ok = n in (1, 6, 11)
                db.add(m.SampleRecord(order_fk=order.id, article_code=article, article_id=order.articles[0].id,
                                      status="APPROVED" if sample_ok else "PROCESS",
                                      customer_approved_by_id=manager.id if sample_ok and manager else None))
            if n in PROGRESS:
                done, skipped, material_days = PROGRESS[n]
                order.material_status = "READY"
                db.add(m.PurchaseOrder(po_no=f"PO-{order.order_id}", order_fk=order.id, item="Kain cotton", qty=qty, unit="m",
                                       status="RECEIVED", material_status="READY", amount=qty * 30_000,
                                       arrival_date=date.today() - timedelta(days=material_days)))
                for code, days in done.items():
                    db.add(OrderStage(order_fk=order.id, stage_code=code, state="DONE", done_at=NOW - timedelta(days=days),
                                      done_by_id=manager.id if manager else None))
                for code in skipped:
                    db.add(OrderStage(order_fk=order.id, stage_code=code, state="SKIPPED", note="Tidak dipakai"))
        db.flush()
        # masalah terbuka & exception contoh
        db.add(OrderBlock(order_fk=created[6].id, stage_code="SEWING", problem="Mesin jahit rusak, 2 unit mati",
                          next_action="Panggil teknisi hari ini, pindahkan jahit ke line 2", pic_name="SITI"))
        db.add(m.ExceptionItem(order_fk=created[4].id, severity="YELLOW", category="Finance", title="DP belum masuk",
                               status="OPEN", next_action="Tagih buyer hari ini"))
        db.add(m.ExceptionItem(order_fk=created[8].id, severity="RED", category="Material", title="Supplier benang tutup",
                               status="OPEN", next_action="Cari supplier alternatif"))
        cfo = db.query(m.User).filter_by(role=m.Role.CFO_MANAGER).first()
        ceo = db.query(m.User).filter_by(role=m.Role.CEO).first()
        logo_id = store(db, "LOGO", picture("LOGO", "SYAMS Manufacturing", (700, 200), (255, 255, 255), (20, 150, 170)), ceo.id if ceo else None, (700, 200))
        profile = db.query(SystemConfig).filter_by(key="company_profile").first() or SystemConfig(key="company_profile", value="{}", updated_at=NOW)
        profile.value = json.dumps({"name": "SYAMS Manufacturing", "tagline": "Screen printing, Sewing, Setting , Adfruk service etc.",
                                    "phone": "082117116036", "email": "syamsproduction15@gmail.com", "address": "Bandung", "logo_image_id": logo_id})
        db.add(profile)
        # karyawan harian + hasil produksi 5 hari terakhir
        crew = [("Asep", "SEWING", 1500), ("Budi", "CUTTING", 800), ("Cecep S", "PRINTING", 1200), ("Dedi", "QC", 500), ("Eko", "PACKING", 400)]
        workers = [DailyWorker(name=name, process=process, rate_per_pcs=rate) for name, process, rate in crew]
        db.add_all(workers)
        db.flush()
        for back in range(5):
            for w in workers:
                qty = 60 + (w.id * 17 + back * 11) % 90
                db.add(ProductionResult(result_date=date.today() - timedelta(days=back), worker_fk=w.id, process=w.process, qty=qty,
                                        rate=w.rate_per_pcs, amount=w.rate_per_pcs * qty, created_by_id=cfo.id if cfo else None))
        # bahan: pembelian & stok
        supplier, store_loc = Supplier(code="SUP-01", name="Toko Kain Jaya"), InventoryLocation(code="GD-01", name="Gudang Utama")
        db.add_all([supplier, store_loc])
        db.flush()
        mats = [Material(code="KAIN-16S", name="Cotton Combed 16S", category="KAIN", unit="kg", standard_cost=95_000, reorder_point=120),
                Material(code="BNG-HTM", name="Benang Jahit Hitam", category="BENANG", unit="cone", standard_cost=12_500, reorder_point=20),
                Material(code="LBL-LHR", name="Label Leher", category="AKSESORIS", unit="pcs", standard_cost=450, reorder_point=500),
                Material(code="OPP-30", name="Plastik OPP 30x40", category="KEMASAN", unit="pcs", standard_cost=300, reorder_point=500)]
        db.add_all(mats)
        db.flush()
        gr = GoodsReceipt(gr_no="GR-DEMO-1", supplier_id=supplier.id, received_date=date.today() - timedelta(days=3), status="POSTED")
        db.add(gr)
        db.flush()
        for mat, qty, stock in zip(mats, (150, 40, 2000, 3000), (110, 60, 1500, 2600)):
            db.add(GoodsReceiptLine(receipt_id=gr.id, material_id=mat.id, location_id=store_loc.id, qty_ordered=qty, qty_received=qty,
                                    unit_cost=mat.standard_cost * 1.04))
            db.add(StockMovement(material_id=mat.id, location_id=store_loc.id, movement_type="RECEIPT", qty=stock))
        # kas kecil + kas besar (kas besar memakai fungsi aplikasi supaya jurnal ikut terbentuk)
        for back, (direction, amount, category, text) in enumerate([("IN", 1_000_000, "Modal kas", "Isi kas kecil"), ("OUT", 85_000, "ATK", "Beli isolasi & spidol"),
                                                                    ("OUT", 150_000, "Transport", "Bensin pengiriman"), ("OUT", 60_000, "Konsumsi", "Konsumsi meeting pagi")]):
            db.add(CashEntry(kind="PETTY", entry_date=date.today() - timedelta(days=max(0, 2 - back)), direction=direction, category=category,
                             description=text, amount=amount, created_by_id=cfo.id if cfo else None))
        db.flush()
        if cfo:
            for direction, amount, cash, counter, text in (("IN", 45_000_000, "1-1100", "4-1000", "Pelunasan buyer Kyan"), ("OUT", 7_500_000, "1-1100", "6-2000", "Sewa gedung Oktober")):
                add_cash(CashIn(kind="BIG", entry_date=date.today(), direction=direction, category="Demo", description=text, amount=amount,
                                cash_account_code=cash, counter_account_code=counter), db, cfo)
        db.commit()
        print(f"{len(created)} order contoh dibuat: {created[0].order_id} … {created[-1].order_id}")


if __name__ == "__main__":
    main()
