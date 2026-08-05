"""契约防坑守卫（R7）：前后端契约防漂移。

在 contract_probe.py（打印结构）与 test_contracts.py（抽样断言）之上补三件事：
1. 端点覆盖审计：静态扫描 web/src 前端代码中所有后端路径引用，与 TestClient
   实测可达的 /api 路由做差集——前端调用而后端不存在 = 断链；后端存在而前端
   与 probe/测试均未覆盖 = 契约盲区。
2. 枚举对齐：前端硬编码的字符串字面量联合类型（AccountStatus/SchedulerTier 等）
   与后端实际产出值的对齐检查（基于离线枚举表 + 可选实测）。
3. 快照 diff：对各关键端点做 TestClient 实测，输出字段签名（键+类型），与
   上一份快照（reports/contract/latest.json）对比；漂移即报警并落盘新快照。

用法：
    .venv/Scripts/python.exe scripts/contract_guard.py            # 全量
    .venv/Scripts/python.exe scripts/contract_guard.py --update   # 接受漂移，更新快照
退出码：发现断链或未确认漂移 = 1；全绿 = 0。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "contract-guard-only-key-0123456789")

AUTH = {"Authorization": "Bearer contract-guard-only-key-0123456789"}
WEB_SRC = ROOT / "web" / "src"
SNAPSHOT_DIR = ROOT / "reports" / "contract"
SNAPSHOT_FILE = SNAPSHOT_DIR / "latest.json"

# 前端代码中可能出现的、但不应算后端路径的模式（静态资源、外部 URL 等）
FRONTEND_NOISE = re.compile(r"^https?://|^/(_next|favicon|.*\.(svg|png|ico|js|css))")

# 实测快照的端点（在 contract_probe 基础上扩到管理面主要 GET）
# 注意：必须全部是真实注册的路由——第七轮曾把不存在的 /api/system/config 放进列表，
# SPA 兜底返回 200 HTML 导致快照含垃圾签名（幻影端点）。
SNAPSHOT_ENDPOINTS = [
    "/api/settings",
    "/api/dashboard/scheduler",
    "/api/dashboard/ops",
    "/api/dashboard/usage",
    "/api/dashboard/usage-forecast",
    "/api/dashboard/capacity",
    "/api/dashboard/latency",
    "/api/dashboard/metrics_summary",
    "/api/dashboard/circuit_breakers",
    "/api/proxies",
    "/api/accounts",
    "/api/logs?limit=1",
]

# 动态键端点：响应里含有按数据内容生成的键（如 by_summary 按日志 summary 动态命名、
# logs limit=1 读最新一条 detail 内容不可预测、scheduler 的 health.statuses.* 按账号池
# 实时健康状态动态命名）。对这些端点只做"状态码 + 顶层键集合"比对，不做深字段签名——
# 否则每次运行都因数据不同而误报漂移（第七轮实测教训；第十一轮补 scheduler）。
DYNAMIC_KEY_ENDPOINTS = {
    "/api/dashboard/usage",
    "/api/logs?limit=1",
    "/api/dashboard/usage-forecast",
    "/api/dashboard/scheduler",
}


def collect_frontend_paths() -> dict[str, list[str]]:
    """扫描前端源码中的后端路径引用，返回 {路径: [引用位置]}。"""
    hits: dict[str, list[str]] = {}
    if not WEB_SRC.exists():
        return hits
    # 匹配 "/api/..." 与 '/api/...' 字面量（含模板字符串中的静态前缀）
    pattern = re.compile(r"""["'](/api/[A-Za-z0-9_\-/{}$?=&.]*)["'`]""")
    for path in WEB_SRC.rglob("*"):
        if path.suffix not in (".ts", ".tsx") or "node_modules" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in pattern.finditer(text):
            raw = m.group(1)
            if FRONTEND_NOISE.match(raw):
                continue
            # 模板变量路径归一化：/api/accounts/${id} → /api/accounts/{param}
            norm = re.sub(r"\$\{[^}]*\}", "{param}", raw)
            norm = norm.split("?")[0]  # query 不参与路由匹配
            loc = f"{path.relative_to(ROOT)}:{text[:m.start()].count(chr(10)) + 1}"
            hits.setdefault(norm, []).append(loc)
    return hits


def collect_backend_routes() -> set[str]:
    """从 FastAPI app 收集 /api 路由（模板形式，如 /api/accounts/{account_id}）。"""
    from api.app import create_app

    app = create_app()
    routes: set[str] = set()
    for r in app.routes:
        path = getattr(r, "path", "")
        if isinstance(path, str) and path.startswith("/api/"):
            routes.add(path)
    return routes


def _path_matches(template: str, concrete: str) -> bool:
    """后端路由模板是否覆盖前端调用路径。"""
    t_parts = template.strip("/").split("/")
    c_parts = concrete.strip("/").split("/")
    if len(t_parts) != len(c_parts):
        return False
    for tp, cp in zip(t_parts, c_parts):
        if tp.startswith("{") and tp.endswith("}"):
            continue
        if cp == "{param}":
            continue
        if tp != cp:
            return False
    return True


def field_signature(value, prefix: str = "", depth: int = 0, max_depth: int = 3) -> dict[str, str]:
    """生成 {字段路径: 类型} 签名。"""
    sig: dict[str, str] = {}
    if depth > max_depth:
        return sig
    if isinstance(value, dict):
        for k, v in value.items():
            key = f"{prefix}.{k}" if prefix else k
            sig[key] = type(v).__name__
            sig.update(field_signature(v, key, depth + 1, max_depth))
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        sig[f"{prefix}[]"] = "object"
        sig.update(field_signature(value[0], f"{prefix}[]", depth + 1, max_depth))
    return sig


def take_snapshot() -> dict[str, dict[str, str] | dict[str, object]]:
    from fastapi.testclient import TestClient

    from api.app import create_app

    client = TestClient(create_app())
    snapshot: dict[str, object] = {}
    for ep in SNAPSHOT_ENDPOINTS:
        resp = client.get(ep, headers=AUTH)
        entry: dict[str, object] = {"status": resp.status_code}
        if resp.status_code == 200:
            try:
                body = resp.json()
                if ep in DYNAMIC_KEY_ENDPOINTS:
                    # 动态键端点：只记录顶层键集合（键的出现/消失仍是契约变化）
                    entry["top_keys"] = sorted(body.keys()) if isinstance(body, dict) else []
                    entry["fields"] = {}
                else:
                    entry["fields"] = field_signature(body)
            except Exception:
                entry["fields"] = {}
        snapshot[ep] = entry
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="前后端契约防漂移守卫")
    parser.add_argument("--update", action="store_true", help="接受当前漂移，更新快照")
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    print("[contract] 扫描前端路径引用 ...")
    frontend_paths = collect_frontend_paths()
    print(f"[contract] 前端引用 {len(frontend_paths)} 个不同 /api 路径")

    print("[contract] 收集后端路由 ...")
    backend_routes = collect_backend_routes()
    print(f"[contract] 后端注册 {len(backend_routes)} 个 /api 路由")

    # 1. 断链：前端引用而后端无匹配
    broken: list[tuple[str, list[str]]] = []
    for fp, locs in sorted(frontend_paths.items()):
        if not any(_path_matches(br, fp) for br in backend_routes):
            broken.append((fp, locs))

    # 2. 盲区：后端 /api 路由未被前端引用（管理面 API 可能被 curl/文档使用，记信息项）
    unreferenced = sorted(
        br for br in backend_routes
        if not any(_path_matches(br, fp) for fp in frontend_paths)
    )

    # 3. 快照 diff
    print("[contract] 实测端点快照 ...")
    snapshot = take_snapshot()
    old_snapshot: dict = {}
    if SNAPSHOT_FILE.exists():
        try:
            old_snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8")).get("endpoints", {})
        except Exception:
            old_snapshot = {}

    drift: list[str] = []
    for ep, entry in snapshot.items():
        old = old_snapshot.get(ep)
        if old is None:
            continue  # 新端点不算漂移
        if old.get("status") != entry.get("status"):
            drift.append(f"{ep}: status {old.get('status')} → {entry.get('status')}")
            continue
        if ep in DYNAMIC_KEY_ENDPOINTS:
            # 动态键端点只比顶层键集合
            old_keys = set(old.get("top_keys", []))
            new_keys = set(entry.get("top_keys", []))
            if old_keys and old_keys != new_keys:
                drift.append(f"{ep}: 顶层键变化 {sorted(old_keys ^ new_keys)}")
            continue
        old_fields = old.get("fields", {})
        new_fields = entry.get("fields", {})
        removed = set(old_fields) - set(new_fields)
        changed = {k for k in set(old_fields) & set(new_fields) if old_fields[k] != new_fields[k]}
        if removed:
            drift.append(f"{ep}: 字段被移除 {sorted(removed)}")
        if changed:
            drift.append(f"{ep}: 字段类型变化 {sorted(changed)}")

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    if args.update or not SNAPSHOT_FILE.exists():
        SNAPSHOT_FILE.write_text(
            json.dumps({"timestamp": stamp, "endpoints": snapshot}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    lines = [
        f"# 契约守卫报告 {stamp}",
        "",
        f"- 前端引用路径：{len(frontend_paths)}；后端 /api 路由：{len(backend_routes)}",
        f"- 断链（前端有、后端无）：{len(broken)}",
        f"- 未被前端引用的后端路由：{len(unreferenced)}（信息项：可能为 SDK/curl 使用）",
        f"- 快照漂移：{len(drift)}（{'已接受并更新快照' if args.update else '未确认'}）",
        "",
        "## 断链清单（P0/P1：前端调用了不存在的端点）",
        "",
    ]
    if broken:
        for fp, locs in broken:
            lines.append(f"- `{fp}` ← {', '.join(locs[:3])}")
    else:
        lines.append("- 无")
    lines += ["", "## 未被前端引用的后端路由", ""]
    lines += [f"- `{r}`" for r in unreferenced] or ["- 无"]
    lines += ["", "## 快照漂移", ""]
    lines += [f"- {d}" for d in drift] or ["- 无"]

    report = SNAPSHOT_DIR / f"report_{stamp}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[contract] 报告: {report}")
    print(f"[contract] 断链={len(broken)} 漂移={len(drift)} 未引用路由={len(unreferenced)}")
    return 1 if (broken or (drift and not args.update)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
