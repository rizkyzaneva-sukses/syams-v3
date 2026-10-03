"""Revision proposals are shared across roles and screenshots stay authenticated."""
import base64


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9vWAAAAABJRU5ErkJggg=="
)


def test_all_users_can_submit_and_read_with_reporter_attribution(client, headers, users):
    first = client.post("/api/revisions", headers=headers("HR_SUPPORT"), data={
        "module_name": "  Training  ", "bug_description": "  Tombol simpan gagal  ",
        "expected_behavior": "  Data tersimpan  ", "reported_by_id": str(users[next(iter(users))].id),
    })
    assert first.status_code == 201, first.text
    assert first.json()["reported_by_name"] == "HR_SUPPORT"
    assert first.json()["module_name"] == "Training"
    assert first.json()["has_image"] is False
    assert first.json()["status"] == "REVISI"
    assert first.json()["owner_role"] == "HR_SUPPORT"

    second = client.post("/api/revisions", headers=headers("PRODUCTION_PIC"), data={
        "module_name": "Production Queue", "bug_description": "Gambar hilang",
        "expected_behavior": "Gambar tampil",
    }, files={"image": ("screenshot.png", PNG, "image/png")})
    assert second.status_code == 201, second.text
    assert second.json()["has_image"] is True

    listed = client.get("/api/revisions", headers=headers("CEO"))
    assert listed.status_code == 200
    assert [item["module_name"] for item in listed.json()] == ["Production Queue", "Training"]
    assert [item["reported_by_name"] for item in listed.json()] == ["PRODUCTION_PIC", "HR_SUPPORT"]
    image = client.get(f"/api/revisions/{second.json()['id']}/image", headers=headers("CMO_SUPPORT"))
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content == PNG


def test_revision_requires_login_and_rejects_invalid_inputs(client, headers):
    payload = {"module_name": "QC", "bug_description": "Gagal", "expected_behavior": "Berhasil"}
    assert client.get("/api/revisions").status_code == 401
    assert client.post("/api/revisions", data=payload).status_code == 401
    assert client.post("/api/revisions", headers=headers("CEO"), data={**payload, "bug_description": "   "}).status_code == 422
    bad_image = client.post("/api/revisions", headers=headers("CEO"), data=payload,
                            files={"image": ("fake.png", b"not an image", "image/png")})
    assert bad_image.status_code == 415
    too_large = client.post("/api/revisions", headers=headers("CEO"), data=payload,
                            files={"image": ("large.png", PNG + b"x" * (5 * 1024 * 1024), "image/png")})
    assert too_large.status_code == 413
    assert client.get("/api/revisions", headers=headers("CEO")).json() == []


def test_tagged_owner_and_ceo_can_send_to_check_and_reporter_reviews(client, headers, db):
    created = client.post("/api/revisions", headers=headers("CMO_SUPPORT"), data={
        "module_name": "CMO-023 — CMO Support — Delivery",
        "bug_description": "Masih ada tombol Delivery", "expected_behavior": "Tombol tidak ada",
        "owner_role": "CMO_SUPPORT",
    }, files={"image": ("screenshot.png", PNG, "image/png")})
    assert created.status_code == 201, created.text
    proposal_id = created.json()["id"]
    path = f"/api/revisions/{proposal_id}/status"
    assert created.json()["allowed_next_statuses"] == ["CHECK"]

    forbidden = client.patch(path, headers=headers("CFO_MANAGER"), json={
        "expected_status": "REVISI", "status": "CHECK", "note": "Sudah diperbaiki"})
    assert forbidden.status_code == 403
    missing_note = client.patch(path, headers=headers("CEO"), json={
        "expected_status": "REVISI", "status": "CHECK", "note": "  "})
    assert missing_note.status_code == 422

    check = client.patch(path, headers=headers("CEO"), json={
        "expected_status": "REVISI", "status": "CHECK", "note": "Tombol sudah disembunyikan."})
    assert check.status_code == 200, check.text
    assert check.json()["status"] == "CHECK"
    stale = client.patch(path, headers=headers("CEO"), json={
        "expected_status": "REVISI", "status": "CHECK", "note": "Duplikat"})
    assert stale.status_code == 409

    revisit = client.patch(path, headers=headers("CMO_SUPPORT"), json={
        "expected_status": "CHECK", "status": "TINJAU_ULANG", "note": "Masih muncul lewat URL langsung."})
    assert revisit.status_code == 200, revisit.text
    assert revisit.json()["status"] == "TINJAU_ULANG"
    assert revisit.json()["allowed_next_statuses"] == ["CHECK"]

    checked_again = client.patch(path, headers=headers("CMO_SUPPORT"), json={
        "expected_status": "TINJAU_ULANG", "status": "CHECK", "note": "Akses URL langsung sudah ditutup."})
    assert checked_again.status_code == 200
    solved = client.patch(path, headers=headers("CMO_SUPPORT"), json={
        "expected_status": "CHECK", "status": "SOLVED", "note": "Sesuai."})
    assert solved.status_code == 200
    assert solved.json()["allowed_next_statuses"] == []

    history = client.get(f"/api/revisions/{proposal_id}/history", headers=headers("CEO"))
    assert history.status_code == 200
    assert [row["to_status"] for row in history.json()] == ["CHECK", "TINJAU_ULANG", "CHECK", "SOLVED"]
    image = client.get(f"/api/revisions/{proposal_id}/image", headers=headers("CEO"))
    assert image.content == PNG
    from app.models import AuditLog
    assert db.query(AuditLog).filter_by(entity="RevisionProposal", entity_id=proposal_id, action="STATUS_CHANGE").count() == 4


def test_only_reporter_or_ceo_can_review_check_result(client, headers):
    created = client.post("/api/revisions", headers=headers("CEO"), data={
        "module_name": "CFO-001", "bug_description": "Bug", "expected_behavior": "Expected",
        "owner_role": "CFO_MANAGER",
    })
    proposal_id = created.json()["id"]
    path = f"/api/revisions/{proposal_id}/status"
    checked = client.patch(path, headers=headers("CFO_MANAGER"), json={
        "expected_status": "REVISI", "status": "CHECK", "note": "Sudah diperbaiki."})
    assert checked.status_code == 200
    assert checked.json()["allowed_next_statuses"] == []
    forbidden = client.patch(path, headers=headers("CMO_SUPPORT"), json={
        "expected_status": "CHECK", "status": "SOLVED", "note": ""})
    assert forbidden.status_code == 403
    solved = client.patch(path, headers=headers("CEO"), json={
        "expected_status": "CHECK", "status": "SOLVED", "note": "Sesuai."})
    assert solved.status_code == 200


def test_title_update_and_recheck_title_on_status_change(client, headers):
    created = client.post("/api/revisions", headers=headers("CMO_SUPPORT"), data={
        "module_name": "CMO Support - Test",
        "bug_description": "Bug description",
        "expected_behavior": "Expected behavior",
        "owner_role": "CMO_SUPPORT",
    })
    assert created.status_code == 201
    prop_id = created.json()["id"]

    # 1. Update title directly
    title_res = client.patch(f"/api/revisions/{prop_id}/title", headers=headers("CMO_SUPPORT"), json={
        "module_name": "#RECHECK1 CMO Support - Test"
    })
    assert title_res.status_code == 200
    assert title_res.json()["module_name"] == "#RECHECK1 CMO Support - Test"

    # 2. Update status to CHECK with module_name
    status_res = client.patch(f"/api/revisions/{prop_id}/status", headers=headers("CMO_SUPPORT"), json={
        "expected_status": "REVISI",
        "status": "CHECK",
        "note": "Perbaikan selesai",
        "module_name": "#RECHECK12 CMO Support - Test"
    })
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "CHECK"
    assert status_res.json()["module_name"] == "#RECHECK12 CMO Support - Test"
