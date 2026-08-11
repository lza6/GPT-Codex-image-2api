"""文档同步检查：VERSION 与核心文档内嵌版本号一致性（第六道防线）。

用途：每次 bump VERSION 后必须同步文档。本脚本比对 VERSION 文件与
CLAUDE.md / workflow_status.md / docs/verification-registry.md /
.claude/skills/chatgpt2api-workflow/SKILL.md 内嵌的当前版本标记，
任一不一致即 FAIL，防「bump VERSION 漏同步文档」复现（历史 P0：
SKILL.md 停在 v2.13.0、verification-registry 停在 v2.9.0，而 VERSION=2.32.0）。

用法：
    .venv/Scripts/python.exe scripts/docs_sync_check.py
退出码：全部一致 = 0（PASS）；任一不一致或文档缺失 = 1（FAIL）。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 每份文档的"当前版本"声明模式（正则，捕获 vX.Y.Z 中的 X.Y.Z）。
# SKILL.md 有标题 + 架构树 VERSION 行两处标记，都要求与 VERSION 一致。
DOC_CHECKS: list[tuple[Path, str, list[str]]] = [
    (ROOT / "CLAUDE.md", "CLAUDE.md", [r"v(\d+\.\d+\.\d+) 已发版"]),
    (ROOT / "workflow_status.md", "workflow_status.md", [r"基线：v(\d+\.\d+\.\d+)"]),
    (
        ROOT / "docs" / "verification-registry.md",
        "docs/verification-registry.md",
        [r"当前验证基线（最新一轮：v(\d+\.\d+\.\d+)"],
    ),
    (
        ROOT / ".claude" / "skills" / "chatgpt2api-workflow" / "SKILL.md",
        "SKILL.md",
        [r"当前真实状态，v(\d+\.\d+\.\d+)", r"当前版本号 \(v(\d+\.\d+\.\d+)\)"],
    ),
]


def _read_version() -> str:
    """VERSION 文件 → 去 v 前缀的版本号（如 2.32.0）。"""
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip().lstrip("v")
    except FileNotFoundError:
        return ""


def _check() -> list[str]:
    """返回不一致描述列表（空 = 全 PASS）。"""
    expected = _read_version()
    if not expected:
        return ["VERSION 文件缺失或为空"]

    problems: list[str] = []
    for path, label, patterns in DOC_CHECKS:
        if not path.exists():
            problems.append(f"{label}: 文件缺失（{path.relative_to(ROOT)}）")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat in patterns:
            match = re.search(pat, text)
            if not match:
                problems.append(f"{label}: 未找到版本声明（模式 {pat}）")
                continue
            if match.group(1) != expected:
                problems.append(f"{label}: 内嵌版本 v{match.group(1)} != VERSION v{expected}")
    return problems


def main() -> int:
    problems = _check()
    report_dir = ROOT / "reports" / "docs_sync"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    if not problems:
        print("[PASS] docs_sync_check: VERSION 与 4 份文档内嵌版本号一致")
        (report_dir / "result.txt").write_text(f"[PASS] {stamp}\n", encoding="utf-8")
        return 0
    print("[FAIL] docs_sync_check: 版本不一致，请同步下列文档后重跑:")
    for problem in problems:
        print(f"  - {problem}")
    (report_dir / "result.txt").write_text(
        f"[FAIL] {stamp}\n" + "\n".join(f"- {p}" for p in problems) + "\n",
        encoding="utf-8",
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
