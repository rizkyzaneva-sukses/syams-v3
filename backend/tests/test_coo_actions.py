"""Kontrak aksi eksekusi produksi — revisi #53 (COO-S-005).

Menguji bahwa enam aksi punya arti yang pasti dan kewenangan yang melekat pada
peran, bukan pada siapa pun yang membuka halaman. Tanpa DB: kontraknya murni.
"""
import pytest

from app import coo_actions as ca


def test_six_actions_exist_in_blueprint_order():
    assert list(ca.ALLOWED_ACTIONS) == [
        "START", "UPDATE_PROGRESS", "REPORT_OUTPUT", "COMPLETE", "HOLD", "HANDOFF"
    ]
    for action in ca.ALLOWED_ACTIONS:
        assert ca.spec_for(action) is not None, action


def test_each_action_has_a_defined_target_status():
    assert ca.status_for("START") == ca.IN_PROCESS
    assert ca.status_for("UPDATE_PROGRESS") == ca.IN_PROCESS
    assert ca.status_for("REPORT_OUTPUT") == ca.IN_PROCESS
    assert ca.status_for("COMPLETE") == ca.DONE
    assert ca.status_for("HOLD") == ca.HOLD_STATUS
    assert ca.status_for("HANDOFF") == ca.DONE


def test_unknown_action_is_rejected():
    assert ca.spec_for("DELETE_EVERYTHING") is None
    verdict = ca.evaluate("DROP_TABLE", "COO_MANAGER")
    assert verdict["allowed"] is False
    assert verdict["known_action"] is False
    assert verdict["blockers"][0]["code"] == "UNKNOWN_ACTION"


def test_complete_and_handoff_are_coo_manager_only():
    # Inti revisi: mengunci output dan memindahkan qty bukan milik PIC lantai.
    assert ca.roles_for("COMPLETE") == {"COO_MANAGER"}
    assert ca.roles_for("HANDOFF") == {"COO_MANAGER"}
    assert ca.can_run("COMPLETE", "COO_MANAGER") is True
    assert ca.can_run("COMPLETE", "PRODUCTION_PIC") is False
    assert ca.can_run("HANDOFF", "PRINTING_PIC") is False


def test_floor_actions_belong_to_production_pic():
    for action in ("START", "UPDATE_PROGRESS", "REPORT_OUTPUT"):
        assert ca.can_run(action, "PRODUCTION_PIC") is True, action
        assert ca.can_run(action, "COO_MANAGER") is True, action


def test_hold_is_available_to_pics_so_the_floor_never_jams():
    for role in ("COO_MANAGER", "PRODUCTION_PIC", "PRINTING_PIC"):
        assert ca.can_run("HOLD", role) is True, role
    # Peran di luar lantai tidak boleh menahan proses produksi.
    for role in ("CFO_MANAGER", "CMO_MANAGER", "HR_SUPPORT", "SHIPMENT_ADMIN", "SAMPLE_PIC"):
        assert ca.can_run("HOLD", role) is False, role


def test_actions_for_role_returns_only_authorised_actions_in_order():
    assert ca.actions_for_role("PRODUCTION_PIC") == [
        "START", "UPDATE_PROGRESS", "REPORT_OUTPUT", "HOLD"
    ]
    assert ca.actions_for_role("COO_MANAGER") == list(ca.ALLOWED_ACTIONS)
    assert ca.actions_for_role("CFO_MANAGER") == []


def test_hold_requires_a_reason():
    spec = ca.spec_for("HOLD")
    assert spec["reason_required"] is True
    assert "reason" in spec["required_fields"]


def test_role_mismatch_is_explained_with_the_allowed_roles():
    verdict = ca.evaluate("COMPLETE", "PRODUCTION_PIC")
    assert verdict["allowed"] is False
    blocker = next(b for b in verdict["blockers"] if b["code"] == "ROLE_NOT_AUTHORISED")
    assert "COO_MANAGER" in blocker["detail"]
    assert "PRODUCTION_PIC" in blocker["detail"]


def test_complete_blocked_while_wip_is_open_and_allowed_once_reconciled():
    open_bucket = {"process": "Cutting", "qty_in": 100, "qty_done": 60,
                   "qty_reject": 5, "statuses": {"IN_PROCESS"}}
    verdict = ca.evaluate("COMPLETE", "COO_MANAGER", bucket=open_bucket, route=["Cutting", "Sewing"])
    codes = {b["code"] for b in verdict["blockers"]}
    assert "WIP_NOT_RECONCILED" in codes
    assert verdict["allowed"] is False
    assert verdict["wip"] == 35

    closed_bucket = {"process": "Cutting", "qty_in": 100, "qty_done": 95,
                     "qty_reject": 5, "statuses": {"IN_PROCESS"}}
    verdict = ca.evaluate("COMPLETE", "COO_MANAGER", bucket=closed_bucket, route=["Cutting", "Sewing"])
    assert verdict["allowed"] is True
    assert verdict["to_status"] == ca.DONE


def test_over_accounted_quantity_blocks_progress_update():
    bucket = {"process": "Cutting", "qty_in": 100, "qty_done": 90, "qty_reject": 20,
              "statuses": {"IN_PROCESS"}}
    verdict = ca.evaluate("UPDATE_PROGRESS", "PRODUCTION_PIC", bucket=bucket)
    assert verdict["allowed"] is False
    assert {b["code"] for b in verdict["blockers"]} == {"QTY_OVER_ACCOUNTED"}
    assert verdict["wip"] == -10


def test_already_done_process_cannot_be_restarted():
    bucket = {"process": "Cutting", "qty_in": 100, "qty_done": 100, "qty_reject": 0,
              "statuses": {"DONE"}}
    verdict = ca.evaluate("START", "COO_MANAGER", bucket=bucket)
    assert verdict["allowed"] is False
    assert "ALREADY_DONE" in {b["code"] for b in verdict["blockers"]}


def test_report_output_requires_actual_output():
    bucket = {"process": "Sewing", "qty_in": 50, "qty_done": 0, "qty_reject": 0,
              "statuses": {"WAITING"}}
    verdict = ca.evaluate("REPORT_OUTPUT", "PRODUCTION_PIC", bucket=bucket)
    assert verdict["allowed"] is False
    assert "NO_OUTPUT" in {b["code"] for b in verdict["blockers"]}


def test_handoff_must_target_the_next_process_in_the_route():
    bucket = {"process": "Cutting", "qty_in": 100, "qty_done": 100, "qty_reject": 0,
              "statuses": {"IN_PROCESS"}}
    route = ["Cutting", "Sewing", "QC"]
    ok = ca.evaluate("HANDOFF", "COO_MANAGER", bucket=bucket, qty_sent=100,
                     to_process="Sewing", route=route)
    assert ok["allowed"] is True, ok["blockers"]

    wrong = ca.evaluate("HANDOFF", "COO_MANAGER", bucket=bucket, qty_sent=100,
                        to_process="QC", route=route)
    assert wrong["allowed"] is False
    assert "WRONG_DOWNSTREAM_PROCESS" in {b["code"] for b in wrong["blockers"]}


def test_handoff_from_last_process_is_refused():
    bucket = {"process": "QC", "qty_in": 30, "qty_done": 30, "qty_reject": 0,
              "statuses": {"IN_PROCESS"}}
    verdict = ca.evaluate("HANDOFF", "COO_MANAGER", bucket=bucket, qty_sent=30,
                          to_process="Packing", route=["Cutting", "Sewing", "QC"])
    assert verdict["allowed"] is False
    codes = {b["code"] for b in verdict["blockers"]}
    # Alasan sebenarnya adalah tidak ada langkah berikutnya — bukan to_process kosong.
    assert "NO_DOWNSTREAM_PROCESS" in codes
    assert "TO_PROCESS_REQUIRED" not in codes


def test_handoff_without_route_still_requires_to_process():
    bucket = {"process": "Cutting", "qty_in": 30, "qty_done": 30, "qty_reject": 0,
              "statuses": {"IN_PROCESS"}}
    verdict = ca.evaluate("HANDOFF", "COO_MANAGER", bucket=bucket, qty_sent=30,
                          to_process=None, route=None)
    assert verdict["allowed"] is False
    assert "TO_PROCESS_REQUIRED" in {b["code"] for b in verdict["blockers"]}


def test_handoff_cannot_send_more_than_was_produced():
    bucket = {"process": "Cutting", "qty_in": 100, "qty_done": 40, "qty_reject": 0,
              "statuses": {"IN_PROCESS"}}
    verdict = ca.evaluate("HANDOFF", "COO_MANAGER", bucket=bucket, qty_sent=80,
                          to_process="Sewing", route=["Cutting", "Sewing"])
    assert verdict["allowed"] is False
    assert "QTY_SENT_EXCEEDS_DONE" in {b["code"] for b in verdict["blockers"]}

    zero = ca.evaluate("HANDOFF", "COO_MANAGER", bucket=bucket, qty_sent=0,
                       to_process="Sewing", route=["Cutting", "Sewing"])
    assert "QTY_SENT_REQUIRED" in {b["code"] for b in zero["blockers"]}


def test_late_is_context_not_a_blocker():
    from datetime import date, timedelta
    bucket = {"process": "Cutting", "qty_in": 100, "qty_done": 100, "qty_reject": 0,
              "statuses": {"IN_PROCESS"}}
    verdict = ca.evaluate("COMPLETE", "COO_MANAGER", bucket=bucket,
                          target_date=date.today() - timedelta(days=3), today=date.today())
    assert verdict["allowed"] is True
    assert verdict["late"] is True


def test_contract_payload_lists_authority_for_every_action():
    payload = ca.contract_payload("PRODUCTION_PIC")
    assert payload["allowed_actions"] == list(ca.ALLOWED_ACTIONS)
    assert payload["actions_for_actor"] == ["START", "UPDATE_PROGRESS", "REPORT_OUTPUT", "HOLD"]
    by_action = {row["action"]: row for row in payload["actions"]}
    assert by_action["COMPLETE"]["allowed_for_actor"] is False
    assert by_action["HANDOFF"]["allowed_for_actor"] is False
    assert by_action["START"]["allowed_for_actor"] is True
    assert by_action["COMPLETE"]["roles"] == ["COO_MANAGER"]
