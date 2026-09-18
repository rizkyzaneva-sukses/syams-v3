#!/usr/bin/env python3
"""Finish the routed order: packing, finance gate, shipping, delivery, closing."""
import json
import ssl
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = "https://client-bos-syam-fix.zvusml.easypanel.host"
PASSWORD = "demo123456789"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

TOKENS = {}
PROBLEMS = []
today = date.today()
ART = "ROUTED-TEE-01"
SH_NO = "SHP-ROUTED-001"


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


def flow_state(order_id, tag):
    status, flow = call("coo.manager", "GET", f"/orders/{order_id}/flow")
    if status == 200 and isinstance(flow, dict):
        print(f"\n  [{tag}] current_step: {flow.get('current_step')}")
        for s in (flow.get("next_steps") or []):
            print(f"    [{'OK  ' if s.get('can_advance') else 'BLOK'}] {s.get('step')}: {s.get('reason') or 'siap'}")
    return flow if status == 200 else None


print("=" * 64)
print("TAHAP AKHIR: packing -> shipment gate -> kirim -> terima -> closing")
print("=" * 64)

_, orders = call("coo.manager", "GET", "/orders")
order = next((o for o in (orders or [])
              if any(a.get("article_code") == ART for a in (o.get("articles") or []))), None)
if not order:
    raise SystemExit("Order ROUTED tidak ditemukan")
oid, order_id = order["id"], order["order_id"]

_, shipments = call("coo.manager", "GET", "/coo/shipments")
sh = next((s for s in (shipments or []) if s.get("shipment_no") == SH_NO), None)
if not sh:
    raise SystemExit(f"{SH_NO} tidak ditemukan")
print(f"\norder {order_id} | shipment {SH_NO}")
print(f"  status={sh.get('status')} packing={sh.get('packing_status')} "
      f"finance_gate={sh.get('finance_gate')} ceo={sh.get('ceo_approval')}")

# ── 1. Packing ──────────────────────────────────────────────────────────────
print("\n1) Packing (COO)")
if sh.get("packing_status") == "PACKED":
    print("  = sudah PACKED")
else:
    step("Packing -> PACKED", "coo.manager", "PATCH", f"/coo/shipments/{sh['id']}",
         {"packing_status": "PACKED", "notes": "Barang selesai dikemas"})

# ── 2. Finance gate shipment (CFO) ──────────────────────────────────────────
print("\n2) Finance gate shipment (CFO)")
_, shipments = call("cfo.manager", "GET", "/coo/shipments")
sh = next((s for s in (shipments or []) if s.get("shipment_no") == SH_NO), sh)
if sh.get("finance_gate") == "CLEAR":
    print("  = finance_gate sudah CLEAR")
else:
    step("Shipment gate APPROVE", "cfo.manager", "POST",
         f"/cfo/shipments/{sh['id']}/gate",
         {"action": "APPROVE", "reason": "Invoice lunas dan terekonsiliasi"})

# ── 3. Kirim ────────────────────────────────────────────────────────────────
print("\n3) Kirim barang (COO)")
_, shipments = call("coo.manager", "GET", "/coo/shipments")
sh = next((s for s in (shipments or []) if s.get("shipment_no") == SH_NO), sh)
if sh.get("status") in ("SHIPPED", "DELIVERED"):
    print(f"  = sudah {sh.get('status')}")
else:
    step("Status -> SHIPPED", "coo.manager", "PATCH", f"/coo/shipments/{sh['id']}",
         {"status": "SHIPPED", "shipped_date": str(today),
          "tracking_no": "JNE-TRK-001", "notes": "Dikirim via JNE"})

flow_state(order_id, "setelah shipment")

# ── 4. Konfirmasi penerimaan ────────────────────────────────────────────────
print("\n4) Konfirmasi penerimaan (CMO)")
_, shipments = call("coo.manager", "GET", "/coo/shipments")
sh = next((s for s in (shipments or []) if s.get("shipment_no") == SH_NO), sh)
_, deliveries = call("cmo.manager", "GET", "/coo/deliveries")
dl = next((d for d in (deliveries or []) if d.get("shipment_fk") == sh["id"]), None)
if dl:
    print(f"  = konfirmasi sudah ada (status {dl.get('status')})")
else:
    step("Delivery confirmation", "cmo.manager", "POST", "/cmo/delivery-confirmations",
         {"shipment_fk": sh["id"], "status": "CONFIRMED",
          "confirmed_by_customer": "Melissa Tan",
          "confirmation_date": str(today + timedelta(days=3)),
          "feedback": "Barang diterima lengkap"})

if sh.get("status") != "DELIVERED":
    step("Status -> DELIVERED", "coo.manager", "PATCH", f"/coo/shipments/{sh['id']}",
         {"status": "DELIVERED", "delivery_date": str(today + timedelta(days=3))})

flow_state(order_id, "setelah delivery")

# ── 5. Order closing ────────────────────────────────────────────────────────
print("\n5) Order closing (CMO)")
status, closing = call("cmo.manager", "GET", f"/coo/order-closing/{oid}")
if status == 200 and closing:
    print(f"  = closing sudah ada: {json.dumps(closing)[:120]}")
    if closing.get("customer_close_status") != "CLOSED":
        step("Closing customer", "cmo.manager", "PATCH", f"/coo/order-closing/{oid}",
             {"customer_close_status": "CLOSED", "notes": "Konfirmasi customer diterima"})
else:
    step("Buat closing", "cmo.manager", "POST", f"/coo/order-closing/{oid}",
         {"order_fk": oid, "customer_close_status": "CLOSED",
          "notes": "Order selesai, semua tahap terpenuhi"})

step("Closing operasional", "coo.manager", "PATCH", f"/coo/order-closing/{oid}",
     {"operational_close_status": "CLOSED", "notes": "Produksi dan serah terima selesai"})
step("Closing finansial", "cfo.manager", "PATCH", f"/coo/order-closing/{oid}",
     {"financial_close_status": "CLOSED", "notes": "Tagihan lunas dan terekonsiliasi"})

flow_state(order_id, "final")

print("\n" + "=" * 64)
if PROBLEMS:
    print(f"MASALAH: {len(PROBLEMS)}")
    print("=" * 64)
    for label, endpoint, st, detail in PROBLEMS:
        print(f"\n  [{st}] {label}\n    {endpoint}\n    {detail}")
else:
    print("LIFECYCLE PENUH LOLOS")
print("=" * 64)
