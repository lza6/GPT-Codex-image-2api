#!/usr/bin/env python3
"""E5：live 测试安全入口（dry-run + 前置条件检查）。

live 测试会真实调用上游（烧账号配额/消耗免费额度），误跑代价高。本脚本：
1. 默认 dry-run：只列出将被执行的 live 测试与运行环境前置检查，不真正执行。
2. `--go` 才真正执行（pytest -m live），并先做前置条件检查：
   - 服务已启动（可选 --base-url 探测）
   - 号池有账号（读取 data/accounts.json）
   - 显式确认（除非 --yes）
用法：
    .venv/Scripts/python.exe scripts/run_live_tests.py            # dry-run 预检
    .venv/Scripts/python.exe scripts/run_live_tests.py --go       # 前置检查+确认后执行
    .venv/Scripts/python.exe scripts/run_live_tests.py --go --yes # 跳过确认（CI 已授权）
退出码：0 = 通过/未执行（dry-run）；1 = 前置检查失败或测试失败。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def _accounts_count() -> int:
    try:
        accounts_path = ROOT / "data" / "accounts.json"
        if not accounts_path.exists():
            return 0
        data = json.loads(accounts_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return len(data)
        return len(data.get("accounts") or {})
    except Exception:
        return 0


def _preflight(base_url: str) -> list[str]:
    """前置条件检查，返回失败项列表（空 = 通过）。"""
    failures: list[str] = []
    if shutil.which("pytest") is None and not PY.exists():
        failures.append("未找到 python/pytest 运行环境")
    if base_url:
        import urllib.request

        try:
            with urllib.request.urlopen(f"{base_url}/v1/models", timeout=3) as resp:  # noqa: S310
                if resp.status >= 400:
                    failures.append(f"服务 {base_url} 返回 {resp.status}")
        except Exception as exc:
            failures.append(f"服务 {base_url} 不可达: {exc}")
    if _accounts_count() == 0:
        failures.append("号池为空（data/accounts.json 无账号）——live 测试将全部失败且白烧配额")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="live 测试安全入口")
    parser.add_argument("--go", action="store_true", help="真正执行 live 测试（默认 dry-run）")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    parser.add_argument("--base-url", default="", help="服务地址探测（可选，如 http://localhost:23456）")
    parser.add_argument("--pytest-args", default="", help="透传 pytest 参数（如 '-k image'）")
    args = parser.parse_args()

    if args.base_url:
        failures = _preflight(args.base_url)
    else:
        failures = _preflight("")
    if failures:
        print("[live] 前置条件检查失败：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"[live] 前置条件检查通过（号池账号数: {_accounts_count()}）")

    if not args.go:
        print("[live] dry-run：未执行。使用 --go 真正运行（会消耗上游配额）。")
        print("[live] 将运行的测试文件：")
        for path in sorted((ROOT / "test").glob("*.py")):
            if "live" in path.read_text(encoding="utf-8", errors="ignore"):
                print(f"  - {path.name}")
        return 0

    if not args.yes:
        answer = input("确认运行 live 测试（消耗上游配额）？[y/N]: ").strip().lower()
        if answer != "y":
            print("[live] 已取消")
            return 0

    cmd = [str(PY), "-m", "pytest", "test/", "-m", "live"]
    if args.pytest_args:
        cmd.extend(args.pytest_args.split())
    print(f"[live] 执行: {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
