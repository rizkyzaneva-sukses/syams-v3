"""Kosongkan data transaksi untuk mulai dari nol (Order ID kembali ke SYM-YYMM-001).

Yang DIHAPUS: order, PO, invoice, pembayaran, produksi, sample, SPK, audit log, karyawan,
jurnal, stok, dan seluruh data transaksi lain, termasuk penomoran Order ID.

Yang DIPERTAHANKAN supaya aplikasi tetap bisa dipakai: akun user, sesi login, kebijakan bisnis
CEO, bagan akun (COA), master Control System (jenis pakaian, PIC, SLA berversi), dan
riwayat migrasi.

Tanpa --confirm skrip hanya MENAMPILKAN apa yang akan dihapus (dry run).

    python -m app.reset_data                        # dry run
    python -m app.reset_data --confirm HAPUS-SEMUA-DATA
    python -m app.reset_data --confirm HAPUS-SEMUA-DATA --allow-production   # bila APP_ENV=production

Tidak ada cara menjalankan skrip ini dari aplikasi web; hanya operator di server.
"""
import argparse
import sys

from sqlalchemy import func, select

from .config import settings
from .database import Base, SessionLocal, engine

CONFIRM_PHRASE = "HAPUS-SEMUA-DATA"
KEEP_TABLES = {
    "users", "auth_sessions", "system_config", "business_policy_versions", "chart_of_accounts",
    "garment_types", "pic_masters", "stage_sla_versions", "stage_sla_items", "alembic_version",
}


def tables_to_clear():
    # Import semua modul model supaya Base.metadata lengkap.
    from . import (models, auth_models, accounting_models, control_models, inventory_models,  # noqa: F401
                   hr_time_models, banking_models, artwork_models, crm_models, platform_models)
    return [t for t in reversed(Base.metadata.sorted_tables) if t.name not in KEEP_TABLES]


def run(confirm: str | None, allow_production: bool) -> int:
    clear = tables_to_clear()
    with SessionLocal() as db:
        counts = {t.name: db.execute(select(func.count()).select_from(t)).scalar() or 0 for t in clear}
        target = engine.url.render_as_string(hide_password=True)
        print(f"Database: {target}")
        for name, n in counts.items():
            if n:
                print(f"  {name}: {n} baris")
        print(f"Total {sum(counts.values())} baris di {sum(1 for n in counts.values() if n)} tabel akan dihapus.")
        if confirm != CONFIRM_PHRASE:
            print(f"DRY RUN — tidak ada yang dihapus. Tambahkan --confirm {CONFIRM_PHRASE} untuk menjalankan.")
            return 0
        if settings.app_env == "production" and not allow_production:
            print("APP_ENV=production: tambahkan --allow-production bila memang ingin mengosongkan data produksi.")
            return 2
        for table in clear:
            db.execute(table.delete())
        db.commit()
        print("Selesai. Data transaksi dikosongkan; akun user dan master data dipertahankan.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confirm")
    parser.add_argument("--allow-production", action="store_true")
    args = parser.parse_args()
    sys.exit(run(args.confirm, args.allow_production))


if __name__ == "__main__":
    main()
