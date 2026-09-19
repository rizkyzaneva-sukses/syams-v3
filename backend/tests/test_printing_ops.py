"""Printing: task/eligibility, batas transisi status, target harian & makloon.

Revisi #41 (PRN-I-002 Task, Assignment & Eligibility), #42 (PRN-I-003 Batas
Proses & Status Transition), #46 (PRN-I-007 Internal Production & Makloon
Embroidery), #47 (PRN-I-008 Target Harian, Integrasi, Exception & Audit).

Router baru ini belum didaftarkan orkestrator di `main.py` (lihat
REQUESTS/printing_ops.md), jadi tes memanggil `include_router` sendiri seperti
diwajibkan AGENT-RULES.md bagian 3. Semua angka berasal dari tabel yang sudah
ada (`production_movements`, `articles`, `orders`, `spks`, `exceptions`,
`audit_logs`) — tidak ada tabel baru yang diasumsikan ada.
"""
from datetime import date, timedelta

from app import models as m
from app.main import app
from app.routers.printing_ops import ACTION_ROLES, STATUS_TRANSITIONS, is_printing_process
from app.routers.printing_ops import router as printing_ops_router

# Idempoten: pytest bisa mengimpor modul ini lebih dari sekali dalam satu sesi.
if not any(getattr(route, "path", "").startswith("/api/printing/daily-target") for route in app.routes):
    app.include_router(printing_ops_router, prefix="/api")

PRINTING_ROUTE = "Cutting > Printing > Bordir > QC > Packing"


def api(client, headers, role, method, path, body=None, expected=200):
    response = client.request(method, path, headers=headers(role), json=body)
    assert response.status_code == expected, response.text
    return response.json() if response.content else None


def signal(job):
    """Status/tindakan yang benar-benar boleh dilakukan sekarang.

    ``allowed_next_statuses`` memuat entri status (dua entri bisa menuju status
    sama), ``signal_statuses`` memuat nilai uniknya supaya assertion tidak
    bergantung pada duplikasi.
    """
    return {
        "actions": list(job["allowed_actions"]),
        "statuses": list(job["allowed_next_statuses"]),
        "signal_statuses": sorted(set(job["allowed_next_statuses"])),
    }


def make_order(db, order_id="SO-PRT-1", route=PRINTING_ROUTE, qty=500, spk_status="RELEASED", with_spk=True):
    order = m.Order(order_id=order_id, buyer="Buyer Printing", order_type=m.OrderType.REPEAT_PRODUCTION)
    db.add(order)
    db.flush()
    article = m.Article(order_fk=order.id, article_code=f"{order_id}-A1", garment_type="T-Shirt",
                        qty=qty, production_route=route)
    db.add(article)
    if with_spk:
        db.add(m.SPK(order_fk=order.id, spk_no=f"SPK-{order_id}", status=spk_status, version=2))
    db.commit()
    return order, article


def add_movement(db, article, process, qty_in=0, qty_done=0, qty_reject=0, status="IN_PROCESS",
                 pic="Iman", target_date=None, reason=None):
    row = m.ProductionMovement(article_id=article.id, process=process, qty_in=qty_in,
                               qty_done=qty_done, qty_reject=qty_reject, status=status,
                               pic_name=pic, target_date=target_date, reject_reason=reason)
    db.add(row)
    db.commit()
    return row


# ── Autentikasi & RBAC ──────────────────────────────────────────────────────
def test_endpoints_require_authentication(client):
    assert client.get("/api/printing/daily-target").status_code == 401
    assert client.get("/api/printing/eligibility").status_code == 401
    assert client.get("/api/printing/prerequisites").status_code == 401


def test_roles_outside_printing_are_rejected(client, headers, db):
    make_order(db, order_id="SO-PRT-RBAC")
    for role in ("CHRO_MANAGER", "HR_SUPPORT", "CMO_SUPPORT"):
        api(client, headers, role, "GET", "/api/printing/daily-target", expected=403)
        api(client, headers, role, "GET", "/api/printing/eligibility", expected=403)
    for role in ("CEO", "COO_MANAGER", "PRINTING_PIC", "PRODUCTION_PIC", "SAMPLE_PIC"):
        api(client, headers, role, "GET", "/api/printing/daily-target")
        api(client, headers, role, "GET", "/api/printing/eligibility")


# ── Revisi #41 — Task, Assignment & Eligibility ─────────────────────────────
def test_prerequisites_expose_task_contract_fields(client, headers, db):
    order, _ = make_order(db, order_id="SO-PRT-41")
    db.add(m.SampleRecord(order_fk=order.id, article_code="SO-PRT-41-A1", status="APPROVED",
                          requested_date=date.today()))
    db.commit()

    body = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/prerequisites")
    row = body["rows"][0]
    assert row["lifecycle"] == ["OPEN", "IN_PROGRESS", "UPDATE", "SUBMIT_RESULT", "DONE"]
    fields = {item["field"]: item["present"] for item in row["task_fields"]}
    # Setiap field wajib task hadir sebagai kontrak, meski sebagian belum ada
    # kolomnya (batch_id = false, itu kebutuhan yang diminta ke orkestrator).
    assert set(fields) == {"job_id", "order_id", "article_id", "batch_id", "spk_version",
                           "artwork_version", "ppm_version", "sample_version", "assignee_team",
                           "priority", "due_sla", "status", "blocker", "next_handoff"}
    assert fields["job_id"] and fields["order_id"] and fields["article_id"]
    assert fields["spk_version"] is True
    assert fields["sample_version"] is True and fields["artwork_version"] is True
    assert row["spk_released"] is True and row["spk_version"] == 2
    assert row["requirement_version"] == "SPK-SO-PRT-41@v2"
    assert row["job_count"] == 2


def test_task_is_blocked_when_spk_is_not_released(client, headers, db):
    make_order(db, order_id="SO-PRT-41B", spk_status="DRAFT")
    body = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/prerequisites")
    row = body["rows"][0]
    assert row["spk_released"] is False
    assert row["status"] == "BLOCKED"
    assert "RELEASED" in row["blocker"]


# ── Revisi #42 — Batas proses & transisi status ─────────────────────────────
def test_eligibility_only_owns_printing_stages_and_bounds_transitions(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-42")
    add_movement(db, article, "Cutting", 500, 500, 0, status="DONE", pic="Budi")
    add_movement(db, article, "Printing", 500, 200, 0, status="IN_PROCESS", target_date=date.today())
    add_movement(db, article, "Bordir", 0, 0, 0, status="WAITING")

    body = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/eligibility")

    # Rute lengkap tetap terlihat (urutan proses), tapi job hanya dibuat untuk
    # tahapan Printing/Bordir — Cutting tidak pernah ditawarkan sebagai job.
    assert {job["stage"] for job in body["jobs"]} == {"Printing", "Bordir"}
    stages = [job["stage"] for job in body["jobs"]]
    assert all(is_printing_process(stage) for stage in stages)
    assert "Cutting" not in stages and "Packing" not in stages
    assert all("CUTTING" in job["production_route"] for job in body["jobs"])
    assert all(job["sequence"] > 1 for job in body["jobs"])
    assert body["owned_processes"] == ["PRINTING", "BORDIR"]

    printing = next(job for job in body["jobs"] if job["stage"] == "Printing")
    assert printing["current_status"] == "IN_PROCESS"
    # Tidak semua status bebas dipilih: WAITING -> DONE tidak ada.
    assert signal(printing)["signal_statuses"] == ["DONE", "HOLD", "IN_PROCESS"]
    assert "WAITING" not in printing["allowed_next_statuses"]
    assert signal(printing)["actions"] == ["UPDATE_PROGRESS", "REPORT_RESULT", "HOLD", "SUBMIT_RESULT"]

    bordir = next(job for job in body["jobs"] if job["stage"] == "Bordir")
    assert bordir["current_status"] == "WAITING"
    assert signal(bordir)["signal_statuses"] == ["HOLD", "IN_PROCESS"]
    assert "DONE" not in bordir["allowed_next_statuses"]   # WAITING tidak bisa langsung DONE
    assert bordir["handoff"]["next_stage"] == "QC"          # handoff ke tahap berikutnya di rute
    assert bordir["handoff"]["reconciled"] is False          # belum ada output

    # Status DONE hanya sah lewat SUBMIT_RESULT, dan DONE hanya bisa dibuka COO.
    assert [entry["to"] for entry in STATUS_TRANSITIONS["WAITING"]] == ["IN_PROCESS", "HOLD"]
    assert STATUS_TRANSITIONS["IN_PROCESS"][-1]["to"] == "DONE"
    assert STATUS_TRANSITIONS["IN_PROCESS"][-1]["action"] == "SUBMIT_RESULT"
    assert STATUS_TRANSITIONS["DONE"][0]["action"] == "REOPEN"
    assert ACTION_ROLES["SUBMIT_RESULT"] == ("PRINTING_PIC",)


def test_eligibility_rejects_process_outside_printing_and_blocks_unreconciled_result(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-42B")
    add_movement(db, article, "Printing", 500, 400, 100, status="IN_PROCESS", reason=None,
                 target_date=date.today())

    body = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/eligibility")
    printing = next(job for job in body["jobs"] if job["stage"] == "Printing")
    codes = {blocker["code"] for blocker in printing["blockers"]}
    assert "REJECT_NO_DISPOSITION" in codes       # reject 100 tanpa alasan -> belum boleh DONE
    assert printing["eligible"] is False
    assert "SUBMIT_RESULT" in printing["allowed_actions"]          # tindakan tetap ditawarkan
    assert signal(printing)["signal_statuses"] == ["DONE", "HOLD", "IN_PROCESS"]
    done_entry = next(entry for entry in STATUS_TRANSITIONS["IN_PROCESS"] if entry["to"] == "DONE")
    assert done_entry["action"] == "SUBMIT_RESULT"
    assert any("remaining WIP nol" in item for item in done_entry["requires"])
    assert printing["reject_closed"] is False
    # Handoff belum terekonsiliasi selama reject belum berdisposisi.
    assert printing["remaining_wip"] == 0 and printing["handoff"]["reconciled"] is False

    # Proses di luar kewenangan Printing tercatat sebagai proses milik role lain.
    cutting = next(item for item in body["process_owners"] if item["process"] == "CUTTING")
    assert cutting["owner_role"] == "PRODUCTION_PIC" and cutting["eligible_role"] != "PRINTING_PIC"
    assert is_printing_process("Bordir ") is True
    assert is_printing_process("Sewing") is False

    # Rute artikel tanpa tahap Printing tidak pernah menghasilkan job Printing.
    _, other = make_order(db, order_id="SO-PRT-42C", route="Cutting > Sewing > QC")
    add_movement(db, other, "Sewing", 10, 0, 0, status="IN_PROCESS")
    rows = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/eligibility")["jobs"]
    assert all(job["order_id"] != "SO-PRT-42C" for job in rows)


def test_eligibility_documents_domain_boundaries(client, headers, db):
    make_order(db, order_id="SO-PRT-42D")
    body = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/eligibility")
    boundaries = {item["field"]: item for item in body["domain_boundaries"]}
    assert boundaries["rate"]["owner_role"] == "CFO_MANAGER" and boundaries["rate"]["printing_allowed"] is False
    assert boundaries["payable"]["printing_allowed"] is False
    assert boundaries["physical_output"]["printing_allowed"] is True
    # Status yang terdaftar terbatas, bukan teks bebas.
    assert body["registered_statuses"] == ["WAITING", "IN_PROCESS", "HOLD", "DONE"]
    assert body["read_only_boundaries"]


# ── Revisi #47 — Target harian, mismatch, exception & audit ─────────────────
def test_daily_target_compares_target_with_realised_output(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-47")
    today = date.today()
    add_movement(db, article, "Printing", 500, 480, 20, status="IN_PROCESS", target_date=today)
    add_movement(db, article, "Bordir", 300, 120, 0, status="IN_PROCESS", target_date=today)
    add_movement(db, article, "Cutting", 500, 500, 0, status="DONE", pic="Budi", target_date=today)

    body = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/daily-target")
    assert body["on_date"] == today.isoformat()
    assert {row["process"] for row in body["rows"]} == {"Printing", "Bordir"}   # Cutting tidak dihitung

    printing = next(row for row in body["rows"] if row["process"] == "Printing")
    assert printing["target_qty"] == 500 and printing["realised_qty"] == 480
    assert printing["attainment_percent"] == 96.0
    assert printing["remaining_vs_target"] == 20 and printing["status"] == "PARTIAL"
    assert printing["achieved"] is False

    bordir = next(row for row in body["rows"] if row["process"] == "Bordir")
    assert bordir["target_qty"] == 300 and bordir["realised_qty"] == 120

    assert body["totals"]["target_qty"] == 800
    assert body["totals"]["realised_qty"] == 600
    assert body["totals"]["attainment_percent"] == 75.0
    assert body["totals"]["achieved_jobs"] == 0 and body["totals"]["unachieved_jobs"] == 2
    # Target yang terlewat dilaporkan sebagai mismatch, bukan didiamkan.
    assert {item["code"] for item in body["mismatch"]} == {"MISSED_TARGET"}
    assert body["mismatch_count"] == 2
    assert body["daily_reconciliation"]["identity"] == "qty_in = qty_done + qty_reject + remaining_wip"
    assert body["daily_reconciliation"]["balanced"] is True

    # Tanggal lain tidak mengambil target hari ini.
    other_day = api(client, headers, "PRINTING_PIC", "GET",
                    f"/api/printing/daily-target?on_date={(today - timedelta(days=1)).isoformat()}")
    assert other_day["totals"]["target_qty"] == 0
    assert all(row["status"] == "NO_TARGET" for row in other_day["rows"])


def test_daily_target_flags_realised_without_target_and_needs_cfo_for_rate(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-47B")
    add_movement(db, article, "Printing", 100, 100, 0, status="DONE", target_date=None)

    body = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/daily-target")
    row = next(item for item in body["rows"] if item["process"] == "Printing")
    assert row["target_qty"] == 0 and row["realised_qty"] == 0
    assert row["status"] == "NO_TARGET"
    assert body["rate_boundary"]["rate_owner"] == "CFO_MANAGER"
    assert body["rate_boundary"]["printing_can_change_rate"] is False
    assert body["internal_production"]["owner_role"] == "PRINTING_PIC"
    assert body["target_source"]["rate_owner"] == "CFO_MANAGER"


def test_daily_target_shows_exception_and_audit(client, headers, db, users):
    order, article = make_order(db, order_id="SO-PRT-47C")
    today = date.today()
    movement = add_movement(db, article, "Printing", 500, 100, 0, status="IN_PROCESS", target_date=today)
    db.add(m.ExceptionItem(order_fk=order.id, severity="RED", category="Printing Delay",
                           title="Printing tertinggal dari target harian", status="OPEN",
                           owner_role="PRINTING_PIC", source_module="Printing",
                           source_entity="ProductionMovement", source_entity_id=movement.id,
                           impact="Bordir & QC tergeser", recommendation="Tambah shift",
                           decision_required=False))
    db.add(m.ExceptionItem(order_fk=order.id, severity="YELLOW", category="Finance",
                           title="Rate & payable menunggu CFO", status="OPEN", owner_role="CFO_MANAGER"))
    db.add(m.AuditLog(user_id=users[m.Role.PRINTING_PIC].id, action="UPDATE", entity="ProductionMovement",
                      entity_id=movement.id, order_id=order.order_id, source_module="ProductionMovement",
                      previous_status="WAITING", new_status="IN_PROCESS", reason="mulai printing",
                      detail="qty_done 100"))
    db.commit()

    body = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/daily-target")
    # Hanya exception ber-scope Printing/Bordir yang muncul; exception finance
    # (kategori Finance) tetap milik CFO dan tidak ikut.
    assert body["exception_count"] == 1
    assert body["exceptions"][0]["severity"] == "RED"
    assert body["exceptions"][0]["category"] == "Printing Delay"
    assert body["exceptions"][0]["source_entity_id"] == movement.id
    assert all(item["category"] != "Finance" for item in body["exceptions"])
    assert body["audit_count"] == 1
    entry = body["audit"][0]
    assert entry["previous_status"] == "WAITING" and entry["new_status"] == "IN_PROCESS"
    assert entry["reason"] == "mulai printing" and entry["order_id"] == "SO-PRT-47C"
    assert entry["actor_id"] == users[m.Role.PRINTING_PIC].id


# ── Revisi #46 — Internal production & makloon embroidery ───────────────────
def test_makloon_activity_is_separated_from_internal_production(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-46")
    today = date.today()
    add_movement(db, article, "Printing", 300, 300, 0, status="DONE", pic="Iman", target_date=today)
    add_movement(db, article, "Bordir", 200, 150, 10, status="IN_PROCESS", pic="CV Bordir Jaya",
                 target_date=today)
    add_movement(db, article, "Bordir", 50, 0, 0, status="WAITING", pic="CV Bordir Jaya")

    body = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/daily-target")

    vendors = body["makloon"]["vendors"]
    assert [vendor["vendor"] for vendor in vendors] == ["CV Bordir Jaya"]
    vendor = vendors[0]
    assert vendor["qty_sent"] == 250 and vendor["qty_returned"] == 160
    assert vendor["qty_accepted"] == 150 and vendor["qty_rejected"] == 10
    assert vendor["outstanding_external_wip"] == 90
    assert vendor["job_count"] == 2
    assert {job["process"] for job in vendor["jobs"]} == {"Bordir"}
    assert body["makloon"]["outstanding_external_wip"] == 90
    assert body["makloon"]["cost_owner"] == "CFO_MANAGER"
    # Iman (internal) tidak dihitung sebagai vendor makloon.
    assert body["internal_production"]["owner_role"] == "PRINTING_PIC"
    assert "machine" in body["internal_production"]["fields"]
    assert body["internal_production"]["machine_shift_columns_present"] is False
    assert "qty_sent" in body["makloon"]["required_fields"]


def test_daily_target_scopes_to_one_order(client, headers, db):
    _, article_a = make_order(db, order_id="SO-PRT-47D")
    order_b, article_b = make_order(db, order_id="SO-PRT-47E")
    today = date.today()
    add_movement(db, article_a, "Printing", 100, 100, 0, status="DONE", target_date=today)
    add_movement(db, article_b, "Printing", 400, 0, 0, status="WAITING", target_date=today)

    body = api(client, headers, "COO_MANAGER", "GET", f"/api/printing/daily-target?order_fk={order_b.id}")
    # Dua job Printing/Bordir milik satu order: Printing (di-target hari ini) dan
    # Bordir (belum di-target). Yang penting: order lain tidak ikut terbawa.
    assert len(body["rows"]) == 2
    assert {row["order_id"] for row in body["rows"]} == {"SO-PRT-47E"}
    assert {row["process"] for row in body["rows"]} == {"Printing", "BORDIR"}
    printing = next(row for row in body["rows"] if row["process"] == "Printing")
    assert printing["target_qty"] == 400 and printing["realised_qty"] == 0
    bordir = next(row for row in body["rows"] if row["process"] == "BORDIR")
    assert bordir["target_qty"] == 0 and bordir["status"] == "NO_TARGET"
    assert body["totals"]["target_qty"] == 400
    assert body["totals"]["jobs"] == 1               # hanya job yang punya target/realisasi
    assert body["totals"]["attainment_percent"] == 0.0


def test_zero_input_movement_is_visible_and_never_negative(client, headers, db):
    _, article = make_order(db, order_id="SO-PRT-47F")
    add_movement(db, article, "Printing", 0, 0, 0, status="WAITING", target_date=None)

    body = api(client, headers, "PRINTING_PIC", "GET", "/api/printing/daily-target")
    row = next(item for item in body["rows"] if item["process"] == "Printing")
    assert row["qty_in"] == 0 and row["remaining_wip"] == 0
    assert row["movement_ids"] and row["status"] == "NO_TARGET"
    assert body["daily_reconciliation"]["rows_without_target"] >= 1
