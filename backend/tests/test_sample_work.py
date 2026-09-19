"""Sample PIC work surface tests — revisi #31, #32, #33, #35, #37.

Router didaftarkan di sini (bukan di main.py) supaya tes membuktikan router
jalan tanpa menunggu orkestrator. Semua penulisan di tes ini hanya menyiapkan
data lewat ORM; endpoint sample_work sendiri read-only.
"""
from datetime import date, datetime, timedelta
import json

import pytest
from fastapi.testclient import TestClient

from app import models as m
from app.routers import sample_work

PREFIX = "/sample"


@pytest.fixture
def sample_client(db):
    """TestClient dengan router sample_work terdaftar langsung."""
    from app.main import app
    from app.database import get_db

    def isolated_db():
        try:
            yield db
        except Exception:
            db.rollback()
            raise

    already = getattr(app.state, "_sample_work_registered", False)
    if not already:
        app.include_router(sample_work.router, prefix="/api")
        app.state._sample_work_registered = True
    app.dependency_overrides[get_db] = isolated_db
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()


def make_order(db, number, *, buyer="Buyer Sample", deadline=None, finance="PAID", **kwargs):
    order = m.Order(order_id=number, buyer=buyer, order_type=m.OrderType.SAMPLE_PRODUCTION,
                    finance_status=finance, buyer_deadline=deadline, **kwargs)
    db.add(order)
    db.commit()
    return order


def make_article(db, order, code="ART-1", *, sample_required=True, sample_status="REQUIRED"):
    article = m.Article(order_fk=order.id, article_code=code, qty=100,
                        sample_required=sample_required, sample_status=sample_status)
    db.add(article)
    db.commit()
    return article


def make_sample(db, order, code, *, status="PROCESS", version=None, submitted=None,
                evidence=(), completed=None, notes=None, sample_version=None,
                article_id=None, evidence_kind=None):
    """Sample Request + versi PPM/mockup eligible.

    `sample_version` = kolom eksplisit `sample_records.sample_version`. Bila
    tidak diisi, baris sengaja dibiarkan pada default kolom (1) supaya tes ini
    juga membuktikan tidak ada penomoran ulang dari urutan `id`.
    """
    ppm = version if version is not None else 1
    payload = {"ppm_version": {"version": ppm, "eligible": True,
                               "submitted": bool(submitted)}}
    if submitted is not None and not submitted:
        payload["ppm_version"]["submitted"] = False
    values = dict(order_fk=order.id, article_code=code, status=status,
                  notes=notes if notes is not None else json.dumps(payload),
                  completed_date=completed)
    if article_id is not None:
        values["article_id"] = article_id
    if sample_version is not None:
        values["sample_version"] = sample_version
    sample = m.SampleRecord(**values)
    db.add(sample)
    db.commit()
    for name in evidence:
        db.add(m.SampleEvidence(sample_fk=sample.id, file_name=name, file_mime="application/pdf",
                                file_data=b"%PDF-1.4", uploaded_by_id=1,
                                evidence_kind=evidence_kind))
    db.commit()
    return sample


def evidence_allowed(*names):
    return tuple(names)


# ─────────────────────── batas akses (SMP-F-007 / #37) ───────────────────────
def test_view_is_role_scoped(sample_client, headers):
    assert sample_client.get(f"/api{PREFIX}/today").status_code == 401
    for role in ("SAMPLE_PIC", "CMO_MANAGER", "CEO", "COO_MANAGER"):
        assert sample_client.get(f"/api{PREFIX}/today", headers=headers(role)).status_code == 200
        assert sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers(role)).status_code == 200
    for role in ("CFO_MANAGER", "FINANCE_SUPPORT", "CHRO_MANAGER", "PRODUCTION_PIC",
                 "PRINTING_PIC", "SHIPMENT_ADMIN", "HR_SUPPORT"):
        assert sample_client.get(f"/api{PREFIX}/today", headers=headers(role)).status_code == 403
        assert sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers(role)).status_code == 403


def test_sample_pic_cannot_decide_or_release(sample_client, db, headers):
    """SMP-F-002 (#32): status buyer & aksi lintas divisi ditolak server-side."""
    auth = headers("SAMPLE_PIC")
    # Tidak ada endpoint tulis sama sekali di modul sample work.
    for method in ("post", "put", "patch"):
        for path in (f"/api{PREFIX}/today", f"/api{PREFIX}/my-tasks",
                     f"/api{PREFIX}/today/APPROVED",
                     f"/api{PREFIX}/my-tasks/SMP-1/APPROVE",
                     f"/api{PREFIX}/samples/1/customer-decision"):
            response = getattr(sample_client, method)(path, headers=auth, json={})
            assert response.status_code in (404, 405), (method, path, response.status_code)
    for path in (f"/api{PREFIX}/today", f"/api{PREFIX}/my-tasks/SMP-1"):
        assert sample_client.delete(path, headers=auth).status_code in (404, 405)
    # SPK / Purchase Order / keputusan buyer tetap tertutup untuk Sample PIC.
    assert sample_client.get("/api/cmo/spk", headers=auth).status_code == 403
    assert sample_client.post("/api/cfo/purchase-orders", headers=auth,
                              json={"po_no": "PO-1", "order_fk": 1}).status_code == 403
    assert sample_client.get("/api/cfo/invoices", headers=auth).status_code == 403
    assert sample_client.post("/api/coo/order-closing", headers=auth, json={}).status_code in (403, 405, 422)
    # Rute keputusan buyer menolak Sample PIC walaupun sample-nya sendiri.
    order = make_order(db, "SO-DENY-1")
    make_article(db, order, "ART-DENY")
    sample = make_sample(db, order, "ART-DENY", evidence=("hasil-final.pdf",))
    denied = sample_client.post(f"/api/cmo/samples/{sample.id}/customer-decision",
                               headers=auth, json={"action": "APPROVE", "reason": "saya setuju"})
    assert denied.status_code == 403
    db.refresh(sample)
    assert sample.status == "PROCESS" and sample.customer_approved_by_id is None


def test_buyer_decision_is_readonly_in_payload(sample_client, db, headers):
    """Keputusan buyer tampil sebagai informasi, bukan sebagai aksi Fahrul."""
    order = make_order(db, "SO-BD-1")
    make_article(db, order, "ART-BD")
    sample = make_sample(db, order, "ART-BD", status="APPROVED", evidence=("hasil-final.pdf",),
                         completed=date.today())
    sample.customer_approved_by_id = 1
    sample.customer_decision_at = datetime.utcnow()
    sample.customer_decision_reason = "Buyer setuju"
    db.commit()

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["sample_id"] == sample.id)
    assert row["buyer_decision"]["status"] == "APPROVED"
    assert row["buyer_decision"]["readonly"] is True
    assert row["buyer_decision"]["owner"] == "CMO_MANAGER"
    assert row["buyer_decision"]["reason"] == "Buyer setuju"
    assert set(row["denied_actions"]) >= {"BUYER_APPROVE", "BUYER_REJECT"}
    assert "APPROVED" not in row["allowed_actions"]
    assert row["stage"] == "DONE"
    # Keputusan buyer bukan hanya UI: contract akses pun menyatakannya.
    assert data["access"]["buyer_decision_owner"] == "CMO_MANAGER"
    assert data["access"]["sample_decision_denied"] is True


def test_cmo_manager_keeps_buyer_decision(sample_client, db, headers):
    """Modul sample tidak mengambil alih keputusan buyer dari CMO_MANAGER."""
    order = make_order(db, "SO-BD-2")
    make_article(db, order, "ART-BD2")
    sample = make_sample(db, order, "ART-BD2", evidence=("hasil-final.pdf",))
    response = sample_client.post(f"/api/cmo/samples/{sample.id}/customer-decision",
                                  headers=headers("CMO_MANAGER"),
                                  json={"action": "APPROVE", "reason": "Bukti valid"})
    assert response.status_code == 200
    db.refresh(sample)
    assert sample.status == "APPROVED"
    # Fahrul sendiri tidak boleh memakai rute itu.
    sample2 = make_sample(db, order, "ART-BD3", evidence=("hasil-final.pdf",))
    denied = sample_client.post(f"/api/cmo/samples/{sample2.id}/customer-decision",
                                headers=headers("SAMPLE_PIC"),
                                json={"action": "APPROVE", "reason": "Saya setuju"})
    assert denied.status_code == 403


# ─────────────────── eligibility & auto task (SMP-F-003 / #33) ───────────────────
def test_auto_creates_task_only_when_sample_required(sample_client, db, headers):
    order = make_order(db, "SO-EL-1")
    make_article(db, order, "ART-YES", sample_required=True, sample_status="REQUIRED")
    make_article(db, order, "ART-NO", sample_required=False, sample_status="NOT_REQUIRED")

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    rows = {r["article_code"]: r for r in data["tasks"]}
    assert rows["ART-YES"]["eligible"] is True
    assert rows["ART-YES"]["required_action"] == "CREATE_SAMPLE"
    assert rows["ART-YES"]["sample_id"] is None
    assert "CREATE SAMPLE" in rows["ART-YES"]["eligibility_reason"]
    assert rows["ART-NO"]["eligible"] is False
    assert rows["ART-NO"]["required_action"] is None
    assert "tidak butuh sample" in rows["ART-NO"]["eligibility_reason"]
    # Task otomatis muncul tanpa input ulang CMO.
    assert data["create_sample_tasks"] == 1
    assert any(r["order_id"] == "SO-EL-1" and r["article_code"] == "ART-YES"
               for r in data["tasks"])


def test_article_without_ppm_version_is_ineligible_with_reason(sample_client, db, headers):
    order = make_order(db, "SO-EL-2")
    make_article(db, order, "ART-PPM")
    make_sample(db, order, "ART-PPM", notes="catatan bebas tanpa versi")

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["article_code"] == "ART-PPM")
    assert row["eligible"] is False
    assert "PPM/mockup" in row["eligibility_reason"]
    assert row["blocker_owner"] == "CMO_MANAGER"
    # Order/article tidak eligible tetap ditampilkan (dengan alasan), bukan disembunyikan.
    today = sample_client.get(f"/api{PREFIX}/today", headers=headers("SAMPLE_PIC")).json()
    assert any(r["article_code"] == "ART-PPM" for r in today["not_eligible"])


def test_row_binds_order_article_and_version(sample_client, db, headers):
    order = make_order(db, "SO-EL-3")
    article = make_article(db, order, "ART-V")
    # Versi EKSPLISIT (kolom), bukan turunan urutan id.
    first = make_sample(db, order, "ART-V", version=1, submitted=False,
                        article_id=article.id, sample_version=1)
    second = make_sample(db, order, "ART-V", version=2, submitted=False,
                         article_id=article.id, sample_version=2)

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    rows = [r for r in data["tasks"] if r["article_code"] == "ART-V"]
    assert {r["sample_version"] for r in rows} == {1, 2}
    for row in rows:
        assert row["order_id"] == "SO-EL-3"
        assert row["article_id"] == article.id
        assert row["order_article_id"] == article.id
        assert row["sample_id"] is not None
        # Batch 2: versi dibaca dari kolom, dan sumbernya dilaporkan.
        assert row["sample_version_source"] == "sample_records.sample_version"
    assert data["data_source"]["sources"]["sample_version"] == "sample_records.sample_version"
    assert "version_from_id_order" not in data["data_source"]["heuristics_active"]


def test_explicit_version_wins_over_id_order(sample_client, db, headers):
    """Revisi #34: versi tersimpan, bukan ditebak dari urutan `id`.

    Baris kedua sengaja TIDAK diberi nomor unik — default kolom 1. Kalau
    router masih menomori dari urutan id, ia akan melaporkan 1 dan 2.
    """
    order = make_order(db, "SO-VER-EXPLICIT")
    article = make_article(db, order, "ART-VER")
    make_sample(db, order, "ART-VER", article_id=article.id)          # default → 1
    make_sample(db, order, "ART-VER", article_id=article.id)          # default → 1 juga

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    rows = [r for r in data["tasks"] if r["article_code"] == "ART-VER"]
    assert {r["sample_version"] for r in rows} == {1}, \
        "versi harus dari kolom sample_version, bukan urutan id"
    assert all(r["sample_version_source"] == "sample_records.sample_version" for r in rows)

    # Versi eksplisit 3 → dilaporkan 3 walaupun ia baris pertama artikel ini.
    third = make_sample(db, order, "ART-VER", article_id=article.id, sample_version=3)
    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["sample_id"] == third.id)
    assert row["sample_version"] == 3


# ─────────────────── jenis bukti eksplisit (SMP-F-005 / #35) ───────────────────
def test_evidence_kind_column_classifies_unnamed_files(sample_client, db, headers):
    """`IMG_2231.pdf` gagal ditebak dari nama; kolom `evidence_kind` menyelesaikannya."""
    order = make_order(db, "SO-EK-1")
    article = make_article(db, order, "ART-EK")
    sample = make_sample(db, order, "ART-EK", article_id=article.id, submitted=True)
    db.add_all([
        m.SampleEvidence(sample_fk=sample.id, file_name="IMG_2231.pdf",
                         file_mime="application/pdf", file_data=b"%PDF-1.4",
                         uploaded_by_id=1, evidence_kind="INSPECTION"),
        m.SampleEvidence(sample_fk=sample.id, file_name="IMG_2232.pdf",
                         file_mime="application/pdf", file_data=b"%PDF-1.4",
                         uploaded_by_id=1, evidence_kind="RESULT"),
        m.SampleEvidence(sample_fk=sample.id, file_name="IMG_2233.pdf",
                         file_mime="application/pdf", file_data=b"%PDF-1.4",
                         uploaded_by_id=1, evidence_kind="PROGRESS"),
    ])
    db.commit()

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["sample_id"] == sample.id)
    assert row["evidence"]["complete"] is True
    assert row["evidence"]["missing"] == []
    assert row["evidence_kind_source"] == "sample_evidence.evidence_kind"
    assert row["evidence_unclassified"] == []
    assert set(row["evidence_kinds"].values()) == {"PROGRESS", "INSPECTION", "RESULT"}
    assert data["data_source"]["sources"]["evidence_kind"] == "sample_evidence.evidence_kind"
    assert "evidence_kind" not in data["data_source"]["heuristics_active"]


def test_missing_evidence_kind_falls_back_and_says_so(sample_client, db, headers):
    """Fallback tebakan nama tetap ada untuk data lama, TAPI ditandai jelas."""
    order = make_order(db, "SO-EK-2")
    article = make_article(db, order, "ART-EK2")
    # Nama file polos: tidak ada kata kunci inspeksi/hasil → tidak terklasifikasi.
    sample = make_sample(db, order, "ART-EK2", article_id=article.id, evidence=("IMG_2231.pdf",))

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["sample_id"] == sample.id)
    assert row["evidence_kind_source"] == "LEGACY_SUBSTRING_HEURISTIC"
    assert row["evidence_unclassified"] == ["IMG_2231.pdf"]
    assert row["evidence"]["missing"] == ["evidence_inspection", "evidence_result"]
    assert "evidence_kind" in data["data_source"]["heuristics_active"]

    # Dan begitu kolomnya diisi, tebakan berhenti dipakai untuk baris itu.
    sample.evidence[0].evidence_kind = "INSPECTION"
    db.commit()
    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["sample_id"] == sample.id)
    assert row["evidence_kind_source"] == "sample_evidence.evidence_kind"
    assert row["evidence_unclassified"] == []


# ─────────────────── task CREATE_SAMPLE dipersist (#33/#35) ───────────────────
def test_create_sample_task_is_persisted_with_prerequisites(sample_client, db, headers):
    """Task CREATE_SAMPLE jadi baris `sample_tasks` + prasyaratnya, idempoten."""
    order = make_order(db, "SO-PERSIST")
    article = make_article(db, order, "ART-PERSIST", sample_required=True,
                           sample_status="REQUIRED")

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["article_code"] == "ART-PERSIST")
    assert row["required_action"] == "CREATE_SAMPLE"
    assert row["persistence"] == "PERSISTED", row
    assert row["task_db_id"] is not None

    task = db.get(m.SampleTask, row["task_db_id"])
    assert task is not None
    assert task.order_fk == order.id
    assert task.article_id == article.id
    assert task.required_action == "CREATE_SAMPLE"
    assert task.stage == "OPEN" and task.status == "OPEN"
    assert task.blocker_owner == "CMO_MANAGER"
    assert task.bottleneck_reason and "Sample Request belum dibuat" in task.bottleneck_reason
    assert task.sla_source and "Master" in task.sla_source

    prereqs = db.query(m.SampleTaskPrerequisite).filter(
        m.SampleTaskPrerequisite.task_id == task.id).all()
    keys = {p.requirement_key for p in prereqs}
    assert keys == {"sample_request", "ppm_version", "article_routed"}
    satisfied = {p.requirement_key: p.satisfied for p in prereqs}
    assert satisfied["article_routed"] is True
    assert satisfied["sample_request"] is False and satisfied["ppm_version"] is False

    # Persistensi terlihat di payload, dan bisa dibaca ulang (idempoten).
    assert data["task_persistence"]["store"] == "sample_tasks"
    assert data["task_persistence"]["persisted"] >= 1
    assert data["task_persistence"]["missing"] == []
    detail = next(r for r in data["task_persistence"]["rows"] if r["task_db_id"] == task.id)
    assert detail["order_id"] == "SO-PERSIST"
    assert row["prerequisites"]["satisfied"] == 1 and row["prerequisites"]["pending"] == 2

    before = db.query(m.SampleTask).count()
    again = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    assert db.query(m.SampleTask).count() == before, "membaca ulang tidak boleh menduplikasi task"
    assert again["task_persistence"]["persisted"] == data["task_persistence"]["persisted"]

    # Artikel yang TIDAK butuh sample tidak boleh membuat task.
    make_article(db, order, "ART-NO-TASK", sample_required=False, sample_status="NOT_REQUIRED")
    sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC"))
    assert db.query(m.SampleTask).filter(m.SampleTask.article_id != article.id).count() == 0


def test_create_sample_task_not_duplicated_when_sample_request_exists(sample_client, db, headers):
    """Begitu Sample Request ada, task CREATE_SAMPLE berhenti ditawarkan."""
    order = make_order(db, "SO-PERSIST-2")
    article = make_article(db, order, "ART-PERSIST-2")
    sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC"))
    assert db.query(m.SampleTask).count() == 1

    make_sample(db, order, "ART-PERSIST-2", article_id=article.id)
    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["article_code"] == "ART-PERSIST-2")
    assert row["required_action"] is None and row["persistence"] is None
    assert data["create_sample_tasks"] == 0
    assert db.query(m.SampleTask).count() == 1


# ─────────────────── exception terikat ke sample & versinya (#37) ───────────────────
def test_exception_links_via_sample_fk_and_version(sample_client, db, headers):
    order = make_order(db, "SO-EX-FK")
    article = make_article(db, order, "ART-EX-FK")
    sample = make_sample(db, order, "ART-EX-FK", article_id=article.id,
                         evidence=("foto-progres.pdf",), sample_version=2)
    db.add_all([
        # Ikatan eksplisit: sample_fk + versi, TANPA source_entity.
        m.ExceptionItem(title="Warna meleset", category="Sample Material", severity="RED",
                        owner_role="SAMPLE_PIC", status="OPEN",
                        sample_fk=sample.id, sample_version=2),
        # Exception lama (belum di-backfill): masih lewat source_entity.
        m.ExceptionItem(title="Ukuran kurang", category="Sample Material", severity="YELLOW",
                        owner_role="SAMPLE_PIC", status="OPEN",
                        sample_fk=sample.id, source_entity="SampleRecord",
                        source_entity_id=sample.id),
    ])
    db.commit()

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["sample_id"] == sample.id)
    assert {e["problem"] for e in row["exceptions"]} == {"Warna meleset", "Ukuran kurang"}
    explicit = next(e for e in row["exceptions"] if e["problem"] == "Warna meleset")
    assert explicit["sample_fk"] == sample.id
    assert explicit["sample_version"] == 2
    assert row["stage"] == "WORK_REVISION"
    assert data["data_source"]["sources"]["exception_link"] == "exceptions.sample_fk"
    assert "exception_link" not in data["data_source"]["heuristics_active"]

    # Exception milik sample LAIN tidak boleh menempel.
    other = make_sample(db, order, "ART-EX-FK2", article_id=None, evidence=("foto-progres.pdf",))
    db.add(m.ExceptionItem(title="Punya sample lain", category="Sample Material", severity="RED",
                           owner_role="SAMPLE_PIC", status="OPEN", sample_fk=other.id))
    db.commit()
    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["sample_id"] == sample.id)
    assert "Punya sample lain" not in {e["problem"] for e in row["exceptions"]}


# ─────────────────── SLA, evidence & lifecycle (SMP-F-005 / #35) ───────────────────
def test_task_not_done_without_submitted_version_and_evidence(sample_client, db, headers):
    order = make_order(db, "SO-LC-1")
    make_article(db, order, "ART-LC")
    make_sample(db, order, "ART-LC", version=1, submitted=False, evidence=("foto-progres.pdf",))

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["article_code"] == "ART-LC")
    assert row["stage"] != "DONE"
    assert row["sample_work_status"] == "PROCESS"
    assert row["evidence"]["complete"] is False
    assert row["evidence"]["uploaded"] == 1
    assert row["next_action"] == "Unggah bukti inspeksi sample"
    assert {k: v["ok"] for k, v in row["requirements"].items()}["version_submitted"] is False


def test_full_evidence_stops_at_submit_result_until_buyer(sample_client, db, headers):
    order = make_order(db, "SO-LC-2")
    make_article(db, order, "ART-FULL")
    sample = make_sample(db, order, "ART-FULL", version=1, submitted=True,
                         evidence=("foto-progres.pdf", "bukti-inspeksi-qc.pdf", "hasil-final.pdf"))
    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["sample_id"] == sample.id)
    assert row["evidence"]["complete"] is True
    # Bukti lengkap != DONE: keputusan buyer masih milik CMO_MANAGER.
    assert row["stage"] == "SUBMIT_RESULT"
    assert all(v["ok"] for v in row["requirements"].values())
    assert row["next_action"] == "Submit hasil + bukti akhir ke CMO"
    assert row["buyer_decision"]["decided"] is False
    assert row["handoff"].startswith("Keputusan buyer")
    assert row["denied_actions"] and row["buyer_decision"]["owner"] == "CMO_MANAGER"


def test_lifecycle_progresses_nothing_skipped(sample_client, db, headers):
    order = make_order(db, "SO-LC-3")
    make_article(db, order, "ART-STEP1")
    make_article(db, order, "ART-STEP2")
    make_article(db, order, "ART-STEP3")
    make_sample(db, order, "ART-STEP1", submitted=False, evidence=())
    make_sample(db, order, "ART-STEP2", submitted=False, evidence=("foto-progres.pdf",))
    make_sample(db, order, "ART-STEP3", submitted=False,
                evidence=("foto-progres.pdf", "bukti-inspeksi-qc.pdf"))

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    stages = {r["article_code"]: r["stage"] for r in data["tasks"] if r["article_code"].startswith("ART-STEP")}
    assert stages == {"ART-STEP1": "UPDATE", "ART-STEP2": "INSPECTION",
                      "ART-STEP3": "SUBMIT_RESULT"}
    assert data["lifecycle"][0] == "OPEN" and data["lifecycle"][-1] == "DONE"


def test_sla_comes_from_master_and_marks_overdue(sample_client, db, headers):
    today = date.today()
    late = make_order(db, "SO-SLA-LATE", deadline=today - timedelta(days=3))
    soon = make_order(db, "SO-SLA-SOON", deadline=today + timedelta(days=1))
    make_article(db, late, "ART-LATE")
    make_article(db, soon, "ART-SOON")
    make_sample(db, late, "ART-LATE", evidence=("foto-progres.pdf",))
    make_sample(db, soon, "ART-SOON", evidence=("foto-progres.pdf",))

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    rows = {r["article_code"]: r for r in data["tasks"]}
    assert rows["ART-LATE"]["sla"]["state"] == "OVERDUE"
    assert rows["ART-LATE"]["sla"]["remaining_days"] == -3
    assert "Terlambat" in rows["ART-LATE"]["sla"]["label"]
    assert rows["ART-SOON"]["sla"]["state"] == "DUE_SOON"
    assert rows["ART-LATE"]["priority"] == "HIGH"
    assert "Master" in data["sla_source"]
    assert data["overdue"] == 1

    # Sample PIC tidak punya cara mengubah SLA: tidak ada endpoint tulis.
    assert sample_client.patch("/api/sample/my-tasks/ART-LATE", headers=headers("SAMPLE_PIC"),
                               json={"sla": "2099-01-01"}).status_code in (404, 405)


def test_sample_evidence_and_result_are_per_article(sample_client, db, headers):
    order = make_order(db, "SO-EV-1")
    done = make_article(db, order, "ART-EV-DONE")
    pending = make_article(db, order, "ART-EV-PENDING")
    make_sample(db, order, "ART-EV-DONE",
                evidence=("foto-progres.pdf", "bukti-inspeksi-qc.pdf", "hasil-final.pdf"),
                completed=date.today())
    make_sample(db, order, "ART-EV-PENDING", evidence=("foto-progres.pdf",))

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    rows = {r["article_code"]: r for r in data["tasks"]}
    assert rows["ART-EV-DONE"]["evidence"]["complete"] is True
    assert rows["ART-EV-PENDING"]["evidence"]["complete"] is False
    assert rows["ART-EV-PENDING"]["evidence"]["missing"] == ["evidence_inspection", "evidence_result"]
    assert rows["ART-EV-DONE"]["handoff"].startswith("Keputusan buyer")


# ─────────────────── Sample Today & exception (SMP-F-001/#31, #37) ───────────────────
def test_today_sections_are_action_first(sample_client, db, headers):
    today = date.today()
    order = make_order(db, "SO-TD-1", deadline=today + timedelta(days=5))
    late_order = make_order(db, "SO-TD-2", deadline=today - timedelta(days=1))
    make_article(db, order, "ART-TD-NEW")            # belum punya sample request
    make_article(db, order, "ART-TD-WORK")
    make_article(db, late_order, "ART-TD-LATE")
    make_sample(db, order, "ART-TD-WORK", evidence=("foto-progres.pdf",))
    make_sample(db, late_order, "ART-TD-LATE", evidence=("foto-progres.pdf",))

    data = sample_client.get(f"/api{PREFIX}/today", headers=headers("SAMPLE_PIC")).json()
    labels = [s["label"] for s in data["sections"]]
    assert labels == ["Belum Mulai", "Sedang Dikerjakan", "Menunggu Revisi",
                      "Siap Diserahkan", "Terlambat"]
    sections = {s["key"]: s["rows"] for s in data["sections"]}
    assert any(r["article_code"] == "ART-TD-NEW" for r in sections["NOT_STARTED"])
    # ART-TD-WORK sudah punya bukti progres → lifecycle berhenti di INSPECTION,
    # bukan langsung SUBMIT_RESULT (bukti inspeksi belum ada). Bucket kerjanya
    # tetap "Sedang Dikerjakan" karena hanya IN_PROGRESS/UPDATE yang di sana,
    # jadi ia harus muncul sebagai baris aktif lewat lifecycle, bukan hilang.
    work_rows = [r for r in sections["IN_PROGRESS"] if r["article_code"] == "ART-TD-WORK"]
    assert len(work_rows) == 1, [r["article_code"] for r in sections["IN_PROGRESS"]]
    assert work_rows[0]["stage"] == "INSPECTION"
    assert work_rows[0]["sample_id"] is not None
    assert any(r["article_code"] == "ART-TD-LATE" for r in sections["OVERDUE"])
    assert data["buckets"]["not_started"] == 1
    # ART-TD-WORK dan ART-TD-LATE sama-sama berhenti di INSPECTION.
    assert data["buckets"]["in_progress"] == 2
    # `overdue` adalah hitungan top-level (tidak di dalam `buckets`).
    assert data["overdue"] == 1
    # Kolom wajib ada di setiap baris (revisi #31).
    for row in [r for s in data["sections"] for r in s["rows"]]:
        for field in ("sample_id", "order_id", "article_id", "sample_version", "priority",
                      "next_action", "sla", "evidence", "blocker", "owner", "handoff"):
            assert field in row, field
        assert row["owner"] == "SAMPLE_PIC"
        assert row["handoff"].startswith("Keputusan buyer")
    assert data["access"]["can"] == list(sample_work.SAMPLE_WORK_ACTIONS)


def test_exception_scopes_to_sample_and_denies_resolve(sample_client, db, headers):
    order = make_order(db, "SO-EX-1")
    make_article(db, order, "ART-EX")
    sample = make_sample(db, order, "ART-EX", evidence=("foto-progres.pdf",))
    other = make_sample(db, order, "ART-EX2", evidence=("foto-progres.pdf",))
    db.add_all([
        m.ExceptionItem(title="Bahan sample terlambat", category="Sample Material",
                        severity="RED", owner_role="SAMPLE_PIC", status="OPEN",
                        sample_fk=sample.id, sample_version=1,
                        next_action="Unggah bukti bahan pengganti", due_date=date.today(),
                        escalation_reason="Supplier belum konfirmasi", confidential=False),
        m.ExceptionItem(title="Setup mesin bordir", category="Production", severity="YELLOW",
                        owner_role="COO_MANAGER", status="OPEN",
                        sample_fk=other.id, sample_version=1,
                        source_module="Production", confidential=False),
        m.ExceptionItem(title="Kasus HR", category="Sample HR", severity="RED",
                        owner_role="SAMPLE_PIC", status="OPEN", confidential=True,
                        sample_fk=sample.id, source_entity="SampleRecord",
                        source_entity_id=sample.id),
    ])
    db.commit()

    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["sample_id"] == sample.id)
    mine = row["exceptions"][0]
    assert mine["problem"] == "Bahan sample terlambat"
    assert mine["scope"] == "SAMPLE"
    assert mine["can_edit"] is True
    assert mine["can_resolve"] is False
    assert mine["can_escalate"] is False
    assert mine["owner"] == "SAMPLE_PIC"
    # Exception lintas owner tidak bisa diedit Fahrul, hanya view/escalate.
    other_row = next(r for r in data["tasks"] if r["sample_id"] == other.id)
    foreign = other_row["exceptions"][0]
    assert foreign["can_edit"] is False
    assert foreign["can_escalate"] is True
    assert foreign["can_resolve"] is False
    # Exception HR rahasia tidak bocor ke antrean sample.
    assert "Kasus HR" not in json.dumps(data["tasks"])
    # Exception membuat task menunggu revisi, bukan DONE.
    assert row["stage"] == "WORK_REVISION"
    assert row["next_action"].startswith("Perbaiki temuan exception")
    assert row["blocker_owner"] == "SAMPLE_PIC"


def test_exception_outside_sample_scope_not_attached(sample_client, db, headers):
    """SMP-F-007: exception lintas owner tidak boleh terbawa sebagai pekerjaan sample."""
    order = make_order(db, "SO-EX-2")
    make_article(db, order, "ART-EX3")
    sample = make_sample(db, order, "ART-EX3", evidence=("foto-progres.pdf",))
    db.add(m.ExceptionItem(title="Invoice macet", category="Finance", severity="RED",
                           owner_role="CFO_MANAGER", status="OPEN",
                           source_entity="Invoice", source_entity_id=sample.id))
    db.commit()
    data = sample_client.get(f"/api{PREFIX}/my-tasks", headers=headers("SAMPLE_PIC")).json()
    row = next(r for r in data["tasks"] if r["sample_id"] == sample.id)
    assert row["exceptions"] == []
    assert row["stage"] != "WORK_REVISION"


def test_my_tasks_filters(sample_client, db, headers):
    order = make_order(db, "SO-FL-1")
    other_order = make_order(db, "SO-FL-2")
    make_article(db, order, "ART-FL-A")
    make_article(db, other_order, "ART-FL-B")
    make_sample(db, order, "ART-FL-A", evidence=("foto-progres.pdf",))
    make_sample(db, other_order, "ART-FL-B", evidence=("foto-progres.pdf",))

    auth = headers("SAMPLE_PIC")
    filtered = sample_client.get(f"/api{PREFIX}/my-tasks?order_id=SO-FL-1", headers=auth).json()
    assert {r["order_id"] for r in filtered["tasks"]} == {"SO-FL-1"}
    assert filtered["total_rows"] == 1


def test_summary_counts_match_rows(sample_client, db, headers):
    today = date.today()
    order = make_order(db, "SO-SM-1", deadline=today - timedelta(days=2))
    make_article(db, order, "ART-SM-1")
    make_article(db, order, "ART-SM-2")
    make_sample(db, order, "ART-SM-1", evidence=("foto-progres.pdf",))

    data = sample_client.get(f"/api{PREFIX}/today", headers=headers("SAMPLE_PIC")).json()
    counted = sum(len(s["rows"]) for s in data["sections"])
    assert data["overdue"] == len([s for s in data["sections"] if s["key"] == "OVERDUE"
                                   for _ in s["rows"]])
    assert data["my_sample_tasks"] == 1
    assert data["create_sample_tasks"] == 1
    assert data["total_rows"] == data["total_eligible"] + len(data["not_eligible"])
    assert counted >= data["overdue"]
    assert data["as_of"] and data["today"] == today.isoformat()
