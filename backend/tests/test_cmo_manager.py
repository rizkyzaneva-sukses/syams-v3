"""CMO Manager — Morning Priority (revisi #13 / #14 poin 2).

Uji endpoint baca `GET /cmo/manager-priority`: antrean action-first yang merakit
prioritas artikel, kapasitas, bottleneck, SLA, PO/draft order, quotation, sample
decision, SPK siap Release to COO, exception, owner, due, evidence/gate dan
handoff berikutnya — dari tabel yang sudah ada, tanpa tabel baru.

Karena orkestrator belum mendaftarkan router ini di `app/main.py` (lihat
REQUESTS/cmo_manager.md), tes ini mendaftarkannya sendiri lewat
`app.include_router(router, prefix='/api')`.
"""
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from app import models as m
from app.database import get_db
from app.main import app
from app.routers.cmo_manager import router as cmo_manager_router

# Daftarkan sekali saja (idempoten) supaya tes bisa jalan sebelum orkestrator
# menambahkan router ini ke main.py.
app.include_router(cmo_manager_router, prefix="/api")

PATH = "/api/cmo/manager-priority"


def get(client, headers, role, path=PATH, expected=200):
    response = client.get(path, headers=headers(role))
    assert response.status_code == expected, response.text
    return response.json() if response.content else None


def queue(data, key):
    for section in data["queues"]:
        if section["key"] == key:
            return section
    raise AssertionError(f"seksi {key} tidak ada di antrean: {[q['key'] for q in data['queues']]}")


def seed(db, users):
    """Satu Order lengkap dengan PO, quotation, sample, SPK, exception, kapasitas."""
    today = date.today()
    order = m.Order(
        order_id="SO-MP-0001", buyer="Buyer Morning", customer_id=None,
        order_type=m.OrderType.SAMPLE_PRODUCTION, order_date=today,
        buyer_deadline=today + timedelta(days=2),  # due 3 hari → SLA ketat
        finance_gate_status="PENDING", overall_status="NEW", flow_step="ORDER",
        created_by_id=users[m.Role.CMO_SUPPORT].id,
    )
    order.articles = [m.Article(article_code="MP-TEE-01", garment_type="tshirt",
                                qty=300, sample_required=True, sample_status="PROCESS")]
    db.add(order)
    db.flush()

    po = m.POIntake(po_number="PO-MP-1", buyer="Buyer Morning",
                    order_type="SAMPLE_PRODUCTION", buyer_deadline=today - timedelta(days=1),
                    articles_json="[{\"article_code\": \"MP-TEE-01\", \"qty\": 300}]",
                    status="SUBMITTED", currency="IDR",
                    missing_items_json="[\"Dokumen PO (PDF/JPG/PNG)\"]",
                    created_by_id=users[m.Role.CMO_SUPPORT].id)
    quote = m.Quotation(order_fk=order.id, quotation_no="QT-MP-1", amount=25000000,
                        hpp_total=19000000, margin_amount=6000000, margin_percent=24.0,
                        status="DRAFT", valid_until=today + timedelta(days=5),
                        currency="IDR", created_at=datetime.utcnow())
    sample = m.SampleRecord(order_fk=order.id, article_code="MP-TEE-01", status="PROCESS",
                            requested_date=today, created_at=datetime.utcnow())
    db.add_all([po, quote, sample])
    db.flush()
    # SPK masih di tangan Deby (Generate/Print) → belum siap Release.
    spk_draft = m.SPK(order_fk=order.id, spk_no="SPK-MP-1", status="DRAFT", version=1)
    # SPK sudah di-Print → siap CMO SPK Release (handoff Release to COO).
    spk_ready = m.SPK(order_fk=order.id, spk_no="SPK-MP-2", status="PRINTED", version=2)
    db.add_all([spk_draft, spk_ready])

    # Exception komersial (milik CMO) vs exception produksi (milik COO) → harus dibuang.
    db.add_all([
        m.ExceptionItem(order_fk=order.id, severity="RED", category="Customer Quotation",
                        title="Buyer menuntut harga", owner_role="CMO_MANAGER",
                        due_date=today - timedelta(days=1), next_action="Putuskan diskon",
                        source_module="Quotation", evidence_ref="email-buyer.pdf", status="OPEN"),
        m.ExceptionItem(order_fk=order.id, severity="RED", category="Production Capacity",
                        title="Mesin cutting penuh", owner_role="COO_MANAGER",
                        due_date=today, status="OPEN"),
    ])
    db.add(m.CapacitySnapshot(snapshot_date=today - timedelta(days=1), process="Cutting",
                              capacity=100, planned_load=130, current_wip=12))
    db.add(m.CapacitySnapshot(snapshot_date=today - timedelta(days=1), process="Packing",
                              capacity=200, planned_load=40, current_wip=3))
    db.add(m.ProductionPlan(order_fk=order.id, plan_date=today + timedelta(days=3),
                            status="APPROVED", notes="Batch tunggal",
                            created_by_id=users[m.Role.COO_MANAGER].id))
    db.commit()
    return order, po, quote, sample, spk_ready, spk_draft


def test_morning_priority_contract_and_order_links(client, headers, users, db):
    """Semua seksi blueprint hadir, setiap baris bisa membuka Order terkait."""
    order, po, quote, sample, spk_ready, spk_draft = seed(db, users)
    data = get(client, headers, "CMO_MANAGER")

    keys = [q["key"] for q in data["queues"]]
    for expected in ("ARTICLE_PRIORITY", "PO_REVIEW", "QUOTATION_APPROVAL",
                     "SAMPLE_DECISION", "SPK_RELEASE", "EXCEPTION_CENTER", "NEXT_HANDOFF"):
        assert expected in keys, keys

    # Kolom wajib antrean keputusan (revisi #13 poin 3) ada di setiap baris.
    required = {"task_id", "decision_type", "order_id", "order_fk", "buyer", "article_code",
                "status", "gate", "evidence", "next_action", "owner", "due", "sla",
                "handoff", "updated_at", "severity", "order_link"}
    for section in data["queues"]:
        assert section["label"] and section["owner"] and section["handoff"]
        for row in section["rows"]:
            assert required <= set(row), (section["key"], sorted(required - set(row)))
            # Setiap baris punya jalan keluar: Order terkait ATAU dokumen sumbernya.
            assert row["order_link"] or row["open_target"], row
            if row["order_link"]:
                assert row["order_link"] == "/orders/SO-MP-0001"
                assert row["order_fk"] == order.id

    # PO menunggu review: gate melaporkan kekurangan dokumen (evidence/gate).
    po_rows = queue(data, "PO_REVIEW")["rows"]
    assert [r["task_id"] for r in po_rows] == [f"PO-{po.id}"]
    assert po_rows[0]["order_link"] is None            # Order belum dibuat
    assert po_rows[0]["source_link"] == f"/cmo/po-inbox/{po.id}/edit"
    assert "Dokumen PO" in po_rows[0]["gate"]
    assert po_rows[0]["due"] == str(date.today() - timedelta(days=1))
    assert po_rows[0]["sla"] == "OVERDUE" and po_rows[0]["severity"] == "RED"

    # Quotation menunggu approval: margin tampil, HPP tidak diubah CMO.
    assert [r["task_id"] for r in queue(data, "QUOTATION_APPROVAL")["rows"]] == [f"QUO-{quote.id}"]

    # Sample decision: gate menyebut bukti yang belum ada.
    sample_row = queue(data, "SAMPLE_DECISION")["rows"][0]
    assert sample_row["task_id"] == f"SMP-{sample.id}"
    assert sample_row["article_code"] == "MP-TEE-01"
    assert "Bukti belum ada" in sample_row["gate"]

    # SPK: yang siap Release masuk antrean, yang masih DRAFT tidak diklaim siap.
    spk_rows = queue(data, "SPK_RELEASE")["rows"]
    ready = [r for r in spk_rows if r["task_id"] == f"SPK-{spk_ready.id}"][0]
    assert ready["gate"] == "Siap Release"
    assert "Release to COO" in ready["handoff"] and "Batch Release" in ready["handoff"]
    draft = [r for r in spk_rows if r["task_id"] == f"SPK-{spk_draft.id}"][0]
    assert "Prasyarat kurang" in draft["gate"]
    assert "finance gate PENDING" in draft["gate"]

    # Exception: hanya komersial/customer yang muncul (produksi milik COO).
    exc_rows = queue(data, "EXCEPTION_CENTER")["rows"]
    assert len(exc_rows) == 1
    assert exc_rows[0]["gate"].startswith("RED · Customer Quotation")
    assert exc_rows[0]["evidence"] == "email-buyer.pdf"
    assert all("Production" not in (r["gate"] or "") for r in exc_rows)

    # Handoff berikutnya: Batch Release/COO ditandai bukan kewenangan CMO.
    handoffs = queue(data, "NEXT_HANDOFF")["rows"]
    assert any(r["decision_type"] == "HANDOFF_COO_BATCH_RELEASE" for r in handoffs)
    assert all(r["owner"] != "CMO_MANAGER"
               for r in handoffs if r["decision_type"] == "HANDOFF_COO_BATCH_RELEASE")


def test_morning_priority_capacity_bottleneck_and_sla_summary(client, headers, users, db):
    """Kapasitas, bottleneck, dan ringkasan SLA dihitung dari data tersimpan."""
    order, po, _quote, _sample, _ready, _draft = seed(db, users)
    exc = (db.query(m.ExceptionItem)
           .filter(m.ExceptionItem.category == "Customer Quotation").one())
    data = get(client, headers, "CMO_MANAGER")

    capacity = data["capacity"]
    assert capacity["total_capacity"] == 300          # 100 Cutting + 200 Packing
    assert capacity["total_planned_load"] == 170
    assert capacity["utilization_percent"] == 56.67
    cutting = [p for p in capacity["processes"] if p["process"] == "Cutting"][0]
    assert cutting["bottleneck"] is True and cutting["overload_qty"] == 30
    assert data["bottleneck"]["processes"] == ["Cutting"]      # daftar nama proses
    assert data["bottleneck"]["count"] == 1
    assert "Cutting kelebihan 30" in data["bottleneck"]["detail"]

    # Prioritas artikel: deadline buyer 2 hari lagi → KRITIS/tinggi, plus Demand Gap.
    article_row = queue(data, "ARTICLE_PRIORITY")["rows"][0]
    assert article_row["order_id"] == order.order_id
    assert article_row["priority_label"] in ("KRITIS", "TINGGI")
    assert article_row["total_qty"] == 300
    assert "Sample artikel tertahan" in article_row["gate"]

    # Ringkasan SLA: PO lewat deadline dan exception lewat due ikut terhitung,
    # tanpa menarik exception produksi ke antrean CMO.
    assert data["summary"]["overdue"] >= 2
    overdue = data["summary"]["overdue_tasks"]
    assert f"PO-{po.id}" in overdue and f"EXC-{exc.id}" in overdue
    assert not any(t.startswith("SHIPEXC") for t in overdue)
    assert data["master_control"]["mode"] == "read_only"
    assert "CMO SPK Release" in data["authority"]["held"]


def test_morning_priority_permission_is_enforced_in_api(client, headers, users, db):
    """Batas kewenangan ditegakkan di server, bukan hanya UI (revisi #14 poin 9)."""
    seed(db, users)
    for role in ("CFO_MANAGER", "COO_MANAGER", "CHRO_MANAGER", "PRODUCTION_PIC", "FINANCE_SUPPORT"):
        get(client, headers, role, expected=403)
    for role in ("CMO_MANAGER", "CMO_SUPPORT", "CEO"):
        data = get(client, headers, role)
        assert data["role"] == role
        assert data["total_actions"] == sum(
            len(q["rows"]) for q in data["queues"] if q["key"] not in ("ARTICLE_PRIORITY", "NEXT_HANDOFF"))


def test_morning_priority_is_read_only_no_new_tables(client, headers, users, db):
    """GET tidak menulis apa pun dan tidak memakai tabel di luar skema yang ada."""
    order, *_ = seed(db, users)
    before = (db.query(m.POIntake).count(), db.query(m.Quotation).count(),
              db.query(m.SPK).count(), db.query(m.ExceptionItem).count(),
              db.query(m.Order).count(), db.query(m.SampleRecord).count())
    get(client, headers, "CMO_MANAGER")
    after = (db.query(m.POIntake).count(), db.query(m.Quotation).count(),
             db.query(m.SPK).count(), db.query(m.ExceptionItem).count(),
             db.query(m.Order).count(), db.query(m.SampleRecord).count())
    assert before == after
    assert set(m.Base.metadata.tables) >= {
        "orders", "articles", "po_intakes", "quotations", "sample_records",
        "spks", "exceptions", "capacity_snapshots", "production_plans",
        "shipment_exceptions",
    }


def test_morning_priority_empty_database_still_answers(client, headers):
    """Tanpa data, antrean tetap berbentuk benar (tidak 500)."""
    data = get(client, headers, "CMO_MANAGER")
    assert [q["key"] for q in data["queues"]] == [
        "PO_REVIEW", "QUOTATION_APPROVAL", "SAMPLE_DECISION", "SPK_RELEASE",
        "EXCEPTION_CENTER", "ARTICLE_PRIORITY", "NEXT_HANDOFF"]
    assert data["total_actions"] == 0
    assert data["capacity"]["processes"] == []
    assert "Belum ada data kapasitas" in data["bottleneck"]["detail"]
