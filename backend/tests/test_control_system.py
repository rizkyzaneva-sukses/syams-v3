"""Control System: Order ID SYM-YYMM-NNN, master data, SLA berversi, papan 15 tahap."""
import re
from datetime import date, datetime, timedelta

import pytest

from app import models as m
from app.control_models import OrderBlock, OrderSequence, StageSlaItem, StageSlaVersion
from app.control_service import (STAGE_CODES, build_board, ensure_control_defaults, next_order_id,
                                 parse_extra_total)


def call(client, headers, role, method, path, body=None, expected=200):
    response = client.request(method, "/api" + path, headers=headers(role), json=body)
    assert response.status_code == expected, response.text
    return response.json() if response.content else None


def make_order(db, users, order_id="SYM-2610-001", order_type=m.OrderType.SAMPLE_PRODUCTION, flow_step="PRODUCTION",
               qty=100, spk_released_days_ago=None, garment="HOODIE", extra="M+2/L+1", created_days_ago=0):
    order = m.Order(order_id=order_id, buyer="Kyan", order_type=order_type, flow_step=flow_step,
                    buyer_deadline=date.today() + timedelta(days=20), overall_status="ACTIVE",
                    created_at=datetime.utcnow() - timedelta(days=created_days_ago))
    order.articles.append(m.Article(article_code="Agape Brown", garment_type=garment, qty=qty, extra_size=extra,
                                    mockup_url="https://drive.google.com/mockup/1"))
    db.add(order)
    db.flush()
    if spk_released_days_ago is not None:
        db.add(m.SPK(order_fk=order.id, spk_no=f"SPK-{order.id}", status="RELEASED",
                     released_at=datetime.utcnow() - timedelta(days=spk_released_days_ago)))
    db.commit()
    return order


def view(db, order, today=None):
    db.refresh(order)
    return build_board(db, [order], today=today)[0]


def stage(v, code):
    return next(s for s in v["stages"] if s["code"] == code)


# ───────────────────────────── Order ID ─────────────────────────────

def test_order_id_format_and_sequence(db):
    first = next_order_id(db, date(2026, 10, 3))
    second = next_order_id(db, date(2026, 10, 30))
    other_month = next_order_id(db, date(2026, 11, 1))
    assert (first, second, other_month) == ("SYM-2610-001", "SYM-2610-002", "SYM-2611-001")


def test_order_id_continues_after_existing_orders(db, users):
    make_order(db, users, order_id="SYM-2610-007")
    make_order(db, users, order_id="SO-LEGACY0001")
    assert next_order_id(db, date(2026, 10, 15)) == "SYM-2610-008"
    assert db.query(OrderSequence).filter_by(period="2610").one().last_no == 8


def test_order_id_widens_past_999(db):
    db.add(OrderSequence(period="2612", last_no=999))
    db.commit()
    assert next_order_id(db, date(2026, 12, 1)) == "SYM-2612-1000"


def test_accepting_po_creates_sym_order_id(client, headers, db):
    po = call(client, headers, "CMO_SUPPORT", "POST", "/cmo/po-intake", {
        "po_number": "PO-9", "buyer": "Kyan", "order_type": "REPEAT_PRODUCTION",
        "buyer_deadline": str(date.today() + timedelta(days=30)),
        "articles": [{"article_code": "A", "qty": 10, "garment_type": "HOODIE",
                      "extra_size": "M+2", "mockup_url": "https://drive.google.com/x"}]}, expected=201)
    client.post(f"/api/cmo/po-intake/{po['id']}/document", headers=headers("CMO_SUPPORT"),
                files={"document": ("po.pdf", b"%PDF-1.4\n1 0 obj\n", "application/pdf")})
    call(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/check")
    call(client, headers, "CMO_SUPPORT", "POST", f"/cmo/po-intake/{po['id']}/submit")
    accepted = call(client, headers, "CMO_MANAGER", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "ACCEPT"})
    assert re.fullmatch(r"SYM-\d{4}-\d{3}", accepted["order_id"])
    order = call(client, headers, "CMO_MANAGER", "GET", "/orders/" + accepted["order_id"])
    assert order["articles"][0]["extra_size"] == "M+2"
    assert order["articles"][0]["mockup_url"] == "https://drive.google.com/x"


# ───────────────────────────── Master data & SLA ─────────────────────────────

def test_defaults_match_old_sheet(db):
    ensure_control_defaults(db)
    ensure_control_defaults(db)  # idempotent
    version = db.query(StageSlaVersion).one()
    items = {i.stage_code: i for i in db.query(StageSlaItem).filter_by(version_fk=version.id)}
    assert list(items) and sorted(items) == sorted(STAGE_CODES)
    assert [items[c].duration_days for c in STAGE_CODES] == [1, 1, 3, 1, 2, 2, 1, 5, 4, 1, 3, 2, 1, 1, 1]
    assert items["SEWING"].daily_capacity == 450 and items["SAMPLE"].capacity_unit == "ARTICLE"
    assert all(i.warning_pct == 0.8 for i in items.values())


def test_master_lists_readable_by_all_but_editable_by_cmo_manager_only(client, headers):
    garments = call(client, headers, "SAMPLE_PIC", "GET", "/control/garment-types")
    assert [g["name"] for g in garments][:3] == ["T-SHIRT", "HOODIE", "SWEATSHIRT"] and len(garments) == 9
    assert len(call(client, headers, "PRINTING_PIC", "GET", "/control/pics")) == 9
    for role in ("CEO", "CMO_SUPPORT", "COO_MANAGER", "CFO_MANAGER"):
        call(client, headers, role, "POST", "/control/garment-types", {"name": "Cap"}, expected=403)
        call(client, headers, role, "POST", "/control/pics", {"name": "Budi"}, expected=403)
    created = call(client, headers, "CMO_MANAGER", "POST", "/control/garment-types", {"name": "Cap"}, expected=201)
    assert created["name"] == "CAP"
    call(client, headers, "CMO_MANAGER", "POST", "/control/garment-types", {"name": "cap"}, expected=409)
    off = call(client, headers, "CMO_MANAGER", "PATCH", f"/control/garment-types/{created['id']}", {"is_active": False})
    assert off["is_active"] is False
    assert "CAP" not in [g["name"] for g in call(client, headers, "SAMPLE_PIC", "GET", "/control/garment-types?active_only=true")]


def sla_payload(client, headers, **changes):
    current = call(client, headers, "CMO_MANAGER", "GET", "/control/sla")
    items = []
    for item in current["items"]:
        items.append({k: item[k] for k in ("stage_code", "duration_days", "primary_pic", "is_active", "daily_capacity",
                                           "capacity_unit", "warning_pct", "note")})
    for item in items:
        if item["stage_code"] in changes:
            item.update(changes[item["stage_code"]])
    return items


def test_sla_changes_create_versions_and_only_cmo_manager_can_save(client, headers):
    items = sla_payload(client, headers, PRINTING={"duration_days": 7})
    for role in ("CEO", "COO_MANAGER", "CMO_SUPPORT"):
        call(client, headers, role, "POST", "/control/sla", {"reason": "Printing lebih lama", "items": items}, expected=403)
    call(client, headers, "CMO_MANAGER", "POST", "/control/sla", {"reason": "x", "items": items}, expected=422)
    call(client, headers, "CMO_MANAGER", "POST", "/control/sla", {"reason": "Printing lebih lama", "items": items[:-1]}, expected=422)
    saved = call(client, headers, "CMO_MANAGER", "POST", "/control/sla", {"reason": "Printing lebih lama", "items": items}, expected=201)
    assert saved["version"] == 2 and next(i for i in saved["items"] if i["stage_code"] == "PRINTING")["duration_days"] == 7
    call(client, headers, "CMO_MANAGER", "POST", "/control/sla", {"reason": "Tanpa perubahan", "items": items}, expected=409)
    versions = call(client, headers, "PRODUCTION_PIC", "GET", "/control/sla/versions")
    assert [v["version"] for v in versions] == [2, 1] and versions[0]["change_reason"] == "Printing lebih lama"


def test_running_orders_keep_the_sla_version_they_were_created_under(client, headers, db, users):
    ensure_control_defaults(db)
    old_order = make_order(db, users, order_id="SYM-2610-001", spk_released_days_ago=3, created_days_ago=2)
    # versi 1 dibuat 'kemarin' agar order di atas (dibuat 2 hari lalu) tetap memakai versi 1 secara tegas
    db.query(StageSlaVersion).update({"created_at": datetime.utcnow() - timedelta(days=5)})
    db.commit()
    items = sla_payload(client, headers, BAHAN={"duration_days": 10})
    call(client, headers, "CMO_MANAGER", "POST", "/control/sla", {"reason": "Bahan diperpanjang", "items": items}, expected=201)
    new_order = make_order(db, users, order_id="SYM-2610-002", spk_released_days_ago=3)
    assert stage(view(db, old_order), "BAHAN")["sla_days"] == 2
    assert stage(view(db, new_order), "BAHAN")["sla_days"] == 10


# ───────────────────────────── Turunan tahap ─────────────────────────────

def test_order_types_decide_which_stages_apply(db, users):
    ensure_control_defaults(db)
    repeat = view(db, make_order(db, users, "SYM-2610-001", m.OrderType.REPEAT_PRODUCTION, flow_step="PPM"))
    assert stage(repeat, "SAMPLE")["status"] == "-" and stage(repeat, "PPM")["is_current"]
    assert stage(repeat, "INVOICE")["status"] == "SELESAI"
    sample_prod = view(db, make_order(db, users, "SYM-2610-002", m.OrderType.SAMPLE_PRODUCTION, flow_step="SAMPLE"))
    assert stage(sample_prod, "PPM")["status"] == "-" and stage(sample_prod, "SAMPLE")["is_current"]
    sample_only = view(db, make_order(db, users, "SYM-2610-003", m.OrderType.SAMPLE_ONLY, flow_step="FOLLOW_UP"))
    assert sample_only["priority"] == "SELESAI" and sample_only["active_qty"] == 0
    assert all(stage(sample_only, c)["status"] == "-" for c in ("SPK_RELEASED", "BAHAN", "SHIPPING"))


def test_revisi_is_off_by_default(db, users):
    ensure_control_defaults(db)
    v = view(db, make_order(db, users, spk_released_days_ago=0))
    assert stage(v, "REVISI")["status"] == "-" and v["current_stage"] == "BAHAN"


def test_sla_drives_progres_perhatian_urgent(db, users):
    ensure_control_defaults(db)
    today = date.today()
    # BAHAN 2 hari. Hari ke-0: PROGRES; hari ke-2 (jatuh tempo hari ini): PERHATIAN; hari ke-3: URGENT.
    fresh = view(db, make_order(db, users, "SYM-2610-001", spk_released_days_ago=0), today)
    assert stage(fresh, "BAHAN")["status"] == "PROGRES" and fresh["priority"] == "PROGRES"
    due_today = view(db, make_order(db, users, "SYM-2610-002", spk_released_days_ago=2), today)
    assert stage(due_today, "BAHAN")["status"] == "PERHATIAN" and due_today["priority"] == "PERHATIAN"
    late = view(db, make_order(db, users, "SYM-2610-003", spk_released_days_ago=3), today)
    assert stage(late, "BAHAN")["status"] == "URGENT" and late["priority"] == "URGENT"
    assert stage(late, "BAHAN")["due_date"] == today - timedelta(days=1)
    waiting = stage(late, "CUTTING")
    assert waiting["status"] == "" and not waiting["is_current"]


def test_row_summary_fields_follow_the_sheet(db, users):
    ensure_control_defaults(db)
    v = view(db, make_order(db, users, qty=96, spk_released_days_ago=0, extra="M+2/L+1"))
    assert v["total_qty"] == 96 == v["active_qty"] and v["extra_total"] == 3
    assert v["garment_types"] == ["HOODIE"] and v["payment"] == "OUTSTANDING"
    assert v["pic"] == "RIADI" and v["next_action"] == "Selesaikan BAHAN"
    assert parse_extra_total("S+1/M+2") == 3 and parse_extra_total(None) == 0 and parse_extra_total("") == 0


# ───────────────────────────── Aksi tahap ─────────────────────────────

def test_stage_actions_follow_roles_and_gates(client, headers, db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, spk_released_days_ago=0)
    base = f"/control/orders/{order.order_id}/stages"
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/INVOICE/done", {}, expected=409)       # otomatis
    call(client, headers, "CMO_MANAGER", "POST", f"{base}/BAHAN/done", {}, expected=403)             # bukan pemegang
    call(client, headers, "PRINTING_PIC", "POST", f"{base}/CUTTING/done", {}, expected=403)          # beda divisi
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/NGAWUR/done", {}, expected=404)
    done = call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/BAHAN/done", {})
    assert stage(done, "BAHAN")["status"] == "SELESAI" and done["current_stage"] == "CUTTING"
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/BAHAN/done", {}, expected=409)          # sudah selesai
    skipped = call(client, headers, "COO_MANAGER", "POST", f"{base}/SORTIR/skip", {"reason": "Tidak ada sortir"})
    assert stage(skipped, "SORTIR")["status"] == "-"
    call(client, headers, "COO_MANAGER", "POST", f"{base}/SORTIR/skip", {"reason": ""}, expected=422)
    back = call(client, headers, "COO_MANAGER", "POST", f"{base}/SORTIR/enable", {})
    assert stage(back, "SORTIR")["status"] == "" and not stage(back, "SORTIR")["is_current"]
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/BAHAN/reopen", {"reason": "Salah klik"})
    reopened = call(client, headers, "COO_MANAGER", "GET", f"/control/orders/{order.order_id}")
    assert stage(reopened, "BAHAN")["is_current"]


def test_production_stage_blocked_until_spk_released(client, headers, db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, flow_step="SPK", spk_released_days_ago=None)
    call(client, headers, "PRODUCTION_PIC", "POST", f"/control/orders/{order.order_id}/stages/BAHAN/done", {}, expected=409)
    sample_only = make_order(db, users, "SYM-2610-002", m.OrderType.SAMPLE_ONLY, flow_step="SAMPLE")
    call(client, headers, "PRODUCTION_PIC", "POST", f"/control/orders/{sample_only.order_id}/stages/BAHAN/done", {}, expected=409)


def test_cannot_reopen_a_stage_while_later_stages_are_done(client, headers, db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, spk_released_days_ago=0)
    base = f"/control/orders/{order.order_id}/stages"
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/BAHAN/done", {})
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/CUTTING/done", {})
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/BAHAN/reopen", {"reason": "Salah klik"}, expected=409)


def test_blocks_make_order_urgent_and_must_be_resolved_to_finish_stage(client, headers, db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, spk_released_days_ago=0)
    base = f"/control/orders/{order.order_id}"
    call(client, headers, "CEO", "POST", f"{base}/blocks", {"stage_code": "BAHAN", "problem": "Bahan kurang", "next_action": "Order ulang"}, expected=403)
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/blocks", {"stage_code": "BAHAN", "problem": "", "next_action": "x"}, expected=422)
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/blocks", {"stage_code": "BAHAN", "problem": "Bahan kurang", "next_action": "Order ulang", "pic_name": "Siapa"}, expected=422)
    v = call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/blocks",
             {"stage_code": "BAHAN", "problem": "Bahan kurang", "next_action": "Order ulang", "pic_name": "riadi"}, expected=201)
    assert v["priority"] == "URGENT" and stage(v, "BAHAN")["status"] == "URGENT"
    assert v["problem"] == "Bahan kurang" and v["next_action"] == "Order ulang" and v["pic"] == "RIADI"
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/stages/BAHAN/done", {}, expected=409)
    block_id = v["open_blocks"][0]["id"]
    call(client, headers, "PRINTING_PIC", "POST", f"/control/blocks/{block_id}/resolve", {"note": "ok"}, expected=403)
    cleared = call(client, headers, "COO_MANAGER", "POST", f"/control/blocks/{block_id}/resolve", {"note": "Bahan datang"})
    assert cleared["priority"] == "PROGRES" and cleared["problem"] == ""
    call(client, headers, "COO_MANAGER", "POST", f"/control/blocks/{block_id}/resolve", {}, expected=409)
    history = call(client, headers, "SAMPLE_PIC", "GET", f"/control/orders/{order.order_id}")["blocks"]
    assert history[0]["resolution_note"] == "Bahan datang"
    call(client, headers, "PRODUCTION_PIC", "POST", f"{base}/stages/BAHAN/done", {})


def test_order_level_block_marks_order_urgent(client, headers, db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, flow_step="INVOICE")
    v = call(client, headers, "CFO_MANAGER", "POST", f"/control/orders/{order.order_id}/blocks",
             {"problem": "DP belum masuk", "next_action": "Tagih buyer"}, expected=201)
    assert v["priority"] == "URGENT" and v["current_stage"] == "INVOICE"


# ───────────────────────────── Papan ─────────────────────────────

def test_board_sorts_filters_and_summarises(client, headers, db, users):
    ensure_control_defaults(db)
    make_order(db, users, "SYM-2610-001", spk_released_days_ago=0)                         # PROGRES
    make_order(db, users, "SYM-2610-002", spk_released_days_ago=9, qty=50)                  # URGENT
    make_order(db, users, "SYM-2610-003", m.OrderType.SAMPLE_ONLY, flow_step="FOLLOW_UP")   # SELESAI
    closed = make_order(db, users, "SYM-2610-004", spk_released_days_ago=0)
    closed.overall_status = "CLOSED"
    db.commit()
    data = call(client, headers, "SHIPMENT_ADMIN", "GET", "/control/board")
    assert [r["order_id"] for r in data["rows"]] == ["SYM-2610-002", "SYM-2610-001", "SYM-2610-003"]
    assert [s["code"] for s in data["stages"]] == STAGE_CODES
    s = data["summary"]
    assert (s["urgent"], s["progress"], s["done"], s["active_orders"]) == (1, 1, 1, 2)
    assert s["active_qty"] == 150 and s["payment_outstanding"] == 2
    assert [r["order_id"] for r in call(client, headers, "SAMPLE_PIC", "GET", "/control/board?priority=URGENT")["rows"]] == ["SYM-2610-002"]
    assert len(call(client, headers, "SAMPLE_PIC", "GET", "/control/board?pic=riadi")["rows"]) == 2
    assert len(call(client, headers, "SAMPLE_PIC", "GET", "/control/board?q=kyan")["rows"]) == 3
    assert len(call(client, headers, "SAMPLE_PIC", "GET", "/control/board?include_closed=true")["rows"]) == 4


def test_board_is_readable_by_every_role(client, headers):
    for role in m.Role:
        call(client, headers, role.value, "GET", "/control/board")


def test_stage_pic_override(client, headers, db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, spk_released_days_ago=0)
    path = f"/control/orders/{order.order_id}/stages/BAHAN/pic"
    call(client, headers, "PRODUCTION_PIC", "PUT", path, {"pic_name": "SITI"}, expected=403)
    call(client, headers, "COO_MANAGER", "PUT", path, {"pic_name": "NOBODY"}, expected=422)
    v = call(client, headers, "COO_MANAGER", "PUT", path, {"pic_name": "siti"})
    assert v["pic"] == "SITI" and stage(v, "BAHAN")["pic_override"] is True
    v = call(client, headers, "COO_MANAGER", "PUT", path, {"pic_name": None})
    assert v["pic"] == "RIADI"
    call(client, headers, "COO_MANAGER", "PUT", f"/control/orders/{order.order_id}/stages/REVISI/pic", {"pic_name": "SITI"}, expected=409)


# ───────────────────────────── Reset data & migrasi ─────────────────────────────

def test_reset_script_keeps_accounts_and_master_data():
    from app.reset_data import KEEP_TABLES, tables_to_clear
    names = {t.name for t in tables_to_clear()}
    assert {"orders", "articles", "order_stages", "order_blocks", "order_sequences", "audit_logs", "invoices"} <= names
    assert not names & KEEP_TABLES and "users" in KEEP_TABLES and "stage_sla_items" in KEEP_TABLES


def test_new_tables_and_columns_exist_after_migration():
    import os, sqlite3, subprocess, sys, tempfile
    from contextlib import closing
    from pathlib import Path
    backend = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "m.sqlite"
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{database.as_posix()}", "APP_ENV": "testing", "SEED_DEMO": "false"}
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"), "upgrade", "head"],
                                cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        with closing(sqlite3.connect(database)) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"garment_types", "pic_masters", "stage_sla_versions", "stage_sla_items", "order_stages",
                    "order_blocks", "order_sequences"} <= tables
            assert {"extra_size", "mockup_url"} <= {r[1] for r in con.execute("PRAGMA table_info(articles)")}


# ───────────────────────────── Tahap 2: data modul lain, exception, ringkasan ─────────────────────────────

def test_spk_release_does_not_need_materials_but_production_does(db, users):
    """Urutan sheet: SPK Released dulu, baru BAHAN. Gate material ada di masuk-produksi, bukan di release SPK."""
    from fastapi import HTTPException
    from app.workflow import materials_ready, spk_ready, spk_release_readiness
    order = make_order(db, users, spk_released_days_ago=0)
    spk = db.query(m.SPK).filter_by(order_fk=order.id).one()
    spk.snapshot = "{}"
    db.commit()
    assert spk_ready(db, order)                                   # SPK released tanpa BOM / material request / PO
    assert not any("material" in key or "bom" in key for key in spk_release_readiness(db, spk)["checks"])
    with pytest.raises(HTTPException) as err:
        materials_ready(db, order)                                # tetapi produksi butuh material READY
    assert "Material requirements" in str(err.value.detail)


def test_bahan_done_automatically_when_materials_are_ready(client, headers, db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, spk_released_days_ago=3)
    db.add(m.PurchaseOrder(po_no="PO-1", order_fk=order.id, item="Cotton", qty=10, unit="m", material_status="READY",
                           status="RECEIVED", arrival_date=date.today()))
    order.material_status = "READY"
    db.commit()
    v = view(db, order)
    bahan = stage(v, "BAHAN")
    assert bahan["status"] == "SELESAI" and bahan["from_data"] and v["current_stage"] == "CUTTING"
    path = f"/control/orders/{order.order_id}/stages/BAHAN"
    call(client, headers, "PRODUCTION_PIC", "POST", path + "/done", {}, expected=409)
    call(client, headers, "PRODUCTION_PIC", "POST", path + "/reopen", {"reason": "coba"}, expected=409)
    call(client, headers, "PRODUCTION_PIC", "POST", path + "/skip", {"reason": "coba"}, expected=409)
    # SLA tahap berikut dihitung dari tanggal bahan diterima
    assert stage(v, "CUTTING")["started_at"].date() == date.today()


def test_production_queue_marks_stages_done_without_double_input(db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, spk_released_days_ago=1)
    article = order.articles[0]
    article.production_route = "Cutting > Sewing > QC > Packing"
    order.material_status = "READY"
    db.add_all([
        m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100, qty_done=100, status="DONE"),
        m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=100, qty_done=40, status="IN_PROCESS"),
        m.ProductionMovement(article_id=article.id, process="QC", qty_in=0, qty_done=0, status="DONE"),
    ])
    db.commit()
    v = view(db, order)
    assert stage(v, "CUTTING")["status"] == "SELESAI" and stage(v, "CUTTING")["from_data"]
    assert v["current_stage"] == "SORTIR"           # Sortir tidak ada di rute, tetap tahap berikut di papan sampai dilewati
    assert stage(v, "SEWING")["status"] != "SELESAI"
    assert stage(v, "QC_PACK")["status"] != "SELESAI"   # QC DONE tapi Packing belum ada catatan
    db.query(m.ProductionMovement).filter_by(process="Sewing").update({"status": "DONE"})
    db.add(m.ProductionMovement(article_id=article.id, process="Packing", qty_in=0, qty_done=0, status="DONE"))
    db.commit()
    v = view(db, order)
    assert stage(v, "SEWING")["status"] == "SELESAI" and stage(v, "QC_PACK")["status"] == "SELESAI"


def test_shipping_follows_shipments(db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, spk_released_days_ago=1)
    db.add_all([m.Shipment(order_fk=order.id, shipment_no="SH-1", status="SHIPPED", shipped_date=date.today()),
                m.Shipment(order_fk=order.id, shipment_no="SH-2", status="PACKED")])
    db.commit()
    assert stage(view(db, order), "SHIPPING")["status"] != "SELESAI"
    db.query(m.Shipment).filter_by(shipment_no="SH-2").update({"status": "DELIVERED"})
    db.commit()
    assert stage(view(db, order), "SHIPPING")["status"] == "SELESAI"


def test_open_exceptions_raise_priority(db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, spk_released_days_ago=0)
    assert view(db, order)["priority"] == "PROGRES"
    db.add(m.ExceptionItem(order_fk=order.id, severity="YELLOW", category="Material", title="Supplier telat",
                           status="OPEN", next_action="Telepon supplier"))
    db.commit()
    v = view(db, order)
    assert v["priority"] == "PERHATIAN" and "[Exception] Supplier telat" in v["problem"] and v["next_action"] == "Telepon supplier"
    db.add(m.ExceptionItem(order_fk=order.id, severity="RED", category="Mutu", title="Reject tinggi", status="OPEN"))
    db.add(m.ExceptionItem(order_fk=order.id, severity="RED", category="HR", title="Kasus rahasia", status="OPEN", confidential=True))
    db.commit()
    v = view(db, order)
    assert v["priority"] == "URGENT" and v["exception_count"] == 2 and "Kasus rahasia" not in v["problem"]
    db.query(m.ExceptionItem).update({"status": "RESOLVED"})
    db.commit()
    assert view(db, order)["priority"] == "PROGRES"


def test_morning_priority_is_sorted_filtered_per_pic(client, headers, db, users):
    ensure_control_defaults(db)
    make_order(db, users, "SYM-2610-001", spk_released_days_ago=0)                             # PROGRES, RIADI
    make_order(db, users, "SYM-2610-002", spk_released_days_ago=9)                             # URGENT, RIADI
    make_order(db, users, "SYM-2610-003", m.OrderType.REPEAT_PRODUCTION, flow_step="INVOICE")  # PROGRES, CFO / CMO
    make_order(db, users, "SYM-2610-004", m.OrderType.SAMPLE_ONLY, flow_step="FOLLOW_UP")      # SELESAI, disembunyikan
    data = call(client, headers, "CMO_SUPPORT", "GET", "/control/morning-priority")
    assert [r["order_id"] for r in data["rows"]][0] == "SYM-2610-002"
    assert "SYM-2610-004" not in [r["order_id"] for r in data["rows"]]
    assert data["totals"] == {"urgent": 1, "attention": 0, "progress": 2}
    riadi = next(p for p in data["pics"] if p["pic"] == "RIADI")
    assert (riadi["orders"], riadi["urgent"]) == (2, 1)
    only = call(client, headers, "CMO_SUPPORT", "GET", "/control/morning-priority?pic=riadi")
    assert {r["order_id"] for r in only["rows"]} == {"SYM-2610-001", "SYM-2610-002"}
    assert [p["pic"] for p in only["pics"]] == [p["pic"] for p in data["pics"]]   # chip PIC tetap lengkap saat difilter
    for role in m.Role:
        call(client, headers, role.value, "GET", "/control/morning-priority")


def test_dashboard_matches_the_sheet_layout(client, headers, db, users):
    ensure_control_defaults(db)
    make_order(db, users, "SYM-2610-001", spk_released_days_ago=9, qty=50, garment="HOODIE")     # URGENT di BAHAN
    make_order(db, users, "SYM-2610-002", spk_released_days_ago=0, qty=30, garment="T-SHIRT")    # PROGRES di BAHAN
    make_order(db, users, "SYM-2610-003", m.OrderType.REPEAT_PRODUCTION, flow_step="INVOICE", qty=20, garment="HOODIE")
    make_order(db, users, "SYM-2610-004", m.OrderType.SAMPLE_ONLY, flow_step="FOLLOW_UP", qty=10)
    data = call(client, headers, "SHIPMENT_ADMIN", "GET", "/control/dashboard")
    assert data["summary"] == {"active_orders": 3, "active_qty": 100, "urgent": 1, "attention": 0, "progress": 2, "done": 1}
    stages = {s["code"]: s for s in data["wip_by_stage"]}
    assert len(stages) == 15
    assert (stages["BAHAN"]["orders"], stages["BAHAN"]["qty"], stages["BAHAN"]["urgent"], stages["BAHAN"]["progress"]) == (2, 80, 1, 1)
    assert stages["INVOICE"]["orders"] == 1 and stages["SEWING"]["orders"] == 0
    garments = {g["garment"]: g for g in data["wip_by_garment"]}
    hoodie = garments["HOODIE"]
    assert (hoodie["orders"], hoodie["qty"], hoodie["urgent_qty"], hoodie["progress_qty"]) == (2, 70, 50, 20)
    assert garments["T-SHIRT"]["progress_qty"] == 30
    assert data["alerts"] == {"payment_outstanding": 3, "urgent_operation": 1, "attention_operation": 0, "open_problems": 0, "deadline_forecast_urgent": 2}
    assert data["by_pic"][0]["pic"] == "RIADI" and data["by_pic"][0]["urgent"] == 1


# ───────────────────────────── Tahap 3: Capacity Planner, Forecast, feed CMO ─────────────────────────────

from app.control_forecast import (capacity_feed, capacity_planner, deadline_risk, forecast_engine, load_ratio,
                                  project_order, status_for, unit_amount)
from app.control_service import SlaBook


def active_items(db):
    return SlaBook(db).active()[1]


def test_status_thresholds_follow_the_sheet():
    assert status_for(1.01, 0.8) == "OVERLOAD" and status_for(1.0, 0.8) == "PERHATIAN"
    assert status_for(0.8, 0.8) == "PERHATIAN" and status_for(0.79, 0.8) == "AVAILABLE"
    assert load_ratio(0, 0) == 0 and load_ratio(5, 0) > 1 and load_ratio(50, 100) == 0.5


def test_planner_is_unit_aware_and_uses_calendar_days(db, users):
    ensure_control_defaults(db)
    make_order(db, users, "SYM-2610-001", spk_released_days_ago=0, qty=100)
    make_order(db, users, "SYM-2610-002", spk_released_days_ago=0, qty=350)
    make_order(db, users, "SYM-2610-003", m.OrderType.REPEAT_PRODUCTION, flow_step="INVOICE", qty=900)
    views = build_board(db, db.query(m.Order).order_by(m.Order.id).all())
    items = active_items(db)
    one_day = {r["code"]: r for r in capacity_planner(views, items, date(2026, 10, 16), date(2026, 10, 16))["rows"]}
    assert one_day["BAHAN"]["period_capacity"] == 500 and one_day["BAHAN"]["load_amount"] == 450
    assert one_day["BAHAN"]["load_pct"] == 90.0 and one_day["BAHAN"]["status"] == "PERHATIAN" and one_day["BAHAN"]["available"] == 50
    # INVOICE berkapasitas 10 ORDER/hari: 900 pcs dihitung sebagai 1 order, bukan 900 (kesalahan satuan di sheet)
    assert one_day["INVOICE"]["load_amount"] == 1 and one_day["INVOICE"]["load_pct"] == 10.0 and one_day["INVOICE"]["status"] == "AVAILABLE"
    assert one_day["INVOICE"]["qty"] == 900
    month = capacity_planner(views, items, date(2026, 10, 1), date(2026, 10, 30))
    assert month["days"] == 30 and {r["code"]: r for r in month["rows"]}["BAHAN"]["period_capacity"] == 15000
    assert month["banner"]["level"] == "AVAILABLE" and "TERSEDIA" in month["banner"]["text"]
    assert capacity_planner(views, items, date(2026, 10, 16), date(2026, 10, 16))["banner"]["level"] == "PERHATIAN"
    make_order(db, users, "SYM-2610-004", spk_released_days_ago=0, qty=200)
    views = build_board(db, db.query(m.Order).order_by(m.Order.id).all())
    crowded = capacity_planner(views, items, date(2026, 10, 16), date(2026, 10, 16))
    assert {r["code"]: r for r in crowded["rows"]}["BAHAN"]["status"] == "OVERLOAD" and crowded["banner"]["level"] == "OVERLOAD"


def test_planner_endpoint_validates_range_and_defaults(client, headers, db, users):
    ensure_control_defaults(db)
    make_order(db, users, spk_released_days_ago=0)
    data = call(client, headers, "CMO_MANAGER", "GET", "/control/capacity-planner")
    assert data["days"] == 30 and data["start"] == str(date.today()) and len(data["rows"]) == 15
    call(client, headers, "CMO_MANAGER", "GET", "/control/capacity-planner?start=2026-10-10&end=2026-10-01", expected=422)
    call(client, headers, "CMO_MANAGER", "GET", "/control/capacity-planner?start=2026-01-01&end=2028-01-01", expected=422)
    one = call(client, headers, "CMO_MANAGER", "GET", "/control/capacity-planner?start=2026-10-16&end=2026-10-16")
    assert one["days"] == 1


def test_inactive_stage_is_excluded_from_planner_and_projection(client, headers, db, users):
    ensure_control_defaults(db)
    items = sla_payload(client, headers, BORDIR={"is_active": False})
    call(client, headers, "CMO_MANAGER", "POST", "/control/sla", {"reason": "Bordir dimatikan dulu", "items": items}, expected=201)
    make_order(db, users, spk_released_days_ago=0)
    planner = call(client, headers, "CMO_MANAGER", "GET", "/control/capacity-planner")
    assert {r["code"]: r for r in planner["rows"]}["BORDIR"]["status"] == "TIDAK DIPAKAI"
    fc = call(client, headers, "CMO_MANAGER", "GET", "/control/forecast")
    assert "BORDIR" not in fc["orders"][0]["stage_dates"] and fc["orders"][0]["est_finish"] == str(date.today() + timedelta(days=18))


def test_projection_stacks_remaining_sla_from_today(db, users):
    ensure_control_defaults(db)
    items = active_items(db)
    today = date.today()
    fresh = view(db, make_order(db, users, "SYM-2610-001", spk_released_days_ago=0))
    p = project_order(fresh, items, today)
    offsets = {code: (d - today).days for code, d in p["starts"].items()}
    assert offsets == {"BAHAN": 0, "CUTTING": 2, "SORTIR": 4, "PRINTING": 5, "BORDIR": 10, "QC_SB": 14, "SEWING": 15,
                       "ACC": 18, "QC_PACK": 20, "SHIPPING": 21}            # REVISI dilewati
    assert (p["finish"] - today).days == 22 and p["next_stage"] == "CUTTING"
    # tahap berjalan memakai sisa SLA: BAHAN (2 hari) sudah 1 hari berjalan -> tinggal 1 hari
    started = view(db, make_order(db, users, "SYM-2610-002", spk_released_days_ago=1))
    assert (project_order(started, items, today)["finish"] - today).days == 21
    late = view(db, make_order(db, users, "SYM-2610-003", spk_released_days_ago=9))     # sudah lewat SLA -> sisa 0
    assert (project_order(late, items, today)["finish"] - today).days == 20
    done = view(db, make_order(db, users, "SYM-2610-004", m.OrderType.SAMPLE_ONLY, flow_step="FOLLOW_UP"))
    assert project_order(done, items, today)["finish"] is None


def test_deadline_risk_rules(db, users):
    ensure_control_defaults(db)
    today = date.today()
    v = view(db, make_order(db, users, spk_released_days_ago=0))
    finish = today + timedelta(days=22)
    for days, expected in ((20, "URGENT"), (22, "PERHATIAN"), (24, "PERHATIAN"), (25, "AMAN"), (60, "AMAN")):
        v["deadline"] = today + timedelta(days=days)
        assert deadline_risk(v, finish, today) == expected, days
    v["deadline"] = today - timedelta(days=1)
    assert deadline_risk(v, today, today) == "URGENT"
    v["deadline"] = None
    assert deadline_risk(v, finish, today) == "TANPA DEADLINE"
    v["priority"] = "SELESAI"
    assert deadline_risk(v, finish, today) == "SELESAI"


def test_forecast_horizons_count_orders_by_when_they_reach_each_stage(db, users):
    ensure_control_defaults(db)
    today = date.today()
    make_order(db, users, "SYM-2610-001", spk_released_days_ago=0, qty=100)
    views = build_board(db, db.query(m.Order).all())
    stages = {s["code"]: s for s in forecast_engine(views, active_items(db), today)["stages"]}
    assert stages["PRINTING"]["orders_7d"] == 1 and stages["BORDIR"]["orders_7d"] == 0 and stages["BORDIR"]["orders_14d"] == 1
    assert stages["SEWING"]["orders_14d"] == 0 and stages["SEWING"]["orders_30d"] == 1
    assert stages["PRINTING"]["load_pct_7d"] == round(100 / (500 * 7) * 100, 1)
    assert stages["REVISI"]["orders_30d"] == 0
    assert stages["PRINTING"]["status"] == "AVAILABLE"


def test_forecast_flags_overload_and_urgent_deadlines(client, headers, db, users):
    ensure_control_defaults(db)
    big = make_order(db, users, "SYM-2610-001", spk_released_days_ago=0, qty=8000)       # PRINTING 14 hari = 7000
    big.buyer_deadline = date.today() + timedelta(days=10)                                 # selesai +22 -> URGENT
    ok = make_order(db, users, "SYM-2610-002", spk_released_days_ago=0, qty=10)
    ok.buyer_deadline = date.today() + timedelta(days=90)
    db.commit()
    data = call(client, headers, "COO_MANAGER", "GET", "/control/forecast")
    assert data["banner"]["level"] == "OVERLOAD" and data["banner"]["tone"] == "red"
    printing = next(s for s in data["stages"] if s["code"] == "PRINTING")
    assert printing["status"] == "OVERLOAD" and printing["load_pct_14d"] > 100 and "STOP" in printing["action"]
    risks = {o["order_id"]: o for o in data["orders"]}
    assert risks["SYM-2610-001"]["risk"] == "URGENT" and risks["SYM-2610-002"]["risk"] == "AMAN"
    assert data["orders"][0]["order_id"] == "SYM-2610-001"                                 # paling berisiko di atas
    assert data["risk_counts"]["URGENT"] == 1 and risks["SYM-2610-001"]["days_to_deadline"] == 10
    dash = call(client, headers, "COO_MANAGER", "GET", "/control/dashboard")
    assert dash["forecast_banner"]["level"] == "OVERLOAD" and dash["alerts"]["deadline_forecast_urgent"] == 1
    assert next(r for r in dash["forecast_14d"] if r["code"] == "PRINTING")["status"] == "OVERLOAD"


def test_capacity_feed_for_cmo(client, headers, db, users):
    ensure_control_defaults(db)
    make_order(db, users, "SYM-2610-001", spk_released_days_ago=0, qty=1000)
    data = call(client, headers, "CMO_SUPPORT", "GET", "/control/capacity-feed")
    assert data["basis"] == "SEWING" and data["daily_capacity"] == 450
    rows = {r["horizon_days"]: r for r in data["rows"]}
    assert [r["available_capacity"] for r in data["rows"]] == [3150, 6300, 13500]       # sama dengan tab 19 di sheet
    assert rows[7]["confirmed_load"] == 0 and rows[14]["confirmed_load"] == 0           # sewing baru mulai hari ke-15
    assert rows[30]["confirmed_load"] == 1000 and rows[30]["free_capacity"] == 12500
    assert rows[30]["current_wip"] == 1000 and rows[30]["printing_load_pct"] > 0
    for role in m.Role:
        call(client, headers, role.value, "GET", "/control/capacity-feed")
        call(client, headers, role.value, "GET", "/control/forecast")
        call(client, headers, role.value, "GET", "/control/capacity-planner")


def test_unit_amount_by_capacity_unit(db, users):
    ensure_control_defaults(db)
    v = view(db, make_order(db, users, qty=120))
    assert (unit_amount("ORDER", v), unit_amount("ARTICLE", v), unit_amount("PCS", v), unit_amount(None, v)) == (1, 1, 120, 120)


# ───────────────────────────── Penutup: kolom CMO (invoice, sample, revisi, siap ke COO) ─────────────────────────────

def test_invoice_status_uses_the_sheet_vocabulary(db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, spk_released_days_ago=0)
    assert view(db, order)["invoice_status"] == "BELUM TERBIT"
    inv = m.Invoice(invoice_no="INV-1", order_fk=order.id, amount=1000, paid_amount=0)
    db.add(inv)
    db.commit()
    assert view(db, order)["invoice_status"] == "OUTSTANDING"
    inv.paid_amount = 300
    db.commit()
    assert view(db, order)["invoice_status"] == "DP"
    inv.paid_amount = 1000
    db.commit()
    assert view(db, order)["invoice_status"] == "SELESAI"


def test_sample_revision_approval_and_ready_to_coo(db, users):
    ensure_control_defaults(db)
    plain = make_order(db, users, "SYM-2610-001", spk_released_days_ago=0)
    v = view(db, plain)
    assert (v["sample_status"], v["buyer_approval"], v["revision"]) == ("SKIP", "TIDAK PERLU", None)
    assert v["spk_released"] and v["ready_to_coo"]

    order = make_order(db, users, "SYM-2610-002", spk_released_days_ago=0)
    article = order.articles[0]
    article.sample_required = True
    db.commit()
    v = view(db, order)
    assert (v["sample_status"], v["buyer_approval"]) == ("PROGRES", "PENDING") and not v["ready_to_coo"]

    record = m.SampleRecord(order_fk=order.id, article_code=article.article_code, article_id=article.id,
                            status="REVISION", sample_version=2)
    db.add(record)
    db.commit()
    v = view(db, order)
    assert (v["sample_status"], v["revision"], v["ready_to_coo"]) == ("REVISION", "REV-01", False)

    record.status, record.customer_approved_by_id = "APPROVED", users[m.Role.CMO_MANAGER].id
    db.commit()
    v = view(db, order)
    assert (v["sample_status"], v["buyer_approval"], v["revision"], v["ready_to_coo"]) == ("APPROVED", "APPROVED", "REV-01", True)

    no_spk = make_order(db, users, "SYM-2610-003", flow_step="SPK")
    assert view(db, no_spk)["ready_to_coo"] is False


def test_qc_sb_stage_follows_production_queue_when_in_route(db, users):
    ensure_control_defaults(db)
    order = make_order(db, users, spk_released_days_ago=1)
    article = order.articles[0]
    article.production_route = "Printing > QC S/B > Sewing"
    db.add(m.ProductionMovement(article_id=article.id, process="QC S/B", qty_in=10, qty_done=10, status="DONE"))
    db.commit()
    v = view(db, order)
    assert stage(v, "QC_SB")["status"] == "SELESAI" and stage(v, "QC_SB")["from_data"]
    assert stage(v, "PRINTING")["status"] != "SELESAI"      # Printing belum ada catatan DONE
