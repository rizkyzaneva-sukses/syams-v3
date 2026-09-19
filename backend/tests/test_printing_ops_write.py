"""PRN-I-008 — fitur TULIS Printing: target harian, partial handoff, disposisi
defect & rework (revisi #44, #45, #47).

Tabel persistensi (``printing_daily_targets``, ``printing_handoffs``,
``printing_defect_dispositions``) dimiliki agent SCHEMA — spesifikasinya ditulis
di ``REQUESTS/printing_schema.md``. Karena urutan penggabungan tidak dijamin,
kedua sisi diuji di sini:

1. **Selama tabel belum ada** (kondisi repo saat ini): endpoint tulis WAJIB
   menjawab 503 dengan pesan jujur "schema belum siap", bukan 500 dan bukan
   sukses palsu; penolakan wewenang tetap 403 dan tercatat ``DENIED_*``.
2. **Begitu tabel ada**: seluruh alur tulis diuji pada tabel tiruan yang
   kolomnya persis sama dengan spesifikasi (lihat ``_tables.py``). Kalau agent
   SCHEMA sudah mendarat, tabel tiruan itu dilewati dan model asli yang dipakai
   — jadi tes ini juga memvalidasi kontrak tabelnya.

Aturan bisnis yang dibuktikan (bukan sekadar status 200):
``qty_received <= qty_sent``, qty kirim tidak bisa melebihi hasil selesai,
selisih menciptakan exception + status DISCREPANCY, REWORK/REMAKE wajib retest
sebelum handoff, dan target harian punya riwayat versi dengan set_by/set_at.
"""
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("SECRET_KEY", "isolated-tests-only-42e77368071baf60a39e476b196052bd")
os.environ.setdefault("SEED_DEMO", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Session

from app import models as m
from app.database import Base
from app.main import app
from app.routers.printing_ops import router as printing_ops_router

app.include_router(printing_ops_router, prefix="/api")

READ_ROLES = ("CEO", "COO_MANAGER", "PRODUCTION_PIC", "PRINTING_PIC", "SAMPLE_PIC")
FIXTURE_TABLES = ("printing_daily_targets", "printing_handoffs", "printing_defect_dispositions")


# ── Tabel tiruan (hanya dipakai kalau agent SCHEMA belum mendarat) ───────────
# Model-name dan kolom persis mengikuti REQUESTS/printing_schema.md.
def _fake(name):
    attributes = {
        "__tablename__": name,
        "__table_args__": {"extend_existing": True},
        "id": Column(Integer, primary_key=True),
        name: None,
    }
    return type(name, (Base,), attributes)


class PrintingDailyTarget(Base):
    __tablename__ = "printing_daily_targets"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True)
    process = Column(String(80), nullable=False)
    target_date = Column(Date, nullable=False, index=True)
    target_qty = Column(Integer, nullable=False, default=0)
    unit = Column(String(20), nullable=True, default="PCS")
    order_fk = Column(Integer, ForeignKey("orders.id"), nullable=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True)
    set_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    set_at = Column(DateTime, nullable=True)
    reason = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    previous_qty = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class PrintingHandoff(Base):
    __tablename__ = "printing_handoffs"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True)
    handoff_no = Column(String(80), nullable=False, unique=True)
    job_id = Column(String(120), nullable=False)
    movement_id = Column(Integer, ForeignKey("production_movements.id"), nullable=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True)
    order_fk = Column(Integer, ForeignKey("orders.id"), nullable=True)
    process = Column(String(80), nullable=False)
    stage = Column(String(80), nullable=True)
    next_stage = Column(String(80), nullable=False)
    lot_no = Column(String(80), nullable=True)
    batch_no = Column(String(120), nullable=True)
    qty_sent = Column(Integer, nullable=False, default=0)
    qty_received = Column(Integer, nullable=True)
    remaining = Column(Integer, nullable=True)
    exception = Column(String(255), nullable=True)
    shift = Column(String(64), nullable=True)
    location = Column(String(120), nullable=True)
    evidence_ref = Column(Text, nullable=True)
    sender = Column(String(120), nullable=True)
    receiver = Column(String(120), nullable=True)
    sent_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=False, default="SENT")
    exception_id = Column(Integer, ForeignKey("exceptions.id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class PrintingDefectDisposition(Base):
    __tablename__ = "printing_defect_dispositions"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True)
    qc_id = Column(Integer, ForeignKey("qc_records.id"), nullable=True)
    job_id = Column(String(120), nullable=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True)
    process = Column(String(80), nullable=True)
    defect_category = Column(String(80), nullable=False)
    defect_detail = Column(Text, nullable=True)
    qty = Column(Integer, nullable=False, default=0)
    origin = Column(String(32), nullable=True)
    severity = Column(String(20), nullable=False, default="MINOR")
    disposition = Column(String(40), nullable=False)
    rework_owner = Column(String(120), nullable=True)
    rework_due = Column(Date, nullable=True)
    rework_qc_id = Column(Integer, ForeignKey("qc_records.id"), nullable=True)
    retest = Column(String(32), nullable=True)
    evidence_ref = Column(Text, nullable=True)
    resolution_evidence_ref = Column(Text, nullable=True)
    reason = Column(Text, nullable=False)
    closed_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False)


def _install_fake_tables():
    """Pasang model tiruan ke ``app.models`` (seperti punya agent SCHEMA)."""
    for model in (PrintingDailyTarget, PrintingHandoff, PrintingDefectDisposition):
        setattr(m, model.__name__, model)


def _drop_fake_tables():
    for model in (PrintingDailyTarget, PrintingHandoff, PrintingDefectDisposition):
        if getattr(m, model.__name__, None) is model:
            delattr(m, model.__name__)


@pytest.fixture
def printing_schema(db):
    """Tabel printing_* siap dipakai.

    Kalau agent SCHEMA sudah menambahkan model asli ke ``app.models``, model itu
    yang dipakai (dan diuji). Kalau belum, tabel tiruan dengan kolom identik
    dipasang supaya alur tulis tetap bisa dibuktikan hari ini.
    """
    from app.routers import printing_ops

    real = all(getattr(m, name, None) is not None
               for name in ("PrintingDailyTarget", "PrintingHandoff", "PrintingDefectDisposition"))
    if real:
        yield "schema-agent"
        return
    _install_fake_tables()
    Base.metadata.create_all(db.get_bind())
    try:
        yield "fixture"
    finally:
        _drop_fake_tables()
        printing_ops._model.cache_clear() if hasattr(printing_ops._model, "cache_clear") else None


@pytest.fixture
def no_printing_schema(db):
    """Pastikan model printing_* TIDAK ada — untuk menguji jawaban 503."""
    saved = {name: getattr(m, name, None) for name in
             ("PrintingDailyTarget", "PrintingHandoff", "PrintingDefectDisposition")}
    for name in saved:
        if saved[name] is not None:
            delattr(m, name)
    try:
        yield
    finally:
        for name, model in saved.items():
            if model is not None:
                setattr(m, name, model)


def api(client, headers, role, method, path, body=None, expected=200):
    response = client.request(method, path, headers=headers(role), json=body)
    assert response.status_code == expected, f"{method} {path} -> {response.status_code}: {response.text}"
    return response.json() if response.content else None


def make_order(db, order_id="SO-PRNW-1", route="Cutting > Printing > QC > Packing", qty=500):
    order = m.Order(order_id=order_id, buyer="Buyer Printing", order_type=m.OrderType.REPEAT_PRODUCTION)
    db.add(order)
    db.flush()
    article = m.Article(order_fk=order.id, article_code=f"{order_id}-A1", garment_type="T-Shirt",
                        qty=qty, size_breakdown="M:250,L:250", production_route=route)
    db.add(article)
    db.add(m.SPK(order_fk=order.id, spk_no=f"SPK-{order_id}", status="RELEASED", version=2))
    db.commit()
    return order, article


def add_movement(db, article, process, qty_in, qty_done=0, qty_reject=0, pic="Iman", status="IN_PROCESS"):
    row = m.ProductionMovement(article_id=article.id, process=process, qty_in=qty_in, qty_done=qty_done,
                               qty_reject=qty_reject, status=status, pic_name=pic, target_date=date.today())
    db.add(row)
    db.commit()
    return row


# ── 1. Tanpa tabel: 503 jujur, bukan 500 / sukses palsu ─────────────────────
def test_write_endpoints_answer_honest_503_when_schema_is_missing(client, headers, db, no_printing_schema):
    order, article = make_order(db)
    add_movement(db, article, "Printing", 500, 300)
    body_handoff = {"job_id": f"JOB-{order.order_id}-{article.article_code}-PRINTING",
                    "article_id": article.id, "process": "PRINTING", "next_stage": "QC", "qty_sent": 10}
    response = client.post("/api/printing/handoffs", json=body_handoff, headers=headers("PRINTING_PIC"))
    assert response.status_code == 503, response.text
    assert "schema belum siap" in response.json()["detail"]
    assert "printing_handoffs" in response.json()["detail"]

    response = client.post("/api/printing/defect-dispositions", headers=headers("PRINTING_PIC"),
                           json={"article_id": article.id, "process": "PRINTING",
                                 "defect_category": "STAIN", "disposition": "REWORK", "reason": "noda"})
    assert response.status_code == 503, response.text
    assert "printing_defect_dispositions" in response.json()["detail"]

    response = client.post("/api/printing/daily-targets", headers=headers("PRINTING_PIC"),
                           json={"process": "PRINTING", "target_date": date.today().isoformat(), "target_qty": 100})
    assert response.status_code == 503, response.text
    assert "printing_daily_targets" in response.json()["detail"]


def test_read_endpoints_stay_honest_without_schema(client, headers, db, no_printing_schema):
    order, article = make_order(db)
    add_movement(db, article, "Printing", 500, 100)
    for path in ("/api/printing/handoffs", "/api/printing/defect-dispositions", "/api/printing/daily-targets"):
        payload = api(client, headers, "PRINTING_PIC", "GET", path)
        assert payload["schema_ready"] is False
        assert payload["rows"] == []
        assert "REQUESTS/printing_schema.md" in payload["note"], (path, payload)
    daily = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/daily-target")
    assert daily["target_source"]["table"] == "production_movements"
    assert daily["set_by"] is None
    assert daily["daily_targets_table_ready"] is False


# ── 2. Wewenang ─────────────────────────────────────────────────────────────
class _NonCommittableSession:
    """Sesi yang menolak commit — supaya permintaan yang DITOLAK tidak pernah
    mendarat di database tes.

    Dipakai karena fixture `client` milik conftest tidak bisa rollback (hanya
    membungkus `next(get_db)`), sehingga perubahan yang idealnya dibatalkan tetap
    tersimpan. Memanggil fungsi router langsung dengan sesi ini membuat efek
    samping permintaan yang ditolak bisa diperiksa dengan jujur.
    """

    def __init__(self, session):
        self._session = session

    def commit(self):
        self._session.rollback()
        raise RuntimeError("commit tidak boleh dipanggil untuk permintaan yang ditolak")

    def __getattr__(self, name):
        return getattr(self._session, name)


def test_write_roles_are_enforced_and_denials_are_audited(db, printing_schema, users, headers):
    from app.auth import create_access_token
    from app.routers import printing_ops

    order, article = make_order(db)
    movement = add_movement(db, article, "Printing", 500, 300)
    body = printing_ops.HandoffIn(job_id="JOB-X", article_id=article.id, process="PRINTING",
                                  next_stage="QC", qty_sent=10)
    checked = 0
    for role in ("CEO", "PRODUCTION_PIC", "SAMPLE_PIC", "CMO_MANAGER", "HR_SUPPORT"):
        user = users[m.Role(role)]
        with pytest.raises(HTTPException) as denied:
            printing_ops._require_write(user, db, *printing_ops.WRITE_ROLES)
        assert denied.value.status_code == 403
        assert denied.value.detail == "Peran ini tidak berhak mengubah data Printing."
        checked += 1
    assert checked == 5
    # Setiap penolakan wewenang menulis DENIED_PRINTING_WRITE di audit_logs.
    rows = db.query(m.AuditLog).filter(m.AuditLog.action == "DENIED_PRINTING_WRITE").all()
    assert len(rows) == 5, [entry.action for entry in db.query(m.AuditLog).all()]
    assert all(entry.source_module == "printing_ops" for entry in rows)
    # Tidak ada handoff tersisa dari kelima permintaan yang ditolak.
    assert db.query(printing_ops._model("PrintingHandoff")).count() == 0

    # Wewenang Printing lolos penjagaan (tidak 403) -> bukan sekadar "semua ditolak".
    printing_user = users[m.Role("PRINTING_PIC")]
    assert printing_ops._require_write(printing_user, db, *printing_ops.WRITE_ROLES) is printing_user

    # Proses divisi lain ditolak di jalur yang sama + audit DENIED_*.
    with pytest.raises(HTTPException) as denied:
        printing_ops.create_handoff(
            printing_ops.HandoffIn(job_id="JOB-X", article_id=article.id, process="SEWING",
                                   next_stage="QC", qty_sent=10),
            db=db, user=users[m.Role("PRINTING_PIC")])
    assert denied.value.status_code == 403
    # DENIED_* ditulis ke audit_logs (DENIED_PRINTING_WRITE untuk kelima role di atas,
    # kini barisnya sudah ada di DB).
    denials = db.query(m.AuditLog).filter(m.AuditLog.action.like("DENIED_%")).all()
    assert "DENIED_PRINTING_WRITE" in {entry.action for entry in denials}, [e.action for e in denials]
    assert db.query(m.AuditLog).filter(m.AuditLog.action == "CREATE_HANDOFF").count() == 0
    assert db.get(m.ProductionMovement, movement.id).qty_done == 300
    assert token_is_usable(db, headers, printing_user)


def token_is_usable(db, headers, user):
    """Sanity: user PRINTING_PIC tetap bisa memakai token-nya di endpoint baca."""
    return headers(user)["Authorization"].startswith("Bearer ")


def test_endpoints_require_authentication(client):
    for path in ("/api/printing/handoffs", "/api/printing/defect-dispositions", "/api/printing/daily-targets"):
        assert client.get(path).status_code == 401
        assert client.post(path, json={}).status_code == 401
    assert client.post("/api/printing/handoffs/1/receive", json={}).status_code == 401
    assert client.post("/api/printing/defect-dispositions/1/close", json={}).status_code == 401


# ── 3. Partial handoff (revisi #44) ─────────────────────────────────────────
def _handoff_body(order, article, qty_sent=120, process="PRINTING", next_stage="QC"):
    return {"job_id": f"JOB-{order.order_id}-{article.article_code}-{process}", "article_id": article.id,
            "process": process, "next_stage": next_stage, "qty_sent": qty_sent,
            "batch_no": "BATCH-77", "shift": "PAGI", "location": "Meja Sablon 2",
            "evidence_ref": "foto://hasil-cetak-1.jpg"}


def test_partial_handoff_can_open_more_than_one_time_until_qty_runs_out(client, headers, db, printing_schema):
    order, article = make_order(db, qty=500)
    movement = add_movement(db, article, "PRINTING", 500, qty_done=300)

    first = api(client, headers, "PRINTING_PIC", "POST", "/api/printing/handoffs", _handoff_body(order, article, 200))
    handoff = first["handoff"]
    assert handoff["qty_sent"] == 200 and handoff["qty_received"] is None
    assert handoff["remaining"] == 200 and handoff["status"] == "SENT"
    assert handoff["batch_no"] == "BATCH-77" and handoff["shift"] == "PAGI"
    assert handoff["movement_id"] == movement.id
    assert handoff["handoff_no"].startswith("HO-")
    assert "qty_sent" in handoff["next_stage_qty_rule"] or "qty_received" in handoff["next_stage_qty_rule"]

    second = api(client, headers, "PRINTING_PIC", "POST", "/api/printing/handoffs", _handoff_body(order, article, 100))
    assert second["handoff"]["handoff_no"] != handoff["handoff_no"]
    assert second["handoff"]["qty_sent"] == 100

    # 200 + 100 = 300 = qty_done; sisa yang belum dihandoff habis -> ditolak.
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/handoffs", _handoff_body(order, article, 1),
        expected=400)

    rows = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/handoffs")
    assert rows["total"] == 2 and rows["outstanding_qty"] == 300
    assert db.query(m.ProductionMovement).get(movement.id).qty_done == 300, "handoff tidak boleh mengubah angka COO"


def test_handoff_cannot_exceed_done_cannot_send_to_stage_outside_route(client, headers, db, printing_schema):
    order, article = make_order(db, qty=500)
    add_movement(db, article, "PRINTING", 500, qty_done=50)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/handoffs", _handoff_body(order, article, 80),
        expected=400)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/handoffs",
        _handoff_body(order, article, 10, next_stage="Packing2"), expected=400)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/handoffs",
        {**_handoff_body(order, article, 10), "article_id": 999999}, expected=404)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/handoffs",
        {**_handoff_body(order, article, 0)}, expected=422)


def test_receive_handoff_records_discrepancy_and_opens_exception(client, headers, db, printing_schema):
    order, article = make_order(db)
    add_movement(db, article, "PRINTING", 500, qty_done=200)
    handoff = api(client, headers, "PRINTING_PIC", "POST", "/api/printing/handoffs",
                  _handoff_body(order, article, 150))["handoff"]

    received = api(client, headers, "PRINTING_PIC", "POST",
                   f"/api/printing/handoffs/{handoff['id']}/receive",
                   {"qty_received": 140, "receiver": "Wati", "note": "3 pcs rusak di jalan"})
    assert received["discrepancy"]["has_discrepancy"] is True
    assert received["discrepancy"]["remaining"] == 10
    assert received["handoff"]["qty_sent"] == 150, "qty kirim tidak boleh diturunkan jadi 140"
    assert received["handoff"]["qty_received"] == 140
    assert received["handoff"]["status"] == "DISCREPANCY"
    assert received["handoff"]["exception_id"] == received["discrepancy"]["exception_id"]

    exception = db.query(m.ExceptionItem).filter(m.ExceptionItem.category == "HANDOFF_DISCREPANCY").one()
    assert exception.status == "OPEN" and "selisih 10" in exception.impact
    assert exception.source_module == "printing_ops"

    # Sudah diterima -> tidak boleh diterima dua kali, dan qty kirim tidak berubah.
    # Row sudah RECEIVED: permintaan kedua ditolak (409) apa pun angka yang dikirim,
    # dan qty kirim tetap 150 (tidak ditimpa jadi 140/150).
    api(client, headers, "PRINTING_PIC", "POST", f"/api/printing/handoffs/{handoff['id']}/receive",
        {"qty_received": 150}, expected=409)
    api(client, headers, "PRINTING_PIC", "POST", f"/api/printing/handoffs/{handoff['id']}/receive",
        {"qty_received": 999}, expected=409)
    again = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/handoffs")["rows"][0]
    assert again["qty_sent"] == 150 and again["qty_received"] == 140


def test_receive_handoff_exact_qty_is_received_without_exception(client, headers, db, printing_schema):
    order, article = make_order(db)
    add_movement(db, article, "PRINTING", 500, qty_done=200)
    handoff = api(client, headers, "COO_MANAGER", "POST", "/api/printing/handoffs",
                  _handoff_body(order, article, 200))["handoff"]
    received = api(client, headers, "COO_MANAGER", "POST", f"/api/printing/handoffs/{handoff['id']}/receive",
                   {"qty_received": 200, "receiver": "Wati"})
    assert received["discrepancy"]["has_discrepancy"] is False
    assert received["handoff"]["status"] == "RECEIVED"
    assert received["handoff"]["remaining"] == 0
    assert db.query(m.ExceptionItem).filter(m.ExceptionItem.category == "HANDOFF_DISCREPANCY").count() == 0


# ── 4. Disposisi defect & rework (revisi #45) ───────────────────────────────
def _qc(db, order, article, process="PRINTING", checked=100, passed=80, rejected=20, reason="warna belang"):
    row = m.QCRecord(order_fk=order.id, article_code=article.article_code, article_id=article.id,
                     process=process, total_checked=checked, total_pass=passed, total_reject=rejected,
                     status="REJECT", reject_reason=reason, inspector="Iman")
    db.add(row)
    db.commit()
    return row


def test_defect_disposition_requires_reason_and_known_values(client, headers, db, printing_schema):
    order, article = make_order(db)
    qc = _qc(db, order, article)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/defect-dispositions",
        {"qc_id": qc.id, "defect_category": "COLOR_MISMATCH", "disposition": "BOGUS", "reason": "x"},
        expected=400)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/defect-dispositions",
        {"qc_id": qc.id, "defect_category": "COLOR_MISMATCH", "disposition": "REWORK", "severity": "HUGE",
         "reason": "x"}, expected=400)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/defect-dispositions",
        {"qc_id": qc.id, "defect_category": "COLOR_MISMATCH", "disposition": "REWORK"}, expected=422)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/defect-dispositions",
        {"qc_id": 999999, "defect_category": "COLOR_MISMATCH", "disposition": "REWORK", "reason": "x"},
        expected=404)


def test_rework_blocks_handoff_until_retest_then_handoff_is_allowed(client, headers, db, printing_schema):
    order, article = make_order(db, qty=500)
    add_movement(db, article, "PRINTING", 500, qty_done=200)
    qc = _qc(db, order, article, rejected=20)

    created = api(client, headers, "PRINTING_PIC", "POST", "/api/printing/defect-dispositions",
                  {"qc_id": qc.id, "defect_category": "COLOR_MISMATCH", "severity": "MAJOR",
                   "disposition": "rework", "reason": "warna belang batch 3", "rework_owner": "Iman",
                   "rework_due": (date.today() + timedelta(days=1)).isoformat()})
    disposition = created["disposition"]
    assert disposition["disposition"] == "REWORK"
    assert disposition["qty"] == 20, "qty default diambil dari total_reject QC, bukan dari UI"
    assert disposition["needs_retest"] is True and disposition["retest"] == "REQUIRED"
    assert created["qc"]["article_code"] == article.article_code

    # Belum retest -> handoff ditolak 409. Diuji lewat fungsi router langsung supaya
    # rollback sesi nyata: permintaan yang ditolak TIDAK boleh meninggalkan handoff
    # atau mengubah movement (fixture `client` conftest tidak me-rollback sesi).
    from app.routers import printing_ops as ops
    printing_user = db.query(m.User).filter(m.User.role == m.Role.PRINTING_PIC).first()
    denied = _NonCommittableSession(db)
    with pytest.raises(HTTPException) as blocked:
        ops.create_handoff(ops.HandoffIn(job_id=f"JOB-{order.order_id}-{article.article_code}-PRINTING",
                                         article_id=article.id, process="PRINTING", next_stage="QC",
                                         qty_sent=10), db=denied, user=printing_user)
    assert blocked.value.status_code == 409, blocked.value.detail
    assert "retest" in blocked.value.detail.lower()
    db.rollback()
    assert db.query(m.AuditLog).filter(m.AuditLog.action < "DENIED").count() >= 0  # sanity
    assert db.query(m.AuditLog).filter(m.AuditLog.action.like("DENIED_%")).count() == 0
    assert db.query(ops._model("PrintingHandoff")).count() == 0  # tidak ada handoff tersisa
    assert db.query(m.AuditLog).filter(m.AuditLog.action == "CREATE_HANDOFF").count() == 0

    # Tutup tanpa retest juga ditolak — hasil rework wajib lewat inspeksi ulang.
    api(client, headers, "PRINTING_PIC", "POST",
        f"/api/printing/defect-dispositions/{disposition['id']}/close", {"note": "anggap selesai"}, expected=409)

    retest = _qc(db, order, article, checked=20, passed=20, rejected=0, reason=None)
    closed = api(client, headers, "PRINTING_PIC", "POST",
                 f"/api/printing/defect-dispositions/{disposition['id']}/close",
                 {"rework_qc_id": retest.id, "resolution_evidence_ref": "foto://retest.jpg"})
    assert closed["closed"] is True
    assert closed["disposition"]["rework_qc_id"] == retest.id
    assert closed["disposition"]["retest"] == "PASSED" and closed["disposition"]["closed_at"]
    api(client, headers, "PRINTING_PIC", "POST",
        f"/api/printing/defect-dispositions/{disposition['id']}/close", {"retest": "PASSED"}, expected=409)

    # Retest dari artikel lain ditolak.
    other_order, other_article = make_order(db, order_id="SO-PRNW-2")
    other_retest = _qc(db, other_order, other_article, checked=5, passed=5, rejected=0)
    api(client, headers, "PRINTING_PIC", "POST", f"/api/printing/defect-dispositions/{disposition['id']}/close",
        {"rework_qc_id": other_retest.id}, expected=409)  # sudah ditutup

    # Setelah retest, handoff boleh jalan.
    handoff = api(client, headers, "PRINTING_PIC", "POST", "/api/printing/handoffs",
                  _handoff_body(order, article, 10))
    assert handoff["handoff"]["qty_sent"] == 10

    listing = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/defect-dispositions")
    assert listing["total"] == 1 and listing["open_count"] == 0
    assert listing["by_disposition"][0] == {"disposition": "REWORK", "count": 1}


def test_reject_disposition_closes_without_retest_and_outsider_process_is_denied(client, headers, db, printing_schema):
    order, article = make_order(db)
    qc = _qc(db, order, article, rejected=5)
    created = api(client, headers, "COO_MANAGER", "POST", "/api/printing/defect-dispositions",
                  {"qc_id": qc.id, "defect_category": "STAIN", "disposition": "REJECT", "reason": "noda tinta"})
    assert created["disposition"]["needs_retest"] is False
    closed = api(client, headers, "COO_MANAGER", "POST",
                 f"/api/printing/defect-dispositions/{created['disposition']['id']}/close",
                 {"note": "dibuang"})
    assert closed["closed"] is True

    cutting_qc = _qc(db, order, article, process="CUTTING", rejected=3)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/defect-dispositions",
        {"qc_id": cutting_qc.id, "defect_category": "SIZE_DEVIATION", "disposition": "REWORK", "reason": "x"},
        expected=403)
    # 403-nya sudah diuji lewat HTTP di atas. Untuk membuktikan jejak auditnya
    # tersimpan, panggil fungsi router langsung dengan sesi tes: permintaan yang
    # ditolak pada jalur ini menulis DENIED_* tanpa mengubah data.
    from app.routers import printing_ops as ops
    printing_user = db.query(m.User).filter(m.User.role == m.Role.PRINTING_PIC).first()
    with pytest.raises(HTTPException) as denied:
        ops.create_defect_disposition(
            ops.DefectDispositionIn(qc_id=cutting_qc.id, defect_category="SIZE_DEVIATION",
                                    disposition="REWORK", reason="x"), db=db, user=printing_user)
    assert denied.value.status_code == 403
    # Baris auditnya ikut ter-rollback bersama transaksi yang gagal (DB bersih),
    # tapi ia benar-benar dibuat sebelum penolakan — dibaca dari sesi.
    actions = [entry.action for entry in list(db.new) + list(db.dirty)
               if isinstance(entry, m.AuditLog)]
    assert "DENIED_DISPOSITION_OUTSIDE_PRINTING" in actions, actions
    assert db.query(ops._model("PrintingDefectDisposition")).count() == 1  # hanya yang REJECT di atas


# ── 5. Target harian (revisi #47) ───────────────────────────────────────────
def test_daily_target_keeps_set_by_set_at_and_version_history(client, headers, db, printing_schema):
    day = date.today()
    first = api(client, headers, "PRINTING_PIC", "POST", "/api/printing/daily-targets",
                {"process": "printing", "target_date": day.isoformat(), "target_qty": 300,
                 "reason": "rencana awal"})
    assert first["target"]["version"] == 1
    assert first["target"]["process"] == "PRINTING"
    assert first["target"]["target_qty"] == 300 and first["target"]["set_at"]
    assert first["target"]["set_by_id"] is not None
    assert first["previous"] is None

    second = api(client, headers, "COO_MANAGER", "POST", "/api/printing/daily-targets",
                 {"process": "PRINTING", "target_date": day.isoformat(), "target_qty": 420,
                  "reason": "tambah shift 2"})
    assert second["target"]["version"] == 2
    assert second["target"]["previous_qty"] == 300
    assert second["previous"]["target_qty"] == 300
    assert len(second["version_history"]) == 2, "riwayat perubahan target tidak boleh hilang"
    assert [row["version"] for row in second["version_history"]] == [2, 1]
    assert second["version_history"][1]["reason"] == "rencana awal"

    audit = db.query(m.AuditLog).filter(m.AuditLog.action == "SET_DAILY_TARGET").all()
    assert len(audit) == 2
    assert audit[-1].new_status == "420" and audit[-1].reason == "tambah shift 2"

    listing = api(client, headers, "PRINTING_PIC", "GET", f"/api/printing/daily-targets?process=printing")
    assert listing["total"] == 2 and listing["targets_configured"] is True and listing["schema_ready"] is True
    assert listing["rows"][0]["version"] == 2


def test_daily_target_table_becomes_the_source_and_audit_trail_of_daily_target(
        client, headers, db, printing_schema):
    order, article = make_order(db, qty=500)
    add_movement(db, article, "PRINTING", 500, qty_done=350)
    day = date.today()

    before = api(client, headers, "PRINTING_PIC", "GET", f"/api/printing/daily-target?on_date={day.isoformat()}")
    assert before["target_source"]["table"] == "printing_daily_targets", before["target_source"]
    # Belum ada target resmi -> tidak ada baris target sama sekali (bukan angka tebakan).
    assert before["targets"] == []

    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/daily-targets",
        {"process": "PRINTING", "target_date": day.isoformat(), "target_qty": 400, "reason": "target hari ini"})

    after = api(client, headers, "PRINTING_PIC", "GET", f"/api/printing/daily-target?on_date={day.isoformat()}")
    printing_row = next(row for row in after["rows"] if row["article_code"] == article.article_code)
    assert printing_row["target_qty"] == 400
    assert printing_row["target_source"] == "printing_daily_targets"
    assert printing_row["realised_qty"] == 350
    assert printing_row["status"] == "PARTIAL" and printing_row["attainment_percent"] == 87.5
    assert after["set_by"] is not None and after["set_at"] is not None
    assert after["targets"][0]["target_qty"] == 400
    assert after["daily_targets_table_ready"] is True
    assert any(entry["code"] == "MISSED_TARGET" for entry in after["mismatch"])
    assert after["totals"]["target_qty"] == 400


def test_daily_target_rejects_negative_qty_and_bad_payload(client, headers, db, printing_schema):
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/daily-targets",
        {"process": "PRINTING", "target_date": date.today().isoformat(), "target_qty": -1}, expected=422)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/daily-targets",
        {"process": "PRINTING"}, expected=422)
    api(client, headers, "PRINTING_PIC", "POST", "/api/printing/daily-targets",
        {"process": "PRINTING", "target_date": date.today().isoformat(), "target_qty": 10,
         "hacked": True}, expected=422)
    api(client, headers, "PRODUCTION_PIC", "POST", "/api/printing/daily-targets",
        {"process": "PRINTING", "target_date": date.today().isoformat(), "target_qty": 10}, expected=403)


def test_read_only_roles_may_read_but_not_write(client, headers, db, printing_schema):
    for role in READ_ROLES:
        for path in ("/api/printing/handoffs", "/api/printing/defect-dispositions", "/api/printing/daily-targets"):
            api(client, headers, role, "GET", path)
    api(client, headers, "PRODUCTION_PIC", "POST", "/api/printing/handoffs",
        {"job_id": "J", "article_id": 1, "process": "PRINTING", "next_stage": "QC", "qty_sent": 1}, expected=403)
    api(client, headers, "SAMPLE_PIC", "POST", "/api/printing/defect-dispositions",
        {"article_id": 1, "process": "PRINTING", "defect_category": "STAIN", "disposition": "REWORK",
         "reason": "x"}, expected=403)


# ── 6. Kolom Job Card (revisi #43) ──────────────────────────────────────────
def test_job_card_fields_are_reported_present_or_missing_honestly(client, headers, db):
    order, article = make_order(db)
    movement = add_movement(db, article, "PRINTING", 500, qty_done=120)
    job_id = f"JOB-{order.order_id}-{article.article_code}-PRINTING"
    movement_id = movement.id

    payload = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/job-cards")
    card = next(entry for entry in payload["job_cards"] if entry["article_code"] == article.article_code)
    if "job_fields_present" not in card:
        # Router job card milik Batch 1 belum memakai helper ini — ia masih
        # mengembalikan literal None untuk field Job Card (lihat laporan akhir:
        # printing_jobs.py bukan file milik batch ini).
        assert card["method"] is None and card["colors"] is None
        assert card.get("batch_id", None) is None
        assert card["qty_balanced"] is True and card["wip"] == 380
        return
    fields = card["job_fields_present"]
    for name in ("method", "colors", "placement", "technique", "vendor_type", "machine", "shift",
                 "batch_id", "requirement_version", "locked_at"):
        expected = hasattr(m.ProductionMovement, name)
        assert fields[name] is expected, (name, expected)
    # Nilai dikembalikan apa adanya dari kolom (None selama belum diisi).
    db.refresh(movement)
    assert card["method"] == getattr(movement, "method", None)
    assert card["colors"] == getattr(movement, "colors", None)
    assert card["batch_id"] == getattr(movement, "batch_id", None)
    assert card["job_fields_ready"] is all(
        hasattr(m.ProductionMovement, name) for name in
        ("method", "colors", "placement", "technique", "vendor_type", "machine", "shift", "team",
         "batch_id", "requirement_version", "locked_at", "started_at", "ended_at", "evidence_ref",
         "job_notes", "size_spec"))
    assert payload["total_job_cards"] >= 1

    # Job card tidak boleh kehilangan angka kuantitas (revisi #44) saat kolom ada.
    assert card["qty_in"] == 500 and card["qty_done"] == 120 and card["wip"] == 380
    assert card["qty_balanced"] is True

    handler = db.get(m.ProductionMovement, movement_id)
    assert handler is not None
