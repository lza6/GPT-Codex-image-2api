import json, urllib.request

# 测试 /api/accounts?page=1&page_size=3
req = urllib.request.Request('http://127.0.0.1:80/api/accounts?page=1&page_size=3')
req.add_header('Authorization', 'Bearer cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO')
try:
    r = urllib.request.urlopen(req, timeout=30)
    d = json.loads(r.read())
    print(f"accounts: total={d.get('total','?')} items={len(d.get('items',[]))}")
except Exception as e:
    print(f"accounts FAIL: {e}")

# 测试 /api/logs?page=1&page_size=2
req2 = urllib.request.Request('http://127.0.0.1:80/api/logs?page=1&page_size=2')
req2.add_header('Authorization', 'Bearer cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO')
try:
    r2 = urllib.request.urlopen(req2, timeout=30)
    d2 = json.loads(r2.read())
    print(f"logs: total={d2.get('total','?')} items={len(d2.get('items',[]))}")
except Exception as e:
    print(f"logs FAIL: {e}")