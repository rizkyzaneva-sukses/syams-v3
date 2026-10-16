"""Capacity Planner, Forecast Engine, dan feed kapasitas untuk CMO (tab CAPACITY PLANNER,
FORECAST ENGINE, dan 19_MASTER_CAPACITY_TO_CMO di sheet lama).

Aturan dari rumus sheet:
  * Kapasitas periode = kapasitas harian × jumlah hari (hari kalender, tanggal akhir − awal + 1).
  * Beban > 100% = OVERLOAD; beban ≥ batas peringatan tahap (80%) = PERHATIAN; selain itu AVAILABLE.
  * Estimasi: tahap berikut mulai = hari ini + sisa durasi SLA tahap sekarang; tahap-tahap
    sesudahnya ditumpuk berurutan sampai SHIPPING (proyeksi full-flow).
  * Risiko deadline: lewat deadline atau estimasi selesai > deadline = URGENT; estimasi + 2 hari
    ≥ deadline = PERHATIAN; selain itu AMAN.

Penyimpangan yang disengaja dari sheet (dan alasannya):
  * Satuan dihormati. Sheet membandingkan pcs dengan kapasitas berisi jumlah order/artikel
    (Invoice, PPM, SPK, Sample, Shipping), sehingga PPM tampil 601% dan Sample 3541%. Di sini
    tahap berkapasitas ORDER dihitung per order, ARTIKEL per artikel, PCS per pcs.
  * Risiko deadline memakai tanggal selesai akhir (FINAL RISK di sheet), bukan tanggal tahap
    berikut, karena yang menentukan terlambat atau tidak adalah tanggal kirim.
  * Tahap yang sudah berjalan memakai sisa SLA-nya (jatuh tempo − hari ini), bukan SLA penuh.
"""
from datetime import date, timedelta

from .control_service import DEFAULT_WARNING_PCT, STAGES

HORIZONS = (7, 14, 30)
MAX_PLANNER_DAYS = 366
FEED_STAGES = (("CUTTING", "cutting_load_pct"), ("PRINTING", "printing_load_pct"), ("SEWING", "sewing_load_pct"))

BANNER = {
    "OVERLOAD": ("red", "ADA PROSES OVERLOAD — TAHAN / ATUR DEADLINE ORDER BARU"),
    "PERHATIAN": ("amber", "ADA PROSES MENDEKATI PENUH — KEJAR WIP SEBELUM TAMBAH ORDER"),
    "AVAILABLE": ("green", "KAPASITAS MASIH TERSEDIA UNTUK PERIODE INI"),
}
STATUS_ACTION = {
    "OVERLOAD": "STOP / GESER DEADLINE / TAMBAH KAPASITAS",
    "PERHATIAN": "KEJAR WIP / BATASI ORDER",
    "AVAILABLE": "SIAPKAN ORDER BERIKUTNYA",
    "TIDAK DIPAKAI": "Tahap dinonaktifkan di SLA",
}


def unit_amount(unit: str | None, view: dict) -> int:
    """Berapa 'satuan kapasitas' yang dipakai order ini di sebuah tahap."""
    unit = (unit or "PCS").upper()
    if unit == "ORDER":
        return 1
    if unit == "ARTICLE":
        return max(1, len(view["articles"]))
    return view["active_qty"]


def load_ratio(amount: int, capacity: int) -> float:
    if capacity <= 0:
        return 0.0 if amount == 0 else 9.99
    return amount / capacity


def status_for(ratio: float, warning: float) -> str:
    if ratio > 1:
        return "OVERLOAD"
    if ratio >= warning:
        return "PERHATIAN"
    return "AVAILABLE"


def worst(statuses) -> str:
    statuses = set(statuses)
    return "OVERLOAD" if "OVERLOAD" in statuses else "PERHATIAN" if "PERHATIAN" in statuses else "AVAILABLE"


def banner(statuses) -> dict:
    level = worst(statuses)
    tone, text = BANNER[level]
    return {"level": level, "tone": tone, "text": text}


def _live(views: list[dict]) -> list[dict]:
    return [v for v in views if v["priority"] != "SELESAI"]


def _item(items: dict, code: str):
    item = items.get(code)
    return item, (item is not None and item.is_active)


# ───────────────────────────── Capacity Planner ─────────────────────────────

def capacity_planner(views: list[dict], items: dict, start: date, end: date) -> dict:
    days = (end - start).days + 1
    live = _live(views)
    rows = []
    for code, label, _ in STAGES:
        item, active = _item(items, code)
        here = [v for v in live if v["current_stage"] == code]
        unit = item.capacity_unit if item else "PCS"
        daily = item.daily_capacity if item else 0
        warn = item.warning_pct if item else DEFAULT_WARNING_PCT
        amount = sum(unit_amount(unit, v) for v in here)
        period_cap = daily * days
        ratio = load_ratio(amount, period_cap)
        status = status_for(ratio, warn) if active else "TIDAK DIPAKAI"
        rows.append({
            "code": code, "label": label, "orders": len(here), "qty": sum(v["active_qty"] for v in here),
            "load_amount": amount, "unit": unit, "daily_capacity": daily, "period_capacity": period_cap,
            "load_pct": round(ratio * 100, 1), "available": max(0, period_cap - amount),
            "status": status, "action": STATUS_ACTION[status], "pic": item.primary_pic if item else None,
            "warning_pct": warn,
        })
    return {"start": start, "end": end, "days": days, "rows": rows,
            "banner": banner(r["status"] for r in rows if r["status"] != "TIDAK DIPAKAI")}


# ───────────────────────────── Forecast Engine ─────────────────────────────

def project_order(view: dict, items: dict, today: date) -> dict:
    """Tanggal mulai tiap tahap yang tersisa dan tanggal selesai akhir, ditumpuk berurutan."""
    cursor = today
    starts: dict[str, date] = {}
    pending = [s for s in view["stages"] if s["status"] not in ("SELESAI", "-")]
    for stage in pending:
        item, active = _item(items, stage["code"])
        if not active:
            continue
        starts[stage["code"]] = cursor
        if stage["is_current"] and stage["due_date"]:
            remaining = max(0, (stage["due_date"] - today).days)
        else:
            remaining = stage["sla_days"]
        cursor += timedelta(days=remaining)
    ordered = [s["code"] for s in pending if s["code"] in starts]
    current = view["current_stage"]
    if ordered and ordered[0] == current:
        next_code = ordered[1] if len(ordered) > 1 else None
    else:
        next_code = ordered[0] if ordered else None
    return {"starts": starts, "finish": cursor if starts else None, "next_stage": next_code}


def deadline_risk(view: dict, finish: date | None, today: date) -> str:
    if view["priority"] == "SELESAI":
        return "SELESAI"
    deadline = view["deadline"]
    if deadline is None:
        return "TANPA DEADLINE"
    if deadline < today or (finish is not None and finish > deadline):
        return "URGENT"
    if finish is not None and finish + timedelta(days=2) >= deadline:
        return "PERHATIAN"
    return "AMAN"


def forecast_engine(views: list[dict], items: dict, today: date) -> dict:
    live = _live(views)
    projections = {v["order_id"]: project_order(v, items, today) for v in live}

    orders = []
    for v in live:
        p = projections[v["order_id"]]
        next_code = p["next_stage"]
        orders.append({
            "order_id": v["order_id"], "buyer": v["buyer"], "articles": v["articles"], "garment_types": v["garment_types"],
            "qty": v["active_qty"], "deadline": v["deadline"], "priority": v["priority"], "pic": v["pic"],
            "current_stage": v["current_stage"], "current_stage_label": v["current_stage_label"],
            "next_stage": next_code, "next_stage_label": next((l for c, l, _ in STAGES if c == next_code), None),
            "est_next_date": p["starts"].get(next_code) if next_code else None,
            "est_finish": p["finish"], "risk": deadline_risk(v, p["finish"], today),
            "days_to_deadline": (v["deadline"] - today).days if v["deadline"] else None,
            "stage_dates": p["starts"],
        })
    risk_rank = {"URGENT": 0, "PERHATIAN": 1, "TANPA DEADLINE": 2, "AMAN": 3}
    orders.sort(key=lambda o: (risk_rank.get(o["risk"], 4), o["deadline"] is None, o["deadline"] or date.max, o["order_id"]))

    stages = []
    for code, label, _ in STAGES:
        item, active = _item(items, code)
        unit = item.capacity_unit if item else "PCS"
        daily = item.daily_capacity if item else 0
        warn = item.warning_pct if item else DEFAULT_WARNING_PCT
        row = {"code": code, "label": label, "unit": unit, "daily_capacity": daily, "pic": item.primary_pic if item else None}
        for horizon in HORIZONS:
            amount = orders_count = 0
            for v in live:
                start = projections[v["order_id"]]["starts"].get(code)
                if start is not None and 0 <= (start - today).days <= horizon:
                    amount += unit_amount(unit, v)
                    orders_count += 1
            row[f"orders_{horizon}d"] = orders_count
            row[f"load_{horizon}d"] = amount
            row[f"load_pct_{horizon}d"] = round(load_ratio(amount, daily * horizon) * 100, 1)
        ratio14 = row["load_pct_14d"] / 100
        row["status"] = status_for(ratio14, warn) if active else "TIDAK DIPAKAI"
        row["action"] = STATUS_ACTION[row["status"]]
        stages.append(row)

    return {"today": today, "orders": orders, "stages": stages,
            "banner": banner(s["status"] for s in stages if s["status"] != "TIDAK DIPAKAI"),
            "risk_counts": {k: sum(1 for o in orders if o["risk"] == k) for k in ("URGENT", "PERHATIAN", "AMAN", "TANPA DEADLINE")}}


# ───────────────────────────── Feed kapasitas untuk CMO ─────────────────────────────

def capacity_feed(views: list[dict], items: dict, today: date) -> dict:
    """Berapa pcs lagi yang bisa diterima Sales dalam 7 / 14 / 30 hari (patokan: kapasitas SEWING)."""
    live = _live(views)
    forecast = forecast_engine(views, items, today)
    stage_pct = {s["code"]: s for s in forecast["stages"]}
    sewing = items.get("SEWING")
    daily = sewing.daily_capacity if sewing else 0
    projections = {v["order_id"]: project_order(v, items, today) for v in live}
    wip = sum(v["active_qty"] for v in live)
    rows = []
    for horizon in HORIZONS:
        confirmed = 0
        for v in live:
            start = projections[v["order_id"]]["starts"].get("SEWING")
            if start is not None and 0 <= (start - today).days <= horizon:
                confirmed += v["active_qty"]
        available = daily * horizon
        row = {"horizon_days": horizon, "available_capacity": available, "confirmed_load": confirmed,
               "free_capacity": max(0, available - confirmed), "current_wip": wip, "source": "MASTER CONTROL — OTOMATIS"}
        for code, key in FEED_STAGES:
            row[key] = stage_pct[code][f"load_pct_{horizon}d"]
        rows.append(row)
    return {"basis": "SEWING", "daily_capacity": daily, "rows": rows}
