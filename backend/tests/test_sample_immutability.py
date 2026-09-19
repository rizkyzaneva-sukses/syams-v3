"""Imutabilitas versi sample yang sudah diputuskan buyer (revisi #38).

Temuan agent sample_lifecycle: workflow.py hanya mengunci versi berstatus
APPROVED. Versi REJECTED/REVISION yang sudah membawa customer_decision_at
masih bisa di-PATCH, sehingga jejak keputusan buyer dapat ditimpa.

Tes ini membuktikan celah itu tertutup: tanpa perbaikan di workflow.py,
kedua tes "decided" akan gagal (PATCH 200, bukan 4xx).
"""
from app import models as m


def _seed_order(db):
    order = m.Order(order_id="SO-SAMPLE-LOCK", buyer="Buyer Lock", order_type="SAMPLE_PRODUCTION")
    db.add(order)
    db.commit()
    article = m.Article(order_fk=order.id, article_code="ART-LOCK", garment_type="shirt", qty=10)
    db.add(article)
    db.commit()
    return order, article


def _sample(db, order, article, status, decided):
    s = m.SampleRecord(
        order_fk=order.id,
        article_id=article.id,
        article_code=article.article_code,
        status=status,
        customer_decision_at=decided,
        customer_decision_reason="Buyer minta ganti warna" if decided else None,
    )
    db.add(s)
    db.commit()
    return s


def test_revision_with_buyer_decision_is_immutable(client, db, headers):
    order, article = _seed_order(db)
    from datetime import datetime
    s = _sample(db, order, article, "REVISION", datetime(2026, 9, 19, 8, 0, 0))

    r = client.patch(
        f"/api/cmo/samples/{s.id}",
        json={"status": "REVISION", "notes": "mencoba menimpa keputusan buyer"},
        headers=headers("CMO_MANAGER"),
    )
    assert r.status_code >= 400, f"versi REVISION yang sudah diputuskan harus terkunci, dapat {r.status_code}"

    db.refresh(s)
    assert s.notes != "mencoba menimpa keputusan buyer"


def test_rejected_with_buyer_decision_is_immutable(client, db, headers):
    order, article = _seed_order(db)
    from datetime import datetime
    s = _sample(db, order, article, "REJECTED", datetime(2026, 9, 19, 9, 0, 0))

    r = client.patch(
        f"/api/cmo/samples/{s.id}",
        json={"status": "REJECTED", "notes": "mencoba menimpa penolakan buyer"},
        headers=headers("CMO_MANAGER"),
    )
    assert r.status_code >= 400, f"versi REJECTED yang sudah diputuskan harus terkunci, dapat {r.status_code}"

    db.refresh(s)
    assert s.notes != "mencoba menimpa penolakan buyer"


def test_undecided_revision_is_still_editable(client, db, headers):
    """Kebalikannya: revisi yang BELUM diputuskan buyer tetap boleh diedit.

    Mencegah perbaikan di atas menjadi terlalu ketat dan memblokir kerja normal.
    """
    order, article = _seed_order(db)
    s = _sample(db, order, article, "REVISION", None)

    r = client.patch(
        f"/api/cmo/samples/{s.id}",
        json={"status": "REVISION", "notes": "revisi masih dalam pengerjaan"},
        headers=headers("CMO_MANAGER"),
    )
    assert r.status_code < 400, f"revisi tanpa keputusan buyer harus tetap bisa diedit, dapat {r.status_code}"
