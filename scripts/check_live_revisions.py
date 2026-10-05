import urllib.request
import ssl
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

login_req = urllib.request.Request(
    'https://client-bos-syam-fix.zvusml.easypanel.host/api/auth/login',
    data=json.dumps({'email': 'ceo@syams.local', 'password': 'demo123456789'}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
token = json.loads(urllib.request.urlopen(login_req, context=ctx).read())['access_token']

rev_req = urllib.request.Request(
    'https://client-bos-syam-fix.zvusml.easypanel.host/api/revisions?limit=200',
    headers={'Authorization': f'Bearer {token}'}
)
items = json.loads(urllib.request.urlopen(rev_req, context=ctx).read())
print(f"Total revisions: {len(items)}")

target_ids = [1, 9] + list(range(10, 31))
for r in sorted(items, key=lambda x: x['id']):
    if r['id'] in target_ids:
        print(f"#{r['id']}: [{r['status']}] '{r['module_name']}'")

