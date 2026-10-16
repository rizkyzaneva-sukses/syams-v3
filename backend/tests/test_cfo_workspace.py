"""Ruang kerja CFO: kas kecil/besar, karyawan harian, hasil produksi, pembelian & stok bahan, COGS mingguan."""
from datetime import date, datetime, timedelta

import pytest

from app import models as m
from app.accounting_models import JournalEntry, JournalLine
from app.cfo_models import CashEntry, ProductionResult
from app.inventory_models import (GoodsReceipt, GoodsReceiptLine, InventoryLocation, Material, StockMovement, Supplier)


def call(client, headers, role, method, path, body=None, expected=200):
    response = client.request(method, "/api" + path, headers=headers(role), json=body)
    assert response.status_code == expected, response.text
    return response.json() if response.content else None


TODAY = date.today()


# ───────────────────────────── kas ─────────────────────────────

def petty(day=TODAY, direction="OUT", amount=50_000, desc="Beli isolasi", category="ATK"):
    return {"kind": "PETTY", "entry_date": str(day), "direction": direction, "category": category, "description": desc, "amount": amount}


def test_petty_cash_daily_report_carries_the_balance_forward(client, headers):
    yesterday = TODAY - timedelta(days=1)
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", petty(yesterday, "IN", 500_000, "Isi kas kecil", "Modal kas"), 201)
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", petty(yesterday, "OUT", 100_000, "Bensin", "Transport"), 201)
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", petty(TODAY, "OUT", 50_000, "Isolasi", "ATK"), 201)
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", petty(TODAY, "OUT", 25_000, "Kertas", "ATK"), 201)
    report = call(client, headers, "CEO", "GET", f"/cfo/cash/daily-report?day={TODAY}")
    assert (report["opening_balance"], report["total_in"], report["total_out"], report["closing_balance"]) == (400_000, 0, 75_000, 325_000)
    assert report["out_by_category"] == [{"category": "ATK", "amount": 75_000}] and len(report["rows"]) == 2
    listing = call(client, headers, "CFO_MANAGER", "GET", f"/cfo/cash?kind=PETTY&date_from={yesterday}")
    assert [r["balance"] for r in listing["rows"]] == [500_000, 400_000, 350_000, 325_000]
    assert listing["opening_balance"] == 0 and listing["closing_balance"] == 325_000
    assert call(client, headers, "CFO_MANAGER", "GET", f"/cfo/cash?kind=BIG&date_from={yesterday}")["rows"] == []


def test_cash_validation_and_roles(client, headers):
    bad = [{**petty(), "amount": 0}, {**petty(), "amount": -5}, {**petty(), "direction": "SIDEWAYS"}, {**petty(), "kind": "HUGE"},
           {**petty(), "description": ""}, {**petty(TODAY + timedelta(days=30))}]
    for body in bad:
        assert client.post("/api/cfo/cash", headers=headers("CFO_MANAGER"), json=body).status_code == 422, body
    for role in ("CMO_MANAGER", "COO_MANAGER", "CMO_SUPPORT", "PRODUCTION_PIC"):
        call(client, headers, role, "POST", "/cfo/cash", petty(), 403)
        call(client, headers, role, "GET", "/cfo/cash", None, 403)
    call(client, headers, "CEO", "POST", "/cfo/cash", petty(), 403)       # CEO hanya membaca
    call(client, headers, "CEO", "GET", "/cfo/cash")


def test_petty_cash_entries_can_be_deleted_with_audit(client, headers, db):
    row = call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", petty(), 201)
    call(client, headers, "CFO_MANAGER", "DELETE", f"/cfo/cash/{row['id']}")
    assert db.query(CashEntry).count() == 0
    assert db.query(m.AuditLog).filter_by(entity="CashEntry", action="DELETE").count() == 1
    call(client, headers, "CFO_MANAGER", "DELETE", f"/cfo/cash/{row['id']}", None, 404)


def test_big_cash_posts_a_balanced_journal(client, headers, db):
    body = {"kind": "BIG", "entry_date": str(TODAY), "direction": "IN", "category": "Penjualan", "description": "Pelunasan buyer",
            "amount": 12_000_000, "cash_account_code": "1-1100", "counter_account_code": "4-1000"}
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", {**body, "counter_account_code": None}, 422)
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", {**body, "counter_account_code": "1-1100"}, 422)
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", {**body, "cash_account_code": "9-9999"}, 422)
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", {**body, "counter_account_code": "7-0000"}, 422)
    income = call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", body, 201)
    expense = call(client, headers, "CFO_MANAGER", "POST", "/cfo/cash", {**body, "direction": "OUT", "description": "Bayar sewa",
                   "amount": 3_000_000, "counter_account_code": "6-2000", "cash_account_code": "1-1000"}, 201)
    for row, debit, credit, amount in ((income, "1-1100", "4-1000", 12_000_000), (expense, "6-2000", "1-1000", 3_000_000)):
        entry = db.get(JournalEntry, row["journal_entry_id"])
        assert entry.status == "POSTED" and entry.source_ref == f"KAS:{row['id']}" and entry.entry_source == "AUTO"
        lines = db.query(JournalLine).filter_by(entry_id=entry.id).order_by(JournalLine.line_no).all()
        assert len(lines) == 2 and float(lines[0].debit) == amount and float(lines[1].credit) == amount
    call(client, headers, "CFO_MANAGER", "DELETE", f"/cfo/cash/{income['id']}", None, 409)
    big = call(client, headers, "CEO", "GET", f"/cfo/cash?kind=BIG&date_from={TODAY}")
    assert big["total_in"] == 12_000_000 and big["total_out"] == 3_000_000 and big["closing_balance"] == 9_000_000


# ───────────────────────────── karyawan harian & hasil produksi ─────────────────────────────

def make_worker(client, headers, name="Asep", process="sewing", rate=1500):
    return call(client, headers, "CFO_MANAGER", "POST", "/cfo/workers", {"name": name, "process": process, "rate_per_pcs": rate}, 201)


def test_worker_master_and_production_results(client, headers, db):
    asep = make_worker(client, headers)
    assert asep["process"] == "SEWING" and asep["rate_per_pcs"] == 1500
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/workers", {"name": "ASEP"}, 409)
    budi = make_worker(client, headers, "Budi", "cutting", 800)
    order = m.Order(order_id="SYM-2610-001", buyer="Kyan", order_type=m.OrderType.REPEAT_PRODUCTION)
    order.articles.append(m.Article(article_code="A", qty=100))
    db.add(order)
    db.commit()
    first = call(client, headers, "CFO_MANAGER", "POST", "/cfo/production-results",
                 {"result_date": str(TODAY), "worker_fk": asep["id"], "process": "sewing", "qty": 120, "order_id": "sym-2610-001"}, 201)
    assert first["amount"] == 180_000 and first["rate"] == 1500 and first["order_id"] == "SYM-2610-001" and first["process"] == "SEWING"
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/production-results",
         {"result_date": str(TODAY), "worker_fk": asep["id"], "process": "SEWING", "qty": 10, "rate": 2000}, 201)
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/production-results",
         {"result_date": str(TODAY - timedelta(days=1)), "worker_fk": budi["id"], "process": "CUTTING", "qty": 300}, 201)
    for bad in ({"qty": 0}, {"qty": -4}, {"process": ""}, {"order_id": "SYM-9999-001"}, {"worker_fk": 9999}, {"result_date": str(TODAY + timedelta(days=9))}):
        body = {"result_date": str(TODAY), "worker_fk": asep["id"], "process": "SEWING", "qty": 5, **bad}
        assert client.post("/api/cfo/production-results", headers=headers("CFO_MANAGER"), json=body).status_code in (422,), bad
    data = call(client, headers, "CEO", "GET", f"/cfo/production-results?date_from={TODAY - timedelta(days=3)}")
    assert data["totals"] == {"qty": 430, "amount": 180_000 + 20_000 + 240_000}
    assert [w["worker"] for w in data["by_worker"]] == ["Budi", "Asep"] or data["by_worker"][0]["amount"] >= data["by_worker"][1]["amount"]
    assert {d["date"]: d["qty"] for d in data["by_day"]} == {str(TODAY): 130, str(TODAY - timedelta(days=1)): 300}
    only = call(client, headers, "CFO_MANAGER", "GET", f"/cfo/production-results?worker_fk={budi['id']}")
    assert only["totals"]["qty"] == 300
    call(client, headers, "CFO_MANAGER", "PATCH", f"/cfo/workers/{asep['id']}", {"is_active": False})
    call(client, headers, "CFO_MANAGER", "POST", "/cfo/production-results",
         {"result_date": str(TODAY), "worker_fk": asep["id"], "process": "SEWING", "qty": 5}, 422)
    assert [w["name"] for w in call(client, headers, "CFO_MANAGER", "GET", "/cfo/workers?active_only=true")] == ["Budi"]
    call(client, headers, "CFO_MANAGER", "DELETE", f"/cfo/production-results/{first['id']}")
    assert db.query(ProductionResult).count() == 2
    for role in ("COO_MANAGER", "CMO_SUPPORT"):
        call(client, headers, role, "POST", "/cfo/workers", {"name": "X"}, 403)
        call(client, headers, role, "GET", "/cfo/production-results", None, 403)


# ───────────────────────────── bahan, stok, COGS ─────────────────────────────

def seed_materials(db):
    supplier = Supplier(code="SUP-1", name="Toko Kain Jaya")
    location = InventoryLocation(code="GD-1", name="Gudang Kain")
    kain = Material(code="KAIN-16S", name="Cotton 16S", category="KAIN", unit="kg", standard_cost=90_000, reorder_point=50)
    benang = Material(code="BNG-1", name="Benang Hitam", category="BENANG", unit="cone", standard_cost=12_000, reorder_point=5)
    label = Material(code="LBL-1", name="Label Leher", category="AKSESORIS", unit="pcs", standard_cost=500, reorder_point=100)
    pack = Material(code="OPP-1", name="Plastik OPP", category="KEMASAN", unit="pcs", standard_cost=300, reorder_point=0)
    db.add_all([supplier, location, kain, benang, label, pack])
    db.flush()
    gr = GoodsReceipt(gr_no="GR-1", supplier_id=supplier.id, received_date=TODAY - timedelta(days=2), status="POSTED")
    db.add(gr)
    db.flush()
    db.add(GoodsReceiptLine(receipt_id=gr.id, material_id=kain.id, location_id=location.id, qty_ordered=100, qty_received=80,
                            qty_rejected=2, unit_cost=95_000))
    db.add(GoodsReceiptLine(receipt_id=gr.id, material_id=benang.id, location_id=location.id, qty_ordered=10, qty_received=10, unit_cost=12_500))
    draft = GoodsReceipt(gr_no="GR-2", supplier_id=supplier.id, received_date=TODAY, status="DRAFT")
    db.add(draft)
    db.flush()
    db.add(GoodsReceiptLine(receipt_id=draft.id, material_id=kain.id, location_id=location.id, qty_received=500, unit_cost=1))
    for mat, qty in ((kain, 40), (benang, 20), (label, 1000), (pack, 2000)):
        db.add(StockMovement(material_id=mat.id, location_id=location.id, movement_type="RECEIPT", qty=qty))
    db.add(StockMovement(material_id=kain.id, location_id=location.id, movement_type="ISSUE", qty=5))
    db.commit()


def test_material_purchases_only_count_posted_receipts_by_category(client, headers, db):
    seed_materials(db)
    data = call(client, headers, "CFO_MANAGER", "GET", "/cfo/material-purchases")
    assert data["category"] == "KAIN" and data["total_amount"] == 80 * 95_000 and len(data["rows"]) == 1
    row = data["rows"][0]
    assert (row["gr_no"], row["supplier"], row["material"], row["qty"], row["rejected"], row["unit_cost"]) == ("GR-1", "Toko Kain Jaya", "Cotton 16S", 80, 2, 95_000)
    assert data["weekly"][0]["amount"] == 7_600_000
    thread = call(client, headers, "CEO", "GET", "/cfo/material-purchases?category=benang")
    assert thread["total_amount"] == 125_000 and thread["rows"][0]["material"] == "Benang Hitam"
    assert call(client, headers, "CFO_MANAGER", "GET", f"/cfo/material-purchases?date_from={TODAY}")["rows"] == []


def test_stock_summary_groups_fabric_thread_and_accessories_with_value(client, headers, db):
    seed_materials(db)
    data = call(client, headers, "CFO_MANAGER", "GET", "/cfo/stock-summary")
    groups = {g["group"]: g for g in data["groups"]}
    assert set(groups) == {"KAIN", "BENANG", "AKSESORIS"}
    fabric = groups["KAIN"]["items"][0]
    assert fabric["qty"] == 35 and fabric["value"] == 35 * 90_000 and fabric["below_reorder"] is True and groups["KAIN"]["below_reorder"] == 1
    assert groups["BENANG"]["total_value"] == 20 * 12_000
    assert groups["AKSESORIS"]["item_count"] == 2 and groups["AKSESORIS"]["total_value"] == 1000 * 500 + 2000 * 300
    assert data["total_value"] == 35 * 90_000 + 240_000 + 1_100_000
    call(client, headers, "COO_MANAGER", "GET", "/cfo/stock-summary", None, 403)


def test_cfo_can_now_record_stock_movements(client, headers, db):
    seed_materials(db)
    material = db.query(Material).filter_by(code="KAIN-16S").one()
    location = db.query(InventoryLocation).one()
    body = {"material_id": material.id, "location_id": location.id, "movement_type": "ADJUSTMENT_IN", "qty": 5, "reason": "Opname kain"}
    response = client.post("/api/inventory/movements", headers=headers("CFO_MANAGER"), json=body)
    assert response.status_code == 201, response.text


def test_weekly_cogs_adds_material_conversion_and_wages(client, headers, db):
    order = m.Order(order_id="SYM-2610-001", buyer="Kyan", order_type=m.OrderType.REPEAT_PRODUCTION)
    article = m.Article(article_code="A", qty=100)
    order.articles.append(article)
    db.add(order)
    db.flush()
    bom = m.BOMItem(article_id=article.id, material_name="Cotton", unit="kg", qty_per_unit=1, planned_unit_cost=90_000)
    db.add(bom)
    db.flush()
    db.add(m.MaterialConsumption(bom_item_id=bom.id, qty=10, actual_unit_cost=5_000, evidence_ref="nota", recorded_by_id=1))
    db.add(m.ProductionCostEntry(article_id=article.id, category="LABOR", amount=20_000, evidence_ref="slip", recorded_by_id=1))
    db.commit()
    asep = make_worker(client, headers, rate=1000)
    for process, qty in (("SEWING", 100), ("PACKING", 100)):
        call(client, headers, "CFO_MANAGER", "POST", "/cfo/production-results",
             {"result_date": str(TODAY), "worker_fk": asep["id"], "process": process, "qty": qty}, 201)
    data = call(client, headers, "CEO", "GET", "/cfo/cogs-weekly?weeks=3")
    assert len(data["rows"]) == 3 and data["rows"][0]["week_start"] > data["rows"][1]["week_start"]
    current = data["rows"][0]
    assert (current["material"], current["conversion"], current["wages"]) == (50_000, 20_000, 200_000)
    assert current["total_cogs"] == 270_000 and current["output_pcs"] == 100 and current["cogs_per_pcs"] == 2700
    assert data["rows"][1]["cogs_per_pcs"] is None and data["rows"][1]["total_cogs"] == 0
    call(client, headers, "CFO_MANAGER", "GET", "/cfo/cogs-weekly?weeks=0", None, 422)
    call(client, headers, "COO_MANAGER", "GET", "/cfo/cogs-weekly", None, 403)


def test_workspace_lists_every_cfo_task_and_links_exist(client, headers):
    data = call(client, headers, "CFO_MANAGER", "GET", "/cfo/workspace")
    keys = [t["key"] for t in data["tasks"]]
    assert len(keys) == 15 and len(set(keys)) == 15
    for needed in ("invoice", "production-results", "fabric-purchases", "cogs", "petty-cash", "receivables", "price-calculator",
                   "workers", "stock-fabric", "stock-thread", "stock-accessories", "big-cash", "income-statement", "balance-sheet", "cash-flow"):
        assert needed in keys, needed
    assert all(t["path"].startswith("/") and t["metric"] for t in data["tasks"])
    call(client, headers, "CMO_SUPPORT", "GET", "/cfo/workspace", None, 403)
