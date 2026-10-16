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
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import settings  # noqa: E402
from app.control_models import OrderBlock, OrderStage  # noqa: E402
from app.control_service import ensure_control_defaults, next_order_id  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app import models as m  # noqa: E402
from app import notifications  # noqa: E402,F401  (agar order contoh ikut membuat notifikasi seperti di aplikasi)

NOW = datetime.utcnow()
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
        db.commit()
        print(f"{len(created)} order contoh dibuat: {created[0].order_id} … {created[-1].order_id}")


if __name__ == "__main__":
    main()
