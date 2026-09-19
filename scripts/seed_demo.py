#!/usr/bin/env python3
"""Seed realistic demo data into BOS SYAMS through the public API.

Idempotent: every create is skipped when a record with the same natural key
already exists, so re-running the script never duplicates rows.
"""
import json
import ssl
import sys
import os
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PASSWORD = "demo123456789"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

TOKENS = {}


def login(account):
    if account in TOKENS:
        return TOKENS[account]
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
            return e.code, raw.decode()[:200]


def ensure(label, account, path, payload, key, existing_path=None):
    """Create payload unless an item with the same `key` value already exists."""
    status, rows = call(account, "GET", existing_path or path)
    if status == 200 and isinstance(rows, list):
        for row in rows:
            if row.get(key) == payload.get(key):
                print(f"  = {label}: {payload.get(key)} (sudah ada)")
                return row
    status, body = call(account, "POST", path, payload)
    if status in (200, 201):
        print(f"  + {label}: {payload.get(key)}")
        return body
    print(f"  ! {label}: {payload.get(key)} -> HTTP {status} {body}")
    return None


today = date.today()

CUSTOMERS = [
    {"name": "PT Nusantara Apparel", "country": "Indonesia", "contact_name": "Bu Rina",
     "contact_info": "rina@nusantara-apparel.co.id", "notes": "Buyer lokal, order rutin tiap kuartal."},
    {"name": "Sakura Garment Co.", "country": "Japan", "contact_name": "Kenji Sato",
     "contact_info": "kenji@sakura-garment.jp", "notes": "Standar QC ketat, wajib PPM sebelum produksi."},
    {"name": "Lembah Hijau Uniform", "country": "Indonesia", "contact_name": "Pak Dimas",
     "contact_info": "dimas@lembahhijau.id", "notes": "Seragam korporat, volume menengah."},
    {"name": "Atlas Sportswear Ltd", "country": "Singapore", "contact_name": "Melissa Tan",
     "contact_info": "melissa@atlas-sport.sg", "notes": "Repeat order kaos olahraga."},
]

ORDERS = [
    {"buyer": "PT Nusantara Apparel", "order_type": "SAMPLE_PRODUCTION",
     "buyer_deadline": str(today + timedelta(days=45)),
     "notes": "Koleksi kemeja formal musim kantor.",
     "articles": [
         {"article_code": "NA-SHIRT-01", "garment_type": "Kemeja Formal", "qty": 1200,
          "size_breakdown": "S:200, M:400, L:400, XL:200", "sample_required": True},
         {"article_code": "NA-SHIRT-02", "garment_type": "Kemeja Casual", "qty": 800,
          "size_breakdown": "M:300, L:300, XL:200", "sample_required": True},
     ]},
    {"buyer": "Sakura Garment Co.", "order_type": "SAMPLE_ONLY",
     "buyer_deadline": str(today + timedelta(days=30)),
     "notes": "Sample approval dulu sebelum bulk.",
     "articles": [
         {"article_code": "SK-JKT-01", "garment_type": "Jaket Bomber", "qty": 50,
          "size_breakdown": "M:20, L:20, XL:10", "sample_required": True},
     ]},
    {"buyer": "Lembah Hijau Uniform", "order_type": "REPEAT_PRODUCTION",
     "buyer_deadline": str(today + timedelta(days=60)),
     "notes": "Repeat seragam, pola sama seperti batch sebelumnya.",
     "articles": [
         {"article_code": "LH-UNI-01", "garment_type": "Seragam Kerja", "qty": 2000,
          "size_breakdown": "S:400, M:700, L:600, XL:300", "sample_required": False},
     ]},
    {"buyer": "Atlas Sportswear Ltd", "order_type": "REPEAT_PRODUCTION",
     "buyer_deadline": str(today + timedelta(days=75)),
     "notes": "Kaos olahraga, bahan dryfit.",
     "articles": [
         {"article_code": "AT-TEE-01", "garment_type": "Kaos Olahraga", "qty": 3000,
          "size_breakdown": "S:600, M:1000, L:900, XL:500", "sample_required": False},
     ]},
]


def main():
    print("1) Customers (CMO Manager)")
    for c in CUSTOMERS:
        ensure("Customer", "cmo.manager", "/cmo/customers", c, "name")

    status, customers = call("cmo.manager", "GET", "/cmo/customers")
    by_name = {c["name"]: c["id"] for c in customers} if status == 200 else {}

    print("\n2) Orders + Articles (CMO Manager)")
    status, existing = call("cmo.manager", "GET", "/orders")
    existing_buyers = {o["buyer"] for o in existing} if status == 200 else set()
    for o in ORDERS:
        if o["buyer"] in existing_buyers:
            print(f"  = Order: {o['buyer']} (sudah ada)")
            continue
        payload = dict(o)
        if o["buyer"] in by_name:
            payload["customer_id"] = by_name[o["buyer"]]
        status, body = call("cmo.manager", "POST", "/orders", payload)
        if status in (200, 201):
            print(f"  + Order: {body.get('order_id')} — {o['buyer']} ({o['order_type']})")
        else:
            print(f"  ! Order: {o['buyer']} -> HTTP {status} {body}")

    print("\n3) Employees (CHRO Manager)")
    employees = [
        {"employee_no": "EMP-001", "name": "Siti Rahayu", "division": "Produksi",
         "position": "Operator Jahit", "employment_status": "ACTIVE"},
        {"employee_no": "EMP-002", "name": "Budi Santoso", "division": "Produksi",
         "position": "Supervisor Cutting", "employment_status": "ACTIVE"},
        {"employee_no": "EMP-003", "name": "Andi Wijaya", "division": "Quality Control",
         "position": "QC Inspector", "employment_status": "ACTIVE"},
        {"employee_no": "EMP-004", "name": "Dewi Lestari", "division": "Logistik",
         "position": "Admin Gudang", "employment_status": "ACTIVE"},
    ]
    for e in employees:
        ensure("Employee", "chro.manager", "/chro/employees", e, "employee_no")

    print("\n4) Ringkasan")
    for label, account, path in [("Customers", "cmo.manager", "/cmo/customers"),
                                 ("Orders", "cmo.manager", "/orders"),
                                 ("Employees", "chro.manager", "/chro/employees")]:
        status, rows = call(account, "GET", path)
        n = len(rows) if status == 200 and isinstance(rows, list) else f"HTTP {status}"
        print(f"  {label}: {n}")


if __name__ == "__main__":
    sys.exit(main())
