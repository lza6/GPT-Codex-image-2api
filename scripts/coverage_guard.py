"""覆盖率守卫（VII-01）：以增量门禁断言 services+api 行覆盖率。

实测基线：60%（2026-08-12，Windows 本机全量 1253 用例，排除 live/redis）。
目标 90%+；门禁阈值在 pyproject.toml [tool.coverage.report] fail_under（当前 55，
留环境波动裕量）。覆盖率每提升一档上调 5pt，基线记录见 docs/verification-registry.md。

用法：
    .venv/Scripts/python.exe scripts/coverage_guard.py
退出码：覆盖率 < fail_under = 1（FAIL）；报告 JSON 写 reports/coverage/coverage.json。
注意：本脚本会完整跑一遍 pytest（排除 live/redis），耗时约 3~4 分钟，
供 run_all_guards 终局校验与 CI coverage job 使用。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 优先 sys.executable（POSIX/Docker 无 .venv/Scripts）；Windows .venv 存在时用之
_VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = str(_VENV_PY) if _VENV_PY.exists() else sys.executable


def _fail_under() -> int:
    """从 pyproject.toml [tool.coverage.report] fail_under 读取门禁阈值。"""
    with open(ROOT / "pyproject.toml", "rb") as f:
        cfg = tomllib.load(f)
    return int(cfg["tool"]["coverage"]["report"]["fail_under"])


def main() -> int:
    fail_under = _fail_under()
    out_dir = ROOT / "reports" / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "coverage.json"

    print(f"[coverage] 门禁 fail_under={fail_under}%，跑全量 pytest（排除 live/redis），耗时约 3~4 分钟 ...")
    cmd = [
        PY, "-m", "pytest",
        "--cov=services", "--cov=api",
        f"--cov-fail-under={fail_under}",
        f"--cov-report=json:{json_path}",
        "--cov-report=term-missing",
        "-q",
        "-m", "not live and not redis",
    ]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900, env=env)
    output = (proc.stdout or "") + (proc.stderr or "")

    # 从 pytest 输出提取实际覆盖率（TOTAL 行），并重写 JSON 报告为可读格式
    total_line = next((ln for ln in output.splitlines() if ln.strip().startswith("TOTAL")), "")
    actual_pct = -1.0
    if total_line:
        try:
            actual_pct = float(total_line.split()[-1].rstrip("%"))
        except ValueError:
            pass

    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    payload = {
        "timestamp": stamp,
        "fail_under": fail_under,
        "measured_pct": actual_pct,
        "pass": actual_pct >= fail_under,
        "exit_code": proc.returncode,
        "summary": total_line.strip() or "（pytest 输出异常，无法解析覆盖率）",
    }
    json_path.write_text(
        __import__("json").dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for line in output.splitlines()[-8:]:
        print(f"  {line}")
    if actual_pct < 0:
        print("[coverage] 无法解析覆盖率输出，请检查 pytest-cov 是否安装（uv sync 需含 dev 组）")
        return 1
    print(f"[coverage] {'PASS' if proc.returncode == 0 else 'FAIL'} "
          f"measured={actual_pct}% fail_under={fail_under}%")
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
