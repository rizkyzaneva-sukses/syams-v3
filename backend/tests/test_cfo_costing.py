"""Tests for CFO Actual Cost vs HPP & Operational Cost — revisi #21 & #24.

The router is not yet registered in ``app/main.py`` (the orchestrator owns that
file), so these tests mount it themselves on a throwaway FastAPI app and prove
the endpoints work end to end with the real dependency wiring.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import models as m
from app.database import get_db
from app.routers.cfo_costing import classify_category, router as costing_router


@pytest.fixture
def costing_client(db: Session):
    """Throwaway app with only the costing router mounted, bound to the test db."""
    def isolated_db():
        try:
            yield db
        except Exception:
            db.rollback()
            raise

    app = FastAPI()
    app.include_router(costing_router, prefix="/api")
    app.dependency_overrides[get_db] = isolated_db
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()


def _make_order(db, buyer="Buyer A", qty=100, unit_hpp="100000", hpp_total="10000000",
                amount="14000000", with_quote=True, breakdown_article=True):
    order = m.Order(order_id=f"SO-CFO-{buyer.replace(' ', '')}", buyer=buyer,
                    order_type=m.OrderType.REPEAT_PRODUCTION, order_date=date(2026, 9, 1))
    article = m.Article(article_code=f"ART-{buyer.replace(' ', '')}", qty=qty)
    order.articles.append(article)
    db.add(order)
    db.commit()
    if with_quote:
        breakdown = ('[{"article_id":%d,"article_code":"%s","qty":%d,"unit_price":"140000","unit_hpp":"%s"}]'
                     % (article.id, article.article_code, qty, unit_hpp)) if breakdown_article else '[{"qty":5}]'
        quote = m.Quotation(order_fk=order.id, quotation_no=f"QT-{order.id}", amount=Decimal(amount),
                            hpp_total=Decimal(hpp_total), margin_amount=Decimal(amount) - Decimal(hpp_total),
                            margin_percent=Decimal("25"), status="APPROVED", pricing_breakdown=breakdown)
        db.add(quote)
        db.commit()
    return order, article


def _add_consumption(db, article, qty="60", unit_cost="30000", planned_qty_per_unit="0.5",
                     planned_unit_cost="25000", evidence="WH-001", user=None):
    item = m.BOMItem(article_id=article.id, material_name="Kain Dryfit", unit="meter",
                     qty_per_unit=Decimal(planned_qty_per_unit), planned_unit_cost=Decimal(planned_unit_cost))
    db.add(item)
    db.commit()
    usage = m.MaterialConsumption(bom_item_id=item.id, qty=Decimal(qty),
                                  actual_unit_cost=Decimal(unit_cost), evidence_ref=evidence,
                                  recorded_by_id=user.id if user else 1)
    db.add(usage)
    db.commit()
    return item, usage


def _add_cost(db, article, category="LABOR", amount="2000000", evidence="PAY-001", user=None):
    entry = m.ProductionCostEntry(article_id=article.id, category=category, amount=Decimal(amount),
                                  evidence_ref=evidence, recorded_by_id=user.id if user else 1)
    db.add(entry)
    db.commit()
    return entry


# --- kontrak: aktual dari fakta nyata, bukan angka quotation -----------------

def test_actual_cost_comes_from_real_usage_not_quotation(costing_client, db, headers, users):
    order, article = _make_order(db, unit_hpp="100000", hpp_total="10000000")
    _add_consumption(db, article, qty="60", unit_cost="30000")
    _add_cost(db, article, category="LABOR", amount="2000000")

    body = costing_client.get("/api/cfo/actual-cost-variance", headers=headers("CFO_MANAGER")).json()
    row = body["orders"][0]

    # 60 x 30000 = 1.800.000 material nyata + 2.000.000 upah = 3.800.000.
    # HPP quotation 100.000 x 100 = 10.000.000 — hanya dipakai sebagai pembanding.
    assert row["quotation_hpp"] == "10000000.00"
    assert row["actual"] == "3800000.00"
    assert row["actual_material_cost"] == "1800000.00"
    assert row["variance"] == "-6200000.00"
    assert row["variance_percent"] == "-62.00"
    assert row["direction"] == "UNDER"
    assert row["has_actual_data"] is True
    assert row["status"] == "OPEN"
    assert body["totals"]["actual_total_cost"] == "3800000.00"
    assert body["totals"]["variance"] == "-6200000.00"


def test_variance_is_over_when_actual_exceeds_quotation(costing_client, db, headers, users):
    order, article = _make_order(db, qty=10, unit_hpp="100000", hpp_total="1000000")
    _add_consumption(db, article, qty="20", unit_cost="40000")
    _add_cost(db, article, category="OVERHEAD", amount="500000")

    row = costing_client.get("/api/cfo/actual-cost-variance", headers=headers("CFO_MANAGER")).json()["orders"][0]
    assert row["actual"] == "1300000.00"          # 800.000 + 500.000
    assert row["variance"] == "300000.00"
    assert row["variance_percent"] == "30.00"
    assert row["direction"] == "OVER"
    assert any("melebihi HPP quotation" in cause["cause"] for cause in row["causes"])


def test_order_without_actual_cost_is_reported_as_no_data(costing_client, db, headers, users):
    _make_order(db, buyer="No Data Buyer")
    body = costing_client.get("/api/cfo/actual-cost-variance", headers=headers("CFO_MANAGER")).json()
    row = body["orders"][0]
    assert row["has_actual_data"] is False
    assert row["status"] == "NO_DATA"
    assert row["actual"] == "0.00"
    assert body["totals"]["orders_without_actual"] == 1


def test_missing_approved_quotation_is_flagged_as_cause(costing_client, db, headers, users):
    order, article = _make_order(db, with_quote=False)
    _add_consumption(db, article)
    row = costing_client.get("/api/cfo/actual-cost-variance", headers=headers("CFO_MANAGER")).json()["orders"][0]
    assert row["quotation_no"] is None
    assert row["hpp_source"] == "unavailable"
    assert any(c["cause"] == "Quotation belum disetujui" for c in row["causes"])


# --- selisih harus bisa ditelusuri sumbernya ---------------------------------

def test_variance_is_traceable_to_evidence_and_source(
        costing_client, db, headers, users, password_hash):
    recorder = m.User(name="COO", email="coo@example.com", password_hash=password_hash,
                      role=m.Role.COO_MANAGER)
    db.add(recorder)
    db.commit()
    order, article = _make_order(db)
    _add_consumption(db, article, qty="60", unit_cost="30000", evidence="WH-77", user=recorder)
    _add_cost(db, article, category="LABOR", amount="2000000", evidence="PAY-77", user=recorder)

    row = costing_client.get("/api/cfo/actual-cost-variance", headers=headers("CFO_MANAGER")).json()["orders"][0]
    art = row["articles"][0]
    sources = {e["source"] for e in art["evidence"]}
    refs = {e["source_ref"] for e in art["evidence"]}

    assert sources == {"material_consumptions", "production_cost_entries"}
    assert refs == {"WH-77", "PAY-77"}
    assert set(row["evidence_refs"]) == {"WH-77", "PAY-77"}
    cause = next(c for c in row["causes"] if "material" in c["cause"].lower())
    assert cause["evidence"] == ["WH-77"]
    assert cause["owner"] == "COO_MANAGER"
    labor_cause = next(c for c in row["causes"] if "Upah" in c["cause"])
    assert labor_cause["evidence"] == ["PAY-77"]
    # Setiap entri bukti membawa nominal supaya angkanya bisa direkonsiliasi.
    material_evidence = next(e for e in art["evidence"] if e["source"] == "material_consumptions")
    assert material_evidence["amount"] == "1800000.00"
    assert material_evidence["qty"] == "60"


def test_waste_and_bom_plan_are_shown_next_to_actual_usage(costing_client, db, headers, users):
    order, article = _make_order(db, qty=100)
    _add_consumption(db, article, qty="60", unit_cost="30000",
                     planned_qty_per_unit="0.5", planned_unit_cost="25000")
    art = costing_client.get("/api/cfo/actual-cost-variance",
                             headers=headers("CFO_MANAGER")).json()["orders"][0]["articles"][0]
    # Rencana BOM 100 x 0.5 x 25000 = 1.250.000; pemakaian nyata 60 m = 1.800.000.
    assert art["planned_material_cost"] == "1250000.00"
    assert art["actual_material_cost"] == "1800000.00"
    # 60 m dipakai vs rencana 50 m -> waste 10 m.
    assert Decimal(art["waste_qty"]) == Decimal("10")
    assert art["material_usage_complete"] is True


def test_incomplete_material_usage_is_a_cause_without_fake_trace(
        costing_client, db, headers, users):
    order, article = _make_order(db)
    # Dua item BOM, hanya satu yang punya pemakaian.
    first, _ = _add_consumption(db, article, evidence="WH-1")
    second = m.BOMItem(article_id=article.id, material_name="Benang", unit="roll",
                       qty_per_unit=Decimal("1"), planned_unit_cost=Decimal("1000"))
    db.add(second)
    db.commit()

    row = costing_client.get("/api/cfo/actual-cost-variance", headers=headers("CFO_MANAGER")).json()["orders"][0]
    assert row["material_usage_complete"] is False
    incomplete = next(c for c in row["causes"] if c["cause"] == "Pemakaian material belum lengkap")
    assert incomplete["traceable"] is False
    assert incomplete["owner"] == "COO_MANAGER"


def test_reviewed_cost_is_locked_and_correction_is_via_version(
        costing_client, db, headers, users):
    order, article = _make_order(db)
    _add_consumption(db, article)
    _add_cost(db, article)
    db.add(m.CostReview(order_fk=order.id, reviewed_total=Decimal("3800000"),
                        evidence_ref="REV-1", reviewed_by_id=1))
    db.commit()

    row = costing_client.get("/api/cfo/actual-cost-variance", headers=headers("CFO_MANAGER")).json()["orders"][0]
    assert row["review"]["reviewed"] is True
    assert row["review"]["status"] == "LOCKED"
    assert row["review"]["matches_actual"] is True
    assert row["status"] == "REVIEWED"
    assert "adjustment/version" in row["articles"][0]["next_action"]


def test_cost_review_mismatch_is_not_treated_as_locked(costing_client, db, headers, users):
    order, article = _make_order(db)
    _add_consumption(db, article)
    db.add(m.CostReview(order_fk=order.id, reviewed_total=Decimal("999"),
                        evidence_ref="REV-OLD", reviewed_by_id=1))
    db.commit()
    row = costing_client.get("/api/cfo/actual-cost-variance", headers=headers("CFO_MANAGER")).json()["orders"][0]
    assert row["review"]["reviewed"] is False
    assert row["review"]["matches_actual"] is False


# --- biaya operasional dipisah dari HPP --------------------------------------

def test_operational_cost_separates_hpp_from_non_hpp(
        costing_client, db, headers, users, password_hash):
    order, article = _make_order(db)
    _add_consumption(db, article, qty="60", unit_cost="30000")
    _add_cost(db, article, category="LABOR", amount="2000000", evidence="PAY-1")
    _add_cost(db, article, category="OPEX_MARKETING", amount="7000000", evidence="MKT-1")
    db.add(m.PurchaseOrder(po_no="PO-CFO-1", order_fk=order.id, item="Kain", qty=60, unit="meter",
                           supplier="Supplier A", amount=Decimal("1800000"), status="RECEIVED"))
    db.commit()

    body = costing_client.get("/api/cfo/operational-cost?period=all",
                              headers=headers("CFO_MANAGER")).json()
    totals = body["totals"]
    assert totals["hpp_material"] == "1800000.00"
    assert totals["hpp_labor_overhead"] == "2000000.00"
    assert totals["hpp_total"] == "3800000.00"
    # OPEX marketing tidak boleh masuk HPP — hanya biaya produksi direct yang masuk.
    assert totals["operational_total"] == "7000000.00"
    assert totals["non_hpp_total"] == "7000000.00"
    assert totals["purchase_orders_not_hpp"] == "1800000.00"
    assert [c["key"] for c in body["hpp_by_category"]] == ["LABOR", "MATERIAL"]
    assert [c["key"] for c in body["operational_by_category"]] == ["OPEX_MARKETING"]
    # Setiap baris ledger menyatakan bucket-nya sendiri.
    buckets = {row["source"]: row["bucket"] for row in body["ledger"]}
    assert buckets["production_cost_entries"] in {"HPP_PRODUCTION", "NON_HPP"}
    assert all(row["bucket"] != "HPP_PRODUCTION" for row in body["ledger"]
               if row["category"] == "OPEX_MARKETING")


def test_unclassified_category_is_never_silently_added_to_hpp(
        costing_client, db, headers, users):
    order, article = _make_order(db)
    _add_cost(db, article, category="MISTERI", amount="500000")
    body = costing_client.get("/api/cfo/operational-cost?period=all",
                              headers=headers("CFO_MANAGER")).json()
    assert body["totals"]["hpp_total"] == "0.00"
    assert body["totals"]["unclassified_total"] == "500000.00"
    assert body["unclassified_entries"][0]["category"] == "MISTERI"
    assert body["classification"][0]["bucket"] == "UNCLASSIFIED"


def test_category_classification_rules():
    assert classify_category("LABOR")[0] == "HPP_PRODUCTION"
    assert classify_category("material")[0] == "HPP_PRODUCTION"
    assert classify_category("OPEX_MARKETING")[0] == "NON_HPP"
    assert classify_category("ASSET_PRINTER")[0] == "NON_HPP"
    assert classify_category("REIMBURSEMENT")[0] == "NON_HPP"
    assert classify_category("SEWA_GUDANG")[0] == "NON_HPP"
    assert classify_category("TAX_PPH")[0] == "NON_HPP"
    unknown_bucket, unknown_value, _ = classify_category("Kategori Baru")
    assert (unknown_bucket, unknown_value) == ("UNCLASSIFIED", "KATEGORI BARU")


def test_operational_cost_groups_by_period(costing_client, db, headers, users):
    order, article = _make_order(db)
    _add_consumption(db, article, qty="60", unit_cost="30000")
    body = costing_client.get("/api/cfo/operational-cost?period=month",
                              headers=headers("CFO_MANAGER")).json()
    today = date.today()
    assert body["period"] == "month"
    assert body["periods"][0]["period"] == f"{today.year}-{today.month:02d}"
    assert body["periods"][0]["hpp_total"] == "1800000.00"

    old = body["periods"][0]["period"]
    body_quarter = costing_client.get("/api/cfo/operational-cost?period=quarter",
                                      headers=headers("CFO_MANAGER")).json()
    quarter = f"{today.year}-Q{(today.month - 1) // 3 + 1}"
    assert body_quarter["periods"][0]["period"] == quarter
    assert body_quarter["periods"][0]["period"] != old or quarter == old


def test_operational_cost_outside_window_is_excluded_and_register_is_flagged(
        costing_client, db, headers, users):
    order, article = _make_order(db)
    _add_consumption(db, article, qty="60", unit_cost="30000")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    future = (date.today() + timedelta(days=1)).isoformat()

    inside = costing_client.get(
        f"/api/cfo/operational-cost?period=all&date_from={yesterday}&date_to={future}",
        headers=headers("CFO_MANAGER")).json()
    assert inside["totals"]["hpp_total"] == "1800000.00"

    stale = costing_client.get(
        f"/api/cfo/operational-cost?period=all&date_from={future}",
        headers=headers("CFO_MANAGER")).json()
    assert stale["totals"]["hpp_total"] == "0.00"
    assert stale["periods"] == []

    register = inside["operational_cost_register"]
    assert register["table"] == "operational_cost_entries"
    assert register["request_ref"] == "REQUESTS/cfo_costing.md"
    assert isinstance(register["entries"], list)
    if not register["available"]:
        # Tabel belum ada di models.py: struktur kosong yang tetap valid.
        assert register["entries"] == []
        assert register["required"] is True
        assert "cost_center" in register["fields_supported"]


def test_month_window_defaults_to_current_month(costing_client, db, headers, users):
    order, article = _make_order(db)
    _add_consumption(db, article, qty="60", unit_cost="30000")
    old = m.ProductionCostEntry(article_id=article.id, category="LABOR", amount=Decimal("999"),
                                evidence_ref="PAY-OLD", recorded_by_id=1,
                                created_at=datetime.utcnow() - timedelta(days=70))
    db.add(old)
    db.commit()
    body = costing_client.get("/api/cfo/operational-cost?period=month",
                              headers=headers("CFO_MANAGER")).json()
    assert body["window"]["date_from"] == date.today().replace(day=1).isoformat()
    # Entri 70 hari lalu berada di luar bulan berjalan.
    assert all(row["source_ref"] != "PAY-OLD" for row in body["ledger"])


# --- RBAC --------------------------------------------------------------------

@pytest.mark.parametrize("role", ["COO_MANAGER", "CMO_MANAGER", "CMO_SUPPORT", "CHRO_MANAGER", "HR_SUPPORT"])
def test_operational_roles_cannot_read_cost_reports(costing_client, headers, users, role):
    assert costing_client.get("/api/cfo/actual-cost-variance",
                              headers=headers(role)).status_code == 403
    assert costing_client.get("/api/cfo/operational-cost",
                              headers=headers(role)).status_code == 403


def test_finance_support_can_read_but_not_filter_by_date(costing_client, headers, users):
    assert costing_client.get("/api/cfo/actual-cost-variance",
                              headers=headers("FINANCE_SUPPORT")).status_code == 200
    assert costing_client.get("/api/cfo/actual-cost-variance?date_from=2026-01-01",
                              headers=headers("FINANCE_SUPPORT")).status_code == 403
    assert costing_client.get("/api/cfo/operational-cost",
                              headers=headers("FINANCE_SUPPORT")).status_code == 200
    assert costing_client.get("/api/cfo/operational-cost?date_from=2026-01-01",
                              headers=headers("FINANCE_SUPPORT")).status_code == 403


def test_ceo_can_read_and_filter(costing_client, headers, users):
    assert costing_client.get("/api/cfo/actual-cost-variance",
                              headers=headers("CEO")).status_code == 200
    assert costing_client.get("/api/cfo/actual-cost-variance?date_from=2026-01-01&date_to=2026-12-31",
                              headers=headers("CEO")).status_code == 200


def test_unauthenticated_request_is_rejected(costing_client):
    assert costing_client.get("/api/cfo/actual-cost-variance").status_code == 401


# --- endpoint ini read-only --------------------------------------------------

def test_only_get_routes_are_registered():
    methods = {method for route in costing_router.routes for method in route.methods}
    assert methods == {"GET"}
    paths = {route.path for route in costing_router.routes}
    assert paths == {"/cfo/actual-cost-variance", "/cfo/operational-cost"}


def test_status_filter_and_order_scoping(costing_client, db, headers, users):
    over_order, over_article = _make_order(db, buyer="Over Buyer", qty=10, unit_hpp="100000",
                                           hpp_total="1000000")
    _add_consumption(db, over_article, qty="20", unit_cost="40000")
    _add_cost(db, over_article, category="OVERHEAD", amount="500000")
    no_data_order, _ = _make_order(db, buyer="Empty Buyer")

    flt = headers("CFO_MANAGER")
    only_over = costing_client.get("/api/cfo/actual-cost-variance?status=OVER", headers=flt).json()
    assert [row["order_id"] for row in only_over["orders"]] == [over_order.order_id]

    only_empty = costing_client.get("/api/cfo/actual-cost-variance?status=NO_DATA", headers=flt).json()
    assert [row["order_id"] for row in only_empty["orders"]] == [no_data_order.order_id]

    scoped = costing_client.get(f"/api/cfo/actual-cost-variance?order_fk={no_data_order.id}",
                                headers=flt).json()
    assert len(scoped["orders"]) == 1
    assert scoped["orders"][0]["order_fk"] == no_data_order.id

    missing = costing_client.get("/api/cfo/actual-cost-variance?order_fk=999999", headers=flt)
    assert missing.status_code == 404


def test_amounts_are_decimal_strings_not_binary_floats(costing_client, db, headers, users):
    order, article = _make_order(db)
    _add_consumption(db, article, qty="0.1", unit_cost="0.2")
    row = costing_client.get("/api/cfo/actual-cost-variance", headers=headers("CFO_MANAGER")).json()["orders"][0]
    # 0.1 x 0.2 harus 0.02 — bukan 0.020000000000000004.
    assert row["articles"][0]["actual_material_cost"] == "0.02"
