#!/usr/bin/env python3
"""图生图单次测试（验证修复后的PNG是否可用）"""
import io
import json
import struct
import time
import urllib.request
import uuid
import zlib


def create_test_png(w=256, h=256) -> bytes:
    def _crc32(d): return zlib.crc32(d) & 0xffffffff
    def _chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", _crc32(c[4:]))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b""
    for y in range(h):
        raw += b"\x00"
        for x in range(w):
            raw += b"\xff\x00\x00"
    idat = zlib.compress(raw)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")

BASE = "http://127.0.0.1:80"
KEY = "Bearer cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO"

png = create_test_png()
print(f"PNG: {len(png)} bytes, starts with {png[:8].decode('latin-1')!r}")

# 单次图生图
boundary = uuid.uuid4().hex
body = io.BytesIO()
body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\ngpt-image-2\r\n".encode())
body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"prompt\"\r\n\r\nmake it blue\r\n".encode())
body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"test.png\"\r\nContent-Type: image/png\r\n\r\n".encode())
body.write(png)
body.write(f"\r\n--{boundary}--\r\n".encode())
raw = body.getvalue()

req = urllib.request.Request(
    BASE + "/v1/images/edits",
    data=raw,
    headers={
        "Authorization": KEY,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    },
    method="POST",
)
t0 = time.time()
try:
    resp = urllib.request.urlopen(req, timeout=300)
    data = json.loads(resp.read())
    d0 = (data.get("data") or [{}])[0] if isinstance(data.get("data"), list) else {}
    url = d0.get("url", "")
    dt = round(time.time() - t0, 1)
    print(f"OK: {dt}s | HTTP {resp.status} | url={str(url)[:60]}")
except Exception as e:
    dt = round(time.time() - t0, 1)
    print(f"FAIL: {dt}s | {str(e)[:200]}")