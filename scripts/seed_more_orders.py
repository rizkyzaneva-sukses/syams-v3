import urllib.request
import json
from uuid import uuid4
from datetime import date, timedelta

BASE = "http://127.0.0.1:8000"
today = date.today()

def login(acc):
    b = json.dumps({"email": f"{acc}@syams.local", "password": "demo123456789"}).encode()
    r = urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/auth/login", data=b, headers={"Content-Type": "application/json"}))
    return json.loads(r.read())["access_token"]

tok_deby = login("cmo.support")
tok_cecep = login("cmo.manager")
tok_riadi = login("cfo.manager")

orders_to_create = [
    {
        "po": "PO-SAKURA-002",
        "buyer": "Sakura Garment Co.",
        "type": "SAMPLE_PRODUCTION",
        "deadline": str(today + timedelta(days=35)),
        "notes": "Jaket Bomber Musim Dingin - Butuh sample bordir dulu",
        "articles": [{"article_code": "SK-BOMBER-01", "garment_type": "Jaket Bomber", "qty": 200, "size_breakdown": "M:80, L:80, XL:40", "sample_required": True, "production_route": "Cutting > Embroidery > Sewing > QC"}]
    },
    {
        "po": "PO-LEMBAH-003",
        "buyer": "Lembah Hijau Uniform",
        "type": "REPEAT_PRODUCTION",
        "deadline": str(today + timedelta(days=50)),
        "notes": "Seragam Karyawan Lapangan",
        "articles": [{"article_code": "LH-POLO-01", "garment_type": "Kaos Polo Lacoste", "qty": 600, "size_breakdown": "S:100, M:250, L:200, XL:50", "sample_required": False, "production_route": "Cutting > Printing > Sewing > QC"}]
    }
]

for o in orders_to_create:
    req = urllib.request.Request(f"{BASE}/api/cmo/po-intake", data=json.dumps({"po_number": o["po"], "buyer": o["buyer"], "order_type": o["type"], "buyer_deadline": o["deadline"], "notes": o["notes"], "articles": o["articles"]}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok_deby}"})
    try:
        with urllib.request.urlopen(req) as resp:
            po = json.loads(resp.read())
            po_id = po["id"]
            bnd = "----BOS" + uuid4().hex
            pdf_body = (
                f"--{bnd}\r\n"
                f'Content-Disposition: form-data; name="document"; filename="{o["po"]}.pdf"\r\n'
                f"Content-Type: application/pdf\r\n\r\n"
                f"%PDF-1.4\nDemo PO\r\n--{bnd}--\r\n"
            ).encode()
            urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/cmo/po-intake/{po_id}/document", data=pdf_body, headers={"Content-Type": f"multipart/form-data; boundary={bnd}", "Authorization": f"Bearer {tok_deby}"}))
            urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/cmo/po-intake/{po_id}/check", data=b"", headers={"Authorization": f"Bearer {tok_deby}"}))
            urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/cmo/po-intake/{po_id}/submit", data=b"", headers={"Authorization": f"Bearer {tok_deby}"}))
            r_acc = urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/cmo/po-intake/{po_id}/review", data=json.dumps({"action": "ACCEPT", "note": "PO diverifikasi dan diterima"}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok_cecep}"}))
            accepted = json.loads(r_acc.read())
            order_id = accepted.get("order_id")
            print(f"Created active order: {order_id} for {o['buyer']}")
            
            # Create Quotation for this order
            q_payload = {
                "quotation_no": f"QT-{o['po']}",
                "order_fk": accepted.get("order_pk", 2 if "SAKURA" in o['po'] else 3),
                "subtotal": 35000000 if "SAKURA" in o['po'] else 48000000,
                "ppn_amount": 3850000 if "SAKURA" in o['po'] else 5280000,
                "grand_total": 38850000 if "SAKURA" in o['po'] else 53280000,
                "dp_percent": 30,
                "dp_amount": 11655000 if "SAKURA" in o['po'] else 15984000,
                "valid_until": str(today + timedelta(days=20)),
                "status": "DRAFT"
            }
            try:
                rq = urllib.request.Request(f"{BASE}/api/cmo/quotations", data=json.dumps(q_payload).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok_cecep}"})
                with urllib.request.urlopen(rq) as q_resp:
                    print(f"  + Quotation created: {q_payload['quotation_no']}")
            except Exception as ex:
                print("  ! Quotation skipped", ex)
    except Exception as e:
        print("Failed to create order for", o["po"], e)
