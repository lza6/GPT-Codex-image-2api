"""八道防线一键执行器：contract → sql → slowquery → mutation → stress → benchmark → docs_sync → coverage。

对应用户指令的终局校验清单，一次调用跑完所有防线并汇总 PASS/FAIL。
用法：
    .venv/Scripts/python.exe scripts/run_all_guards.py
退出码：任一防线 FAIL = 1。各防线详细报告在 reports/<防线名>/ 下。
E2：执行锁——reports/.guards.lock 文件互斥，防 CI 与本地并发双跑导致防线互相污染。
注：benchmark 依赖前一道 stress 刚产出的 reports/stress/*.json，顺序不可交换；
coverage 会完整跑一遍 pytest（~3-4 分钟），是全套中耗时最长的一道。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_LOCK_PATH = ROOT / "reports" / ".guards.lock"


def _acquire_lock() -> bool:
    """原子建锁（O_EXCL）。拿到锁才返回 True；已被占用返回 False。"""
    try:
        ROOT.joinpath("reports").mkdir(parents=True, exist_ok=True)
        fd = os.open(str(_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"pid={os.getpid()} started={time.time()}".encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock() -> None:
    try:
        _LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
# 优先 sys.executable（POSIX/Docker 无 .venv/Scripts）；Windows .venv 存在时用之
_VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = str(_VENV_PY) if _VENV_PY.exists() else sys.executable

GUARDS = [
    ("契约守卫", "scripts/contract_guard.py", []),
    ("SQL 安全审查", "scripts/sql_audit.py", []),
    ("慢查询猎杀", "scripts/slow_query_report.py", []),
    ("变异探针", "scripts/mutation_probe.py", []),
    ("极限施压", "scripts/stress_test.py", ["--requests", "200", "--concurrency", "15"]),
    ("性能基准", "scripts/benchmark_check.py", []),
    ("文档同步", "scripts/docs_sync_check.py", []),
    ("覆盖率门禁", "scripts/coverage_guard.py", []),
]


def main() -> int:
    if not _acquire_lock():
        print("[guards] 另一实例正在运行（reports/.guards.lock 存在）——已退出，避免防线并发双跑")
        return 2
    try:
        return _run_guards()
    finally:
        _release_lock()


def _run_guards() -> int:
    results: list[tuple[str, bool, float]] = []
    for name, script, extra in GUARDS:
        print(f"\n===== [{name}] {script} =====")
        t0 = time.perf_counter()
        proc = subprocess.run(
            [str(PY), script, *extra],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
        elapsed = time.perf_counter() - t0
        ok = proc.returncode == 0
        results.append((name, ok, elapsed))
        tail = (proc.stdout or "").strip().splitlines()
        for line in tail[-3:]:
            print(f"  {line}")
        if not ok and proc.stderr:
            for line in proc.stderr.strip().splitlines()[-3:]:
                print(f"  [stderr] {line}")

    print("\n===== 八道防线汇总 =====")
    all_ok = True
    for name, ok, elapsed in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({elapsed:.1f}s)")
        all_ok = all_ok and ok
    print(f"总体: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
