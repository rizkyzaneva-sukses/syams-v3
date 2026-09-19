"""CMO Support (Deby) — halaman awal & antrean kerja (revisi #1, #9).

Modul ini sebelumnya TIDAK punya tes sama sekali, sehingga bug nyata lolos:
payload `GET /cmo/deby-today` tidak memuat `buyer_id`, `article_id`, dan `stage`
— padahal blueprint #1/#9 poin 3 mewajibkan setiap baris antrean membawa
Task ID, Buyer ID, Order ID, Article ID, tahap proses, status, data/bukti
kurang, next action, owner, due/SLA, sumber, updated_at, dan handoff.

Router sudah terdaftar di `app/main.py` oleh orkestrator, jadi tes ini memakai
app yang sebenarnya (tanpa `include_router` manual).
"""
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import models as m

PATH = "/api/cmo/deby-today"

# Kontrak antrean wajib (revisi #9 poin 3) — dipakai #1 juga.
MANDATORY_ROW_FIELDS = (
    "task_id", "order_id", "stage", "status", "missing", "next_action",
    "owner", "due", "source", "handoff", "updated_at",
)


def make_order(db, number, **kwargs):
    order = m.Order(order_id=number, buyer="Buyer Deby",
                    order_type=m.OrderType.SAMPLE_PRODUCTION,
                    finance_status="PAID", order_date=date.today(),
                    buyer_deadline=date.today() + timedelta(days=3), **kwargs)
    db.add(order)
    db.commit()
    return order


def make_article(db, order, code="ART-DEBY", sample_required=True):
    article = m.Article(order_fk=order.id, article_code=code, qty=10,
                        sample_required=sample_required, sample_status="REQUIRED")
    db.add(article)
    db.commit()
    return article


def make_sample(db, order, article, status="PROCESS"):
    sample = m.SampleRecord(order_fk=order.id, article_id=article.id,
                            article_code=article.article_code, status=status)
    db.add(sample)
    db.commit()
    return sample


def rows_of(body):
    return [r for q in body.get("queues", []) for r in (q.get("rows") or [])]


# ───────────────────────────── akses ─────────────────────────────

def test_deby_today_requires_auth_and_is_scoped_to_cmo(client, headers):
    assert client.get(PATH).status_code == 401
    for role in ("CMO_SUPPORT", "CMO_MANAGER", "CEO"):
        assert client.get(PATH, headers=headers(role)).status_code == 200, role
    # Peran di luar CMO tidak boleh membaca antrean kerja Deby.
    for role in ("CFO_MANAGER", "COO_MANAGER", "CHRO_MANAGER", "PRODUCTION_PIC",
                 "PRINTING_PIC", "SAMPLE_PIC", "SHIPMENT_ADMIN"):
        assert client.get(PATH, headers=headers(role)).status_code == 403, role


# ─────────────────── kontrak baris antrean (revisi #1) ───────────────────

def test_every_row_carries_the_mandatory_queue_contract(db, client, headers):
    """Bug yang diperbaiki: `buyer_id`, `article_id`, `stage` hilang dari payload."""
    order = make_order(db, "SO-DEBY-1")
    article = make_article(db, order)
    sample = make_sample(db, order, article)

    body = client.get(PATH, headers=headers("CMO_SUPPORT")).json()
    rows = rows_of(body)
    assert rows, "antrean Deby tidak boleh kosong untuk data uji ini"

    for row in rows:
        for field in MANDATORY_ROW_FIELDS:
            assert field in row, f"field kontrak '{field}' hilang dari baris antrean"

    row = next(r for r in rows if r["task_id"] == f"SMP-{sample.id}")
    assert row["article_id"] == article.id, \
        "article_id harus ID artikel nyata supaya baris bisa ditautkan"
    assert row["order_id"] == order.order_id
    assert row["stage"], "stage (tahap proses) tidak boleh kosong"
    assert "buyer_id" in row and "article_id" in row, \
        "kunci tautan ke record terkait harus selalu ada di payload"


def test_row_helper_never_returns_empty_stage_or_missing_link_keys():
    from app.routers import cmo_support as cs

    row = cs._row(task_id="T-1", kind="FOLLOW_UP", order=None, stage="FOLLOW_UP")
    assert row["stage"] == "FOLLOW_UP"
    # Tanpa `stage` eksplisit, `kind` dipakai — tahap tidak pernah kosong.
    assert cs._row(task_id="T-2", kind="AFTER_SALES", order=None)["stage"] == "AFTER_SALES"
    for key in ("buyer_id", "article_id", "stage"):
        assert key in row, f"'{key}' harus selalu ada di payload"


def test_deby_today_buckets_match_the_revisi_1_work_list(db, client, headers):
    """#1 minta lima jenis pekerjaan Deby terlihat sebagai antrean."""
    order = make_order(db, "SO-DEBY-2")
    article = make_article(db, order)
    make_sample(db, order, article)

    body = client.get(PATH, headers=headers("CMO_SUPPORT")).json()
    keys = {q.get("key") for q in body["queues"]}
    # Nama bucket boleh beda, tapi kelima pekerjaan #1 harus terwakili.
    assert any("PO" in str(k) for k in keys), "PO masuk/belum lengkap harus muncul"
    assert any("SAMPLE" in str(k) for k in keys), "bukti approval buyer belum lengkap"
    assert any("SPK" in str(k) for k in keys), "SPK perlu dibuat/dicetak"
    assert any("FOLLOW" in str(k) for k in keys), "follow-up buyer jatuh tempo"
    assert any("AFTER" in str(k) for k in keys), "after-sales"
    # Setiap bucket menyatakan owner & handoff-nya (bukan hanya judul).
    for q in body["queues"]:
        assert "owner" in q and "handoff" in q, f"bucket {q.get('key')} tanpa owner/handoff"


# ─────────────────── wewenang: Deby vs Cecep (revisi #1) ───────────────────

def test_cmo_support_cannot_release_or_void_spk():
    """Deby menyiapkan & mencetak; Release/VOID tetap milik Cecep.

    Diuji pada sumber `modules.py` karena semua jalur HTTP-nya sudah dijaga
    `spk_require` dengan daftar peran yang sama; tes ini mengunci daftarnya
    supaya `CMO_SUPPORT` tidak diam-diam ditambahkan ke aksi keputusan.
    """
    import re

    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "modules.py").read_text(encoding="utf-8")
    for action in ("RELEASE", "VOID"):
        mt = re.search(rf'"{action}"\s*,\s*\{{([^}}]*)\}}', src)
        assert mt, f"batas peran untuk aksi {action} tidak ditemukan"
        assert "CMO_SUPPORT" not in mt.group(1), \
            f"CMO_SUPPORT tidak boleh punya aksi {action}"
        assert "CMO_MANAGER" in mt.group(1), f"{action} harus milik CMO_MANAGER"
    # Generate & Print justru HARUS tetap boleh untuk Deby (tugasnya).
    for action in ("GENERATE", "PRINT"):
        mt = re.search(rf'"{action}"\s*,\s*\{{([^}}]*)\}}', src)
        assert mt and "CMO_SUPPORT" in mt.group(1), \
            f"{action} adalah tugas Deby dan harus tetap diizinkan"


def test_deby_cannot_write_cross_divisional_endpoints(client, headers):
    """#1: Deby hanya input, administrasi, dan komunikasi."""
    auth = headers("CMO_SUPPORT")
    for method, path in (("post", "/api/coo/material-requests"),
                         ("post", "/api/cfo/invoices"),
                         ("post", "/api/cfo/purchase-orders"),
                         ("post", "/api/coo/production-plans")):
        response = getattr(client, method)(path, headers=auth, json={})
        assert response.status_code in (403, 405, 422), (method, path, response.status_code)
