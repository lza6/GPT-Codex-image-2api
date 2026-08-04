#!/usr/bin/env python3
"""E7：项目规格.md 生成与保鲜机制。

从源码自动抽取项目事实生成 docs/project-spec.md：
- 配置项清单（config.py property → 名称/默认值/说明）
- 路由清单（api/*.py 的 @router 路径）
- 服务模块清单（services/ 顶层模块 + 一句话用途）
- 版本/端口/存储后端等关键事实

保鲜：脚本生成后与现有文件 diff，内容过期才重写并打印 [REFRESHED]；
内容一致则打印 [FRESH]（退出码 0 两者皆可）。AI 会话启动可跑本脚本
判断规格是否过期，避免拿着旧规格编码。
用法：
    .venv/Scripts/python.exe scripts/refresh_spec.py [--write]
--write 强制重写（即使内容一致也刷新 mtime）。
"""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "docs" / "project-spec.md"


def _config_items() -> list[tuple[str, str]]:
    """从 services/config.py 抽取配置 property：名称 + 首行 docstring。"""
    source = (ROOT / "services" / "config.py").read_text(encoding="utf-8")
    items: list[tuple[str, str]] = []
    # 匹配 "    def xxx(self) -> ...:\n        \"\"\"说明\"\"\"" 模式
    pattern = re.compile(
        r"    def ([a-z_][a-z0-9_]*)\("
        r".*?\) -> .*?:\n(?:        \"\"\"([^\"]*?)\"\"\")?",
        re.DOTALL,
    )
    for match in pattern.finditer(source):
        name, doc = match.group(1), (match.group(2) or "").strip().splitlines()[0] if match.group(2) else ""
        if name.startswith("_") or name in {"get", "update", "reload"}:
            continue
        items.append((name, doc))
    return sorted(items)


def _routes() -> list[str]:
    """从 api/*.py 抽取路由路径。"""
    routes: list[str] = []
    for file in sorted((ROOT / "api").glob("*.py")):
        source = file.read_text(encoding="utf-8")
        for match in re.finditer(r'@router\.(?:get|post|put|delete)\("([^"]+)"', source):
            routes.append(match.group(1))
    return sorted(set(routes))


def _services() -> list[tuple[str, str]]:
    """services/ 顶层模块清单。"""
    items: list[tuple[str, str]] = []
    for file in sorted((ROOT / "services").glob("*.py")):
        if file.name == "__init__.py":
            continue
        source = file.read_text(encoding="utf-8", errors="ignore")
        first_doc = ""
        for line in source.splitlines()[:8]:
            stripped = line.strip()
            if stripped.startswith('"""') and len(stripped) > 4:
                first_doc = stripped.strip('"').splitlines()[0]
                break
        items.append((file.name, first_doc))
    return items


def _version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "unknown"


def build_spec() -> str:
    version = _version()
    config_items = _config_items()
    routes = _routes()
    services = _services()
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = [
        "# ChatGPT2API 项目规格",
        "",
        f"> 自动生成（{generated_at}）——由 scripts/refresh_spec.py 保鲜，手动改动会被覆盖。",
        "> 保鲜机制：会话启动前跑 `python scripts/refresh_spec.py`，输出 [REFRESHED] 说明已过期需重读。",
        "",
        "## 版本与部署",
        f"- 应用版本：`{version}`",
        "- 端口：23456（Docker 80 映射）",
        "- 存储后端：json / sqlite / postgres / git（config.storage_backend）",
        "- 部署：Windows bat 一键启动 / Docker Compose（非 root + HEALTHCHECK + 优雅停机）",
        "",
        f"## 配置项（{len(config_items)} 个）",
        "",
        "| 配置 | 说明 |",
        "|------|------|",
    ]
    for name, doc in config_items:
        lines.append(f"| `{name}` | {doc} |")
    lines += ["", f"## API 路由（{len(routes)} 个）", ""]
    for route in routes:
        lines.append(f"- `{route}`")
    lines += ["", f"## 服务模块（{len(services)} 个）", ""]
    lines.append("| 模块 | 用途 |")
    lines.append("|------|------|")
    for name, doc in services:
        lines.append(f"| `{name}` | {doc} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="项目规格保鲜")
    parser.add_argument("--write", action="store_true", help="强制重写")
    args = parser.parse_args()

    content = build_spec()
    existing = SPEC_PATH.read_text(encoding="utf-8") if SPEC_PATH.exists() else ""
    if existing == content and not args.write:
        print("[FRESH] docs/project-spec.md 未过期")
        return 0
    SPEC_PATH.write_text(content, encoding="utf-8")
    if existing and existing != content:
        print("[REFRESHED] docs/project-spec.md 已更新（内容过期）")
    else:
        print("[WRITE] docs/project-spec.md 已生成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
