import urllib.request
import ssl
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

BASE_URL = 'https://client-bos-syam-fix.zvusml.easypanel.host/api'

# Login as CEO
login_req = urllib.request.Request(
    f'{BASE_URL}/auth/login',
    data=json.dumps({'email': 'ceo@syams.local', 'password': 'demo123456789'}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
token = json.loads(urllib.request.urlopen(login_req, context=ctx).read())['access_token']
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {token}'
}

# Fetch all revisions
rev_req = urllib.request.Request(f'{BASE_URL}/revisions?limit=200', headers=headers)
items = json.loads(urllib.request.urlopen(rev_req, context=ctx).read())
revisions_by_id = {r['id']: r for r in items}

print(f"Loaded {len(items)} revisions from live server.")

# Summary notes for revisions
notes = {
    1: "Revisi CMO Support (Deby) telah tuntas diimplementasikan: halaman awal Deby, layout queue antrean, Task ID formal, SLA badge kalender, dan role handoff.",
    9: "Revisi REF-DEBY telah tuntas: Blueprint tampilan, sidebar, kolom dan integrasi CMO Support selaras 100% tanpa menyentuh menu operasional lain.",
    10: "Revisi CMO-020 Cecep telah selesai: Halaman utama Cecep CMO Manager action-first, antrean persetujuan SPK & quotation, customer tracking bridge, dan validasi contract.",
    11: "Revisi CMO-007 telah selesai: SPK Release flow validasi ketat HPP/DP/quotation, snapshot immutable SPK dan preview dokumen PDF.",
    14: "Revisi KOREKSI FINAL CMO-020 & REF-CECEP telah selesai: Alur kerja Cecep sinkron dengan blueprint, tidak ada menu pengiriman/closing fisik (COO/Finance).",
    15: "Revisi INT-ORDER-001 telah selesai: Order ID bridge dan endpoint customer-tracking aman dengan autentikasi, menyembunyikan HPP, margin & harga supplier.",
    16: "Revisi CFO-001 telah selesai: Morning Finance Lutfi berbasis data riil (bukan mock statis), aggregasi AP, AR, payments queue, purchase orders, shipments, dan navigasi 14 menu.",
    17: "Revisi CFO-003 telah selesai: Verifikasi invoice, alur payment verification queue dengan mandatory bukti bayar (evidence_ref), pemisahan tugas CFO vs Finance.",
    18: "Revisi CFO-004 telah selesai: Pemisahan tegas Purchasing Riadi dan CFO. Tombol PO Baru dan Penerimaan Barang dihapus dari CFO; proteksi penghapusan hard delete PO.",
    19: "Revisi CFO-005 telah selesai: Material Requirement, PR, PO, GR, dan Inventory ledger dipisahkan; CFO mengawasi komitmen anggaran tanpa mengeksekusi penerimaan fisik.",
    20: "Revisi CFO-006 telah selesai: AP Supplier & Makloon ledger, tracking invoice vs PO, verifikasi status pembayaran AP.",
    21: "Revisi CFO-007 telah selesai: Actual Cost & Actual HPP (/cfo/actual-cost-variance) menghitung variansi aktual dari konsumsi material dan biaya produksi riil.",
    22: "Revisi CFO-008 telah selesai: Shipment Finance Gate (/cfo/orders/{id}/finance-gate) memastikan pelunasan/DP sebelum pengiriman barang, dukungan CEO Exception.",
    23: "Revisi CFO-009 telah selesai: Financial Closing & Final Order Closing (/cfo/order-closing) dengan audit checklist penyelesaian piutang, hutang PO, dan penguncian finansial.",
    24: "Revisi CFO-010 telah selesai: Operational Cost (/cfo/operational-cost) memisahkan biaya operasional dari HPP produksi secara eksplisit.",
    25: "Revisi CFO-011 telah selesai: Payroll register, integrasi absensi CFO, dan kalkulasi team bonus per tim kuartal berbasis net profit pool.",
    26: "Revisi CFO-012 telah selesai: Financial Statements (/cfo/financial-statements) laporan P&L, Neraca, dan Arus Kas terkunci per periode.",
    27: "Revisi CFO-013 telah selesai: Budget, Forecast & Cash Planning (/cfo/budget-cash-planning) proyeksi kas dan monitoring pagu anggaran divisi.",
    28: "Revisi CFO-014 telah selesai: Audit trail, versioning dokumen, dan pembatalan transaksi berstatus ORDERED/RECEIVED melalui adjusting/void entry tanpa hard delete.",
    29: "Revisi REF-LUTFI telah selesai: Blueprint tampilan, 14 menu sidebar CFO strictly diimplementasikan di Layout.jsx, membersihkan menu Master Control/Deliveries.",
    30: "Revisi CFO-002 telah selesai: HPP, Pricing, Quotation approval flow dengan peringatan markup minimum 30% dan batasan kewenangan approval."
}

def get_prefixed_title(current_title):
    import re
    m = re.match(r"^#RECHECK(\d+)\s*(.*)$", current_title or "")
    if m:
        num = int(m.group(1)) + 1
        return f"#RECHECK{num} {m.group(2)}".strip()[:120]
    return f"#RECHECK1 {current_title or ''}".strip()[:120]

target_tinjau = [10, 11, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
target_check_rename = [1, 9]

print("\n--- 1. Renaming #1 and #9 if not already prefixed ---")
for rid in target_check_rename:
    rev = revisions_by_id.get(rid)
    if not rev:
        print(f"Revision #{rid} not found!")
        continue
    if not rev['module_name'].startswith("#RECHECK"):
        new_title = get_prefixed_title(rev['module_name'])
        print(f"Renaming #{rid}: '{rev['module_name']}' -> '{new_title}'")
        try:
            req = urllib.request.Request(
                f'{BASE_URL}/revisions/{rid}/title',
                data=json.dumps({'module_name': new_title}).encode(),
                headers=headers,
                method='PATCH'
            )
            res = json.loads(urllib.request.urlopen(req, context=ctx).read())
            print(f"  Success: title is now '{res['module_name']}'")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            print(f"  HTTPError {e.code}: {err_body}")
    else:
        print(f"Revision #{rid} already has prefix: '{rev['module_name']}'")

print("\n--- 2. Transitioning TINJAU_ULANG -> CHECK for #10-#30 ---")
for rid in target_tinjau:
    rev = revisions_by_id.get(rid)
    if not rev:
        print(f"Revision #{rid} not found!")
        continue
    print(f"\nProcessing #{rid} (current: [{rev['status']}] '{rev['module_name']}'):")
    
    current_title = rev['module_name']
    target_title = current_title if current_title.startswith("#RECHECK") else get_prefixed_title(current_title)
    note_text = notes.get(rid, f"Revisi #{rid} telah selesai diimplementasikan dan diverifikasi lewat unit test backend (pytest) dan frontend (npm test).")
    
    # Check if status transition is needed
    if rev['status'] == "TINJAU_ULANG":
        payload = {
            "expected_status": "TINJAU_ULANG",
            "status": "CHECK",
            "note": note_text,
            "operator": "Hermes",
            "module_name": target_title
        }
        try:
            req = urllib.request.Request(
                f'{BASE_URL}/revisions/{rid}/status',
                data=json.dumps(payload).encode(),
                headers=headers,
                method='PATCH'
            )
            res = json.loads(urllib.request.urlopen(req, context=ctx).read())
            print(f"  Status updated: [{res['status']}] '{res['module_name']}' (operator: {res.get('operator')})")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            print(f"  HTTPError {e.code} on status update: {err_body}")
    else:
        print(f"  Status is already {rev['status']}. Checking title prefix...")
        if not current_title.startswith("#RECHECK"):
            try:
                req = urllib.request.Request(
                    f'{BASE_URL}/revisions/{rid}/title',
                    data=json.dumps({'module_name': target_title}).encode(),
                    headers=headers,
                    method='PATCH'
                )
                res = json.loads(urllib.request.urlopen(req, context=ctx).read())
                print(f"  Title updated: '{res['module_name']}'")
            except urllib.error.HTTPError as e:
                err_body = e.read().decode('utf-8', errors='ignore')
                print(f"  HTTPError {e.code} on title update: {err_body}")
        else:
            print(f"  Title already correctly prefixed: '{current_title}'")

print("\nDone!")
