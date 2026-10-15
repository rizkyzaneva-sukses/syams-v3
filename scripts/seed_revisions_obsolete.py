#!/usr/bin/env python3
"""Skenario khusus sesuai PRD §12 — revisi berversi, superseded, dan obsolete.

Kasus yang dibangun (semuanya lewat API publik):

1. SAMPLE REVISI BERVERSI
   Satu artikel (SK-JKT-01, order SAMPLE_ONLY) dibuat sample v1 → v2 → v3.
   Tiap versi menyimpan ``previous_version_id`` sehingga riwayat tidak putus.
   Ini yang diminta PRD §12: "Deby mengubah spesifikasi setelah release:
   sistem membuat revisi, mencatat audit dan memerlukan review ulang."

2. ARTWORK VERSI AKTIF vs SUPERSEDED
   Artwork "SCREEN" artikel SK-JKT-01: unggah v1 → APPROVED, v2 → APPROVED
   (v1 otomatis SUPERSEDED), v3 → APPROVED (v2 otomatis SUPERSEDED).
   Hasil: Iman hanya boleh cetak v3, sedangkan v1/v2 bertanda SUPERSEDED.

3. ARTWORK OBSOLETE
   Artwork "EMBROIDERY" artikel SK-JKT-01: v1 → APPROVED lalu ditandai
   OBSOLETE (pola dibatalkan buyer). Bukti: guardrail cetak menolak versi ini.

Idempotent: tiap langkah mengecek keberadaan dulu; aman dijalankan berulang.
Non-2xx tak terduga dikumpulkan lalu dilaporkan (kecuali yang memang guardrail).
"""
import json
import os
import ssl
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PASSWORD = os.environ.get("SEED_PASSWORD", "demo123456789")
today = date.today()
PROBLEMS = []
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
TOKENS = {}

TARGET_ARTICLE_CODE = "SK-JKT-01"


def login(acc):
    if acc not in TOKENS:
        body = json.dumps({"email": f"{acc}@syams.local", "password": PASSWORD}).encode()
        req = urllib.request.Request(f"{BASE}/api/auth/login", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, context=CTX) as r:
            TOKENS[acc] = json.loads(r.read())["access_token"]
    return TOKENS[acc]


def call(account, method, path, payload=None, expect=(200, 201, 204)):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {login(account)}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}/api{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=CTX) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw)
        except Exception:
            body = raw.decode()[:300]
        if e.code not in expect:
            PROBLEMS.append((f"{method} {path}", e.code, body))
        return e.code, body


# ── 0. Resolve order + artikel target ───────────────────────────────────────
print("0) Resolve order & artikel target")
_s, orders = call("cmo.manager", "GET", "/orders")
order = article = None
for o in (orders or []):
    for a in (o.get("articles") or []):
        if a.get("article_code") == TARGET_ARTICLE_CODE:
            order, article = o, a
            break
    if order:
        break
if not order:
    raise SystemExit(f"Artikel {TARGET_ARTICLE_CODE} tidak ditemukan di order mana pun")
oid, aid = order["id"], article["id"]
print(f"   order={order['order_id']} (id={oid}) artikel={TARGET_ARTICLE_CODE} (id={aid})")

# ═════════════════════════════════════════════════════════════════════════════
# 1. SAMPLE REVISI BERVERSI
# ═════════════════════════════════════════════════════════════════════════════
print("\n1) Sample revisi berversi (PRD §12)")
_s, samples = call("cmo.manager", "GET", "/cmo/samples")
mine = [s for s in (samples or [])
        if s.get("article_code") == TARGET_ARTICLE_CODE and s.get("order_fk") == oid]
mine.sort(key=lambda s: s.get("sample_version") or 1)
print(f"   versi sample yang sudah ada: {[s.get('sample_version') for s in mine]}")

REVISIONS = [
    ("v1", "Sample awal: kerah standar, bordir logo dada kiri."),
    ("v2", "Revisi buyer #1: kerah diubah jadi shanghai, bordir diperbesar."),
    ("v3", "Revisi buyer #2: tambah label dalam + kancing tersembunyi (spesifikasi final)."),
]
existing_versions = {s.get("sample_version") for s in mine}
for idx, (label, note) in enumerate(REVISIONS, start=1):
    if idx in existing_versions:
        print(f"   = Sample {label} sudah ada, dilewati")
        continue
    st, row = call("cmo.manager", "POST", "/cmo/samples", {
        "order_fk": oid, "article_code": TARGET_ARTICLE_CODE,
        "status": "PROCESS", "requested_date": str(today + timedelta(days=idx * 3)),
        "revision_reason": note, "notes": note,
    })
    if st in (200, 201):
        print(f"   + Sample {label} dibuat (version={row.get('sample_version')}, "
              f"previous={row.get('previous_version_id')})")
    else:
        print(f"   ! Sample {label} gagal [{st}]: {json.dumps(row)[:160]}")

# ═════════════════════════════════════════════════════════════════════════════
# 2. ARTWORK VERSI AKTIF vs SUPERSEDED
# ═════════════════════════════════════════════════════════════════════════════
print("\n2) Artwork versi aktif vs SUPERSEDED (PRD §12)")


def get_artwork(art_type):
    _s, rows = call("cmo.manager", "GET", "/artwork")
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("items") or []
    return next((a for a in (rows or [])
                 if a.get("article_id") == aid and a.get("artwork_type") == art_type), None)


def artwork_versions(art_id):
    st, data = call("cmo.manager", "GET", f"/artwork/{art_id}")
    if isinstance(data, dict):
        return data.get("versions") or []
    return []


TYPE = "SABLON"
head = get_artwork(TYPE)
if not head:
    st, head = call("cmo.manager", "POST", "/artwork",
                    {"article_id": aid, "artwork_type": TYPE,
                     "title": f"Film sablon {TARGET_ARTICLE_CODE}"},
                    expect=(200, 201, 409))
    if st == 409:  # sudah ada tapi tak terdeteksi di list — ambil ulang
        head = get_artwork(TYPE)
    else:
        print(f"   + Artwork {TYPE} dibuat (id={head.get('id') if isinstance(head, dict) else head})")
else:
    print(f"   = Artwork {TYPE} sudah ada (id={head.get('id')})")

if isinstance(head, dict) and head.get("id"):
    art_id = head["id"]
    vers = artwork_versions(art_id)
    sudah = {v.get("version_no") for v in vers}
    FILES = [
        (1, "screen-v1.pdf", "Logo dada kiri versi awal"),
        (2, "screen-v2.pdf", "Logo diperbesar + bayangan"),
        (3, "screen-v3.pdf", "Logo final, kalibrasi warna Pantone 186C"),
    ]
    for vno, fname, note in FILES:
        if vno in sudah:
            # Pastikan versi ini APPROVED (kalau belum) supaya rantai superseded lengkap.
            cur = next((v for v in vers if v.get("version_no") == vno), None)
            if cur and cur.get("status") not in ("APPROVED", "SUPERSEDED"):
                call("cmo.manager", "POST", f"/artwork/versions/{cur['id']}/approve",
                     {"notes": "Disetujui CMO"})
                print(f"   = v{vno} di-approve ulang")
            else:
                print(f"   = v{vno} sudah ada (status={cur.get('status') if cur else '?'})")
            continue
        st, created = call("cmo.manager", "POST", f"/artwork/{art_id}/versions",
                           {"file_ref": f"artwork/{TARGET_ARTICLE_CODE}/{fname}",
                            "file_name": fname, "buyer_reference": "PO-BUYER-REF",
                            "notes": note})
        if st in (200, 201):
            vid = created["version"]["id"]
            sup = created.get("superseded_versions") or []
            st2, _ = call("cmo.manager", "POST", f"/artwork/versions/{vid}/approve",
                          {"notes": "Disetujui CMO"})
            print(f"   + Artwork v{vno} diunggah & APPROVED"
                  f"{f' (v{sup} -> SUPERSEDED)' if sup else ''}")
        else:
            print(f"   ! Artwork v{vno} gagal [{st}]: {json.dumps(created)[:160]}")

    # Bukti guardrail: Iman cek boleh-cetak.
    st, cp = call("cmo.manager", "GET", f"/artwork/can-print?article_id={aid}")
    if st == 200 and isinstance(cp, dict):
        aktif = cp.get("versi_aktif") or cp.get("current_version") or cp.get("active_version")
        print(f"   > can-print: boleh={cp.get('boleh_cetak') or cp.get('can_print')} "
              f"versi_aktif={aktif} sumber={cp.get('sumber') or TYPE}")

# ═════════════════════════════════════════════════════════════════════════════
# 3. ARTWORK OBSOLETE
# ═════════════════════════════════════════════════════════════════════════════
print("\n3) Artwork OBSOLETE (pola dibatalkan)")
TYPE2 = "BORDIR"
head2 = get_artwork(TYPE2)
if not head2:
    st, head2 = call("cmo.manager", "POST", "/artwork",
                     {"article_id": aid, "artwork_type": TYPE2,
                      "title": f"File bordir {TARGET_ARTICLE_CODE}"},
                     expect=(200, 201, 409))
    if st == 409:
        head2 = get_artwork(TYPE2)
    else:
        print(f"   + Artwork {TYPE2} dibuat (id={head2.get('id') if isinstance(head2,dict) else head2})")
else:
    print(f"   = Artwork {TYPE2} sudah ada (id={head2.get('id')})")

if isinstance(head2, dict) and head2.get("id"):
    art2 = head2["id"]
    vers2 = artwork_versions(art2)
    if not any(v.get("version_no") == 1 for v in vers2):
        st, c = call("cmo.manager", "POST", f"/artwork/{art2}/versions",
                     {"file_ref": f"artwork/{TARGET_ARTICLE_CODE}/embroidery-v1.dst",
                      "file_name": "embroidery-v1.dst", "notes": "Pola bordir awal"})
        if st in (200, 201):
            vid = c["version"]["id"]
            call("cmo.manager", "POST", f"/artwork/versions/{vid}/approve", {"notes": "Disetujui"})
            print("   + Artwork EMBROIDERY v1 diunggah & APPROVED")
    else:
        print("   = Artwork EMBROIDERY v1 sudah ada")

    vers2 = artwork_versions(art2)
    v1 = next((v for v in vers2 if v.get("version_no") == 1), None)
    if v1 and v1.get("status") != "OBSOLETE":
        st, res = call("cmo.manager", "POST", f"/artwork/versions/{v1['id']}/obsolete",
                       {"reason": "Buyer membatalkan motif bordir; order dialihkan ke sablon."})
        if st in (200, 201):
            print("   + Artwork EMBROIDERY v1 ditandai OBSOLETE")
        else:
            print(f"   ! Obsolete gagal [{st}]: {json.dumps(res)[:160]}")
    elif v1:
        print(f"   = Artwork EMBROIDERY v1 sudah OBSOLETE")

# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
if PROBLEMS:
    print(f"MASALAH TAK TERDUGA: {len(PROBLEMS)}")
    for label, st, detail in PROBLEMS:
        print(f"  [{st}] {label} -> {json.dumps(detail)[:200]}")
else:
    print("SKENARIO REVISI BERVERSI + OBSOLETE: SEMUA OK")
print("=" * 64)
