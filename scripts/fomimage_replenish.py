"""持续灌号脚本（本地跑，经公网 API 触发服务器批量注册，直到号池达标）。"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

AUTH = "Bearer cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO"
BASE = "http://43.165.173.36:23456"
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 500
BATCH = int(sys.argv[2]) if len(sys.argv) > 2 else 50
MAX_ROUNDS = 60


def api(path: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": AUTH, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[{time.strftime('%H:%M:%S')}] api {path} fail: {exc}", flush=True)
        return None


def main() -> None:
    rounds = 0
    while rounds < MAX_ROUNDS:
        s = api("/api/registration/fomimage/status")
        if s is None:
            time.sleep(30)
            continue
        pool = s["fomimage_pool"]["available"]
        stats = s.get("stats", {}).get("last_run_result") or {}
        print(
            f"[{time.strftime('%H:%M:%S')}] pool={pool} target={TARGET} "
            f"last_run={stats} busy={s.get('registration_busy')}",
            flush=True,
        )
        if pool >= TARGET:
            print(f"达标 pool={pool} >= target={TARGET}", flush=True)
            return
        if not s.get("registration_busy"):
            r = api("/api/registration/fomimage/register", "POST", {"count": BATCH})
            print(f"[{time.strftime('%H:%M:%S')}] 触发 {BATCH} 个注册, resp_ok={bool(r)}", flush=True)
            rounds += 1
            time.sleep(60)  # 触发后等 1 分钟再查（批跑约 5-6 分钟，期间会 busy）
        else:
            time.sleep(45)  # 上一批还在跑
    print(f"达最大轮次 {MAX_ROUNDS}，pool 未达标（当前见上）", flush=True)


if __name__ == "__main__":
    main()
