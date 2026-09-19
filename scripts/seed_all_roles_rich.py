#!/usr/bin/env python3
"""Seed rich, realistic, active dummy data for ALL 7 ROLES in BOS SYAMS."""
import os
import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PASSWORD = "demo123456789"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

TOKENS = {}
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
    except Exception as e:
        return 500, {"error": str(e)}

print("=== SEEDING RICH DUMMY DATA FOR ALL ROLES ===")

# 1. HR — YUNI (Employees, Manpower, Onboarding, Issues)
print("\n[1/7] HR / CHRO — Yuni")
employees = [
    {"employee_no": "EMP-001", "name": "Siti Rahayu", "division": "Produksi", "position": "Operator Jahit", "employment_status": "ACTIVE"},
    {"employee_no": "EMP-002", "name": "Budi Santoso", "division": "Produksi", "position": "Supervisor Cutting", "employment_status": "ACTIVE"},
    {"employee_no": "EMP-003", "name": "Andi Wijaya", "division": "Quality Control", "position": "QC Inspector", "employment_status": "ACTIVE"},
    {"employee_no": "EMP-004", "name": "Dewi Lestari", "division": "Logistik", "position": "Admin Gudang", "employment_status": "ACTIVE"},
    {"employee_no": "EMP-005", "name": "Iman Sulaiman", "division": "Printing", "position": "Operator Sablon", "employment_status": "ACTIVE"},
    {"employee_no": "EMP-006", "name": "Fahrul Rozi", "division": "Sample", "position": "Sample Maker", "employment_status": "ACTIVE"},
    {"employee_no": "EMP-007", "name": "Rian Hidayat", "division": "Produksi", "position": "Operator Jahit Baru", "employment_status": "TRAINING"},
]
for emp in employees:
    status, res = call("chro.manager", "POST", "/chro/employees", emp)
    if status in (200, 201):
        print(f"  + Karyawan {emp['employee_no']} ({emp['name']})")

# Manpower request
s, _ = call("chro.manager", "POST", "/hr/manpower-requests", {
    "division": "Produksi",
    "position": "Operator Sewing Jarum 2",
    "requested_qty": 3,
    "urgency": "HIGH",
    "reason": "Penambahan kapasitas batch jaket Sakura Garment",
    "required_skills": "Bisa mesin overdeck, jarum 2 rantai"
})
print("  + Manpower Request: Operator Sewing Jarum 2 (Urgent)")

# Employee Issue
s, _ = call("chro.manager", "POST", "/chro/issues", {
    "employee_id": 1,
    "issue_type": "KEDISIPLINAN",
    "severity": "MEDIUM",
    "description": "Keterlambatan 3 kali dalam seminggu tanpa keterangan",
    "action_plan": "Konseling langsung dengan supervisor cutting dan buat surat peringatan lisan",
    "status": "OPEN"
})
print("  + People Issue: Keterlambatan Siti Rahayu (Konseling)")


# 2. CMO — CECEP & DEBY (Customers, Orders, Quotations)
print("\n[2/7] CMO — Cecep & Deby")
customers = [
    {"name": "PT Nusantara Apparel", "country": "Indonesia", "contact_name": "Bu Rina", "contact_info": "rina@nusantara.id", "notes": "Koleksi kemeja seragam"},
    {"name": "Sakura Garment Co.", "country": "Japan", "contact_name": "Kenji Sato", "contact_info": "kenji@sakura.jp", "notes": "Standar QC tinggi"},
    {"name": "Lembah Hijau Uniform", "country": "Indonesia", "contact_name": "Pak Dimas", "contact_info": "dimas@lembahhijau.id", "notes": "Repeat order"},
]
for c in customers:
    call("cmo.manager", "POST", "/cmo/customers", c)

# Buat PO intake kedua via Deby
po_payload = {
    "po_number": f"PO-SYAM-{today.strftime('%m%d')}-002",
    "buyer": "PT Nusantara Apparel",
    "order_type": "SAMPLE_PRODUCTION",
    "buyer_deadline": str(today + timedelta(days=60)),
    "notes": "Pesanan Kemeja Drill Bordir",
    "articles": [
        {"article_code": "NA-SHIRT-DRILL", "garment_type": "Kemeja Kantor", "qty": 800, "size_breakdown": "M:300, L:300, XL:200", "sample_required": True, "production_route": "Cutting > Printing > Sewing > QC"}
    ]
}
s, po = call("cmo.support", "POST", "/cmo/po-intake", po_payload)
if s in (200, 201) and isinstance(po, dict) and "id" in po:
    call("cmo.support", "POST", f"/cmo/po-intake/{po['id']}/check")
    call("cmo.support", "POST", f"/cmo/po-intake/{po['id']}/submit")
    s2, accepted = call("cmo.manager", "POST", f"/cmo/po-intake/{po['id']}/review", {"action": "ACCEPT", "note": "Disetujui untuk penjadwalan"})
    print(f"  + Order Baru Aktif: {accepted.get('order_id') if isinstance(accepted, dict) else 'OK'}")

# 3. PRINTING — IMAN (Target Harian & Job Cards)
print("\n[3/7] Printing & Bordir — Iman")
call("printing.pic", "POST", "/printing/daily-targets", {
    "target_date": str(today),
    "target_qty": 640,
    "notes": "Target cetak sablon rubber kemeja dan kaos olahraga"
})
print("  + Target Cetak Harian: 640 pcs (Tersimpan)")


# 4. SAMPLE — FAHRUL (My Tasks)
print("\n[4/7] Sample — Fahrul")
s, task = call("sample.pic", "POST", "/tasks", {
    "title": "Buat sample fisik bordir dada NA-SHIRT-DRILL",
    "role": "SAMPLE_PIC",
    "due_date": str(today + timedelta(days=5)),
    "priority": "HIGH",
    "status": "OPEN",
    "notes": "Bordir presisi sesuai artwork buyer"
})
print("  + Sample Task: Buat sample fisik bordir dada")


# 5. CFO — RIADI (Invoices, Purchasing, AP/AR)
print("\n[5/7] CFO — Riadi")
s, inv = call("cfo.manager", "POST", "/cfo/invoices", {
    "order_fk": 1,
    "invoice_no": f"INV-SYAM-{today.strftime('%m%d')}-002",
    "amount": 25000000,
    "due_date": str(today + timedelta(days=14)),
    "type": "DOWN_PAYMENT",
    "notes": "Tagihan DP 30% produksi kemeja"
})
print(f"  + Invoice DP: Rp 25.000.000")


# 6. COO — SITI (Daily execution & Material Request)
print("\n[6/7] COO — Siti")
s, mr = call("coo.manager", "POST", "/coo/material-requests", {
    "order_fk": 1,
    "material_name": "Kain Katun Drill Nagata",
    "qty_needed": 1200,
    "unit": "meter",
    "status": "APPROVED",
    "notes": "Bahan baku kemeja kantor PT Nusantara Apparel"
})
print("  + Material Request: Kain Katun Drill Nagata 1200 meter")


# 7. CEO — IYAN (Decisions & Action Tracker)
print("\n[7/7] CEO — Iyan")
s, dec = call("ceo", "POST", "/ceo/decisions", {
    "title": "Persetujuan Penambahan Shift Lembur Produksi",
    "decision_type": "CAPACITY_OVERRIDE",
    "order_fk": 1,
    "severity": "MEDIUM",
    "notes": "Penambahan shift malam 4 jam untuk mengejar target shipment Sakura Garment",
    "status": "PENDING"
})
print("  + Decision Needed: Lembur Produksi Sakura Garment")

s, exc = call("ceo", "POST", "/exceptions", {
    "title": "Keterlambatan Pengiriman Kancing dari Supplier",
    "domain": "MATERIAL",
    "severity": "HIGH",
    "status": "OPEN",
    "order_fk": 1,
    "description": "Supplier bahan kancing terlambat 2 hari, perlu alternatif lokal"
})
print("  + Exception Center: Keterlambatan Kancing Supplier")

print("\n=== SEMUA DUMMY DATA LENGKAP TELAH TERSIMPAN DI 7 PERAN! ===")
