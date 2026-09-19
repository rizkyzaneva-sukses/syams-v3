"""COO daily execution, WIP/handoff/capacity, and physical BOM usage.

Revisi #53 / #54 / #57. The router is not yet registered in app/main.py (the
orchestrator owns that file), so every test mounts it explicitly here.
"""
from datetime import date, timedelta

import pytest

from app import models as m


@pytest.fixture(autouse=True)
def mount_router():
    """Register the COO execution router on the shared app for this test module."""
    from app.main import app
    from app.routers.coo_execution import router

    already = any(getattr(r, "path", "").startswith("/api/coo/daily-execution") for r in app.routes)
    if not already:
        app.include_router(router, prefix="/api")
    yield


def make_order(db, number, route="Cutting>Sewing>QC", qty=100):
    order = m.Order(order_id=number, buyer="Buyer", order_type=m.OrderType.REPEAT_PRODUCTION)
    db.add(order)
    db.flush()
    article = m.Article(order_fk=order.id, article_code="A-1", qty=qty, production_route=route)
    db.add(article)
    db.commit()
    return order, article


def test_endpoints_require_authentication(client):
    assert client.get("/api/coo/daily-execution").status_code == 401
    assert client.get("/api/coo/handoff-capacity").status_code == 401
    assert client.get("/api/coo/bom-physical").status_code == 401


def test_daily_execution_reports_target_today_and_quantity_identity(db, client, headers):
    order, article = make_order(db, "SO-EXEC-1")
    today = date.today()
    db.add_all([
        m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                             qty_done=100, target_date=today, status="DONE"),
        m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=100,
                             qty_done=60, qty_reject=5, target_date=today, status="IN_PROCESS"),
        m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=0,
                             qty_done=0, status="IN_PROCESS"),
    ])
    db.commit()

    body = client.get(f"/api/coo/daily-execution?order_fk={order.id}", headers=headers("COO_MANAGER")).json()
    assert body["invariant"] == "qty_in = qty_done + qty_reject + wip"
    assert body["rows"][0]["order_id"] == "SO-EXEC-1"
    row = body["rows"][0]

    cutting, sewing, qc = row["steps"]
    assert cutting["qty_in"] == 100 and cutting["qty_done"] == 100 and cutting["qty_wip"] == 0
    assert sewing["qty_in"] == 100 and sewing["qty_done"] == 60 and sewing["qty_reject"] == 5
    assert sewing["qty_wip"] == 35
    # QC belum jalan sama sekali: tetap muncul dari rute aktif, bukan dihilangkan.
    assert qc["status"] == "NOT_STARTED" and qc["qty_in"] == 0

    # Cutting dan Sewing sama-sama jatuh tempo hari ini.
    assert row["target_today"] == 200
    assert row["realised_today"] == 160
    assert row["attainment_percent"] == 80.0

    # Kuantitas harus konsisten: in = done + reject + wip.
    assert row["qty_in"] == 200 and row["qty_done"] == 160 and row["qty_reject"] == 5
    assert row["qty_wip"] == 35
    assert row["qty_done"] + row["qty_reject"] + row["qty_wip"] == row["qty_in"]
    assert row["balanced"] is True
    assert body["totals"]["qty_in"] == 200

    # Drill-down: identitas transaksi sumber ikut dikirim.
    assert cutting["movement_ids"] and sewing["movement_ids"]
    assert body["allowed_actions"] == [
        "START", "UPDATE_PROGRESS", "REPORT_OUTPUT", "COMPLETE", "HOLD", "HANDOFF"
    ]


def test_daily_execution_flags_duplicate_and_over_accounted_quantities(db, client, headers):
    order, article = make_order(db, "SO-EXEC-2", route="Cutting>Sewing")
    # Sewing menerima 150 padahal Cutting baru selesai 100 -> tidak sah.
    db.add_all([
        m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                             qty_done=100, status="DONE"),
        m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=150,
                             qty_done=50, status="IN_PROCESS"),
    ])
    db.commit()

    row = client.get(f"/api/coo/daily-execution?order_fk={order.id}",
                     headers=headers("COO_MANAGER")).json()["rows"][0]
    codes = {issue["code"] for issue in row["reconciliation"]}
    assert "QTY_IN_EXCEEDS_UPSTREAM" in codes
    assert row["qty_wip"] == 100  # 150 - 50 - 0, tetap dilaporkan apa adanya


def test_daily_execution_flags_negative_wip_as_over_accounted(db, client, headers):
    order, article = make_order(db, "SO-EXEC-3", route="Cutting")
    db.add(m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                                qty_done=90, qty_reject=20, status="DONE"))
    db.commit()
    row = client.get(f"/api/coo/daily-execution?order_fk={order.id}",
                     headers=headers("COO_MANAGER")).json()["rows"][0]
    codes = {issue["code"] for issue in row["reconciliation"]}
    assert "QTY_OVER_ACCOUNTED" in codes
    assert row["steps"][0]["balanced"] is False
    assert row["steps"][0]["qty_wip"] == -10


def test_closed_orders_are_excluded(db, client, headers):
    order, article = make_order(db, "SO-EXEC-4")
    db.add(m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=10, qty_done=10))
    order.overall_status = "CLOSED"
    db.commit()
    body = client.get("/api/coo/daily-execution", headers=headers("COO_MANAGER")).json()
    assert body["rows"] == []
    assert body["totals"]["articles"] == 0


def test_handoff_shows_from_to_and_discrepancy(db, client, headers):
    order, article = make_order(db, "SO-HANDOFF-1", route="Cutting>Sewing>QC", qty=100)
    db.add_all([
        m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                             qty_done=100, pic_name="Budi", status="DONE"),
        # Baru 95 yang diterima Sewing -> selisih -5 (belum diterima).
        m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=95,
                             qty_done=40, pic_name="Siti", status="IN_PROCESS"),
    ])
    db.commit()

    body = client.get(f"/api/coo/handoff-capacity?order_fk={order.id}",
                      headers=headers("COO_MANAGER")).json()
    # Rute Cutting>Sewing>QC menghasilkan dua edge handoff.
    assert body["summary"]["handoff_count"] == 2
    edge = body["handoffs"][0]
    assert (edge["from_process"], edge["to_process"]) == ("CUTTING", "SEWING")
    assert edge["qty_sent"] == 100
    assert edge["qty_received"] == 95
    assert edge["discrepancy"] == -5
    assert edge["remaining_balance"] == 5
    assert edge["status"] == "PENDING_RECEIPT"
    assert edge["sender_pics"] == ["Budi"]
    assert edge["receiver_pics"] == ["Siti"]

    # Sewing->QC: 40 dikirim, belum ada yang diterima QC.
    downstream = body["handoffs"][1]
    assert (downstream["from_process"], downstream["to_process"]) == ("SEWING", "QC")
    assert downstream["qty_sent"] == 40 and downstream["qty_received"] == 0
    assert downstream["discrepancy"] == -40

    # Discrepancy wajib muncul sebagai tindak lanjut, bukan angka yang lewat.
    assert body["summary"]["discrepancy_count"] == 2
    assert body["summary"]["total_discrepancy"] == -45
    kinds = {f["kind"] for f in body["follow_ups"]}
    assert "HANDOFF_DISCREPANCY" in kinds


def test_handoff_matched_when_sent_equals_received(db, client, headers):
    order, article = make_order(db, "SO-HANDOFF-2", route="Cutting>Sewing", qty=50)
    db.add_all([
        m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=50, qty_done=50, status="DONE"),
        m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=50, qty_done=10, status="IN_PROCESS"),
    ])
    db.commit()
    body = client.get(f"/api/coo/handoff-capacity?order_fk={order.id}",
                      headers=headers("PRODUCTION_PIC")).json()
    assert body["handoffs"][0]["status"] == "MATCHED"
    assert body["handoffs"][0]["discrepancy"] == 0


def test_capacity_uses_real_committed_load_and_reports_conflict(db, client, headers):
    order, article = make_order(db, "SO-CAP-1", route="Cutting>Sewing", qty=100)
    today = date.today()
    db.add_all([
        # Cutting: 100 committed (open WIP) vs 80/hari -> konflik.
        m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                             qty_done=0, status="IN_PROCESS"),
        # Sewing open WIP 0 -> beban kosong.
        m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=10,
                             qty_done=10, status="DONE"),
        m.CapacitySnapshot(process="Cutting", snapshot_date=today, capacity=80, planned_load=999),
        m.CapacitySnapshot(process="Sewing", snapshot_date=today - timedelta(days=3), capacity=200, planned_load=50),
    ])
    db.commit()

    body = client.get(f"/api/coo/handoff-capacity?order_fk={order.id}",
                      headers=headers("COO_MANAGER")).json()
    rows = {r["process"]: r for r in body["capacity"]}

    cutting = rows["CUTTING"]
    assert cutting["capacity_per_day"] == 80
    assert cutting["committed_load"] == 100
    assert cutting["utilization_percent"] == 125.0
    assert cutting["available_capacity"] == 0
    assert cutting["queue"] == 20
    assert cutting["conflict"] is True
    assert cutting["is_stale"] is False
    assert cutting["source"] == "capacity_snapshots"

    sewing = rows["SEWING"]
    assert sewing["is_stale"] is True
    assert sewing["committed_load"] == 0
    assert sewing["utilization_percent"] == 0.0

    assert body["summary"]["conflict_count"] == 1
    assert body["summary"]["bottleneck_process"] == "CUTTING"
    assert body["summary"]["stale_snapshots"] == 1
    assert any(f["kind"] == "CAPACITY_CONFLICT" for f in body["follow_ups"])


def test_capacity_without_snapshot_is_marked_not_fabricated(db, client, headers):
    order, article = make_order(db, "SO-CAP-2", route="Cutting", qty=30)
    db.add(m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=30,
                                qty_done=10, status="IN_PROCESS"))
    db.commit()
    row = client.get(f"/api/coo/handoff-capacity?order_fk={order.id}",
                     headers=headers("COO_MANAGER")).json()["capacity"][0]
    assert row["process"] == "CUTTING"
    assert row["capacity_per_day"] is None
    assert row["utilization_percent"] is None
    assert row["source"] == "NO_SNAPSHOT"
    assert row["committed_load"] == 20


def test_bom_physical_compares_usage_to_plan_and_shows_difference(db, client, headers):
    order, article = make_order(db, "SO-BOM-1", qty=100)
    item = m.BOMItem(article_id=article.id, material_name="Kain Dryfit", unit="meter",
                     qty_per_unit=0.5, planned_unit_cost=25000)
    db.add(item)
    db.flush()
    # Rencana 0.5 x 100 = 50 m; fisik terpakai 62 m -> selisih +12 (over).
    db.add(m.MaterialConsumption(bom_item_id=item.id, qty=62, actual_unit_cost=26000,
                                 evidence_ref="GD-001", recorded_by_id=2))
    db.commit()

    body = client.get(f"/api/coo/bom-physical?order_fk={order.id}",
                      headers=headers("COO_MANAGER")).json()
    assert body["cost_access"] == "READ_ONLY"
    row = body["rows"][0]
    assert row["material_name"] == "Kain Dryfit"
    assert row["planned_qty"] == 50.0
    assert row["actual_qty"] == 62.0
    assert row["difference_qty"] == 12.0
    assert row["variance_percent"] == 24.0
    assert row["status"] == "OVER_USAGE"
    # Biaya tetap terlihat sebagai referensi ter-mask, bukan field input.
    assert row["cost_field_access"] == "READ_ONLY"
    assert row["planned_cost"] == 1250000.0
    assert row["actual_cost"] == 1612000.0
    assert row["difference_cost"] == 362000.0
    assert body["summary"]["over_usage_items"] == 1


def test_bom_physical_without_usage_is_under_usage_not_zero_plan(db, client, headers):
    order, article = make_order(db, "SO-BOM-2", qty=40)
    db.add(m.BOMItem(article_id=article.id, material_name="Benang", unit="roll",
                     qty_per_unit=0.25, planned_unit_cost=8000))
    db.commit()
    row = client.get(f"/api/coo/bom-physical?order_fk={order.id}",
                     headers=headers("COO_MANAGER")).json()["rows"][0]
    assert row["planned_qty"] == 10.0
    assert row["actual_qty"] == 0.0
    assert row["status"] == "UNDER_USAGE"
    assert row["difference_qty"] == -10.0
    assert row["variance_percent"] == -100.0


def test_bom_physical_zero_plan_does_not_divide_by_zero(db, client, headers):
    order, article = make_order(db, "SO-BOM-3", qty=0)
    db.add(m.BOMItem(article_id=article.id, material_name="Label", unit="pcs",
                     qty_per_unit=1, planned_unit_cost=500))
    db.commit()
    row = client.get(f"/api/coo/bom-physical?order_fk={order.id}",
                     headers=headers("COO_MANAGER")).json()["rows"][0]
    assert row["planned_qty"] == 0.0
    assert row["variance_percent"] is None
    assert row["status"] == "MATCH"


def test_role_scope_blocks_unrelated_roles(client, headers):
    assert client.get("/api/coo/daily-execution", headers=headers("HR_SUPPORT")).status_code == 403
    assert client.get("/api/coo/handoff-capacity", headers=headers("SHIPMENT_ADMIN")).status_code == 403


# ── Revisi #53: kontrak aksi melekat pada peran ──────────────────────────────
def test_daily_execution_exposes_action_contract_per_actor_role(db, client, headers):
    order, article = make_order(db, "SO-ACT-1", route="Cutting>Sewing", qty=100)
    db.add(m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                                qty_done=100, status="IN_PROCESS"))
    db.commit()

    coo = client.get(f"/api/coo/daily-execution?order_fk={order.id}",
                     headers=headers("COO_MANAGER")).json()
    assert coo["allowed_actions"] == [
        "START", "UPDATE_PROGRESS", "REPORT_OUTPUT", "COMPLETE", "HOLD", "HANDOFF"
    ]
    assert coo["action_contract"]["actions_for_actor"] == list(coo["allowed_actions"])

    pic = client.get(f"/api/coo/daily-execution?order_fk={order.id}",
                     headers=headers("PRODUCTION_PIC")).json()
    # PIC lantai tidak memegang COMPLETE/HANDOFF — inti revisi #53.
    assert pic["action_contract"]["actions_for_actor"] == [
        "START", "UPDATE_PROGRESS", "REPORT_OUTPUT", "HOLD"
    ]
    assert pic["allowed_actions"] == list(coo["allowed_actions"])


def test_step_actions_block_role_without_authority_but_still_show_owner(db, client, headers):
    order, article = make_order(db, "SO-ACT-2", route="Cutting>Sewing", qty=100)
    db.add(m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                                qty_done=100, status="IN_PROCESS"))
    db.commit()

    step = client.get(f"/api/coo/daily-execution?order_fk={order.id}",
                      headers=headers("PRODUCTION_PIC")).json()["rows"][0]["steps"][0]
    by_action = {a["action"]: a for a in step["actions"]["actions"]}

    # COMPLETE sah secara WIP (100 = 100 + 0) tapi tetap dilarang untuk PIC.
    complete = by_action["COMPLETE"]
    assert complete["allowed"] is False
    assert complete["authorised"] is False
    assert complete["roles"] == ["COO_MANAGER"]
    assert {b["code"] for b in complete["blockers"]} == {"ROLE_NOT_AUTHORISED"}

    # START sah dan diizinkan untuk PIC.
    assert by_action["START"]["allowed"] is True
    assert by_action["START"]["authorised"] is True

    assert "COMPLETE" not in step["actions"]["allowed_actions"]
    assert "START" in step["actions"]["allowed_actions"]


def test_step_complete_becomes_allowed_for_coo_when_wip_reconciled(db, client, headers):
    order, article = make_order(db, "SO-ACT-3", route="Cutting>Sewing", qty=100)
    db.add(m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                                qty_done=90, qty_reject=10, status="IN_PROCESS"))
    db.commit()
    step = client.get(f"/api/coo/daily-execution?order_fk={order.id}",
                      headers=headers("COO_MANAGER")).json()["rows"][0]["steps"][0]
    by_action = {a["action"]: a for a in step["actions"]["actions"]}
    assert by_action["COMPLETE"]["allowed"] is True
    assert by_action["COMPLETE"]["to_status"] == "DONE"
    assert "COMPLETE" in step["actions"]["allowed_actions"]


def test_step_complete_blocked_while_wip_remains(db, client, headers):
    order, article = make_order(db, "SO-ACT-4", route="Cutting>Sewing", qty=100)
    db.add(m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                                qty_done=40, status="IN_PROCESS"))
    db.commit()
    step = client.get(f"/api/coo/daily-execution?order_fk={order.id}",
                      headers=headers("COO_MANAGER")).json()["rows"][0]["steps"][0]
    complete = {a["action"]: a for a in step["actions"]["actions"]}["COMPLETE"]
    assert complete["allowed"] is False
    assert "WIP_NOT_RECONCILED" in {b["code"] for b in complete["blockers"]}


def test_handoff_action_targets_next_process_in_route(db, client, headers):
    order, article = make_order(db, "SO-ACT-5", route="Cutting>Sewing>QC", qty=80)
    db.add(m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=80,
                                qty_done=80, status="IN_PROCESS"))
    db.commit()
    steps = client.get(f"/api/coo/daily-execution?order_fk={order.id}",
                       headers=headers("COO_MANAGER")).json()["rows"][0]["steps"]
    cutting = {a["action"]: a for a in steps[0]["actions"]["actions"]}
    # Cutting punya langkah berikutnya (Sewing) -> HANDOFF sah.
    assert cutting["HANDOFF"]["allowed"] is True
    qc = {a["action"]: a for a in steps[2]["actions"]["actions"]}
    # QC langkah terakhir -> tidak ada downstream, HANDOFF ditolak.
    assert qc["HANDOFF"]["allowed"] is False
    assert "NO_DOWNSTREAM_PROCESS" in {b["code"] for b in qc["HANDOFF"]["blockers"]}


# ── Revisi #54: WIP & handoff bisa ditelusuri ke transaksi sumbernya ─────────
def test_wip_carries_its_source_movement_ids(db, client, headers):
    order, article = make_order(db, "SO-TRACE-1", route="Cutting>Sewing", qty=100)
    mv1 = m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                               qty_done=100, status="DONE")
    mv2 = m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=100,
                               qty_done=60, status="IN_PROCESS")
    mv3 = m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=0,
                               qty_done=0, status="IN_PROCESS")
    db.add_all([mv1, mv2, mv3])
    db.commit()

    steps = client.get(f"/api/coo/daily-execution?order_fk={order.id}",
                       headers=headers("COO_MANAGER")).json()["rows"][0]["steps"]
    sewing = steps[1]
    assert sewing["qty_wip"] == 40
    source = sewing["wip_source"]
    # Angka WIP harus bisa ditelusuri ke movement id nyata, bukan tebakan.
    assert source["movement_ids"] == sorted([mv2.id, mv3.id])
    assert source["qty_in"] == 100 and source["qty_done"] == 60 and source["qty_reject"] == 0
    assert source["qty_in"] - source["qty_done"] - source["qty_reject"] == sewing["qty_wip"]
    assert source["derived_from"] == f"production_movements{(mv2.id, mv3.id)}"


def test_handoff_qty_sources_name_their_movements_and_persistence_gap(db, client, headers):
    order, article = make_order(db, "SO-TRACE-2", route="Cutting>Sewing", qty=100)
    mv_in = m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                                 qty_done=100, status="DONE")
    mv_out = m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=95,
                                  qty_done=40, status="IN_PROCESS")
    db.add_all([mv_in, mv_out])
    db.commit()

    edge = client.get(f"/api/coo/handoff-capacity?order_fk={order.id}",
                      headers=headers("COO_MANAGER")).json()["handoffs"][0]
    assert edge["qty_sent"] == 100 and edge["qty_received"] == 95
    source = edge["qty_source"]
    assert source["sent_movement_ids"] == [mv_in.id]
    assert source["received_movement_ids"] == [mv_out.id]
    # Tanpa baris production_handoffs, edge ini jujur menyebut dirinya rekonstruksi.
    assert source["persisted"] is False
    assert "production_handoffs" in source["persistence_note"]


# ── Revisi #54 lanjutan: papan membaca transaksi tersimpan lebih dulu ────────
def test_persisted_handoff_supersedes_reconstruction_on_the_board(db, client, headers):
    order, article = make_order(db, "SO-PERSIST-1", route="Cutting>Sewing", qty=100)
    db.add_all([
        m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                             qty_done=100, status="DONE"),
        m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=95,
                             qty_done=40, status="IN_PROCESS"),
    ])
    db.commit()
    row = m.ProductionHandoff(
        order_fk=order.id, article_id=article.id, handoff_no="HO-PB-1",
        from_process="CUTTING", to_process="SEWING", batch_no="BATCH-9",
        qty_sent=100, qty_received=95, discrepancy=-5, status="PARTIAL",
        evidence_ref="GD-9", shift="SHIFT-1", location="LINE-B",
    )
    db.add(row)
    db.commit()

    body = client.get(f"/api/coo/handoff-capacity?order_fk={order.id}",
                      headers=headers("COO_MANAGER")).json()
    edge = body["handoffs"][0]
    assert edge["qty_sent"] == 100 and edge["qty_received"] == 95
    assert edge["discrepancy"] == -5
    assert edge["handoff_ids"] == [row.id]
    assert edge["handoff_nos"] == ["HO-PB-1"]
    # batch/evidence/shift/location HANYA ada karena baris tersimpan (#54).
    assert edge["batch_nos"] == ["BATCH-9"]
    assert edge["evidence_refs"] == ["GD-9"]
    assert edge["shifts"] == ["SHIFT-1"]
    assert edge["locations"] == ["LINE-B"]
    assert edge["qty_sent_locked"] is True
    assert edge["qty_source"]["source"] == "production_handoffs"
    assert edge["qty_source"]["persisted"] is True
    assert body["summary"]["persisted_handoffs"] == 1
    # Rute Cutting>Sewing hanya punya satu edge dan edge itu tersimpan.
    assert body["summary"]["reconstructed_handoffs"] == 0


def test_end_to_end_send_then_board_reads_persisted_values(db, client, headers):
    """Kirim lewat POST /coo/handoffs, lalu papan harus membaca angka itu."""
    from app.routers.coo_handoffs import router as handoff_router

    from app.main import app
    if not any(getattr(r, "path", "") == "/api/coo/handoffs" for r in app.routes):
        app.include_router(handoff_router, prefix="/api")

    order, article = make_order(db, "SO-E2E-1", route="Cutting>Sewing>QC", qty=100)
    db.add(m.ProductionMovement(article_id=article.id, process="Cutting", qty_in=100,
                                qty_done=100, status="DONE"))
    db.commit()

    sent = client.post("/api/coo/handoffs",
                       json={"order_fk": order.id, "article_id": article.id,
                             "from_process": "Cutting", "to_process": "Sewing",
                             "qty_sent": 100, "batch_no": "BATCH-E2E",
                             "evidence_ref": "GD-E2E", "shift": "SHIFT-3",
                             "location": "LINE-C"},
                       headers=headers("COO_MANAGER"))
    assert sent.status_code == 201, sent.text
    handoff_id = sent.json()["handoff"]["id"]

    # Belum diterima: board melaporkan discrepancy -100 dan qty belum terkunci.
    body = client.get(f"/api/coo/handoff-capacity?order_fk={order.id}",
                      headers=headers("COO_MANAGER")).json()
    edge = body["handoffs"][0]
    assert edge["handoff_ids"] == [handoff_id]
    assert edge["qty_sent"] == 100 and edge["qty_received"] == 0
    assert edge["discrepancy"] == -100
    assert edge["batch_nos"] == ["BATCH-E2E"]
    assert edge["locations"] == ["LINE-C"]
    assert edge["qty_sent_locked"] is False

    # Terima sebagian: board mengikuti angka tersimpan dan mengunci qty_sent.
    assert client.post(f"/api/coo/handoffs/{handoff_id}/receive",
                       json={"qty_received": 100},
                       headers=headers("PRODUCTION_PIC")).status_code == 200
    body = client.get(f"/api/coo/handoff-capacity?order_fk={order.id}",
                      headers=headers("COO_MANAGER")).json()
    edge = body["handoffs"][0]
    assert edge["qty_received"] == 100 and edge["discrepancy"] == 0
    assert edge["status"] == "MATCHED"
    assert edge["qty_sent_locked"] is True

    # Dan qty_sent-nya benar-benar tidak bisa ditimpa lagi.
    tamper = client.patch(f"/api/coo/handoffs/{handoff_id}",
                          json={"qty_sent": 60}, headers=headers("COO_MANAGER"))
    assert tamper.status_code == 409, tamper.text
    db.expire_all()
    assert db.get(m.ProductionHandoff, handoff_id).qty_sent == 100
