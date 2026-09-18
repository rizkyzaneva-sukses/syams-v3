#!/usr/bin/env python3
"""Drive the full BOS SYAMS business flow through the public API.

Doubles as an end-to-end smoke test: every non-2xx response is collected and
reported at the end instead of aborting, so one broken step still lets the rest
of the flow run and surface further problems.

Idempotent: records are matched on their natural key and skipped when present.
"""
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
    PROBLEMS.append((label, account, f"{method} {path}", status, detail))
    return None


def find(rows, key, value):
    return next((r for r in (rows or []) if r.get(key) == value), None)


print("=" * 62)
print("SEED + SMOKE TEST: alur bisnis penuh BOS SYAMS")
print("=" * 62)

# ── 1. CEO menetapkan kebijakan harga (gate untuk approval quotation) ────────
print("\n1) Business policy (CEO)")
status, pol = call("ceo", "GET", "/config/business-policy")
if status == 200:
    print("  = Policy sudah ada")
else:
    step("Set business policy", "ceo", "PUT", "/config/business-policy", {
        "minimum_margin_percent": 15,
        "minimum_dp_percent": 30,
        "cfo_quotation_limit": 500000000,
        "allow_credit_terms": True,
    })

# ── 2. Ambil order hasil seed sebelumnya ────────────────────────────────────
print("\n2) Ambil order")
_, orders = call("cmo.manager", "GET", "/orders")
orders = orders or []
print(f"  order tersedia: {len(orders)}")
for o in orders:
    arts = ", ".join(a.get("article_code", "?") for a in (o.get("articles") or []))
    print(f"    {o['order_id']} | {o['buyer']} | {o['order_type']} | artikel: {arts}")

if not orders:
    raise SystemExit("Tidak ada order untuk diproses")

# ── 3. Quotation untuk tiap order ───────────────────────────────────────────
print("\n3) Quotation (CMO Manager)")
_, quotes = call("cmo.manager", "GET", "/cmo/quotations")
quotes = quotes or []
for i, o in enumerate(orders, start=1):
    qno = f"QT-{today.year}-{i:03d}"
    if find(quotes, "quotation_no", qno):
        print(f"  = {qno} (sudah ada)")
        continue
    arts = o.get("articles") or []
    lines = [{"article_id": a["id"], "unit_price": "85000", "unit_hpp": "60000"} for a in arts]
    amount = sum(85000 * a.get("qty", 0) for a in arts)
    step(f"{qno} — {o['buyer']} (Rp {amount:,})", "cmo.manager", "POST", "/cmo/quotations", {
        "quotation_no": qno,
        "order_fk": o["id"],
        "amount": amount,
        "status": "DRAFT",
        "valid_until": str(today + timedelta(days=30)),
        "notes": f"Penawaran untuk {o['buyer']}",
        "pricing_lines": lines,
        "payment_plan": "DP 30%, pelunasan sebelum pengiriman",
    })

# ── 4. Sample untuk order yang mensyaratkan sample ──────────────────────────
print("\n4) Sample (CMO Manager)")
_, samples = call("cmo.manager", "GET", "/cmo/samples")
samples = samples or []
for o in orders:
    if o["order_type"] not in ("SAMPLE_ONLY", "SAMPLE_PRODUCTION"):
        continue
    for a in (o.get("articles") or []):
        if not a.get("sample_required"):
            continue
        code = a["article_code"]
        if find(samples, "article_code", code):
            print(f"  = Sample {code} (sudah ada)")
            continue
        step(f"Sample {code} — {o['buyer']}", "cmo.manager", "POST", "/cmo/samples", {
            "order_fk": o["id"],
            "article_code": code,
            "status": "PROCESS",
            "requested_date": str(today),
            "notes": "Menunggu pengerjaan sample PIC",
        })

# ── 5. SPK untuk order produksi ─────────────────────────────────────────────
print("\n5) SPK (CMO Manager)")
_, spks = call("cmo.manager", "GET", "/cmo/spk")
spks = spks or []
n = 0
for o in orders:
    if o["order_type"] == "SAMPLE_ONLY":
        continue
    n += 1
    spk_no = f"SPK-{today.year}-{n:03d}"
    if find(spks, "spk_no", spk_no):
        print(f"  = {spk_no} (sudah ada)")
        continue
    step(f"{spk_no} — {o['buyer']}", "cmo.manager", "POST", "/cmo/spk", {
        "order_fk": o["id"],
        "spk_no": spk_no,
        "notes": "Surat perintah kerja produksi",
    })

# ── 6. Laporan ──────────────────────────────────────────────────────────────
print("\n" + "=" * 62)
print("RINGKASAN DATA")
print("=" * 62)
for label, account, path in [
    ("Customers", "cmo.manager", "/cmo/customers"),
    ("Orders", "cmo.manager", "/orders"),
    ("Quotations", "cmo.manager", "/cmo/quotations"),
    ("Samples", "cmo.manager", "/cmo/samples"),
    ("SPK", "cmo.manager", "/cmo/spk"),
    ("Employees", "chro.manager", "/chro/employees"),
]:
    status, rows = call(account, "GET", path)
    n = len(rows) if status == 200 and isinstance(rows, list) else f"HTTP {status}"
    print(f"  {label:12s}: {n}")

print("\n" + "=" * 62)
if PROBLEMS:
    print(f"MASALAH DITEMUKAN: {len(PROBLEMS)}")
    print("=" * 62)
    for label, account, endpoint, status, detail in PROBLEMS:
        print(f"\n  [{status}] {label}")
        print(f"    akun     : {account}")
        print(f"    endpoint : {endpoint}")
        print(f"    detail   : {detail}")
else:
    print("TIDAK ADA ERROR")
print("=" * 62)
