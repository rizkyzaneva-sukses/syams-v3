"""SMP-F-004 / SMP-F-006 / SMP-F-008 — versioned sample lifecycle, evidence and
immutability (revisi #34, #36, #38).

The router is registered here with `include_router` because the orchestrator owns
`main.py`; the assertions below therefore run against the real app, real DB
fixtures and the real workflow/audit code paths.
"""
import base64
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import models as m
from app.routers import sample_lifecycle as sl

# A real 1x1 PNG: the evidence endpoint sniffs the file signature, so a fake
# header would be rejected with 415.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9vWAAAAABJRU5ErkJggg=="
)

READ_ROLES = ["CEO", "CMO_MANAGER", "CMO_SUPPORT", "COO_MANAGER", "SAMPLE_PIC"]
DENIED_ROLES = ["CFO_MANAGER", "FINANCE_SUPPORT", "CHRO_MANAGER", "HR_SUPPORT",
                "PRINTING_PIC", "PRODUCTION_PIC", "SHIPMENT_ADMIN"]


@pytest.fixture(autouse=True)
def mount_router():
    """Service the sample lifecycle router on the shared app (AGENT-RULES §3)."""
    from app.main import app
    from app.routers import sample_lifecycle as sl

    if not any(getattr(r, "path", "") == "/api/cmo/samples-version-summary" for r in app.routes):
        app.include_router(sl.router, prefix="/api")
    yield
    # Drop the routes again so this module cannot leak into other test files.
    app.router.routes[:] = [r for r in app.router.routes
                            if not getattr(r, "path", "").startswith("/api/cmo/samples-version")]


def make_order(db, number="SO-LC-001", order_type=m.OrderType.REPEAT_PRODUCTION, **kwargs):
    row = m.Order(order_id=number, buyer="Buyer Sample", order_type=order_type, **kwargs)
    db.add(row)
    db.commit()
    return row


def make_article(db, order, code="ART-LC-1", sample_required=True, **kwargs):
    row = m.Article(order_fk=order.id, article_code=code, qty=100,
                    sample_required=sample_required, sample_status="PROCESS", **kwargs)
    db.add(row)
    db.commit()
    return row


def make_sample(db, order, article, code=None, status="PROCESS", **kwargs):
    row = m.SampleRecord(order_fk=order.id, article_id=article.id,
                         article_code=code or article.article_code, status=status, **kwargs)
    db.add(row)
    db.commit()
    return row


def add_evidence(db, sample, user, name="approval.png", note="Bukti approval buyer"):
    row = m.SampleEvidence(sample_fk=sample.id, file_name=name, file_mime="image/png",
                           file_data=PNG, note=note, uploaded_by_id=user.id)
    db.add(row)
    db.commit()
    return row


def add_spk(db, order, status="RELEASED"):
    row = m.SPK(order_fk=order.id, spk_no=f"SPK-{order.id}-{status}", status=status, version=1)
    db.add(row)
    db.commit()
    return row


def decide(db, client, headers, sample, action="APPROVE", reason="Email buyer 19 Sep 2026"):
    return client.post(f"/api/cmo/samples/{sample.id}/customer-decision",
                       headers=headers("CMO_MANAGER"),
                       json={"action": action, "reason": reason})


# ───────────────────────── samples-version-summary ─────────────────────────

def test_summary_needs_auth_and_stays_inside_the_cmo_readership(client, headers):
    assert client.get("/api/cmo/samples-version-summary").status_code == 401
    for role in READ_ROLES:
        assert client.get("/api/cmo/samples-version-summary",
                          headers=headers(role)).status_code == 200, role
    for role in DENIED_ROLES:
        assert client.get("/api/cmo/samples-version-summary",
                          headers=headers(role)).status_code == 403, role


def test_summary_reports_latest_version_evidence_decision_and_actor(db, client, headers, users):
    order = make_order(db)
    article = make_article(db, order)
    first = make_sample(db, order, article, status="REVISION",
                        notes="Warna terlalu gelap",
                        customer_decision_at=datetime.utcnow(),
                        customer_decision_reason="Perbaiki warna",
                        requested_date=date.today() - timedelta(days=5))
    second = make_sample(db, order, article, status="PROCESS", notes="PPM v2")
    add_evidence(db, second, users[m.Role.SAMPLE_PIC], "ppm-v2.png", "PPM revisi 2")
    add_evidence(db, second, users[m.Role.SAMPLE_PIC], "foto-sample.jpg")
    assert decide(db, client, headers, second).status_code == 200

    body = client.get("/api/cmo/samples-version-summary", headers=headers("CMO_MANAGER")).json()
    assert body["stages"][0] == "SAMPLE_REQUEST"
    row = next(r for r in body["rows"] if r["article_code"] == article.article_code)
    # versioned lifecycle
    assert row["version_count"] == 2
    assert row["latest_version"] == 2
    assert row["latest_sample_id"] == second.id
    assert row["previous_version"] == 1
    assert row["previous_version_sample_id"] == first.id
    assert row["order_id"] == order.order_id
    assert row["article_id"] == article.id

    # evidence with actor + timestamp
    assert row["evidence_count"] == 2
    assert sorted(row["evidence_file_names"]) == ["foto-sample.jpg", "ppm-v2.png"]
    assert row["evidence_complete"] is True

    # buyer decision and the actor who recorded it
    assert row["status"] == "APPROVED"
    assert row["buyer_decision"] == "APPROVED"
    assert row["buyer_decision_status"] == "APPROVED"
    assert row["decision_by_id"] == users[m.Role.CMO_MANAGER].id
    assert row["decision_by"] == "CMO_MANAGER"
    assert row["decision_at"] is not None
    assert row["decision_reason"] == "Email buyer 19 Sep 2026"
    assert row["stage"] == "CLOSED" and row["stage_label"] == "Selesai"

    # approved sample: immutable, no edit/delete in the UI
    assert row["immutable"] is True
    assert row["immutability_state"] == "IMMUTABLE_APPROVED"
    assert row["requires_new_version"] is True
    assert "CREATE_NEW_VERSION" in row["allowed_actions"]
    assert "EDIT" not in row["allowed_actions"]
    assert row["open_version_count"] == 0
    assert row["next_action"].startswith("Versi final")


def test_summary_marks_approved_version_without_actor_as_mismatch(db, client, headers):
    """Revisi #36: Sample/Article bilang APPROVED tapi gate Order Flow tetap tertutup."""
    order = make_order(db, "SO-LC-MISMATCH")
    article = make_article(db, order)
    # Bypass the decision endpoint so no approver is recorded: the exact state
    # that used to show "Article Sample APPROVED" while progress stayed 0%.
    make_sample(db, order, article, status="APPROVED")
    article.sample_status = "APPROVED"
    db.commit()

    body = client.get("/api/cmo/samples-version-summary", headers=headers("CEO")).json()
    row = next(r for r in body["rows"] if r["order_id"] == "SO-LC-MISMATCH")
    assert row["master_sample_status"] == "APPROVED"
    assert row["gate_satisfied"] is False
    codes = {item["code"] for item in row["mismatch"]}
    assert "MASTER_APPROVED_GATE_CLOSED" in codes
    assert "APPROVED_WITHOUT_ACTOR" in codes
    assert row["has_mismatch"] is True
    assert body["totals"]["mismatch"] >= 1


def test_summary_surfaces_missing_evidence_before_approval(db, client, headers):
    order = make_order(db, "SO-LC-NOEVID")
    article = make_article(db, order, "ART-LC-NOEVID")
    make_sample(db, order, article, status="PROCESS")

    body = client.get("/api/cmo/samples-version-summary", headers=headers("CMO_SUPPORT")).json()
    row = next(r for r in body["rows"] if r["article_code"] == "ART-LC-NOEVID")
    assert row["latest_version"] == 1
    assert row["previous_version"] is None
    assert row["evidence_count"] == 0
    assert row["evidence_complete"] is False
    assert row["immutable"] is False and row["immutability_state"] == "OPEN"
    assert row["requires_new_version"] is False
    assert "Unggah evidence" in row["next_action"]
    assert row["blocker"] == "Evidence missing"


def test_summary_counts_versions_per_article_not_per_order(db, client, headers):
    order = make_order(db, "SO-LC-MULTI")
    first = make_article(db, order, "ART-LC-A")
    second = make_article(db, order, "ART-LC-B")
    make_sample(db, order, first)
    make_sample(db, order, first, status="REVISION")
    make_sample(db, order, second, status="APPROVED", customer_approved_by_id=None)

    body = client.get("/api/cmo/samples-version-summary", headers=headers("CMO_MANAGER")).json()
    rows = {r["article_code"]: r for r in body["rows"] if r["order_id"] == "SO-LC-MULTI"}
    assert rows["ART-LC-A"]["version_count"] == 2
    assert rows["ART-LC-A"]["latest_version"] == 2
    assert rows["ART-LC-B"]["version_count"] == 1
    assert body["totals"]["versions"] >= 3


def test_spk_locks_a_still_open_sample_version(db, client, headers):
    """Sample belum APPROVED tetapi SPK sudah dirilis: riwayatnya dibekukan."""
    order = make_order(db, "SO-LC-SPK")
    article = make_article(db, order, "ART-LC-SPK")
    sample = make_sample(db, order, article, status="PROCESS")
    add_spk(db, order, "RELEASED")

    body = client.get("/api/cmo/samples-version-summary", headers=headers("CEO")).json()
    row = next(r for r in body["rows"] if r["article_code"] == "ART-LC-SPK")
    assert row["immutable"] is True
    assert row["immutability_state"] == "LOCKED_BY_SPK"
    assert row["gate_consumed_by_spk"] is True
    assert row["requires_new_version"] is True
    assert "EDIT" not in row["allowed_actions"]
    assert "versi baru" in row["next_action"]

    decisions = client.get("/api/cmo/samples-version-decisions", headers=headers("CEO")).json()
    locked = next(r for r in decisions["rows"] if r["sample_id"] == sample.id)
    assert locked["can_edit"] is False and locked["can_delete"] is False


# ───────────────────────── GET /cmo/samples/{id}/versions ─────────────────────────

def test_versions_endpoint_returns_chain_with_evidence_and_decision(db, client, headers, users):
    order = make_order(db, "SO-LC-CHAIN")
    article = make_article(db, order, "ART-LC-CHAIN")
    first = make_sample(db, order, article, status="REVISION",
                        customer_decision_at=datetime.utcnow(),
                        customer_decision_reason="Ukuran kurang 2 cm")
    add_evidence(db, first, users[m.Role.CMO_SUPPORT], "sample-v1.png")
    second = make_sample(db, order, article, status="PROCESS", notes="PPM v2")
    add_evidence(db, second, users[m.Role.SAMPLE_PIC], "sample-v2.png")
    assert decide(db, client, headers, second, reason="Approved via email buyer").status_code == 200

    body = client.get(f"/api/cmo/samples/{first.id}/versions",
                      headers=headers("SAMPLE_PIC")).json()
    assert body["version_count"] == 2
    assert body["current_version"] == 1
    assert body["is_latest_version"] is False
    assert body["latest_version"] == 2
    assert body["latest_sample_id"] == second.id
    assert [v["sample_id"] for v in body["versions"]] == [first.id, second.id]

    v1, v2 = body["versions"]
    assert v1["sample_version"] == 1 and v1["previous_version"] is None
    assert v1["evidence_count"] == 1
    assert v1["evidence"][0]["file_name"] == "sample-v1.png"
    assert v1["evidence"][0]["uploaded_by"] == "CMO_SUPPORT"
    assert v1["evidence"][0]["created_at"] is not None
    assert v1["buyer_decision"] == "REVISION"
    assert v1["decision_reason"] == "Ukuran kurang 2 cm"
    # A version the buyer sent back is still a decision artefact: it must not be
    # re-edited in place, the correction lands on version 2.
    assert v1["immutability_state"] == "IMMUTABLE_DECIDED"
    assert v1["immutable"] is True and v1["requires_new_version"] is True
    assert "EDIT" not in v1["allowed_actions"]

    assert v2["sample_version"] == 2
    assert v2["previous_version"] == 1
    assert v2["previous_version_sample_id"] == first.id
    assert v2["is_latest_version"] is True
    assert v2["status"] == "APPROVED"
    assert v2["decision_by"] == "CMO_MANAGER"
    assert v2["approval_reference"] == "Approved via email buyer"
    assert v2["gate_satisfied"] is True
    assert v2["immutable"] is True
    assert v2["immutability_state"] == "IMMUTABLE_APPROVED"
    assert v2["evidence_gap"]["complete"] is True
    assert body["current"]["sample_id"] == first.id
    assert body["history"][-1]["sample_id"] == second.id
    assert body["history"][0]["immutable"] is True


def test_versions_endpoint_404s_for_unknown_sample(db, client, headers):
    assert client.get("/api/cmo/samples/999999/versions",
                      headers=headers("CEO")).status_code == 404
    assert client.get("/api/cmo/samples/999999/versions").status_code == 401
    assert client.get("/api/cmo/samples/999999/versions",
                      headers=headers("HR_SUPPORT")).status_code == 403


def test_versions_endpoint_reports_stored_version_chain_and_decision_source(db, client, headers, users):
    """Revisi #32/#34: keputusan dibaca dari `sample_versions`, rantai eksplisit.

    Baris di sini meniru kondisi NYATA sesudah `POST /api/cmo/samples` +
    `customer-decision`: kolom `sample_version` dan `previous_version_id` terisi,
    dan keputusan tersimpan pada baris versinya.
    """
    order = make_order(db, "SO-LC-STORED")
    article = make_article(db, order, "ART-LC-STORED")
    first = make_sample(db, order, article, status="REJECTED",
                        customer_decision_at=datetime.utcnow(),
                        customer_decision_reason="Ukuran kurang 2 cm",
                        sample_version=1)
    first.previous_version_id = None
    second = make_sample(db, order, article, status="APPROVED",
                         customer_approved_by_id=users[m.Role.CMO_MANAGER].id,
                         customer_decision_at=datetime.utcnow(),
                         customer_decision_reason="Warna sudah benar",
                         sample_version=2,
                         revision_reason="Perbaiki warna sesuai PPM v2")
    second.previous_version_id = first.id
    db.add_all([
        m.SampleVersion(sample_fk=first.id, version=1, decision="REJECTED",
                        decided_by_id=users[m.Role.CMO_MANAGER].id,
                        decided_at=first.customer_decision_at,
                        decision_reason="Ukuran kurang 2 cm"),
        m.SampleVersion(sample_fk=second.id, version=2, decision="APPROVED",
                        submitted=True, submitted_at=datetime.utcnow(),
                        decided_by_id=users[m.Role.CMO_MANAGER].id,
                        decided_at=second.customer_decision_at,
                        decision_reason="Warna sudah benar"),
    ])
    db.commit()

    body = client.get(f"/api/cmo/samples/{first.id}/versions",
                      headers=headers("CMO_MANAGER")).json()
    assert body["version_count"] == 2
    assert body["latest_version"] == 2
    v1, v2 = body["versions"]
    # Rantai eksplisit dari previous_version_id, bukan tebakan identitas.
    assert v1["chain_source"] == "previous_version_id" == v2["chain_source"]
    assert v1["sample_version"] == 1 and v1["stored_sample_version"] == 1
    assert v2["sample_version"] == 2 and v2["stored_sample_version"] == 2
    assert v2["previous_version_sample_id"] == first.id
    assert v2["stored_previous_version_id"] == first.id
    assert v1["version_number_source"] == "sample_records.sample_version"
    # Keputusan per versi: sumber kebenarannya `sample_versions`.
    assert v1["buyer_decision"] == "REJECTED" and v1["decision_source"] == "sample_versions"
    assert v2["buyer_decision"] == "APPROVED" and v2["decision_source"] == "sample_versions"
    assert v1["decision_reason"] == "Ukuran kurang 2 cm"
    assert v2["decision_reason"] == "Warna sudah benar"
    assert v2["revision_reason"] == "Perbaiki warna sesuai PPM v2"
    assert v1["sample_version_id"] is not None and v2["sample_version_id"] is not None
    assert v1["sample_version_row"]["decision"] == "REJECTED"
    assert v2["sample_version_row"]["submitted"] is True
    # Versi yang ditolak buyer tetap terkunci (revisi #38).
    assert v1["immutable"] is True and v1["immutability_state"] == "IMMUTABLE_DECIDED"

    # Ringkasan ikut memakai keputusan versi terakhir, dan rantai eksplisit.
    summary = client.get("/api/cmo/samples-version-summary", headers=headers("CEO")).json()
    row = next(r for r in summary["rows"] if r["article_code"] == "ART-LC-STORED")
    assert row["version_count"] == 2 and row["latest_version"] == 2
    assert row["previous_version_sample_id"] == first.id
    assert row["status"] == "APPROVED"
    assert row["decision_by"] == "CMO_MANAGER"


def test_versions_chain_falls_back_and_says_which_path_was_used(db, client, headers):
    """Kolom versi ada tapi kosong → nomor urut rantai, dan sumbernya dibuka."""
    order = make_order(db, "SO-LC-FALLBACK")
    article = make_article(db, order, "ART-LC-FALLBACK")
    # Dibuat lewat ORM tanpa mengisi kolom versi (kondisi data lama).
    first = make_sample(db, order, article, status="REVISION",
                        customer_decision_at=datetime.utcnow(),
                        customer_decision_reason="Mockup salah")
    second = make_sample(db, order, article, status="PROCESS")
    assert first.sample_version == 1 and second.sample_version == 1
    assert first.previous_version_id is None and second.previous_version_id is None

    body = client.get(f"/api/cmo/samples/{second.id}/versions",
                      headers=headers("SAMPLE_PIC")).json()
    assert body["version_count"] == 2
    # Nomor urut tetap 1,2 (kontrak UI) tapi dilaporkan bukan dari kolom.
    assert [v["sample_version"] for v in body["versions"]] == [1, 2]
    assert [v["version_number_source"] for v in body["versions"]] == \
        ["sample_records.sample_version", "chain_position_fallback"]
    assert body["versions"][1]["stored_sample_version"] == 1
    assert body["versions"][1]["chain_source"] == \
        "article_identity_fallback_previous_version_id_empty"
    assert body["latest_version"] == 2


def test_versions_falls_back_to_article_code_when_article_id_missing(db, client, headers, users):
    """Sample lama tanpa article_id tetap tergabung ke satu rantai versi."""
    order = make_order(db, "SO-LC-LEGACY")
    article = make_article(db, order, "ART-LC-LEGACY")
    old = m.SampleRecord(order_fk=order.id, article_id=None, article_code="ART-LC-LEGACY",
                         status="REVISION", customer_decision_at=datetime.utcnow(),
                         customer_decision_reason="Mockup salah")
    db.add(old)
    db.commit()
    latest = make_sample(db, order, article, status="PROCESS")
    add_evidence(db, latest, users[m.Role.CMO_SUPPORT], "legacy-v2.png")

    body = client.get(f"/api/cmo/samples/{latest.id}/versions", headers=headers("CEO")).json()
    assert body["version_count"] == 2
    assert [v["sample_id"] for v in body["versions"]] == [old.id, latest.id]
    assert body["versions"][1]["previous_version_sample_id"] == old.id
    # Legacy row has no article_id of its own; `matched_article_id` proves the
    # code-based match used by workflow.samples_ready was applied.
    assert body["versions"][0]["article_id"] is None
    assert body["versions"][0]["matched_article_id"] == article.id
    assert body["article_id"] == article.id


# ───────────────────────── immutability register ─────────────────────────

def test_decisions_register_lists_only_immutable_versions(db, client, headers, users):
    order = make_order(db, "SO-LC-REG")
    article = make_article(db, order, "ART-LC-REG")
    open_sample = make_sample(db, order, article, status="PROCESS")
    approved = make_sample(db, order, article, status="APPROVED",
                           customer_approved_by_id=users[m.Role.CMO_MANAGER].id,
                           customer_decision_at=datetime.utcnow(),
                           customer_decision_reason="Email buyer")
    add_evidence(db, approved, users[m.Role.CMO_MANAGER], "approval.png")

    body = client.get("/api/cmo/samples-version-decisions", headers=headers("CEO")).json()
    ids = {row["sample_id"] for row in body["rows"]}
    assert approved.id in ids
    assert open_sample.id not in ids
    row = next(r for r in body["rows"] if r["sample_id"] == approved.id)
    assert row["can_edit"] is False and row["can_delete"] is False
    assert row["immutability_state"] == "IMMUTABLE_APPROVED"
    assert set(row["allowed_actions"]) >= {"CREATE_NEW_VERSION", "REVISE", "VOID", "CORRECT"}
    assert "Versi ini sudah disetujui buyer" in row["reason"]
    assert row["decision_by"] == "CMO_MANAGER"
    assert body["totals"]["immutable_versions"] >= 1
    assert body["totals"]["supported_actions"] == ["CREATE_NEW_VERSION", "REVISE", "VOID", "CORRECT"]

    filtered = client.get("/api/cmo/samples-version-decisions?status=REJECTED",
                          headers=headers("CEO")).json()
    assert all(r["status"] == "REJECTED" for r in filtered["rows"])


def test_locked_fields_cover_every_mutable_sample_column():
    """Kalau kolom bisa diubah tapi tidak terkunci, revisi #38 bocor."""
    verdict = sl._immutability("APPROVED", gate_consumed=False, approved_handler_id=1)
    assert verdict["locked_fields"] == ["status", "notes", "requested_date", "completed_date",
                                        "article_code", "customer_decision_reason"]
    assert verdict["state"] == "IMMUTABLE_APPROVED"
    undecided = sl._immutability("PROCESS", gate_consumed=False, approved_handler_id=None)
    assert undecided["immutable"] is False and undecided["locked_fields"] == []
    assert sl._immutability("PROCESS", gate_consumed=True, approved_handler_id=None)["state"] == "LOCKED_BY_SPK"


def test_lifecycle_stage_projection_follows_revisi_34_order():
    assert sl._stage_of("PROCESS", 0, False) == "SAMPLE_REQUEST"
    assert sl._stage_of("IN_PROCESS", 0, False) == "WORK_VERSION"
    assert sl._stage_of("PROCESS", 2, False) == "SUBMISSION_HANDOFF"
    assert sl._stage_of("REJECTED", 1, True) == "REQUIREMENT_PPM"
    assert sl._stage_of("APPROVED", 1, True) == "CLOSED"
    assert sl.STAGES.index("WORK_VERSION") < sl.STAGES.index("SUBMISSION_HANDOFF")


# ───────────────────────── audit trail ─────────────────────────

def test_version_audit_records_actor_action_status_and_reason(db, client, headers, users):
    order = make_order(db, "SO-LC-AUDIT")
    article = make_article(db, order, "ART-LC-AUDIT")
    sample = make_sample(db, order, article, status="PROCESS")
    # Upload through the real endpoint: that is what writes the audit entry.
    upload = client.post(f"/api/cmo/samples/{sample.id}/evidence",
                         headers=headers("SAMPLE_PIC"),
                         data={"note": "bukti"},
                         files={"evidence": ("audit.png", PNG, "image/png")})
    assert upload.status_code == 201, upload.text
    assert decide(db, client, headers, sample, reason="WA konfirmasi buyer").status_code == 200

    body = client.get("/api/cmo/samples-version-audit?limit=500", headers=headers("CEO")).json()
    mine = [row for row in body["rows"] if row["sample_id"] == sample.id]
    assert mine, "audit trail for the decided sample must be visible"
    decision = next(row for row in mine if row["action"] == "CUSTOMER_SAMPLE_APPROVE")
    assert decision["actor"] == "CMO_MANAGER"
    assert decision["previous_status"] == "PROCESS"
    assert decision["new_status"] == "APPROVED"
    assert decision["reason"] == "WA konfirmasi buyer"
    assert decision["order_id"] == "SO-LC-AUDIT"
    assert decision["source_module"] == "SampleRecord"
    assert decision["created_at"] is not None
    upload = next(row for row in mine if row["action"] == "UPLOAD_EVIDENCE")
    assert upload["actor"] == "SAMPLE_PIC"
    assert upload["article_code"] == "ART-LC-AUDIT"
    # The mutation endpoint writes its own UPDATE row too — every change is traced.
    assert any(row["action"] == "UPDATE" and row["new_status"] == "APPROVED" for row in mine)


def test_version_audit_rejects_out_of_range_limit(db, client, headers):
    headers_cmo = headers("CMO_MANAGER")
    assert client.get("/api/cmo/samples-version-audit?limit=0", headers=headers_cmo).status_code == 422
    assert client.get("/api/cmo/samples-version-audit?limit=501", headers=headers_cmo).status_code == 422
    assert client.get("/api/cmo/samples-version-audit?limit=5", headers=headers_cmo).status_code == 200


# ───────────────────────── immutable data contract on the existing API ─────────────────────────

def test_patch_on_approved_sample_is_refused_by_workflow(db, client, headers, users):
    """Revisi #38: API harus menolak edit versi APPROVED, bukan hanya UI."""
    order = make_order(db, "SO-LC-IMMUT")
    article = make_article(db, order, "ART-LC-IMMUT")
    sample = make_sample(db, order, article, status="APPROVED",
                         customer_approved_by_id=users[m.Role.CMO_MANAGER].id,
                         customer_decision_at=datetime.utcnow(),
                         customer_decision_reason="Email buyer")
    response = client.patch(f"/api/cmo/samples/{sample.id}", headers=headers("CMO_MANAGER"),
                            json={"notes": "ubah diam-diam"})
    assert response.status_code == 400
    assert "immutable" in response.json()["detail"].lower()


def test_delete_on_approved_sample_is_refused_by_workflow(db, client, headers, users):
    order = make_order(db, "SO-LC-DEL")
    article = make_article(db, order, "ART-LC-DEL")
    sample = make_sample(db, order, article, status="APPROVED",
                         customer_approved_by_id=users[m.Role.CMO_MANAGER].id,
                         customer_decision_at=datetime.utcnow(),
                         customer_decision_reason="Email buyer")
    response = client.delete(f"/api/cmo/samples/{sample.id}", headers=headers("CMO_MANAGER"))
    assert response.status_code in (400, 404, 405)
    assert db.query(m.SampleRecord).filter(m.SampleRecord.id == sample.id).count() == 1


def test_approval_requires_evidence_and_records_the_version(db, client, headers):
    order = make_order(db, "SO-LC-GATE")
    article = make_article(db, order, "ART-LC-GATE")
    sample = make_sample(db, order, article, status="PROCESS")

    blocked = decide(db, client, headers, sample)
    assert blocked.status_code == 409
    assert "evidence" in blocked.json()["detail"].lower()

    body = client.get(f"/api/cmo/samples/{sample.id}/versions",
                      headers=headers("CMO_MANAGER")).json()
    assert body["versions"][0]["evidence_gap"]["complete"] is False
    assert body["versions"][0]["gate_satisfied"] is False


def test_summary_and_existing_samples_endpoint_agree(db, client, headers, users):
    """Satu event, dua tampilan: field nyata dari GET /api/cmo/samples harus cocok."""
    order = make_order(db, "SO-LC-SYNC")
    article = make_article(db, order, "ART-LC-SYNC")
    sample = make_sample(db, order, article, status="PROCESS")
    add_evidence(db, sample, users[m.Role.CMO_SUPPORT], "sync.png", "Bukti")
    assert decide(db, client, headers, sample, reason="Buyer OK").status_code == 200

    real = client.get("/api/cmo/samples", headers=headers("CMO_MANAGER")).json()
    detail = next(row for row in real if row["id"] == sample.id)
    summary = client.get("/api/cmo/samples-version-summary",
                         headers=headers("CMO_MANAGER")).json()
    row = next(r for r in summary["rows"] if r["latest_sample_id"] == sample.id)

    assert row["status"] == detail["status"]
    assert row["article_code"] == detail["article_code"]
    assert row["order_fk"] == detail["order_fk"]
    assert row["evidence_count"] == detail["evidence_count"]
    assert row["decision_by_id"] == detail["customer_decision_by_id"]
    assert row["latest_sample_id"] == detail["id"]
    assert row["master_sample_status"] == detail["status"]
    assert row["gate_satisfied"] is True
    assert detail["customer_decision_by_id"] == row["decision_by_id"]
    assert detail["customer_decision_reason"] == row["decision_reason"]


def test_client_registers_router_without_main_edits(client, headers):
    """include_router di file tes ini benar-benar melayani prefix /api.

    Router yang di-`include_router` tidak muncul sebagai route ber-`path` di
    versi Starlette ini, jadi buktinya diambil dari OpenAPI schema + respons asli.
    """
    schema = client.get("/openapi.json").json()
    assert "/api/cmo/samples-version-summary" in schema["paths"]
    assert "/api/cmo/samples/{sample_id}/versions" in schema["paths"]
    assert set(schema["paths"]["/api/cmo/samples-version-summary"]) == {"get"}
    assert isinstance(client, TestClient)
    assert client.get("/api/cmo/samples-version-summary",
                      headers=headers("CEO")).status_code == 200


@pytest.mark.parametrize("path", ["/api/cmo/samples-version-summary",
                                 "/api/cmo/samples-version-decisions",
                                 "/api/cmo/samples-version-audit"])
def test_read_endpoints_are_get_only(db, client, headers, path):
    """Read-only: tidak ada endpoint tulis di modul ini."""
    assert client.post(path, headers=headers("CEO")).status_code == 405
    assert client.delete(path, headers=headers("CEO")).status_code == 405
