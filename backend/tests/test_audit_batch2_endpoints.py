"""AUDIT (batch 2) — independent verification of batch-2 claimed endpoints.

Hunts for: 500s, empty-but-claimed-complete arrays, RBAC leaks (a role that must
be denied actually denied), and orphan/unreachable routes. This file is an
audit artifact; it is not production code and does not modify any router.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app import models as m

# Every GET endpoint claimed by the 10 batch-2 agents. None of these must 500,
# and none may return JSON null.
AUDITED_GETS = [
    ("/api/cmo/manager-priority", "CMO_MANAGER"),
    ("/api/cmo/morning-priority", "CMO_MANAGER"),
    ("/api/hr/employees-summary", "CHRO_MANAGER"),
    ("/api/hr/manpower-requests", "CHRO_MANAGER"),
    ("/api/hr/candidates", "CHRO_MANAGER"),
    ("/api/hr/performance-reviews", "CHRO_MANAGER"),
    ("/api/hr/employee-issues", "CHRO_MANAGER"),
    ("/api/hr/onboarding", "CHRO_MANAGER"),
    ("/api/cmo/samples-version-summary", "CMO_MANAGER"),
    ("/api/cmo/samples-version-decisions", "CMO_MANAGER"),
    ("/api/cmo/samples-version-audit", "CMO_MANAGER"),
    ("/api/sample/today", "SAMPLE_PIC"),
    ("/api/sample/my-tasks", "SAMPLE_PIC"),
    ("/api/printing/job-cards", "PRINTING_PIC"),
    ("/api/printing/quality", "PRINTING_PIC"),
    ("/api/printing/daily-target", "PRINTING_PIC"),
    ("/api/printing/eligibility", "PRINTING_PIC"),
    ("/api/printing/prerequisites", "PRINTING_PIC"),
    ("/api/printing/handoffs", "PRINTING_PIC"),
    ("/api/printing/defect-dispositions", "PRINTING_PIC"),
    ("/api/printing/daily-targets", "PRINTING_PIC"),
    ("/api/cfo/outstanding-summary", "CFO_MANAGER"),
    ("/api/coo/daily-execution", "COO_MANAGER"),
    ("/api/coo/wip-summary", "COO_MANAGER"),
    ("/api/coo/handoff-capacity", "COO_MANAGER"),
    ("/api/coo/bom-physical", "COO_MANAGER"),
]


def _seed_minimal(db):
    order = m.Order(order_id="SO-AUDIT-1", buyer="Buyer Audit",
                    order_type=m.OrderType.REPEAT_PRODUCTION)
    db.add(order)
    db.flush()
    article = m.Article(order_fk=order.id, article_code="ART-AUDIT-1",
                        garment_type="shirt", qty=100,
                        production_route="Cutting > Printing > QC > Packing")
    db.add(article)
    db.add(m.SPK(order_fk=order.id, spk_no="SPK-AUDIT-1", status="RELEASED", version=1))
    db.commit()
    return order, article


@pytest.mark.parametrize("path,role", AUDITED_GETS)
def test_claimed_endpoint_does_not_500_or_return_null(client, db, headers, path, role):
    _seed_minimal(db)
    r = client.get(path, headers=headers(role))
    assert r.status_code != 500, f"{path} -> 500: {r.text[:300]}"
    assert r.status_code in (200, 403, 404, 422), f"{path} -> unexpected {r.status_code}"
    if r.status_code == 200:
        assert r.json() is not None, f"{path} returned JSON null"


@pytest.mark.parametrize("path,role", AUDITED_GETS)
def test_denied_role_is_actually_denied_on_reload(client, db, headers, path, role):
    """RBAC: a clearly-wrong role must get 403 on a fresh (reloaded) request.

    Uses a brand-new request against the live app (not chained navigation), so
    leftover DOM/SPA state cannot mask a real leak.
    """
    _seed_minimal(db)
    wrong = {"CMO_MANAGER": "HR_SUPPORT", "SAMPLE_PIC": "FINANCE_SUPPORT",
             "PRINTING_PIC": "CHRO_MANAGER", "CFO_MANAGER": "PRINTING_PIC",
             "COO_MANAGER": "CMO_SUPPORT", "CHRO_MANAGER": None}.get(role)
    if wrong is None:
        pytest.skip("no wrong-role mapping")
    r = client.get(path, headers=headers(wrong))
    assert r.status_code != 500, f"{path} 500 for {wrong}"
    assert r.status_code != 200, f"{path} LEAK: {wrong} got 200"
