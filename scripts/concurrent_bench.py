#!/usr/bin/env python3
"""并发压测脚本：5文生图 + 5图生图，真实调用线上 API。
用法：uv run python scripts/concurrent_bench.py
"""
from __future__ import annotations

import base64
import io
import json
import sys
import time
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

BASE = "http://127.0.0.1:80"
KEY = "cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO"
HDRS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

results: list[dict] = []


def _req(method: str, path: str, body: bytes | None = None, headers: dict | None = None) -> dict:
    h = {**HDRS, **(headers or {})}
    req = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
    t0 = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=300)
        data = json.loads(resp.read())
        cost = round(time.time() - t0, 1)
        return {"ok": True, "status": resp.status, "cost_s": cost, "data": data}
    except urllib.error.HTTPError as e:
        cost = round(time.time() - t0, 1)
        body_text = e.read().decode()[:200] if e.fp else ""
        return {"ok": False, "status": e.code, "cost_s": cost, "error": body_text}
    except Exception as e:
        cost = round(time.time() - t0, 1)
        return {"ok": False, "status": 0, "cost_s": cost, "error": str(e)[:200]}


def get_quota_snapshot() -> dict:
    """获取配额快照：{email: quota}"""
    r = _req("GET", "/api/dashboard/quota")
    if not r.get("ok"):
        return {}
    snapshot = {}
    for acct in r.get("data", {}).get("accounts", []):
        snapshot[acct["email"]] = acct["quota"]
    return snapshot


def do_text2img(seq: int) -> dict:
    prompt = f"a simple red circle on white background, minimal style, test seq {seq}"
    body = json.dumps({"model": "gpt-image-2", "prompt": prompt, "size": "1024x1024", "n": 1}).encode()
    return _req("POST", "/v1/images/generations", body)


def create_test_png() -> bytes:
    """生成一个 256x256 红色 PNG 用于图生图测试（纯手工构造，无PIL依赖）"""
    import struct, zlib
    def _crc32(data: bytes) -> int:
        return zlib.crc32(data) & 0xFFFFFFFF
    def _chunk(ctype: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + ctype + data
        return c + struct.pack(">I", _crc32(c[4:]))
    W, H = 256, 256
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    raw = b''
    for y in range(H):
        raw += b'\x00'  # filter byte
        for x in range(W):
            raw += b'\xff\x00\x00'  # RGB red
    idat = zlib.compress(raw)
    return sig + _chunk(b'IHDR', ihdr) + _chunk(b'IDAT', idat) + _chunk(b'IEND', b'')


def do_img2img(seq: int, test_png: bytes) -> dict:
    """图生图：multipart/form-data 上传"""
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    prompt = f"make it blue, test seq {seq}"
    def _w(text: str) -> None:
        body.write(text.encode())
    _w(f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\ngpt-image-2\r\n")
    _w(f"--{boundary}\r\nContent-Disposition: form-data; name=\"prompt\"\r\n\r\n{prompt}\r\n")
    _w(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"test.png\"\r\nContent-Type: image/png\r\n\r\n")
    body.write(test_png)
    _w(f"\r\n--{boundary}--\r\n")
    raw = body.getvalue()
    ct = f"multipart/form-data; boundary={boundary}"
    t0 = time.time()
    try:
        req = urllib.request.Request(BASE + "/v1/images/edits", data=raw, headers={
            "Authorization": f"Bearer {KEY}", "Content-Type": ct,
        }, method="POST")
        resp = urllib.request.urlopen(req, timeout=300)
        data = json.loads(resp.read())
        cost = round(time.time() - t0, 1)
        return {"ok": True, "status": resp.status, "cost_s": cost, "data": data}
    except urllib.error.HTTPError as e:
        cost = round(time.time() - t0, 1)
        body_text = e.read().decode()[:200] if e.fp else ""
        return {"ok": False, "status": e.code, "cost_s": cost, "error": body_text}
    except Exception as e:
        cost = round(time.time() - t0, 1)
        return {"ok": False, "status": 0, "cost_s": cost, "error": str(e)[:200]}


def main() -> None:
    print("=" * 60)
    print("并发压测：10并发（5文生图 + 5图生图）")
    print("=" * 60)

    # 1. 配额快照（before）
    print("\n[1/5] 记录配额快照(before)...")
    q_before = get_quota_snapshot()
    total_before = sum(q_before.values())
    print(f"  总配额: {total_before}, 账号数: {len(q_before)}")

    # 2. 生成测试图
    print("\n[2/5] 生成测试用红色PNG...")
    test_png = create_test_png()
    print(f"  测试图片大小: {len(test_png)} bytes")

    # 3. 并发提交10个请求
    print("\n[3/5] 提交10并发请求...")
    tasks = []
    for i in range(5):
        tasks.append(("text2img", i, test_png))
    for i in range(5):
        tasks.append(("img2img", i, test_png))

    t_start = time.time()
    pool_results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {}
        for kind, seq, png in tasks:
            if kind == "text2img":
                f = ex.submit(do_text2img, seq)
            else:
                f = ex.submit(do_img2img, seq, png)
            futs[f] = (kind, seq)
        for f in as_completed(futs):
            kind, seq = futs[f]
            try:
                r = f.result()
            except Exception as e:
                r = {"ok": False, "error": str(e)[:200], "cost_s": 0, "status": 0}
            r["kind"] = kind
            r["seq"] = seq
            pool_results.append(r)
    total_wall = round(time.time() - t_start, 1)

    # 4. 汇总结果
    print(f"\n[4/5] 结果汇总（总耗时: {total_wall}s）")
    pool_results.sort(key=lambda x: (x["kind"], x["seq"]))
    success = 0
    fail = 0
    costs = []
    for r in pool_results:
        label = f"{r['kind']}#{r['seq']}"
        if r["ok"]:
            success += 1
            cost = r["cost_s"]
            costs.append(cost)
            # 提取url和提示
            d0 = r.get("data", {}).get("data", [{}])[0] if r.get("data") else {}
            url = str(d0.get("url", ""))[:60]
            b64 = bool(d0.get("b64_json", ""))
            expires = d0.get("expires_at", "")
            print(f"  [OK] {label} {cost}s | url={url} | b64={b64} | expires={expires}")
        else:
            fail += 1
            print(f"  [FAIL] {label} {r['cost_s']}s | HTTP {r.get('status')} | {r.get('error','')[:80]}")

    # 5. 配额快照（after）
    print("\n[5/5] 配额快照(after)...")
    time.sleep(2)  # 等配额同步
    q_after = get_quota_snapshot()
    total_after = sum(q_after.values())
    print(f"  总配额: {total_before} -> {total_after}，消耗: {total_before - total_after}")

    # 负载均衡分析
    print("\n" + "=" * 60)
    print("负载均衡分析")
    print("=" * 60)
    # 看哪些账号被用了 - 通过配额变化分析
    changed = {e: q_before.get(e, 0) - q_after.get(e, 0) for e in set(q_before) | set(q_after) if q_before.get(e, 0) != q_after.get(e, 0)}
    if changed:
        print(f"  配额发生变化的账号: {len(changed)}")
        for email, diff in sorted(changed.items(), key=lambda x: -abs(x[1])):
            print(f"    {email}: {q_before.get(email,0)} -> {q_after.get(email,0)} (消耗 {diff})")
    else:
        print("  配额无变化（可能透传模式不扣配额，或配额同步延迟）")

    # 统计
    avg_cost = round(sum(costs) / len(costs), 1) if costs else 0
    max_cost = max(costs) if costs else 0
    min_cost = min(costs) if costs else 0
    print(f"\n统计:")
    print(f"  成功: {success}/{len(pool_results)}")
    print(f"  失败: {fail}/{len(pool_results)}")
    print(f"  平均耗时: {avg_cost}s")
    print(f"  最慢: {max_cost}s")
    print(f"  最快: {min_cost}s")
    print(f"  总墙钟: {total_wall}s")
    print(f"  配额消耗: {total_before - total_after}")

    # 返回结果用于后续分析
    return {
        "total": len(pool_results),
        "success": success,
        "fail": fail,
        "avg_cost_s": avg_cost,
        "max_cost_s": max_cost,
        "min_cost_s": min_cost,
        "wall_clock_s": total_wall,
        "quota_before": total_before,
        "quota_after": total_after,
        "quota_consumed": total_before - total_after,
        "details": pool_results,
    }


if __name__ == "__main__":
    main()