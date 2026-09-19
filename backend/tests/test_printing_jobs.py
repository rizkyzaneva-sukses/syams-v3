"""PRN-I-004/005/006 — Job Card, Quantity Control & Partial Handoff,
Evidence/Inspection/Defect & Rework (revisi #43, #44, #45).

Router baru ini belum didaftarkan orkestrator di `main.py` (lihat
REQUESTS/printing_jobs.md), jadi tes memanggil `include_router` sendiri seperti
yang diwajibkan AGENT-RULES.md bagian 3 — dengan prefix `/api` yang sama seperti
main.py. Tabel baru juga belum ada, sehingga yang diuji adalah endpoint baca
yang dibangun dari tabel yang sudah ada (`production_movements`, `qc_records`,
`articles`, `orders`, `spks`, `sample_records`).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("SECRET_KEY", "isolated-tests-only-42e77368071baf60a39e476b196052bd")
os.environ.setdefault("SEED_DEMO", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from app import models as m
from app.main import app
from app.routers.printing_jobs import router as printing_router

app.include_router(printing_router, prefix="/api")


def api(client, headers, role, method, path, body=None, expected=200):
    response = client.request(method, path, headers=headers(role), json=body)
    assert response.status_code == expected, response.text
    return response.json() if response.content else None


def make_order(db, order_id="SO-PRT-1", route="Cutting > Printing > Bordir > QC > Packing"):
    """Order + artikel + SPK yang sudah dirilis. Membalikkan (order, article)."""
    order = m.Order(order_id=order_id, buyer="Buyer Printing", order_type=m.OrderType.REPEAT_PRODUCTION)
    db.add(order)
    db.flush()
    article = m.Article(
        order_fk=order.id, article_code=f"{order_id}-A1", garment_type="T-Shirt",
        qty=500, size_breakdown="M:250,L:250", production_route=route,
    )
    db.add(article)
    db.add(m.SPK(order_fk=order.id, spk_no=f"SPK-{order_id}", status="RELEASED", version=2))
    db.commit()
    return order, article


def add_movement(db, article, process, qty_in, qty_done=0, qty_reject=0, status="IN_PROCESS", pic="Iman", reason=None):
    row = m.ProductionMovement(
        article_id=article.id, process=process, qty_in=qty_in, qty_done=qty_done,
        qty_reject=qty_reject, status=status, pic_name=pic, reject_reason=reason,
    )
    db.add(row)
    db.commit()
    return row


def add_qc(db, order, article, process, checked, passed, rejected, status="PASS", reason=None, parent=None, inspector="Iman"):
    row = m.QCRecord(
        order_fk=order.id, article_code=article.article_code, article_id=article.id,
        process=process, total_checked=checked, total_pass=passed, total_reject=rejected,
        status=status, reject_reason=reason, rework_parent_id=parent, inspector=inspector,
    )
    db.add(row)
    db.commit()
    return row


# ── Revisi #43 — Job Card ────────────────────────────────────────────────────
def test_job_cards_are_locked_to_spk_version_and_only_printing_stages(client, headers, db):
    order, article = make_order(db)
    add_movement(db, article, "CUTTING", 500, 500, 0, status="DONE", pic="Budi")   # harus dikecualikan
    add_movement(db, article, "PRINTING", 500, 300, 50, status="IN_PROCESS", pic="Iman")
    add_movement(db, article, "Bordir", 500, 180, 20, status="IN_PROCESS", pic="Iman")

    payload = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/job-cards")
    stages = sorted(card["stage"] for card in payload["job_cards"])
    assert stages == ["Bordir", "PRINTING"], payload
    assert payload["total_job_cards"] == 2

    printing = next(card for card in payload["job_cards"] if card["stage"] == "PRINTING")
    # Requirement version dikunci saat START: SPK dirilis versi 2.
    assert printing["spk_no"] == f"SPK-{order.order_id}"
    assert printing["spk_version"] == 2
    assert printing["requirement_version"] == f"SPK-{order.order_id}@v2"
    assert printing["order_id"] == order.order_id
    assert printing["article_code"] == article.article_code
    assert printing["route"] == "Cutting > Printing > Bordir > QC > Packing"
    assert printing["printing_stages"] == ["Printing", "Bordir"]
    assert printing["size_spec"] == "M:250,L:250"
    assert printing["team_shift"] == "Iman"
    assert printing["required_evidence"] == ["hasil_cetak", "inspeksi", "handoff"]
    # Next handoff mengikuti route, bukan tebakan UI.
    assert printing["next_handoff"] == "Bordir"
    assert printing["job_id"].startswith("JOB-")
    assert payload["printing_stage_rule"] == ["PRINTING", "BORDIR"]


def test_approved_sample_is_exposed_as_artwork_version(client, headers, db):
    order, article = make_order(db, order_id="SO-PRT-9")
    db.add(m.SampleRecord(order_fk=order.id, article_code=article.article_code, article_id=article.id, status="APPROVED"))
    db.commit()
    add_movement(db, article, "PRINTING", 100, 40, 0)
    card = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/job-cards")["job_cards"][0]
    assert card["artwork_version"] == f"SAMPLE-{article.article_code}@approved"


def test_cutting_movements_never_appear_as_printing_job_cards(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-2")
    add_movement(db, article, "CUTTING", 100, 100, 0, status="DONE")
    add_movement(db, article, "SEWING", 100, 0, 0, status="WAITING")
    payload = api(client, headers, "COO_MANAGER", "GET", "/api/printing/job-cards")
    assert payload["job_cards"] == []
    assert payload["total_job_cards"] == 0
    assert payload["quantity_balanced"] is True


# ── Revisi #44 — Quantity control & partial handoff ──────────────────────────
def test_quantity_control_balances_in_done_reject_wip(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-3")
    add_movement(db, article, "PRINTING", 500, 300, 50, status="IN_PROCESS")

    payload = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/job-cards")
    card = payload["job_cards"][0]
    assert (card["qty_in"], card["qty_done"], card["qty_reject"], card["wip"]) == (500, 300, 50, 150)
    # qty_in = qty_done + qty_reject + WIP
    assert card["qty_in"] == card["qty_done"] + card["qty_reject"] + card["wip"]
    assert card["qty_balanced"] is True
    assert card["remaining_balance"] == 150
    assert payload["quantity_balanced"] is True


def test_partial_handoff_is_visible_and_remaining_balance_reported(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-4")
    add_movement(db, article, "PRINTING", 400, 250, 10, status="IN_PROCESS")            # partial
    add_movement(db, article, "PRINTING", 100, 100, 0, status="DONE", pic="Iman-2")     # tuntas
    cards = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/job-cards")["job_cards"]
    partial = [card for card in cards if card["partial_handoff"]]
    done = [card for card in cards if not card["partial_handoff"]]
    assert len(partial) == 1 and partial[0]["wip"] == 140
    assert len(done) == 1 and done[0]["remaining_balance"] == 0
    # Qty Sent tidak boleh ditimpa: tiap movement tetap baris terpisah.
    assert len(cards) == 2


def test_quantity_check_endpoint_rejects_over_and_negative(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-5")
    add_movement(db, article, "PRINTING", 500, 0, 0, status="WAITING")

    ok = api(client, headers, "PRINTING_PIC", "GET",
             f"/api/printing/quantity-check?article_id={article.id}&process=PRINTING&qty_done=300&qty_reject=50")
    assert ok["allowed"] is True and ok["wip"] == 150
    assert ok["source"] == "production_movements"
    assert ok["qty_in"] == 500

    over = api(client, headers, "PRINTING_PIC", "GET",
               f"/api/printing/quantity-check?article_id={article.id}&process=PRINTING&qty_done=480&qty_reject=50")
    assert over["allowed"] is False and over["errors"]

    # Angka negatif ditolak di layer validasi query.
    api(client, headers, "PRINTING_PIC", "GET",
        f"/api/printing/quantity-check?article_id={article.id}&process=PRINTING&qty_done=-5", expected=422)
    api(client, headers, "PRINTING_PIC", "GET",
        "/api/printing/quantity-check?article_id=99999&process=PRINTING&qty_done=1", expected=404)


# ── Revisi #45 — Evidence, inspection, defect & rework ───────────────────────
def test_quality_summary_records_inspection_defect_reason_and_rework(client, headers, db):
    order, article = make_order(db, order_id="SO-PRT-6")
    parent = add_qc(db, order, article, "PRINTING", 500, 450, 50, status="FAIL", reason="warna sablon miring")
    add_qc(db, order, article, "PRINTING", 50, 45, 5, status="REWORK", reason="hasil bordir kurang rapat", parent=parent.id)
    add_qc(db, order, article, "QC", 400, 400, 0, status="PASS", inspector="Andi")   # QC final

    payload = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/quality")
    assert payload["total_inspections"] == 3
    assert payload["total_checked"] == 950
    assert payload["total_pass"] == 895
    assert payload["total_reject"] == 55
    assert payload["overall_pass_rate"] == pytest.approx(94.21, abs=0.01)

    # Reject wajib punya alasan -> yang punya alasan tertutup, tanpa alasan OPEN.
    assert payload["total_defects"] == 2
    assert payload["total_rework"] == 1
    assert payload["open_reject_count"] == 0

    rework = payload["rework"][0]
    assert rework["rework_parent_id"] == parent.id
    assert rework["reason"] == "hasil bordir kurang rapat"
    assert rework["retest_required"] is True

    categories = {row["category"] for row in payload["defect_categories"]}
    assert "COLOR_MISMATCH" in categories and "EMBROIDERY_DEFECT" in categories
    # QC final tetap terlihat terpisah, bukan dianggap inspeksi Printing.
    final = [row for row in payload["inspections"] if row["process"] == "QC"][0]
    assert final["is_printing_stage"] is False
    printing_rows = [row for row in payload["inspections"] if row["process"] == "PRINTING"]
    assert all(row["is_printing_stage"] is True for row in printing_rows)


def test_reject_without_disposition_is_flagged_and_blocks_job(client, headers, db):
    order, article = make_order(db, order_id="SO-PRT-7")
    add_movement(db, article, "PRINTING", 300, 100, 40, status="IN_PROCESS", reason=None)
    add_qc(db, order, article, "PRINTING", 300, 260, 40, status="FAIL", reason=None)

    quality = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/quality")
    assert quality["open_reject_count"] == 1
    assert quality["open_reject_no_disposition"][0]["disposition"] == "OPEN"
    assert quality["open_reject_no_disposition"][0]["defect_category"] == "UNSPECIFIED"

    card = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/job-cards")["job_cards"][0]
    assert card["reject_closed"] is False
    assert card["blocker"] == "Reject belum berdisposisi"


def test_reject_recorded_without_reason_in_movement_also_blocks(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-10")
    add_movement(db, article, "Bordir", 200, 150, 30, status="IN_PROCESS", reason=None)
    card = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/job-cards")["job_cards"][0]
    assert card["defect_dispositions"] == 30
    assert card["reject_closed"] is False


# ── RBAC ─────────────────────────────────────────────────────────────────────
def test_printing_endpoints_enforce_roles(client, headers, db):
    make_order(db, order_id="SO-PRT-8")
    for role in ("CHRO_MANAGER", "CMO_SUPPORT"):
        api(client, headers, role, "GET", "/api/printing/job-cards", expected=403)
        api(client, headers, role, "GET", "/api/printing/quality", expected=403)
    for role in ("CEO", "COO_MANAGER", "PRINTING_PIC", "PRODUCTION_PIC"):
        api(client, headers, role, "GET", "/api/printing/job-cards")
        api(client, headers, role, "GET", "/api/printing/quality")
