# -*- coding: utf-8 -*-
"""只读契约探测脚本：用 TestClient 调用看板/代理端点，打印实际 JSON 键与类型。

不修改任何数据；仅 GET 请求。运行: uv run python scripts/contract_probe.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# 保证项目根目录在 sys.path（脚本位于 scripts/ 下）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402

AUTH = {"Authorization": "Bearer chatgpt2api"}

ENDPOINTS = [
    "/api/dashboard/scheduler",
    "/api/dashboard/ops",
    "/api/dashboard/usage",
    "/api/dashboard/latency",
    "/api/dashboard/metrics_summary",
    "/api/proxies",
]


def describe(value, depth=0):
    """返回 (类型描述, 子结构) 供打印。"""
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return f"array[{len(value)}]"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number(float)"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def print_schema(value, indent=0, max_depth=4, key_path=""):
    pad = "  " * indent
    if isinstance(value, dict):
        for k, v in value.items():
            t = describe(v)
            print(f"{pad}{k}: {t}")
            if isinstance(v, dict) and indent < max_depth:
                print_schema(v, indent + 1, max_depth, f"{key_path}.{k}")
            elif isinstance(v, list) and v and isinstance(v[0], dict) and indent < max_depth:
                print(f"{pad}  [0]:")
                print_schema(v[0], indent + 2, max_depth, f"{key_path}.{k}[0]")
    elif isinstance(value, list):
        print(f"{pad}(array len={len(value)})")
        if value and isinstance(value[0], dict):
            print_schema(value[0], indent + 1, max_depth, f"{key_path}[0]")


def main():
    app = create_app()
    client = TestClient(app)
    for ep in ENDPOINTS:
        print("=" * 72)
        print(f"GET {ep}")
        resp = client.get(ep, headers=AUTH)
        print(f"status: {resp.status_code}")
        try:
            data = resp.json()
        except Exception:
            print("non-JSON body:", resp.text[:200])
            continue
        print_schema(data)
        # 同时输出原始 JSON 截断版，便于核对嵌套
        raw = json.dumps(data, ensure_ascii=False)
        print(f"raw(len={len(raw)}): {raw[:600]}")
    print("=" * 72)


if __name__ == "__main__":
    main()
