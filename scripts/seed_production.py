#!/usr/bin/env python3
"""Close the remaining production gates for the routed test order.

Chain required by the backend invariants:
  BOM per article -> material request (>= BOM x qty) -> purchase order READY
  (>= request qty) -> production plan APPROVED -> movements -> final QC

Quantities are computed from the BOM so the >= checks in materials_ready pass.
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from decimal import Decimal

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PASSWORD = "demo123456789"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

TOKENS = {}
PROBLEMS = []
today = date.today()
TAG = "ROUTED"
ART = f"{TAG}-TEE-01"


def login(account):
    if account not in TOKENS:
        body = json.dumps({"email": f"{account}@syams.local", "password": PASSWORD}).encode()
        req = urllib.request.Request(f"{BASE}/api/auth/login", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, context=CTX) as r:
            TOKENS[account] = json.loads(r.read())["access_token"]
    return TOKENS[account]


def call(account, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}/api{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {login(account)}"})
    try:
        with urllib.request.urlopen(req, context=CTX) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode()[:300]


def step(label, account, method, path, payload=None, ok=(200, 201, 204)):
    status, body = call(account, method, path, payload)
    if status in ok:
        print(f"  + {label}")
        return body
    detail = body.get("detail") if isinstance(body, dict) else body
    print(f"  ! {label} -> HTTP {status}: {detail}")
    PROBLEMS.append((label, f"{method} {path}", status, detail))
    return None


def find(rows, key, value):
    return next((r for r in (rows or []) if r.get(key) == value), None)


print("=" * 64)
print("MENUTUP GATE PRODUKSI: BOM -> MR -> PO -> PLAN -> MOVEMENT -> QC")
print("=" * 64)

_, orders = call("coo.manager", "GET", "/orders")
order = next((o for o in (orders or [])
              if any(a.get("article_code") == ART for a in (o.get("articles") or []))), None)
if not order:
    raise SystemExit(f"Order dengan artikel {ART} tidak ditemukan — jalankan seed_routed.py dulu")

oid = order["id"]
article = order["articles"][0]
aid = article["id"]
qty = article["qty"]
print(f"\norder {order['order_id']} | artikel {ART} | qty {qty} | rute {article.get('production_route')!r}")

# ── 1. BOM ──────────────────────────────────────────────────────────────────
print("\n1) BOM item (COO)")
MATERIAL, UNIT, PER_UNIT = "Kain Dryfit", "meter", Decimal("0.5")
_, boms = call("coo.manager", "GET", "/coo/bom")
existing = [b for b in (boms or []) if b.get("article_id") == aid]
if existing:
    print(f"  = BOM {ART} sudah ada ({len(existing)} item)")
else:
    step(f"BOM {MATERIAL} {PER_UNIT} {UNIT}/pcs", "coo.manager", "POST", "/coo/bom",
         {"article_id": aid, "material_name": MATERIAL, "unit": UNIT,
          "qty_per_unit": str(PER_UNIT), "planned_unit_cost": "25000"})

need = Decimal(qty) * PER_UNIT
print(f"  kebutuhan total: {need} {UNIT} ({qty} pcs x {PER_UNIT})")

# ── 2. Material request >= BOM ──────────────────────────────────────────────
print("\n2) Material request (COO) — harus >= kebutuhan BOM")
_, mrs = call("coo.manager", "GET", "/coo/material-requests")
mr = next((r for r in (mrs or [])
           if r.get("order_fk") == oid and r.get("item_name") == MATERIAL), None)
if mr:
    print(f"  = MR {MATERIAL} sudah ada (qty {mr.get('qty')})")
else:
    step(f"MR {MATERIAL} {need} {UNIT}", "coo.manager", "POST", "/coo/material-requests",
         {"order_fk": oid, "item_name": MATERIAL, "qty": float(need), "unit": UNIT,
          "required_date": str(today + timedelta(days=7))})

# ── 3. Purchase order READY >= MR ───────────────────────────────────────────
print("\n3) Purchase order (CFO) — status READY")
po_no = f"PO-{TAG}-001"
_, pos = call("cfo.manager", "GET", "/cfo/purchase-orders")
po = find(pos, "po_no", po_no)
if po:
    print(f"  = {po_no} sudah ada (material_status {po.get('material_status')})")
else:
    po = step(f"{po_no} {MATERIAL} {need} {UNIT} READY", "cfo.manager", "POST",
              "/cfo/purchase-orders",
              {"po_no": po_no, "order_fk": oid, "item": MATERIAL, "qty": float(need),
               "unit": UNIT, "supplier": "PT Tekstil Makmur",
               "amount": float(need) * 25000, "status": "RECEIVED",
               "arrival_date": str(today), "material_status": "READY"})

if po and po.get("material_status") != "READY":
    step(f"Set {po_no} -> READY", "cfo.manager", "PATCH",
         f"/cfo/purchase-orders/{po['id']}",
         {"material_status": "READY", "status": "RECEIVED", "arrival_date": str(today)})

# ── 4. Production plan APPROVED ─────────────────────────────────────────────
print("\n4) Production plan (COO) — harus APPROVED")
_, plans = call("coo.manager", "GET", "/coo/production-plans")
plan = next((p for p in (plans or []) if p.get("order_fk") == oid), None)
if not plan:
    plan = step("Plan PLANNING", "coo.manager", "POST", "/coo/production-plans",
                {"order_fk": oid, "plan_date": str(today + timedelta(days=3)),
                 "status": "PLANNING", "notes": "Rencana produksi batch tunggal"})
else:
    print(f"  = plan sudah ada (status {plan.get('status')})")

if plan and plan.get("status") not in ("APPROVED", "RELEASED", "IN_PROGRESS", "DONE"):
    step("Plan -> APPROVED", "coo.manager", "PATCH",
         f"/coo/production-plans/{plan['id']}",
         {"status": "APPROVED", "plan_date": str(today + timedelta(days=3))})

# ── 5. Movement mengikuti rute ──────────────────────────────────────────────
print("\n5) Process movement")
_, movements = call("coo.manager", "GET", "/coo/movements")
movements = movements or []
for process in ("CUTTING", "SEWING"):
    if any(m.get("article_id") == aid and str(m.get("process", "")).upper() == process
           for m in movements):
        print(f"  = {process} (sudah ada)")
        continue
    step(f"{process} {qty}/{qty}", "coo.manager", "POST", "/coo/movements",
         {"article_id": aid, "process": process, "qty_in": qty, "qty_done": qty,
          "qty_reject": 0, "status": "DONE", "pic_name": "Budi Santoso",
          "target_date": str(today + timedelta(days=10))})

# ── 6. QC final ─────────────────────────────────────────────────────────────
print("\n6) QC final")
_, qcs = call("coo.manager", "GET", "/coo/qc-records")
if any(q.get("article_code") == ART for q in (qcs or [])):
    print(f"  = QC {ART} (sudah ada)")
else:
    step(f"QC {ART} {qty}/{qty} PASS", "coo.manager", "POST", "/coo/qc-records",
         {"order_fk": oid, "article_code": ART, "process": "QC",
          "total_checked": qty, "total_pass": qty, "total_reject": 0,
          "inspector": "Andi Wijaya", "status": "PASS"})

# ── 7. Flow akhir ───────────────────────────────────────────────────────────
print("\n7) Flow state")
status, flow = call("coo.manager", "GET", f"/orders/{order['order_id']}/flow")
if status == 200 and isinstance(flow, dict):
    print(f"  current_step: {flow.get('current_step')}")
    for s in (flow.get("next_steps") or []):
        print(f"    [{'OK  ' if s.get('can_advance') else 'BLOK'}] {s.get('step')}: {s.get('reason') or 'siap'}")
else:
    print(f"  ! HTTP {status}: {flow}")

print("\n" + "=" * 64)
if PROBLEMS:
    print(f"MASALAH: {len(PROBLEMS)}")
    print("=" * 64)
    for label, endpoint, st, detail in PROBLEMS:
        print(f"\n  [{st}] {label}\n    {endpoint}\n    {detail}")
else:
    print("SEMUA GATE PRODUKSI LOLOS")
print("=" * 64)
