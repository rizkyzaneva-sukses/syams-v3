"""Kontrak aksi eksekusi produksi (revisi #53, COO-S-005).

Papan eksekusi harian sebelumnya hanya menampilkan label status yang bisa
ditafsirkan bebas. Revisi #53 meminta enam aksi dengan arti yang pasti dan
kewenangan yang melekat pada peran — bukan pada siapa pun yang membuka
halaman. Modul ini adalah satu-satunya sumber kebenaran untuk:

* daftar aksi yang sah dan transisi status yang diizinkan tiap aksi;
* siapa yang boleh memicunya (COO_MANAGER, PRODUCTION_PIC, PRINTING_PIC);
* prasyarat yang harus dipenuhi sebelum aksi boleh dijalankan;
* field wajib pada payload tiap aksi.

Sengaja murni (tanpa DB, tanpa FastAPI) supaya bisa diuji dan dipakai ulang
oleh router mana pun tanpa risiko efek samping.
"""
from datetime import date

# ── Enam aksi revisi #53 ─────────────────────────────────────────────────────
START = "START"
UPDATE_PROGRESS = "UPDATE_PROGRESS"
REPORT_OUTPUT = "REPORT_OUTPUT"
COMPLETE = "COMPLETE"
HOLD = "HOLD"
HANDOFF = "HANDOFF"

# Urutan ini adalah urutan yang ditampilkan di UI dan diuji apa adanya.
ALLOWED_ACTIONS = (START, UPDATE_PROGRESS, REPORT_OUTPUT, COMPLETE, HOLD, HANDOFF)

# ── Status movement yang dipakai lantai produksi ─────────────────────────────
NOT_STARTED = "NOT_STARTED"
WAITING = "WAITING"
IN_PROCESS = "IN_PROCESS"
HOLD_STATUS = "HOLD"
DONE = "DONE"

# Status yang berarti proses masih menyimpan WIP terbuka.
OPEN_STATUSES = frozenset({WAITING, IN_PROCESS, HOLD_STATUS})


def _spec(action, to_status, roles, required_fields, requires_open, requires_closed,
          requires_output, reason_required, description):
    return {
        "action": action,
        "to_status": to_status,
        "roles": tuple(roles),
        "required_fields": tuple(required_fields),
        "requires_open_wip": requires_open,
        "requires_closed_wip": requires_closed,
        "requires_output": requires_output,
        "reason_required": reason_required,
        "description": description,
    }


# Kewenangan per peran adalah inti revisi: PRODUCTION_PIC boleh menjalankan
# lantai, tetapi tidak boleh mengunci output atau memindahkan barang ke proses
# berikutnya tanpa COO_MANAGER — pemindahan qty adalah titik sengketa
# kuantitas, jadi harus ada satu pihak yang bertanggung jawab penuh.
CONTRACT = {
    START: _spec(
        START, IN_PROCESS,
        roles=(  "COO_MANAGER", "PRODUCTION_PIC"),
        required_fields=("process", "qty_in", "pic_name"),
        requires_open=True, requires_closed=False, requires_output=False,
        reason_required=False,
        description="Mulai proses dari status NOT_STARTED/WAITING dengan qty_in yang sah",
    ),
    UPDATE_PROGRESS: _spec(
        UPDATE_PROGRESS, IN_PROCESS,
        roles=("COO_MANAGER", "PRODUCTION_PIC"),
        required_fields=("process", "qty_done"),
        requires_open=True, requires_closed=False, requires_output=False,
        reason_required=False,
        description="Perbarui qty_done/qty_reject tanpa menutup proses",
    ),
    REPORT_OUTPUT: _spec(
        REPORT_OUTPUT, IN_PROCESS,
        roles=("COO_MANAGER", "PRODUCTION_PIC"),
        # Reject wajib beralasan: reject tanpa disposisi tidak bisa ditelusuri.
        required_fields=("process", "qty_done", "pic_name"),
        requires_open=True, requires_closed=False, requires_output=True,
        reason_required=False,
        description="Laporkan output selesai + reject beserta alasannya",
    ),
    COMPLETE: _spec(
        COMPLETE, DONE,
        # Hanya COO_MANAGER yang boleh menutup proses: menutup berarti
        # menyatakan qty dan reject final.
        roles=("COO_MANAGER",),
        required_fields=("process",),
        requires_open=True, requires_closed=True, requires_output=True,
        reason_required=False,
        description="Tutup proses setelah output, reject, dan WIP terekonsiliasi",
    ),
    HOLD: _spec(
        HOLD, HOLD_STATUS,
        roles=("COO_MANAGER", "PRODUCTION_PIC", "PRINTING_PIC"),
        required_fields=("process", "reason"),
        requires_open=True, requires_closed=False, requires_output=False,
        reason_required=True,
        description="Tahan proses; alasan wajib agar tidak jadi tempat parkir diam-diam",
    ),
    HANDOFF: _spec(
        HANDOFF, DONE,
        # Handoff mengirim qty ke proses berikutnya — hanya COO_MANAGER.
        roles=("COO_MANAGER",),
        required_fields=("process", "to_process", "qty_sent"),
        requires_open=False, requires_closed=False, requires_output=True,
        reason_required=False,
        description="Kirim qty ke proses berikutnya; qty_sent terkunci setelah diterima",
    ),
}


def spec_for(action):
    """Ambil spesifikasi satu aksi, atau None kalau aksinya tidak dikenal."""
    return CONTRACT.get((action or "").strip().upper())


def roles_for(action):
    """Peran yang boleh memicu aksi."""
    spec = spec_for(action)
    return set(spec["roles"]) if spec else set()


def actions_for_role(role):
    """Daftar aksi yang boleh dijalankan peran ini, urut sesuai ALLOWED_ACTIONS."""
    return [a for a in ALLOWED_ACTIONS if role in roles_for(a)]


def can_run(action, role):
    """True kalau peran ini punya kewenangan atas aksi tersebut."""
    return role in roles_for(action)


def status_for(action):
    spec = spec_for(action)
    return spec["to_status"] if spec else None


def _bucket_totals(bucket):
    """qty_in/qty_done/qty_reject dari bucket rollup mana pun (dict atau None)."""
    bucket = bucket or {}
    return (
        int(bucket.get("qty_in") or 0),
        int(bucket.get("qty_done") or 0),
        int(bucket.get("qty_reject") or 0),
    )


def evaluate(action, role, bucket=None, target_date=None, today=None,
             qty_sent=0, upstream_available=None, to_process=None, route=None):
    """Putuskan boleh/tidaknya satu aksi, lengkap dengan alasannya.

    Mengembalikan dict ``{action, allowed, blockers, ...}`` sehingga endpoint
    bisa mengirim alasan yang bisa dibaca COO, bukan hanya 403 tanpa konteks.
    Blocker dikumpulkan semua, bukan berhenti di yang pertama, supaya satu
    perbaikan tidak mengungkap blocker berikutnya.
    """
    action = (action or "").strip().upper()
    blockers = []
    spec = spec_for(action)
    if spec is None:
        return {
            "action": action,
            "allowed": False,
            "known_action": False,
            "blockers": [{"code": "UNKNOWN_ACTION",
                          "detail": f"Aksi '{action}' tidak ada dalam kontrak revisi #53"}],
            "to_status": None,
            "roles": [],
        }

    if not can_run(action, role):
        allowed = sorted(spec["roles"])
        blockers.append({
            "code": "ROLE_NOT_AUTHORISED",
            "detail": f"{role} tidak berwenang menjalankan {action}; hanya {', '.join(allowed)}",
        })

    qty_in, qty_done, qty_reject = _bucket_totals(bucket)
    wip = qty_in - qty_done - qty_reject
    status = (bucket or {}).get("status")
    statuses = (bucket or {}).get("statuses")
    current = None
    if statuses:
        statuses = {str(s).upper() for s in statuses}
        current = (
            HOLD_STATUS if HOLD_STATUS in statuses
            else IN_PROCESS if IN_PROCESS in statuses
            else DONE if statuses == {DONE}
            else WAITING
        )
    elif status:
        current = str(status).upper()

    # Blocker kuantitas: WIP negatif berarti done+reject melebihi qty_in.
    if spec["requires_open_wip"] and bucket is not None:
        if current == DONE:
            blockers.append({"code": "ALREADY_DONE",
                             "detail": "Proses sudah DONE; tidak bisa diubah tanpa koreksi resmi"})
        elif wip < 0:
            blockers.append({
                "code": "QTY_OVER_ACCOUNTED",
                "detail": f"done+reject ({qty_done}+{qty_reject}) melebihi qty_in ({qty_in})",
            })

    if spec["requires_closed_wip"] and bucket is not None:
        if qty_in == 0:
            blockers.append({"code": "NO_QTY_IN",
                             "detail": "Proses belum punya qty_in; tidak ada yang bisa ditutup"})
        elif wip != 0:
            blockers.append({
                "code": "WIP_NOT_RECONCILED",
                "detail": f"Masih ada WIP {wip}; qty_in harus sama dengan done+reject",
            })

    if spec["requires_output"] and bucket is not None:
        if qty_done <= 0 and qty_reject <= 0:
            blockers.append({"code": "NO_OUTPUT",
                             "detail": "Belum ada output (qty_done/qty_reject) untuk dilaporkan"})

    # Handoff: qty yang dikirim tidak boleh melebihi yang tersedia di proses ini,
    # dan harus menuju proses berikutnya yang benar-benar ada di rute artikel.
    if action == HANDOFF:
        if qty_sent is None or int(qty_sent) <= 0:
            blockers.append({"code": "QTY_SENT_REQUIRED",
                             "detail": "qty_sent wajib > 0"})
        elif bucket is not None and int(qty_sent) > qty_done:
            blockers.append({
                "code": "QTY_SENT_EXCEEDS_DONE",
                "detail": f"qty_sent {int(qty_sent)} melebihi qty_done {qty_done}",
            })
        if upstream_available is not None and bucket is not None and qty_in > upstream_available:
            blockers.append({
                "code": "QTY_IN_EXCEEDS_UPSTREAM",
                "detail": f"qty_in {qty_in} melebihi sumber sah {upstream_available}",
            })
        if not to_process:
            blockers.append({"code": "TO_PROCESS_REQUIRED",
                             "detail": "to_process wajib diisi"})
        elif route:
            route_upper = [str(p).strip().upper() for p in route]
            here_process = str((bucket or {}).get("process") or "").strip().upper()
            here = next((i for i, p in enumerate(route_upper) if p == here_process), None)
            todo = route_upper[here + 1] if here is not None and here + 1 < len(route_upper) else None
            if here is None:
                blockers.append({
                    "code": "PROCESS_NOT_IN_ROUTE",
                    "detail": f"Proses {here_process} tidak ada di rute artikel",
                })
            elif todo is None:
                blockers.append({
                    "code": "NO_DOWNSTREAM_PROCESS",
                    "detail": "Proses ini langkah terakhir; handoff tidak berlaku",
                })
            elif str(to_process).strip().upper() != todo:
                blockers.append({
                    "code": "WRONG_DOWNSTREAM_PROCESS",
                    "detail": f"Handoff harus ke {todo}, bukan {str(to_process).strip().upper()}",
                })

    # Keterlambatan dilaporkan sebagai konteks, bukan penghalang.
    late = bool(target_date and today and _as_date(target_date) < today)

    return {
        "action": action,
        "allowed": not blockers,
        "known_action": True,
        "to_status": spec["to_status"],
        "roles": sorted(spec["roles"]),
        "required_fields": list(spec["required_fields"]),
        "reason_required": spec["reason_required"],
        "description": spec["description"],
        "current_status": current,
        "qty_in": qty_in,
        "qty_done": qty_done,
        "qty_reject": qty_reject,
        "wip": wip,
        "late": late,
        "blockers": blockers,
    }


def _as_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return date.max
    return value


def contract_payload(role):
    """Kontrak lengkap untuk satu peran — dipakai endpoint agar UI tidak menebak."""
    rows = []
    for action in ALLOWED_ACTIONS:
        spec = CONTRACT[action]
        rows.append({
            "action": action,
            "to_status": spec["to_status"],
            "roles": sorted(spec["roles"]),
            "required_fields": list(spec["required_fields"]),
            "reason_required": spec["reason_required"],
            "description": spec["description"],
            "allowed_for_actor": role in spec["roles"],
        })
    return {
        "allowed_actions": list(ALLOWED_ACTIONS),
        "actions_for_actor": actions_for_role(role),
        "actions": rows,
        "authority_rule": (
            "COMPLETE dan HANDOFF hanya COO_MANAGER; lantai (START/UPDATE_PROGRESS/"
            "REPORT_OUTPUT) dipegang PRODUCTION_PIC; HOLD boleh PIC agar tidak macet"
        ),
    }
