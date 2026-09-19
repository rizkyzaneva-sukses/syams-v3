"""CEO Override Governance (revisi #74 / CEO-I-005).

Router belum didaftarkan di app/main.py, dan tabel `ceo_overrides` belum
dimigrasi (spesifikasi di REQUESTS/ceo_batch2.md). Karena itu tes ini:

1. selalu memverifikasi kontrak governance yang TIDAK butuh tabel (siapa
   pemutus tiap tipe, dan bahwa transaksi rutin tidak bisa dibuat lewat sini);
2. membuat tabel `ceo_overrides` sementara di schema tes supaya jalur
   request/decide/acknowledge/rollback benar-benar dieksekusi — bukan diasumsikan;
3. memverifikasi bahwa tanpa tabel, override ditolak 503 alih-alih lolos
   diam-diam tanpa jejak audit.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import text as sa_text

from app import models as m


@pytest.fixture(autouse=True)
def mount_router():
    from app.main import app
    from app.routers.ceo_override import router

    if not any(getattr(r, "path", "") == "/api/ceo/overrides" for r in app.routes):
        app.include_router(router, prefix="/api")
    yield


def _create_override_table(db):
    """Buat tabel ceo_overrides sesuai spesifikasi REQUESTS (tanpa migration).

    Hanya dipakai di database tes supaya jalur kode override teruji sungguhan;
    produksi tetap menunggu migration milik orkestrator. Idempoten: schema tes
    dibuat ulang tiap fixture, jadi kelasnya di-cache di modul.
    """
    import sqlalchemy as sa
    from app.database import Base

    existing = getattr(m, "CEOOverride", None)
    if existing is not None and "ceo_overrides" in Base.metadata.tables:
        Base.metadata.create_all(db.get_bind(), tables=[existing.__table__])
        return existing

    class CEOOverride(Base):
        __tablename__ = "ceo_overrides"
        id = sa.Column(sa.Integer, primary_key=True)
        override_no = sa.Column(sa.String(40), unique=True)
        override_type = sa.Column(sa.String(40), nullable=False)
        status = sa.Column(sa.String(24), default="REQUESTED", nullable=False)
        source_module = sa.Column(sa.String(80), nullable=False)
        source_entity = sa.Column(sa.String(80), nullable=False)
        source_entity_id = sa.Column(sa.Integer, nullable=True)
        affected_entity = sa.Column(sa.String(160), nullable=False)
        original_value = sa.Column(sa.Text, nullable=False)
        proposed_value = sa.Column(sa.Text, nullable=False)
        requester_id = sa.Column(sa.Integer, sa.ForeignKey("users.id"), nullable=False)
        reason = sa.Column(sa.Text, nullable=False)
        impact = sa.Column(sa.Text, nullable=False)
        evidence_ref = sa.Column(sa.Text, nullable=True)
        scope = sa.Column(sa.String(300), nullable=False)
        effective_from = sa.Column(sa.Date, nullable=False)
        effective_to = sa.Column(sa.Date, nullable=True)
        ceo_decision = sa.Column(sa.String(24), nullable=True)
        ceo_decision_reason = sa.Column(sa.Text, nullable=True)
        ceo_decided_by_id = sa.Column(sa.Integer, sa.ForeignKey("users.id"), nullable=True)
        ceo_decided_at = sa.Column(sa.DateTime, nullable=True)
        acknowledged_by_id = sa.Column(sa.Integer, sa.ForeignKey("users.id"), nullable=True)
        acknowledged_at = sa.Column(sa.DateTime, nullable=True)
        rolled_back_at = sa.Column(sa.DateTime, nullable=True)
        rollback_reason = sa.Column(sa.Text, nullable=True)
        correction_note = sa.Column(sa.Text, nullable=True)
        created_at = sa.Column(sa.DateTime, nullable=True)
        updated_at = sa.Column(sa.DateTime, nullable=True)

    Base.metadata.create_all(db.get_bind(), tables=[CEOOverride.__table__])
    m.CEOOverride = CEOOverride
    return CEOOverride


PAYLOAD = {
    "override_type": "PRODUCTION_PRIORITY",
    "source_module": "production_plans",
    "source_entity": "ProductionPlan",
    "source_entity_id": 7,
    "affected_entity": "Order SO-900 prioritas produksi",
    "original_value": "normal",
    "proposed_value": "priority-1",
    "reason": "Buyer mengejar tenggat ekspor",
    "impact": "Order lain bergeser 1 hari",
    "evidence_ref": "email-buyer-2026-09-19",
    "scope": "line-cutting-saja",
    "effective_from": date.today().isoformat(),
}


def test_read_endpoints_require_authentication(client):
    assert client.get("/api/ceo/overrides").status_code == 401


def test_governance_contract_matches_blueprint(db, client, headers):
    """Empat batas override: siapa pemutusnya, dan apakah CEO memutuskan."""
    body = client.get("/api/ceo/overrides", headers=headers("CEO")).json()
    g = body["governance"]
    assert g["PRODUCTION_PRIORITY"]["decider"] == "CEO"
    assert g["PRODUCTION_PRIORITY"]["ceo_decides"] is True
    assert g["PRICING_EXCEPTION"]["decider"] == "CFO_MANAGER"
    assert g["PRICING_EXCEPTION"]["ceo_decides"] is False
    assert g["PRICING_EXCEPTION"]["informed"] == ["CEO"]
    assert g["SHIPMENT_OUTSTANDING"]["decider"] == "CEO"
    assert g["PURCHASING_EXCEPTION"]["decider"] == "CFO_MANAGER"


def test_without_table_override_is_refused_not_silently_allowed(db, client, headers):
    """Override tanpa jejak audit harus gagal keras (503), bukan lolos.

    Sejak migration `0025_ceo_overrides` mendarat, tabelnya ADA di skema normal —
    jadi jalur 503 ini tidak lagi terjadi "karena belum migrasi". Supaya
    perilaku pentingnya tetap terjaga, tabelnya dilepas dulu di tes ini dan
    harus dikembalikan setelahnya; kalau tidak, tes ini akan lulus palsu.
    """
    from sqlalchemy import inspect as sa_inspect

    present = "ceo_overrides" in sa_inspect(db.get_bind()).get_table_names()
    if not present:
        # Belum dimigrasi (mis. DB bersih tanpa migration): jalur 503 asli.
        response = client.post("/api/ceo/overrides", headers=headers("CEO"), json=PAYLOAD)
        assert response.status_code == 503
        assert "ceo_overrides" in response.json()["detail"]
        listing = client.get("/api/ceo/overrides", headers=headers("CEO")).json()
        assert listing["migration_pending"] is True
        return

    # Tabel ada: buktikan dulu override BOLEH dibuat (bukan diblokir selamanya)...
    created = client.post("/api/ceo/overrides", headers=headers("CEO"), json=PAYLOAD)
    assert created.status_code == 201, created.text
    listing = client.get("/api/ceo/overrides", headers=headers("CEO")).json()
    assert listing["migration_pending"] is False
    assert len(listing["items"]) == 1

    # ...lalu buktikan jalur "tabel hilang" tetap menolak keras, bukan meloloskan.
    db.query(m.CEOOverride).delete()
    db.commit()
    db.execute(sa_text("DROP TABLE ceo_overrides"))
    db.commit()
    try:
        blocked = client.post("/api/ceo/overrides", headers=headers("CEO"), json=PAYLOAD)
        assert blocked.status_code == 503, blocked.text
        assert "ceo_overrides" in blocked.json()["detail"]
    finally:
        m.CEOOverride.__table__.create(db.get_bind(), checkfirst=True)


def test_full_lifecycle_request_decide_acknowledge_rollback(db, client, headers):
    _create_override_table(db)
    created = client.post("/api/ceo/overrides", headers=headers("CEO"), json=PAYLOAD)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["override_no"] == f"OVR-{row['id']:05d}"
    assert row["status"] == "REQUESTED"
    assert row["is_active"] is False
    # Semua field yang diminta revisi #74 harus tersimpan dan terbaca kembali.
    for field in ("source_module", "source_entity", "source_entity_id", "affected_entity",
                  "original_value", "proposed_value", "requester_id", "reason", "impact",
                  "evidence_ref", "scope", "effective_from", "effective_to"):
        assert field in row, field
    assert row["original_value"] == "normal"
    assert row["proposed_value"] == "priority-1"

    # Keputusan: tipe ini milik CEO.
    decided = client.post(f"/api/ceo/overrides/{row['id']}/decide", headers=headers("CEO"),
                          json={"decision": "APPROVED", "reason": "Tenggat ekspor kritis"})
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["status"] == "APPROVED"
    assert body["ceo_decision"] == "APPROVED"
    assert body["ceo_decision_reason"] == "Tenggat ekspor kritis"
    assert body["ceo_decided_by_id"] is not None
    assert body["ceo_decided_at"] is not None
    assert body["is_active"] is True

    # Tidak boleh diputus dua kali.
    again = client.post(f"/api/ceo/overrides/{row['id']}/decide", headers=headers("CEO"),
                        json={"decision": "REJECTED", "reason": "berubah pikiran"})
    assert again.status_code == 409

    # Acknowledgement owner.
    ack = client.post(f"/api/ceo/overrides/{row['id']}/acknowledge", headers=headers("COO_MANAGER"))
    assert ack.status_code == 200
    assert ack.json()["acknowledged_at"] is not None

    # Rollback/koreksi oleh CEO — tanpa hard delete, barisnya tetap ada.
    rolled = client.post(f"/api/ceo/overrides/{row['id']}/rollback", headers=headers("CEO"),
                         json={"reason": "Buyer menunda ekspor",
                               "correction_note": "Prioritas dikembalikan ke normal"})
    assert rolled.status_code == 200
    rb = rolled.json()
    assert rb["status"] == "ROLLED_BACK"
    assert rb["rolled_back_at"] is not None
    assert rb["rollback_reason"] == "Buyer menunda ekspor"
    assert rb["correction_note"] == "Prioritas dikembalikan ke normal"
    assert rb["is_active"] is False
    assert len(client.get("/api/ceo/overrides", headers=headers("CEO")).json()["items"]) == 1


def test_pricing_exception_is_decided_by_cfo_not_ceo(db, client, headers):
    """Blueprint #74: pricing exception final oleh CFO, CEO hanya diinformasikan."""
    _create_override_table(db)
    payload = {**PAYLOAD, "override_type": "PRICING_EXCEPTION"}
    row = client.post("/api/ceo/overrides", headers=headers("CFO_MANAGER"), json=payload).json()

    denied = client.post(f"/api/ceo/overrides/{row['id']}/decide", headers=headers("CEO"),
                         json={"decision": "APPROVED", "reason": "CEO ingin menyetujui"})
    assert denied.status_code == 403
    assert "CFO_MANAGER" in denied.json()["detail"]

    allowed = client.post(f"/api/ceo/overrides/{row['id']}/decide", headers=headers("CFO_MANAGER"),
                          json={"decision": "APPROVED", "reason": "Margin masih di atas batas"})
    assert allowed.status_code == 200
    assert allowed.json()["ceo_decision"] == "APPROVED"


def test_cfo_cannot_decide_ceo_owned_overrides(db, client, headers):
    """Shipment outstanding wajib persetujuan CEO — CFO tidak boleh memutus."""
    _create_override_table(db)
    payload = {**PAYLOAD, "override_type": "SHIPMENT_OUTSTANDING"}
    row = client.post("/api/ceo/overrides", headers=headers("CFO_MANAGER"), json=payload).json()
    denied = client.post(f"/api/ceo/overrides/{row['id']}/decide", headers=headers("CFO_MANAGER"),
                         json={"decision": "APPROVED", "reason": "CFO menyetujui sendiri"})
    assert denied.status_code == 403
    assert "CEO" in denied.json()["detail"]
    allowed = client.post(f"/api/ceo/overrides/{row['id']}/decide", headers=headers("CEO"),
                          json={"decision": "APPROVED", "reason": "Outstanding dijamin"})
    assert allowed.status_code == 200


def test_unknown_override_type_is_rejected(db, client, headers):
    _create_override_table(db)
    bad = {**PAYLOAD, "override_type": "DELETE_INVOICE"}
    response = client.post("/api/ceo/overrides", headers=headers("CEO"), json=bad)
    assert response.status_code == 422


def test_override_payload_cannot_carry_operational_write_fields(db, client, headers):
    """`extra=forbid`: payload tidak bisa menyelipkan kolom transaksi rutin."""
    _create_override_table(db)
    sneaky = {**PAYLOAD, "invoice_id": 5, "po_id": 9, "close_order": True}
    response = client.post("/api/ceo/overrides", headers=headers("CEO"), json=sneaky)
    assert response.status_code == 422


def test_decision_requires_a_real_reason(db, client, headers):
    _create_override_table(db)
    row = client.post("/api/ceo/overrides", headers=headers("CEO"), json=PAYLOAD).json()
    short = client.post(f"/api/ceo/overrides/{row['id']}/decide", headers=headers("CEO"),
                        json={"decision": "APPROVED", "reason": "ok"})
    assert short.status_code == 422


def test_rollback_is_ceo_only(db, client, headers):
    _create_override_table(db)
    row = client.post("/api/ceo/overrides", headers=headers("CEO"), json=PAYLOAD).json()
    client.post(f"/api/ceo/overrides/{row['id']}/decide", headers=headers("CEO"),
                json={"decision": "APPROVED", "reason": "Perlu jalur cepat"})
    denied = client.post(f"/api/ceo/overrides/{row['id']}/rollback", headers=headers("COO_MANAGER"),
                         json={"reason": "COO membatalkan", "correction_note": "batal"})
    assert denied.status_code == 403


def test_filters_by_type_and_active_only(db, client, headers):
    _create_override_table(db)
    first = client.post("/api/ceo/overrides", headers=headers("CEO"), json=PAYLOAD).json()
    client.post("/api/ceo/overrides", headers=headers("CFO_MANAGER"),
                json={**PAYLOAD, "override_type": "PURCHASING_EXCEPTION"}).json()
    client.post(f"/api/ceo/overrides/{first['id']}/decide", headers=headers("CEO"),
                json={"decision": "APPROVED", "reason": "Disetujui karena tenggat"})

    by_type = client.get("/api/ceo/overrides?override_type=PURCHASING_EXCEPTION",
                         headers=headers("CEO")).json()["items"]
    assert len(by_type) == 1
    assert by_type[0]["override_type"] == "PURCHASING_EXCEPTION"

    active = client.get("/api/ceo/overrides?active_only=true", headers=headers("CEO")).json()["items"]
    assert [r["id"] for r in active] == [first["id"]]

    # CFO hanya melihat tipe di wilayahnya, bukan production priority milik CEO.
    cfo_view = client.get("/api/ceo/overrides", headers=headers("CFO_MANAGER")).json()["items"]
    assert all(r["override_type"] != "PRODUCTION_PRIORITY" for r in cfo_view)


def test_every_mutation_is_audited(db, client, headers):
    """Revisi #74: request/keputusan/acknowledge/rollback wajib teraudit."""
    _create_override_table(db)
    row = client.post("/api/ceo/overrides", headers=headers("CEO"), json=PAYLOAD).json()
    client.post(f"/api/ceo/overrides/{row['id']}/decide", headers=headers("CEO"),
                json={"decision": "APPROVED", "reason": "Tenggat ekspor kritis"})
    client.post(f"/api/ceo/overrides/{row['id']}/rollback", headers=headers("CEO"),
                json={"reason": "Buyer menunda", "correction_note": "Kembalikan normal"})

    actions = [entry.action for entry in db.query(m.AuditLog).all()]
    assert "OVERRIDE_REQUEST" in actions
    assert "OVERRIDE_DECIDE" in actions
    assert "OVERRIDE_ROLLBACK" in actions

    decide_log = db.query(m.AuditLog).filter_by(action="OVERRIDE_DECIDE").one()
    assert decide_log.reason == "Tenggat ekspor kritis"
    assert decide_log.new_status == "APPROVED"
    assert decide_log.source_module == "CEOOverride"
    assert decide_log.entity == "CEOOverride"
    assert decide_log.user_id is not None


def test_override_router_exposes_no_operational_write_paths(db, client, headers):
    """Tidak ada jalur PO/invoice/delivery/closing lewat router override."""
    from app.routers.ceo_override import router

    paths = [r.path for r in router.routes]
    for forbidden in ("purchase-order", "invoice", "delivery", "closing", "material-request"):
        assert not any(forbidden in p for p in paths), (forbidden, paths)
    # Satu-satunya resource yang boleh berubah adalah override itu sendiri.
    assert all(p.startswith("/ceo/overrides") for p in paths), paths
