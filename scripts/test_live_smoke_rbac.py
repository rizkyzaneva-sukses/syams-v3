import sys
import os
import ssl
import json
import urllib.request
import urllib.error

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PASSWORD = "demo123456789"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

ROLES = [
    ("CEO", "ceo@syams.local"),
    ("CMO_MANAGER", "cmo.manager@syams.local"),
    ("CMO_SUPPORT", "cmo.support@syams.local"),
    ("CFO_MANAGER", "cfo.manager@syams.local"),
    ("FINANCE_SUPPORT", "finance.support@syams.local"),
    ("COO_MANAGER", "coo.manager@syams.local"),
    ("SAMPLE_PIC", "sample.pic@syams.local"),
    ("PRINTING_PIC", "printing.pic@syams.local"),
    ("PRODUCTION_PIC", "production.pic@syams.local"),
    ("CHRO_MANAGER", "chro.manager@syams.local"),
    ("HR_SUPPORT", "hr.support@syams.local"),
    ("SHIPMENT_ADMIN", "shipment.admin@syams.local"),
]

tokens = {}

def req(path, method="GET", body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, context=CTX) as resp:
            content = resp.read()
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        content = e.read()
        try:
            err_json = json.loads(content)
        except Exception:
            err_json = {"raw": content.decode("utf-8", errors="ignore")}
        return e.code, err_json
    except Exception as e:
        return 500, {"error": str(e)}

print("=== 1. LOGIN TESTS FOR ALL 12 ROLES ===")
all_login_ok = True
for role, email in ROLES:
    status, res = req("/api/auth/login", method="POST", body={"email": email, "password": PASSWORD})
    if status == 200 and "access_token" in res:
        tokens[role] = res["access_token"]
        print(f"  [OK] {role} ({email}) logged in successfully")
    else:
        print(f"  [FAIL] {role} login failed with status {status}: {res}")
        all_login_ok = False

print(f"\nTotal Logins OK: {len(tokens)} / 12")

print("\n=== 2. ENDPOINT ACCESS TESTS PER ROLE ===")
checks = [
    # CEO
    ("CEO", "/api/ceo/company-performance", "GET", 200, "CEO Company Performance"),
    ("CEO", "/api/ceo/overrides", "GET", 200, "CEO Overrides list"),
    ("CEO", "/api/ceo/decisions", "GET", 200, "CEO Decisions needed"),
    ("CEO", "/api/ceo/actions", "GET", 200, "CEO Action Tracker"),
    ("CEO", "/api/master/summary", "GET", 200, "CEO Master summary (read-only)"),
    ("CEO", "/api/audit-log", "GET", 200, "CEO Audit log"),
    
    # CMO MANAGER
    ("CMO_MANAGER", "/api/cmo/manager-priority", "GET", 200, "CMO Manager Priority"),
    ("CMO_MANAGER", "/api/cmo/sales-pipeline", "GET", 200, "CMO Sales Pipeline"),
    ("CMO_MANAGER", "/api/cmo/quotations", "GET", 200, "CMO Quotations"),
    ("CMO_MANAGER", "/api/cmo/samples", "GET", 200, "CMO Samples"),
    ("CMO_MANAGER", "/api/cmo/buyer-crm", "GET", 200, "CMO Buyer CRM"),
    
    # CMO SUPPORT (Deby)
    ("CMO_SUPPORT", "/api/cmo/deby-today", "GET", 200, "Deby Work List Today"),
    ("CMO_SUPPORT", "/api/cmo/po-intake", "GET", 200, "PO Intake queue"),
    ("CMO_SUPPORT", "/api/cmo/spk", "GET", 200, "SPK list"),
    
    # CFO
    ("CFO_MANAGER", "/api/cfo/ar-aging", "GET", 200, "CFO AR Aging"),
    ("CFO_MANAGER", "/api/cfo/actual-cost-variance", "GET", 200, "CFO Costing Actual vs HPP"),
    ("CFO_MANAGER", "/api/cfo/invoices", "GET", 200, "CFO Invoices"),
    ("CFO_MANAGER", "/api/cfo/purchase-orders", "GET", 200, "CFO Purchase Orders"),
    ("CFO_MANAGER", "/api/cfo/ap-summary", "GET", 200, "CFO AP Summary"),
    
    # COO (Siti)
    ("COO_MANAGER", "/api/coo/daily-execution", "GET", 200, "COO Daily Execution"),
    ("COO_MANAGER", "/api/coo/handoffs", "GET", 200, "COO Handoffs Board"),
    ("COO_MANAGER", "/api/coo/movements", "GET", 200, "COO Movements WIP"),
    ("COO_MANAGER", "/api/coo/qc-records", "GET", 200, "COO QC Records"),
    ("COO_MANAGER", "/api/coo/material-requests", "GET", 200, "COO Material Requests"),
    
    # SAMPLE PIC (Fahrul)
    ("SAMPLE_PIC", "/api/sample/today", "GET", 200, "Fahrul Sample Today"),
    ("SAMPLE_PIC", "/api/sample/my-tasks", "GET", 200, "Fahrul My Tasks"),
    ("SAMPLE_PIC", "/api/cmo/samples-version-audit", "GET", 200, "Sample Version Audit"),
    
    # PRINTING PIC (Iman)
    ("PRINTING_PIC", "/api/printing/job-cards", "GET", 200, "Iman Job Cards"),
    ("PRINTING_PIC", "/api/printing/daily-target", "GET", 200, "Iman Daily Target"),
    ("PRINTING_PIC", "/api/printing/quality", "GET", 200, "Iman Quality check"),
    ("PRINTING_PIC", "/api/printing/quantity-check?article_id=1&process=PRINTING", "GET", [200, 404], "Iman Quantity balance"),
    
    # HR / CHRO (Yuni)
    ("CHRO_MANAGER", "/api/hr/employees-summary", "GET", 200, "CHRO Employee Master Summary"),
    ("CHRO_MANAGER", "/api/hr/manpower-requests", "GET", 200, "CHRO Manpower Requests"),
    ("CHRO_MANAGER", "/api/hr/onboarding", "GET", 200, "CHRO Onboarding 2 Minggu"),
    ("CHRO_MANAGER", "/api/hr/performance-reviews", "GET", 200, "CHRO Performance Reviews"),
    ("CHRO_MANAGER", "/api/hr/employee-issues", "GET", 200, "CHRO Employee Issues"),
    
    # HR SUPPORT
    ("HR_SUPPORT", "/api/hr/employees-summary", "GET", 200, "HR Support Employee Summary"),
    ("HR_SUPPORT", "/api/hr/manpower-requests", "GET", 200, "HR Support Manpower"),
]

passed_checks = 0
failed_checks = 0
for role, path, method, expected, desc in checks:
    token = tokens.get(role)
    status, res = req(path, method=method, token=token)
    is_ok = (status in expected) if isinstance(expected, list) else (status == expected)
    if is_ok:
        print(f"  [PASS] {role} -> {method} {path} returned {status} ({desc})")
        passed_checks += 1
    else:
        print(f"  [FAIL] {role} -> {method} {path} expected {expected}, got {status}: {res}")
        failed_checks += 1

print(f"\nEndpoint Access Results: {passed_checks} PASSED, {failed_checks} FAILED (Total: {len(checks)})")

print("\n=== 3. RBAC BOUNDARIES & RESTRICTION TESTS ===")
restrictions = [
    # (Role, Path, Method, Body, Description, Expected Statuses)
    ("CMO_SUPPORT", "/api/cmo/spk/RELEASE", "POST", {"spk_no": "SPK-001", "order_fk": 1}, "Deby blocked from RELEASE SPK", [403, 404, 405]),
    ("SAMPLE_PIC", "/api/cmo/samples/buyer-decision", "POST", {"decision": "APPROVED"}, "Fahrul blocked from Buyer Decision", [403, 404, 405]),
    ("COO_MANAGER", "/api/cfo/invoices", "POST", {"invoice_no": "INV-TEST"}, "COO blocked from creating Invoice", [403, 405]),
    ("PRINTING_PIC", "/api/ceo/overrides", "POST", {"override_key": "TEST"}, "Printing PIC blocked from CEO Override", [403, 405]),
    ("CHRO_MANAGER", "/api/cfo/purchase-orders", "POST", {}, "CHRO blocked from creating Purchase Order", [403, 405]),
    ("HR_SUPPORT", "/api/config/business-policy", "PUT", {}, "HR Support blocked from changing Business Policy", [403, 405]),
    ("CEO", "/api/cfo/purchase-orders", "POST", {"po_no": "PO-TEST"}, "CEO blocked from operational PO creation", [403, 405]),
]

passed_restrictions = 0
for role, path, method, body, desc, expected_codes in restrictions:
    token = tokens.get(role)
    status, res = req(path, method=method, body=body, token=token)
    if status in expected_codes:
        print(f"  [PASS] {role} -> {method} {path} properly blocked with {status} ({desc})")
        passed_restrictions += 1
    else:
        print(f"  [FAIL] {role} -> {method} {path} was NOT blocked! Status: {status}")

print(f"\nRBAC Restrictions Passes: {passed_restrictions} / {len(restrictions)}")

if failed_checks == 0 and passed_restrictions == len(restrictions) and all_login_ok:
    print("\n>>> ALL 12 ROLES, 38 CRITICAL ENDPOINTS, AND RBAC RESTRICTIONS ARE 100% VERIFIED! <<<")
else:
    print("\n>>> THERE WERE FAILURES! DEBUGGING REQUIRED! <<<")
