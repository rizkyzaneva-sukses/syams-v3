"""Verify the migration chain on a disposable database."""
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def migration_head_revisions(backend):
    """Read the real head revision(s) from the Alembic script directory.

    Deriving the head instead of hardcoding a revision id keeps this test from
    going stale every time a new migration lands. Returns a sorted list so a
    branched (multi-head) history is reported explicitly rather than silently
    picking one side.
    """
    script = ScriptDirectory.from_config(Config(str(backend / "alembic.ini")))
    return sorted(script.get_heads())


def test_fresh_database_migrates_to_head():
    backend = Path(__file__).resolve().parents[1]
    heads = migration_head_revisions(backend)
    assert len(heads) == 1, f"migration history is branched, expected a single head: {heads}"
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "migration.sqlite"
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{database.as_posix()}",
               "APP_ENV": "testing", "SEED_DEMO": "false"}
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"),
                                 "upgrade", "head"], cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        with closing(sqlite3.connect(database)) as db:
            applied = db.execute("SELECT version_num FROM alembic_version").fetchall()
            assert [row[0] for row in applied] == heads
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == heads[0]
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"orders", "po_intakes", "quotations", "bom_items", "material_consumptions", "production_cost_entries", "cost_reviews", "qc_records", "revision_proposals", "revision_status_events"} <= names
            spk_columns = {row[1] for row in db.execute("PRAGMA table_info(spks)")}
            assert {"released_by", "released_at", "released_version", "release_prerequisites", "release_reason", "correction_reason"} <= spk_columns
            shipment_columns = {row[1] for row in db.execute("PRAGMA table_info(shipments)")}
            assert "line_reconciliation_required" in shipment_columns
            assert "shipment_lines" in names


def test_po_document_bytes_survive_following_migrations():
    backend = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "po-document.sqlite"
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{database.as_posix()}",
               "APP_ENV": "testing", "SEED_DEMO": "false"}
        command = [sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"), "upgrade"]
        before = subprocess.run(command + ["0011_po_intake"], cwd=backend, env=env,
                                capture_output=True, text=True)
        assert before.returncode == 0, before.stdout + before.stderr
        document = b"%PDF-1.4\nretained-customer-po"
        with closing(sqlite3.connect(database)) as db:
            db.execute("""INSERT INTO users (id, name, email, password_hash, role, is_active, created_at)
                       VALUES (1, 'Deby', 'deby@example.com', 'hash', 'CMO_SUPPORT', 1, '2026-09-16 00:00:00')""")
            db.execute("""INSERT INTO po_intakes
                       (id, po_number, buyer, articles_json, document_name, document_mime, document_data,
                        status, missing_items_json, created_by_id, received_at, created_at, updated_at)
                       VALUES (1, 'PO-1', 'Buyer', '[]', 'po.pdf', 'application/pdf', ?,
                               'DRAFT', '[]', 1, '2026-09-16', '2026-09-16 00:00:00', '2026-09-16 00:00:00')""", (document,))
            db.commit()
        after = subprocess.run(command + ["head"], cwd=backend, env=env,
                               capture_output=True, text=True)
        assert after.returncode == 0, after.stdout + after.stderr
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT document_data FROM po_intakes WHERE id = 1").fetchone()[0] == document


def test_existing_revisions_and_images_survive_status_migration():
    backend = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "existing.sqlite"
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{database.as_posix()}",
               "APP_ENV": "testing", "SEED_DEMO": "false"}
        command = [sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"), "upgrade"]
        before = subprocess.run(command + ["0007_revision_proposals"], cwd=backend, env=env,
                                capture_output=True, text=True)
        assert before.returncode == 0, before.stdout + before.stderr
        image = b"\x89PNG\r\n\x1a\nexisting-image"
        with closing(sqlite3.connect(database)) as db:
            db.execute("""INSERT INTO users (id, name, email, password_hash, role, is_active, created_at)
                       VALUES (1, 'Deby', 'deby@example.com', 'hash', 'CMO_SUPPORT', 1, '2026-09-16 00:00:00')""")
            db.execute("""INSERT INTO revision_proposals
                       (id, module_name, bug_description, expected_behavior, image_data, image_mime, reported_by_id, created_at)
                       VALUES (1, 'CMO-023 — CMO Support — Delivery', 'Bug asli', 'Hasil asli', ?, 'image/png', 1, '2026-09-16 00:00:00')""", (image,))
            db.execute("""INSERT INTO orders
                       (id, order_id, buyer, order_type, order_date, finance_gate_status, finance_status,
                        material_status, shipment_status, customer_close_status, financial_close_status,
                        overall_status, flow_step, created_at, updated_at)
                       VALUES (1, 'SO-LEGACY', 'Buyer', 'SAMPLE_ONLY', '2026-09-16', 'APPROVED', 'PAID',
                               'READY', 'DELIVERED', 'CLOSED', 'CLOSED', 'CLOSED', 'CLOSED',
                               '2026-09-16 00:00:00', '2026-09-16 00:00:00')""")
            db.execute("""INSERT INTO order_closings
                       (id, order_fk, customer_close_status, financial_close_status, order_close_status,
                        closed_by, close_date, created_at, updated_at)
                       VALUES (1, 1, 'CLOSED', 'CLOSED', 'CLOSED', 'Cecep', '2026-09-16',
                               '2026-09-16 00:00:00', '2026-09-16 00:00:00')""")
            db.executemany("""INSERT INTO spks (order_fk, spk_no, status, version, snapshot, created_at)
                           VALUES (1, ?, ?, 1, ?, '2026-09-16 00:00:00')""", [
                ("SPK-OLD-DRAFT", "NEW", None),
                ("SPK-OLD-VOID", "CANCELLED", None),
                ("SPK-OLD-RELEASED", "RELEASED", '[{"article_code":"A"}]'),
            ])
            db.commit()
        after = subprocess.run(command + ["head"], cwd=backend, env=env,
                               capture_output=True, text=True)
        assert after.returncode == 0, after.stdout + after.stderr
        with closing(sqlite3.connect(database)) as db:
            row = db.execute("""SELECT module_name, bug_description, expected_behavior, image_data,
                              status, owner_role FROM revision_proposals WHERE id = 1""").fetchone()
            assert row == ("CMO-023 — CMO Support — Delivery", "Bug asli", "Hasil asli",
                           image, "REVISI", "CMO_SUPPORT")
            assert db.execute("SELECT operational_close_status, overall_status FROM orders WHERE id=1").fetchone() == ("LEGACY_UNVERIFIED", "CLOSED")
            assert db.execute("SELECT operational_close_status, order_close_status FROM order_closings WHERE id=1").fetchone() == ("LEGACY_UNVERIFIED", "CLOSED")
            assert db.execute("SELECT status FROM spks ORDER BY id").fetchall() == [("DRAFT",), ("VOID",), ("RELEASED",)]
            assert db.execute("SELECT released_by, released_at, released_version, release_prerequisites FROM spks WHERE spk_no='SPK-OLD-RELEASED'").fetchone() == (None, None, None, None)
