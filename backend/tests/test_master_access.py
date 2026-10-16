"""RBAC regression: HR roles (CHRO_MANAGER, HR_SUPPORT) may READ Master Control.

The Master Control page (/master) is read-only for everyone. The only write
endpoint /api/master/wip-capacity (POST) stays COO_MANAGER-only.
"""
from app.models import Role

NEW_READ_ROLES = ["CHRO_MANAGER", "HR_SUPPORT"]
LEGACY_MASTER_ROLES = [
    "CEO", "CMO_MANAGER", "CMO_SUPPORT", "CFO_MANAGER",
    "COO_MANAGER", "SAMPLE_PIC", "PRINTING_PIC", "PRODUCTION_PIC", "SHIPMENT_ADMIN",
]
MASTER_READ_ENDPOINTS = [
    "/api/master/summary",
    "/api/master/morning-priority",
    "/api/master/wip-capacity",
    "/api/master/forecast",
]


def test_new_hr_roles_can_read_master_control(client, headers):
    for role in NEW_READ_ROLES:
        auth = headers(role)
        for endpoint in MASTER_READ_ENDPOINTS:
            resp = client.get(endpoint, headers=auth)
            assert resp.status_code == 200, f"{role} GET {endpoint} -> {resp.status_code}: {resp.text}"
        resp = client.get("/api/orders", headers=auth)
        assert resp.status_code == 200, f"{role} GET /api/orders -> {resp.status_code}: {resp.text}"


def test_master_summary_requires_token(client):
    resp = client.get("/api/master/summary")
    assert resp.status_code in (401, 403), f"unauth -> {resp.status_code}"


def test_wip_capacity_write_stays_coo_only(client, headers):
    snapshot = {"process": "Sewing", "snapshot_date": "2026-10-16", "capacity": 500, "planned_load": 600}
    chro = client.post("/api/master/wip-capacity", json=snapshot, headers=headers("CHRO_MANAGER"))
    assert chro.status_code == 403, f"CHRO_MANAGER POST -> {chro.status_code}: {chro.text}"
    coo = client.post("/api/master/wip-capacity", json=snapshot, headers=headers("COO_MANAGER"))
    assert coo.status_code == 200, f"COO_MANAGER POST -> {coo.status_code}: {coo.text}"


def test_legacy_master_roles_still_read_summary(client, headers):
    assert len(LEGACY_MASTER_ROLES) == 9
    for role in LEGACY_MASTER_ROLES:
        resp = client.get("/api/master/summary", headers=headers(role))
        assert resp.status_code == 200, f"{role} GET /api/master/summary -> {resp.status_code}: {resp.text}"


def test_role_enum_contains_new_roles():
    assert Role.CHRO_MANAGER.value == "CHRO_MANAGER"
    assert Role.HR_SUPPORT.value == "HR_SUPPORT"
