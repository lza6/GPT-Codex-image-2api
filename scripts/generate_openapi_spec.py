#!/usr/bin/env python
"""生成 OpenAPI 3.1 规范 JSON 文件到 docs/ 目录。

用法：
    .venv/Scripts/python.exe scripts/generate_openapi_spec.py

输出：
    docs/openapi.json — 完整 OpenAPI 规范文件
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from api.app import create_app  # noqa: E402

OUTPUT = BASE_DIR / "docs" / "openapi.json"


def main() -> None:
    app = create_app()
    openapi = app.openapi()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(openapi, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ OpenAPI spec 已生成: {OUTPUT}")
    print(f"   路径数: {len(openapi.get('paths', {}))}")
    print(f"   组件数: {len(openapi.get('components', {}).get('schemas', {}))}")


if __name__ == "__main__":
    main()