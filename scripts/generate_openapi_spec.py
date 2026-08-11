#!/usr/bin/env python
"""生成 OpenAPI 3.1 规范 JSON 文件到 docs/ 目录。

用法：
    .venv/Scripts/python.exe scripts/generate_openapi_spec.py            # 生成并写文件
    .venv/Scripts/python.exe scripts/generate_openapi_spec.py --check   # 只校验不写文件

输出：
    docs/openapi.json — 完整 OpenAPI 规范文件

--check 模式（VII-04）：在内存生成当前 spec 并与 docs/openapi.json 逐字节比对，
不一致时 exit 1 并提示重新生成，供 CI 校验 job 使用，防"改了 API 忘了重生成 spec"。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from api.app import create_app  # noqa: E402

OUTPUT = BASE_DIR / "docs" / "openapi.json"


def _generate() -> dict:
    app = create_app()
    return app.openapi()


def _format(openapi: dict) -> str:
    return json.dumps(openapi, ensure_ascii=False, indent=2)


def _check(openapi: dict) -> int:
    if not OUTPUT.exists():
        print(f"[FAIL] docs/openapi.json 不存在，请先运行 {Path(__file__).name} 生成")
        return 1
    current = OUTPUT.read_text(encoding="utf-8")
    expected = _format(openapi) + "\n"
    if current == expected:
        print(f"[PASS] OpenAPI spec 与 docs/openapi.json 一致（路径数 {len(openapi.get('paths', {}))}）")
        return 0
    print("[FAIL] OpenAPI spec 已漂移：当前应用生成的 spec 与 docs/openapi.json 不一致。")
    print("      请重新运行 scripts/generate_openapi_spec.py 并提交更新后的 docs/openapi.json。")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 OpenAPI spec 到 docs/openapi.json")
    parser.add_argument("--check", action="store_true", help="只校验不写文件，与现有 spec 不一致则 exit 1")
    args = parser.parse_args()

    openapi = _generate()
    if args.check:
        raise SystemExit(_check(openapi))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(_format(openapi) + "\n", encoding="utf-8")
    print(f"[OK] OpenAPI spec 已生成: {OUTPUT}")
    print(f"   路径数: {len(openapi.get('paths', {}))}")
    print(f"   组件数: {len(openapi.get('components', {}).get('schemas', {}))}")


if __name__ == "__main__":
    main()
