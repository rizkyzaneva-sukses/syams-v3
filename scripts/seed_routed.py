#!/usr/bin/env python3
"""Prove the production stages work end to end on an order that has a routing.

The four originally seeded orders were created without production_route, which
no endpoint can backfill, so they can never release an SPK. This creates one
fully specified order and drives it through the entire lifecycle, then reports
every non-2xx response.
"""
import json
import os
import ssl
import urllib.error
import urllib.request
from uuid import uuid4
from datetime import date, timedelta

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PASSWORD = "demo123456789"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

TOKENS = {}
PROBLEMS = []
today = date.today()
TAG = "ROUTED"


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
            if r.headers.get_content_type() == "application/pdf":
                return r.status, {"pdf_bytes": len(raw)}
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode()[:300]


def upload_po_document(account, po_id, filename, document):
    boundary = "----BOSSYAMS" + uuid4().hex
    body = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
            "Content-Type: application/pdf\r\n\r\n").encode() + document + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{BASE}/api/cmo/po-intake/{po_id}/document", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Authorization": f"Bearer {login(account)}"})
    try:
        with urllib.request.urlopen(req, context=CTX) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw.decode()[:300]


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
print("UJI PRODUKSI: order dengan production_route lengkap")
print("=" * 64)

ROUTE = "Cutting > Sewing > QC"
ART = f"{TAG}-TEE-01"
BUYER = "Atlas Sportswear Ltd"

# ── 1. Order dengan routing ─────────────────────────────────────────────────
print("\n1) PO intake + aktivasi Order (Deby → Cecep)")
_, orders = call("cmo.manager", "GET", "/orders")
order = next((o for o in (orders or [])
              if any(a.get("article_code") == ART for a in (o.get("articles") or []))), None)
if order:
    print(f"  = Order {order['order_id']} (sudah ada)")
else:
    po = step(f"PO {BUYER} — rute '{ROUTE}'", "cmo.support", "POST", "/cmo/po-intake", {
        "po_number": f"PO-{TAG}-001", "buyer": BUYER, "order_type": "REPEAT_PRODUCTION",
        "buyer_deadline": str(today + timedelta(days=90)),
        "notes": "Order uji dengan rute produksi lengkap",
        "articles": [{"article_code": ART, "garment_type": "Kaos Olahraga",
                      "qty": 500, "size_breakdown": "M:200, L:200, XL:100",
                      "sample_required": False, "production_route": ROUTE}],
    })
    if po:
        status, body = upload_po_document("cmo.support", po["id"], f"PO-{TAG}-001.pdf", b"%PDF-1.4\nRouted seed PO")
        if status != 200:
            detail = body.get("detail") if isinstance(body, dict) else body
            PROBLEMS.append(("Upload PO", "POST /cmo/po-intake/{id}/document", status, detail))
        else:
            step("Cek kelengkapan PO", "cmo.support", "POST", f"/cmo/po-intake/{po['id']}/check")
            step("Kirim PO ke Cecep", "cmo.support", "POST", f"/cmo/po-intake/{po['id']}/submit")
            accepted = step("Terima & aktifkan Order", "cmo.manager", "POST", f"/cmo/po-intake/{po['id']}/review",
                            {"action": "ACCEPT", "note": "PO uji lengkap"})
            if accepted:
                _, order = call("cmo.manager", "GET", f"/orders/{accepted['order_id']}")
if not order:
    raise SystemExit("Order gagal dibuat")

oid = order["id"]
article = order["articles"][0]
aid = article["id"]
print(f"  order_id={order['order_id']} article_id={aid} route={article.get('production_route')!r}")

# ── 2. Quotation -> approve ─────────────────────────────────────────────────
print("\n2) Quotation + approval CFO")
qno = f"QT-{TAG}-001"
_, quotes = call("cmo.manager", "GET", "/cmo/quotations")
q = find(quotes, "quotation_no", qno)
if not q:
    q = step(f"{qno} (Rp 42,500,000)", "cmo.manager", "POST", "/cmo/quotations", {
        "quotation_no": qno, "order_fk": oid, "amount": 42500000, "status": "DRAFT",
        "valid_until": str(today + timedelta(days=30)),
        "pricing_lines": [{"article_id": aid, "unit_price": "85000", "unit_hpp": "60000"}],
        "payment_plan": "Pelunasan penuh sebelum produksi",
    })
else:
    print(f"  = {qno} (sudah ada)")
if q and q.get("status") != "APPROVED":
    step(f"Approve {qno}", "cfo.manager", "PATCH", f"/cmo/quotations/{q['id']}",
         {"status": "APPROVED", "approval_reason": "Margin 29% di atas minimum"})
elif q:
    print(f"  = {qno} sudah APPROVED")

# ── 3. Invoice -> payment -> reconcile -> finance gate ──────────────────────
print("\n3) Invoice -> payment -> reconcile -> finance gate")
inv_no = f"INV-{TAG}-001"
_, invoices = call("cfo.manager", "GET", "/cfo/invoices")
inv = find(invoices, "invoice_no", inv_no)
if not inv:
    inv = step(f"{inv_no} (Rp 42,500,000)", "cfo.manager", "POST", "/cfo/invoices", {
        "invoice_no": inv_no, "order_fk": oid, "amount": 42500000, "paid_amount": 0,
        "due_date": str(today + timedelta(days=30)), "status": "UNPAID"})
else:
    print(f"  = {inv_no} (sudah ada)")

if inv:
    outstanding = round(float(inv.get("amount") or 0) - float(inv.get("paid_amount") or 0), 2)
    if outstanding > 0:
        step(f"Bayar Rp {outstanding:,.0f}", "cfo.manager", "POST", "/cfo/payments",
             {"invoice_no": inv_no, "amount": outstanding, "payment_date": str(today),
              "method": "TRANSFER", "notes": "Pelunasan"})
    else:
        print("  = sudah lunas")
    _, invoices = call("cfo.manager", "GET", "/cfo/invoices")
    inv = find(invoices, "invoice_no", inv_no)
    if inv and inv.get("reconciliation_status") != "VERIFIED":
        step("Reconcile", "cfo.manager", "POST", f"/cfo/invoices/{inv['id']}/reconcile",
             {"evidence_ref": f"BANK-{inv_no}", "notes": "Mutasi cocok"})
    else:
        print("  = sudah VERIFIED")

step("Finance gate APPROVE", "cfo.manager", "POST", f"/cfo/orders/{oid}/finance-gate",
     {"action": "APPROVE", "reason": "Lunas dan terekonsiliasi",
      "term_kind": "FULL", "evidence_ref": f"BANK-{inv_no}"})

# ── 4. SPK release (gate yang tadi gagal) ───────────────────────────────────
print("\n4) SPK release — gate yang sebelumnya blokir")
spk_no = f"SPK-{TAG}-001"
_, spks = call("cmo.manager", "GET", "/cmo/spk")
spk = find(spks, "spk_no", spk_no)
if not spk:
    spk = step(f"{spk_no}", "cmo.manager", "POST", "/cmo/spk",
               {"order_fk": oid, "spk_no": spk_no,
                "notes": "SPK order ber-routing"})
else:
    print(f"  = {spk_no} (sudah ada)")
if spk and spk.get("status") == "DRAFT":
    spk = step(f"Generate {spk_no}", "cmo.manager", "POST", f"/cmo/spk/{spk['id']}/generate")
if spk and spk.get("status") == "GENERATED":
    printed = step(f"Print {spk_no}", "cmo.manager", "POST", f"/cmo/spk/{spk['id']}/print")
    if printed:
        spk["status"] = "PRINTED"
if spk and spk.get("status") == "PRINTED":
    spk = step(f"Release {spk_no}", "cmo.manager", "POST", f"/cmo/spk/{spk['id']}/release",
               {"version_id": spk["id"], "reason": "Finance, quotation, sample, dan rute produksi diverifikasi"})
elif spk and spk.get("status") == "RELEASED":
    print(f"  = {spk_no} sudah RELEASED")

# ── 5. Movement mengikuti rute ──────────────────────────────────────────────
print("\n5) Process movement sesuai rute Cutting > Sewing > QC")
_, movements = call("coo.manager", "GET", "/coo/movements")
movements = movements or []
for process in ("CUTTING", "SEWING"):
    if any(m.get("article_id") == aid and str(m.get("process", "")).upper() == process
           for m in movements):
        print(f"  = {process} (sudah ada)")
        continue
    step(f"{process} 500/500", "coo.manager", "POST", "/coo/movements",
         {"article_id": aid, "process": process, "qty_in": 500, "qty_done": 500,
          "qty_reject": 0, "status": "DONE", "pic_name": "Budi Santoso",
          "target_date": str(today + timedelta(days=10))})

# ── 6. QC final ─────────────────────────────────────────────────────────────
print("\n6) QC final")
_, qcs = call("coo.manager", "GET", "/coo/qc-records")
if any(q.get("article_code") == ART for q in (qcs or [])):
    print(f"  = QC {ART} (sudah ada)")
else:
    step(f"QC {ART} 500/500 PASS", "coo.manager", "POST", "/coo/qc-records",
         {"order_fk": oid, "article_code": ART, "process": "QC",
          "total_checked": 500, "total_pass": 500, "total_reject": 0,
          "inspector": "Andi Wijaya", "status": "PASS"})

# ── 7. Shipment ─────────────────────────────────────────────────────────────
print("\n7) Shipment")
sh_no = f"SHP-{TAG}-001"
_, shipments = call("coo.manager", "GET", "/coo/shipments")
sh = find(shipments, "shipment_no", sh_no)
if not sh:
    sh = step(f"{sh_no}", "coo.manager", "POST", "/coo/shipments",
              {"order_fk": oid, "shipment_no": sh_no, "status": "PREPARING",
               "packing_status": "PENDING", "notes": "Siap dikirim"})
else:
    print(f"  = {sh_no} (sudah ada)")

# ── 8. Flow state ───────────────────────────────────────────────────────────
print("\n8) Flow state order")
status, flow = call("coo.manager", "GET", f"/orders/{order['order_id']}/flow")
if status == 200 and isinstance(flow, dict):
    print(f"  current_step: {flow.get('current_step')}")
    for s in (flow.get("next_steps") or []):
        mark = "OK " if s.get("can_advance") else "BLOK"
        print(f"    [{mark}] {s.get('step')}: {s.get('reason') or 'siap'}")
else:
    print(f"  ! flow -> HTTP {status}: {flow}")

print("\n" + "=" * 64)
if PROBLEMS:
    print(f"MASALAH: {len(PROBLEMS)}")
    print("=" * 64)
    for label, endpoint, status, detail in PROBLEMS:
        print(f"\n  [{status}] {label}")
        print(f"    {endpoint}")
        print(f"    {detail}")
else:
    print("SEMUA TAHAP PRODUKSI LOLOS")
print("=" * 64)
