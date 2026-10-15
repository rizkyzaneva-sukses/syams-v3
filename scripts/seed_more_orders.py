#!/usr/bin/env python3
"""Kasus tambahan (PRD §12): order dengan butuh sample dulu + repeat production.

Membuat PO intake lengkap sampai order aktif, lalu quotation (skema v1:
`amount` + `pricing_lines`) menyesuaikan artikel order. Idempotent: dilewati
bila PO / quotation sudah ada. Semua lewat API publik — non-2xx = sinyal bug.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import date, timedelta
from uuid import uuid4

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PASSWORD = os.environ.get("SEED_PASSWORD", "demo123456789")
today = date.today()
PROBLEMS = []


def login(acc):
    body = json.dumps({"email": f"{acc}@syams.local", "password": PASSWORD}).encode()
    req = urllib.request.Request(f"{BASE}/api/auth/login", data=body,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["access_token"]


def call(tok, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {tok}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}/api{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None


tok_deby = login("cmo.support")
tok_cecep = login("cmo.manager")

ORDERS = [
    {
        "po": "PO-SAKURA-002",
        "buyer": "Sakura Garment Co.",
        "type": "SAMPLE_PRODUCTION",
        "deadline": str(today + timedelta(days=35)),
        "notes": "Jaket Bomber Musim Dingin - Butuh sample bordir dulu",
        "article": {"article_code": "SK-BOMBER-01", "garment_type": "Jaket Bomber",
                    "qty": 200, "size_breakdown": "M:80, L:80, XL:40",
                    "sample_required": True,
                    "production_route": "Cutting > Embroidery > Sewing > QC"},
        "unit_price": "175000", "unit_hpp": "125000",
    },
    {
        "po": "PO-LEMBAH-003",
        "buyer": "Lembah Hijau Uniform",
        "type": "REPEAT_PRODUCTION",
        "deadline": str(today + timedelta(days=50)),
        "notes": "Seragam Karyawan Lapangan",
        "article": {"article_code": "LH-POLO-01", "garment_type": "Kaos Polo Lacoste",
                    "qty": 600, "size_breakdown": "S:100, M:250, L:200, XL:50",
                    "sample_required": False,
                    "production_route": "Cutting > Printing > Sewing > QC"},
        "unit_price": "80000", "unit_hpp": "55000",
    },
]


def upload_document(tok, intake_id, filename):
    bnd = "----BOS" + uuid4().hex
    body = (
        f"--{bnd}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
        f"%PDF-1.4\nDemo PO\r\n--{bnd}--\r\n"
    ).encode()
    req = urllib.request.Request(
        f"{BASE}/api/cmo/po-intake/{intake_id}/document", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={bnd}",
                 "Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


for o in ORDERS:
    print(f"\n=== {o['po']} ({o['buyer']}) ===")
    st, orders = call(tok_cecep, "GET", "/orders")
    existing = next((x for x in (orders or [])
                     if any(a.get("article_code") == o["article"]["article_code"]
                            for a in (x.get("articles") or []))), None)

    if existing:
        print(f"  = Order sudah ada: {existing['order_id']}")
        order = existing
    else:
        st, po = call(tok_deby, "POST", "/cmo/po-intake", {
            "po_number": o["po"], "buyer": o["buyer"], "order_type": o["type"],
            "buyer_deadline": o["deadline"], "notes": o["notes"],
            "articles": [o["article"]]})
        if st not in (200, 201):
            PROBLEMS.append((f"PO intake {o['po']}", st, po))
            print(f"  ! PO intake gagal [{st}]: {po}")
            continue
        up = upload_document(tok_deby, po["id"], f"{o['po']}.pdf")
        if up != 200:
            print(f"  ! Upload dokumen [{up}]")
        call(tok_deby, "POST", f"/cmo/po-intake/{po['id']}/check")
        call(tok_deby, "POST", f"/cmo/po-intake/{po['id']}/submit")
        st, accepted = call(tok_cecep, "POST", f"/cmo/po-intake/{po['id']}/review",
                            {"action": "ACCEPT", "note": "PO diverifikasi dan diterima"})
        if st not in (200, 201):
            PROBLEMS.append((f"Review {o['po']}", st, accepted))
            print(f"  ! Review gagal [{st}]: {accepted}")
            continue
        st, order = call(tok_cecep, "GET", f"/orders/{accepted['order_id']}")
        print(f"  + Order aktif: {order['order_id']}")

    oid = order["id"]
    article = next((a for a in (order.get("articles") or [])
                    if a.get("article_code") == o["article"]["article_code"]),
                   (order.get("articles") or [{}])[0])
    aid = article.get("id")

    qno = f"QT-{o['po']}"
    st, quotes = call(tok_cecep, "GET", "/cmo/quotations")
    if any(q.get("quotation_no") == qno for q in (quotes or [])):
        print(f"  = Quotation {qno} sudah ada")
        continue

    qty = o["article"]["qty"]
    amount = int(o["unit_price"]) * qty
    st, q = call(tok_cecep, "POST", "/cmo/quotations", {
        "quotation_no": qno, "order_fk": oid, "amount": amount, "status": "DRAFT",
        "valid_until": str(today + timedelta(days=20)),
        "pricing_lines": [{"article_id": aid, "unit_price": o["unit_price"],
                           "unit_hpp": o["unit_hpp"]}],
        "payment_plan": "DP 30%, pelunasan sebelum produksi",
    })
    if st in (200, 201):
        print(f"  + Quotation {qno} (Rp {amount:,})")
    else:
        PROBLEMS.append((f"Quotation {qno}", st, q))
        print(f"  ! Quotation gagal [{st}]: {q}")

print("\n" + "=" * 60)
if PROBLEMS:
    print(f"MASALAH: {len(PROBLEMS)}")
    for label, st, detail in PROBLEMS:
        print(f"  [{st}] {label} -> {json.dumps(detail)[:200]}")
else:
    print("SEMUA KASUS TAMBAHAN OK")
