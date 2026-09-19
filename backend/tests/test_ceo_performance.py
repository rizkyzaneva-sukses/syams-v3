"""CEO Company Performance — KPI bertarget, drill-down read-only, closing,
rekonsiliasi, dan override governance (revisi #71 / #74 / #77).

Router belum didaftarkan di app/main.py (itu milik orkestrator), jadi tiap
modul tes memasangnya sendiri — pola yang sama dengan test_coo_execution.py.
"""
from datetime import date, timedelta

import pytest

from app import models as m


@pytest.fixture(autouse=True)
def mount_routers():
    from app.main import app
    from app.routers.ceo_performance import router as perf

    if not any(getattr(r, "path", "") == "/api/ceo/company-performance" for r in app.routes):
        app.include_router(perf, prefix="/api")
    yield


def make_order(db, number, buyer="Buyer A", qty=100, status="IN_PROGRESS", deadline=None):
    order = m.Order(order_id=number, buyer=buyer, order_type=m.OrderType.REPEAT_PRODUCTION,
                    overall_status=status, buyer_deadline=deadline)
    db.add(order)
    db.flush()
    article = m.Article(order_fk=order.id, article_code="A-1", qty=qty,
                        production_route="Cutting>Sewing>QC")
    db.add(article)
    db.commit()
    return order, article


def test_endpoints_require_authentication(client):
    assert client.get("/api/ceo/company-performance").status_code == 401
    assert client.get("/api/ceo/drilldown/finance").status_code == 401
    assert client.get("/api/ceo/closing-status").status_code == 401


def test_non_ceo_roles_are_rejected(db, client, headers):
    """Company Performance adalah halaman CEO; divisi lain tidak boleh masuk."""
    for role in ("CMO_MANAGER", "CFO_MANAGER", "COO_MANAGER", "CHRO_MANAGER", "CMO_SUPPORT"):
        response = client.get("/api/ceo/company-performance", headers=headers(role))
        assert response.status_code == 403, role


def test_every_kpi_carries_id_period_target_source_and_cutoff(db, client, headers):
    """Revisi #71: KPI tanpa provenance adalah bug, bukan angka yang boleh tampil."""
    make_order(db, "SO-KPI-1")
    body = client.get("/api/ceo/company-performance", headers=headers("CEO")).json()

    assert body["read_only"] is True
    assert body["allowed_actions"] == ["VIEW_DRILLDOWN", "DECIDE", "OVERRIDE"]
    assert body["period"]["as_of"] == date.today().isoformat()
    assert body["period"]["month"] == date.today().strftime("%Y-%m")
    assert body["calculated_at"]
    assert body["kpis"], "harus ada KPI"

    for kpi in body["kpis"]:
        assert kpi["kpi_id"], kpi
        assert kpi["source_module"], kpi["kpi_id"]
        assert kpi["owner"], kpi["kpi_id"]
        assert kpi["period"]["as_of"]
        assert kpi["calculated_at"]
        assert kpi["status"] in ("GREEN", "YELLOW", "RED", "MISSING", "NOT_APPLICABLE")
        assert kpi["data_state"] in ("VALUE", "ZERO", "MISSING", "NOT_APPLICABLE")
        assert "target" in kpi and "variance" in kpi and "numerator" in kpi
        assert kpi["drilldown"], kpi["kpi_id"]

    ids = {k["kpi_id"] for k in body["kpis"]}
    assert "CEO-KPI-AR-OVERDUE" in ids
    assert "CEO-KPI-ON-TIME" in ids
    assert "CEO-KPI-PEOPLE-ACTIVE" in ids


def test_kpi_denominator_and_variance_are_real_numbers(db, client, headers):
    """On-time % harus punya numerator/denominator nyata, bukan persen hampa."""
    order, _ = make_order(db, "SO-KPI-2", deadline=date.today())
    db.add(m.Shipment(order_fk=order.id, shipment_no="SHP-1", status="DELIVERED",
                      shipped_date=date.today(), finance_gate="CLEAR"))
    db.commit()

    body = client.get("/api/ceo/company-performance", headers=headers("CEO")).json()
    on_time = next(k for k in body["kpis"] if k["kpi_id"] == "CEO-KPI-ON-TIME")
    assert on_time["denominator"] == 1
    assert on_time["numerator"] == 1
    assert on_time["value"] == 100.0
    assert on_time["status"] == "GREEN"
    # Target 95% tercapai -> variance positif dan angkanya nyata.
    assert on_time["target"] == 95.0
    assert on_time["variance"] == pytest.approx(5.0)


def test_missing_data_is_not_reported_as_zero(db, client, headers):
    """Revisi #71: 'belum ada data' tidak boleh tampil sebagai 0.

    Tanpa satu pun baris QC, persentase lulus tidak punya pembagi: statusnya
    MISSING dengan nilai None, bukan 0% yang menyesatkan.
    """
    body = client.get("/api/ceo/company-performance", headers=headers("CEO")).json()
    qc = next(k for k in body["kpis"] if k["kpi_id"] == "CEO-KPI-QC-PASS")
    assert qc["value"] is None
    assert qc["status"] == "MISSING"
    assert qc["data_state"] == "MISSING"
    assert qc["denominator"] == 0

    health = body["health"]
    assert health["missing"] >= 1
    assert "CEO-KPI-QC-PASS" in health["missing_ids"]


def test_zero_and_missing_are_different_states(db, client, headers):
    """AR lewat jatuh tempo tanpa invoice = nol nyata (bukan missing)."""
    order, _ = make_order(db, "SO-KPI-3")
    db.add(m.Invoice(order_fk=order.id, invoice_no="INV-1", amount=100, paid_amount=100,
                     status="PAID", due_date=date.today() + timedelta(days=5)))
    db.commit()
    body = client.get("/api/ceo/company-performance", headers=headers("CEO")).json()
    ar = next(k for k in body["kpis"] if k["kpi_id"] == "CEO-KPI-AR-OVERDUE")
    assert ar["value"] == 0.0
    assert ar["data_state"] == "ZERO"
    assert ar["status"] == "GREEN"


def test_health_counts_track_the_kpis(db, client, headers):
    order, _ = make_order(db, "SO-KPI-4")
    db.add(m.Invoice(order_fk=order.id, invoice_no="INV-2", amount=5000, paid_amount=0,
                     status="UNPAID", due_date=date.today() - timedelta(days=10)))
    db.commit()
    body = client.get("/api/ceo/company-performance", headers=headers("CEO")).json()
    health = body["health"]
    assert health["red"] == len(health["red_ids"])
    assert health["yellow"] == len(health["yellow_ids"])
    assert health["label"] in ("GREEN", "YELLOW", "RED")
    # Policy AR lewat jatuh tempo punya target 0 -> begitu ada nilai, statusnya RED.
    assert "CEO-KPI-AR-OVERDUE" in health["red_ids"]


def test_seed_and_test_rows_are_separated_from_live_kpi(db, client, headers):
    """Revisi #77: data TEST/UAT tidak boleh ikut KPI produksi."""
    make_order(db, "SO-LIVE-1")
    make_order(db, "SO-TEST-1")
    make_order(db, "UAT-ORDER-9")
    db.commit()

    live = client.get("/api/ceo/company-performance?environment=LIVE",
                      headers=headers("CEO")).json()
    assert live["environment"] == "LIVE"
    assert live["environment_rows"]["TEST"] == 2
    assert live["environment_rows"]["LIVE"] == 1
    count = next(k for k in live["kpis"] if k["kpi_id"] == "CEO-KPI-ORDER-ACTIVE")
    assert count["value"] == 1

    everything = client.get("/api/ceo/company-performance?environment=ALL",
                            headers=headers("CEO")).json()
    all_count = next(k for k in everything["kpis"] if k["kpi_id"] == "CEO-KPI-ORDER-ACTIVE")
    assert all_count["value"] == 3


def test_reconciliation_matches_authoritative_modules(db, client, headers):
    order, _ = make_order(db, "SO-REC-1")
    db.add(m.Invoice(order_fk=order.id, invoice_no="INV-3", amount=1000, paid_amount=400,
                     status="PARTIAL", due_date=date.today() - timedelta(days=1)))
    db.commit()
    body = client.get("/api/ceo/company-performance", headers=headers("CEO")).json()
    rows = {row["check"]: row for row in body["reconciliation"]}
    assert rows["Order aktif"]["match"] is True
    assert rows["Order aktif"]["source_module"] == "Master Control"
    assert rows["Piutang (outstanding)"]["match"] is True
    assert rows["Piutang (outstanding)"]["ceo_value"] == 600.0
    assert all(row["source_module"] for row in body["reconciliation"])


def test_drilldown_finance_is_read_only_and_exposes_source_rows(db, client, headers):
    order, _ = make_order(db, "SO-DR-1")
    db.add(m.Invoice(order_fk=order.id, invoice_no="INV-DR", amount=2000, paid_amount=500,
                     status="PARTIAL", due_date=date.today() - timedelta(days=3)))
    db.commit()
    body = client.get("/api/ceo/drilldown/finance", headers=headers("CEO")).json()
    assert body["read_only"] is True
    assert body["source_module"] == "CFO"
    assert body["rows"][0]["invoice_no"] == "INV-DR"
    assert body["rows"][0]["outstanding"] == 1500.0
    assert body["rows"][0]["days_overdue"] == 3
    assert body["rows"][0]["source_entity"] == "Invoice"
    assert body["totals"]["ar_overdue"] == 1500.0


def test_drilldown_production_surfaces_quantity_identity(db, client, headers):
    order, article = make_order(db, "SO-DR-2")
    db.add(m.ProductionMovement(article_id=article.id, process="Sewing", qty_in=100,
                                qty_done=60, qty_reject=5, target_date=date.today(),
                                status="IN_PROCESS"))
    db.commit()
    body = client.get("/api/ceo/drilldown/production", headers=headers("CEO")).json()
    row = body["rows"][0]
    assert row["qty_wip"] == 35
    assert row["qty_done"] + row["qty_reject"] + row["qty_wip"] == row["qty_in"]
    assert row["is_today"] is True
    assert body["today"]["done_qty"] == 60
    assert body["today"]["target_qty"] == 100


def test_drilldown_sales_and_people(db, client, headers):
    order, _ = make_order(db, "SO-DR-3")
    db.add(m.Quotation(order_fk=order.id, quotation_no="Q-DR-1", amount=1000, margin_amount=200,
                       margin_percent=20, status="APPROVED"))
    db.add(m.Customer(name="Buyer A", country="ID"))
    employee = m.Employee(employee_no="EMP-1", name="Rina", division="Produksi",
                          position="Operator", employment_status="ACTIVE")
    db.add(employee)
    db.flush()
    db.add(m.EmployeeIssue(employee_id=employee.id, issue_type="Disiplin",
                           description="Terlambat", severity="RED", status="OPEN"))
    db.commit()

    sales = client.get("/api/ceo/drilldown/sales", headers=headers("CEO")).json()
    assert sales["read_only"] is True
    assert sales["quotations"][0]["quotation_no"] == "Q-DR-1"
    assert sales["totals"]["revenue"] == 1000.0
    assert sales["totals"]["margin"] == 200.0
    assert sales["totals"]["customers"] == 1

    people = client.get("/api/ceo/drilldown/people", headers=headers("CEO")).json()
    assert people["read_only"] is True
    assert people["employees"][0]["employee_no"] == "EMP-1"
    assert people["totals"]["active_employees"] == 1
    assert people["totals"]["open_issues"] == 1
    assert people["totals"]["escalated_issues"] == 1


def test_unknown_drilldown_domain_is_404(db, client, headers):
    assert client.get("/api/ceo/drilldown/hr-payroll", headers=headers("CEO")).status_code == 404


def test_closing_status_keeps_three_dimensions_separate(db, client, headers):
    """Revisi #77: final close hanya ketika operational+customer+financial lulus."""
    closed, _ = make_order(db, "SO-CLOSE-1")
    closed.operational_close_status = "CLOSED"
    closed.customer_close_status = "CLOSED"
    closed.financial_close_status = "CLOSED"
    open_order, _ = make_order(db, "SO-CLOSE-2")
    db.commit()

    body = client.get("/api/ceo/closing-status", headers=headers("CEO")).json()
    assert body["read_only"] is True
    assert body["operational"]["closed"] == 1 and body["operational"]["open"] == 1
    assert body["customer"]["closed"] == 1 and body["customer"]["open"] == 1
    assert body["financial"]["closed"] == 1 and body["financial"]["open"] == 1
    assert body["final_close_ready"] is False
    assert "BELUM" in body["verdict"]
    assert body["owner_module"] == {"operational": "COO", "customer": "CMO", "financial": "CFO"}

    open_order.operational_close_status = "CLOSED"
    open_order.customer_close_status = "CLOSED"
    open_order.financial_close_status = "CLOSED"
    db.commit()
    ready = client.get("/api/ceo/closing-status", headers=headers("CEO")).json()
    assert ready["final_close_ready"] is True
    assert ready["verdict"] == "FINAL CLOSE SIAP"


def test_closing_is_not_ready_for_an_empty_book(db, client, headers):
    """Tanpa order sama sekali, 'semua lulus' tidak boleh berarti siap."""
    body = client.get("/api/ceo/closing-status", headers=headers("CEO")).json()
    assert body["final_close_ready"] is False


def test_thresholds_are_reported_and_configurable(db, client, headers):
    body = client.get("/api/ceo/company-performance", headers=headers("CEO")).json()
    assert body["thresholds"]["green_at_or_above_percent"] == 100.0
    assert body["thresholds"]["yellow_at_or_above_percent"] == 90.0

    import json
    from datetime import datetime
    db.add(m.SystemConfig(key="business_policy", updated_at=datetime.utcnow(),
                          value=json.dumps({"kpi_thresholds": {"green_at_or_above_percent": 50.0,
                                                               "yellow_at_or_above_percent": 40.0}})))
    db.commit()
    tuned = client.get("/api/ceo/company-performance", headers=headers("CEO")).json()
    assert tuned["thresholds"]["green_at_or_above_percent"] == 50.0
    assert tuned["thresholds"]["yellow_at_or_above_percent"] == 40.0


def test_ceo_cannot_write_operational_entities_through_this_router(db, client, headers):
    """Revisi #74/#77: API RBAC wajib menolak routine writes CEO.

    Router Company Performance hanya GET; tidak ada jalur untuk membuat PO,
    invoice, delivery, atau closing dari halaman CEO.
    """
    from app.routers.ceo_performance import router as perf
    methods = {r.path: getattr(r, "methods", set()) for r in perf.routes}
    for path, verbs in methods.items():
        if path.startswith("/ceo/drilldown") or path in ("/ceo/company-performance", "/ceo/closing-status"):
            assert verbs == {"GET"}, (path, verbs)
    for forbidden in ("/ceo/purchase-orders", "/ceo/invoices", "/ceo/deliveries", "/ceo/closing"):
        assert forbidden not in methods
    assert client.post("/api/ceo/company-performance", headers=headers("CEO")).status_code == 405


def test_non_ceo_gets_403_on_every_read_endpoint(db, client, headers):
    for path in ("/api/ceo/drilldown/finance", "/api/ceo/closing-status"):
        assert client.get(path, headers=headers("CFO_MANAGER")).status_code == 403
