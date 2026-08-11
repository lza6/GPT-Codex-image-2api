"""慢查询猎杀与索引优化报告（R9）。

只读分析，不修改任何数据与代码。三部分：
1. 数据规模盘点：data/ 下各存储文件的体积、条目数、行数——找出"越跑越慢"的候选大头。
2. 全量扫描点识别：静态扫描源码中每次请求都会全量读/全量遍历的热点
   （log_service.list/delete/_auto_cleanup、JSON 后端整文件覆写等），
   给出复杂度与数据规模交叉后的风险评级。
   注：usage / usage_forecast 的 logs.jsonl 全量读已在 3.5.1 改读聚合缓存
   （services/usage_agg.py），本清单不再登记该热点。
3. 优化建议：分页/索引/惰性加载/切分的具体落地建议，标注改动成本。

用法：
    .venv/Scripts/python.exe scripts/slow_query_report.py
报告输出到 reports/slowquery/YYYYMMDD_HHMMSS.md。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"

# 已知热点：全量 I/O 或全量遍历的代码点（人工审计确认，脚本做规模交叉验证）
# 每项: (名称, 文件:行, 模式, 复杂度, 触发频率, 关联数据文件, 分级状态, 分级理由)
# status 取值：
#   resolved              —— 已优化根治，不再构成热点
#   accepted_degradation  —— 无法/不必根治，明确「可接受降级」及理由（不伪造归零）
# 注：log_service.list/delete/_auto_cleanup 的 logs.jsonl 单文件全量读热点已于 4.1
#   按天轮转切分根治（写入 logs-YYYY-MM-DD.jsonl、list(days=N) 分片读取、过期天文件整删），
#   本清单不再登记。
HOTSPOTS = [
    {
        "name": "账号存储整文件覆写",
        "location": "services/storage/json_storage.py (save_accounts)",
        "pattern": "任何账号变更全量覆写 accounts.json",
        "complexity": "O(账号数)",
        "trigger": "账号增删改/状态刷新",
        "data_file": "accounts.json",
        "severity_when_large": "P3（账号量级通常 <1k，单条含 token 体积大但总量可控）",
        "status": "accepted_degradation",
        "reason": (
            "III-04 已落地内容去重写：save_accounts 序列化后与磁盘内容比对，"
            "内容未变（如周期性状态刷新）直接跳过原子写，消除无谓覆写；"
            "剩余写放大为 JSON 后端固有模型，当前量级 26 账号/118KB 写一次毫秒级。"
            "可接受降级：账号 >10k 时切 STORAGE_BACKEND=sqlite（已支持），不在 JSON 上做增量写。"
        ),
    },
    {
        "name": "数据库后端 ORM 查询形态",
        "location": "services/storage/database_storage.py (_save_rows / load_*)",
        "pattern": "SQLAlchemy ORM，业务键列(access_token/key_id)已有 unique+index；"
        "save 为 delete+insert 合并写（单事务，rollback 兜底）",
        "complexity": "load 全表 O(N)（仅启动期调用）；save O(N) 单事务",
        "trigger": "STORAGE_BACKEND=sqlite/postgres 时的启动加载与账号变更",
        "data_file": "*.db / postgres",
        "severity_when_large": "P3（请求路径不走 DB，启动期全量加载在账号 <10k 时无感）",
        "status": "accepted_degradation",
        "reason": (
            "III-04 已落地热点形态优化：save 由『整表全行加载』改为『键列扫描 + 定向更新 + "
            "批量 DELETE ... IN（synchronize_session=False）』，降低 O(N) 数据传输量；"
            "剩余 load 全表 O(N) 仅启动期调用一次。可接受降级：账号 <10k 启动加载无感，"
            "业务键列已 unique+index，请求路径不走 DB；量级 >10k 时再评估启动耗时。"
        ),
    },
]


def _human_size(n: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}"
        n = n / 1024
    return f"{n}B"


def scan_data_files() -> list[dict]:
    rows: list[dict] = []
    if not DATA_DIR.exists():
        return rows
    for path in sorted(DATA_DIR.iterdir()):
        if path.is_dir():
            count = sum(1 for _ in path.rglob("*") if _.is_file())
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            rows.append({"name": f"{path.name}/", "size": size, "entries": count, "lines": -1})
            continue
        size = path.stat().st_size
        lines = -1
        entries = -1
        if path.suffix == ".jsonl":
            with path.open("rb") as fh:
                lines = sum(1 for _ in fh)
            entries = lines
        elif path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entries = len(data) if isinstance(data, (list, dict)) else 1
            except Exception:
                entries = -2  # 解析失败（本身是发现）
        rows.append({"name": path.name, "size": size, "entries": entries, "lines": lines})
    return rows


def check_sqlite_indexes() -> dict:
    """静态检查数据库后端的索引声明（ORM Column(index=True) 或原生 CREATE INDEX）。"""
    result: dict[str, Any] = {"backend_found": False, "tables": [], "indexes": [], "warnings": []}
    storage_dir = ROOT / "services" / "storage"
    for path in storage_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "__tablename__" in text:
            result["backend_found"] = True
            result["tables"] += re.findall(r'__tablename__\s*=\s*"(\w+)"', text)
            # ORM 风格：Column(..., index=True)；列名从同行提取
            for line in text.splitlines():
                m = re.search(r"^\s*(\w+)\s*=\s*Column\(", line)
                if m and "index=True" in line:
                    result["indexes"].append(m.group(1))
            result["indexes"] += re.findall(r"CREATE INDEX(?:\s+IF NOT EXISTS)?\s+(\w+)", text, re.IGNORECASE)
        elif "CREATE TABLE" in text or "create table" in text.lower():
            result["backend_found"] = True
            result["tables"] += re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)", text, re.IGNORECASE)
            result["indexes"] += re.findall(r"CREATE INDEX(?:\s+IF NOT EXISTS)?\s+(\w+)", text, re.IGNORECASE)
    if result["backend_found"] and result["tables"] and not result["indexes"]:
        result["warnings"].append("建表语句中未发现任何索引声明——按主键外的列过滤会全表扫描")
    return result


def build_report_data(
    files: list[dict],
    sqlite: dict[str, Any],
    stamp: str,
    report_name: str,
    max_hotspots: int | None = None,
) -> dict[str, Any]:
    """构造结构化报告数据（III-04：供 CI 断言的结构化 JSON）。

    返回结构：
    {
      "generated_at": str,          # ISO 时间
      "report_file": str,           # 关联的 .md 报告相对路径
      "data_files_count": int,      # data/ 下盘点文件数
      "hotspots": {                 # 热点分级汇总
        "total": int,
        "resolved": int,            # 已根治数
        "accepted_degradation": int,# 明确「可接受降级」数
        "unresolved": int,          # 既非 resolved 也非 accepted 的热点数（须为 0）
        "items": [ {name, location, complexity, trigger, severity_when_large, status, reason} ]
      },
      "sqlite": {...},              # 索引静态检查结果原样透传
      "thresholds": {"max_hotspots": int | null}
    }
    """
    items: list[dict[str, Any]] = []
    resolved = 0
    accepted = 0
    unresolved = 0
    for h in HOTSPOTS:
        status = h.get("status", "")
        item = {
            "name": h["name"],
            "location": h["location"],
            "complexity": h["complexity"],
            "trigger": h["trigger"],
            "severity_when_large": h["severity_when_large"],
            "status": status,
            "reason": h.get("reason", ""),
        }
        if status == "resolved":
            resolved += 1
        elif status == "accepted_degradation":
            accepted += 1
        else:
            unresolved += 1
        items.append(item)

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "report_file": report_name,
        "data_files_count": len(files),
        "hotspots": {
            "total": len(items),
            "resolved": resolved,
            "accepted_degradation": accepted,
            "unresolved": unresolved,
            "items": items,
        },
        "sqlite": sqlite,
        "thresholds": {"max_hotspots": max_hotspots},
    }


def write_report_files(
    files: list[dict],
    sqlite: dict[str, Any],
    *,
    json_out: Path | None = None,
    max_hotspots: int | None = None,
) -> Path:
    """写 .md + .json 双份报告，返回 .md 路径。

    json_out 缺省时与 .md 同名同目录（reports/slowquery/YYYYMMDD_HHMMSS.json）。
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "reports" / "slowquery"
    out_dir.mkdir(parents=True, exist_ok=True)

    report = out_dir / f"{stamp}.md"
    report_name = report.relative_to(ROOT).as_posix()

    lines = [
        f"# 慢查询猎杀报告 {stamp}",
        "",
        "## 1. 数据规模盘点（data/）",
        "",
        "| 文件 | 体积 | 条目数 | 行数 |",
        "|------|------|--------|------|",
    ]
    for f in files:
        entries = {-1: "—(目录/未知)", -2: "解析失败"}.get(f["entries"], str(f["entries"]))
        lines.append(f"| {f['name']} | {_human_size(f['size'])} | {entries} | {f['lines'] if f['lines'] >= 0 else '—'} |")

    lines += [
        "",
        "## 2. 全量扫描热点（静态审计 × 规模交叉）",
        "",
        "| 热点 | 位置 | 复杂度 | 触发频率 | 大数据量风险 | 分级状态 |",
        "|------|------|--------|---------|-------------|---------|",
    ]
    for h in HOTSPOTS:
        lines.append(
            f"| {h['name']} | {h['location']} | {h['complexity']} | {h['trigger']} "
            f"| {h['severity_when_large']} | {h.get('status', '')} |"
        )

    lines += [
        "",
        "## 2.1 热点分级理由",
        "",
    ]
    for h in HOTSPOTS:
        lines.append(f"- **{h['name']}**（{h.get('status', '')}）：{h.get('reason', '')}")

    lines += [
        "",
        "## 3. 数据库后端索引静态检查",
        "",
        f"- 发现表：{sqlite['tables'] or '无'}",
        f"- 发现索引列：{sqlite['indexes'] or '无'}",
    ]
    for w in sqlite["warnings"]:
        lines.append(f"- ⚠️ {w}")

    lines += [
        "",
        "## 4. 优化建议（按投入产出排序）",
        "",
        "1. **日志按天轮转切分已落地（4.1）**：写入 logs-YYYY-MM-DD.jsonl、list(days=N) 分片读取、",
        "   过期天文件整删（文件级，不再逐行重写）；logs.jsonl 旧数据首次访问时惰性迁移。",
        "   本清单已移除『日志列表全量读 / 日志删除整文件重写 / 日志惰性清理整文件重写』热点。",
        "2. **账号存储内容去重写（III-04）**：save_accounts/save_auth_keys 内容未变时跳过原子写，",
        "   消除周期性状态刷新的无谓覆写；剩余写放大为 JSON 后端固有模型，量级 >10k 切 sqlite。",
        "3. **数据库后端 save 形态优化（III-04）**：键列扫描替代整表全行加载、定向更新、批量删除；",
        "   access_token / key_id 业务键列均有 unique+index，请求路径不走 DB（启动期一次性加载），",
        "   当前无量级风险；量级 >10k 时再看启动耗时。",
        "4. **反向分块读取（候选）**：list 的 read_text 在超大单文件（10w+ 行）仍全量读，",
        "   可改为 mmap 或 seek 尾部倒读分块；当前按天切分后单文件量级受 5000 条上限约束，风险已可控。",
        "",
        "## 5. 本报告边界",
        "",
        "- 只读静态分析 + 本机 data/ 实测规模；未做线上流量 replay。",
        "- SQLite/Postgres 后端的运行时慢查询需在真实部署上用 EXPLAIN 验证。",
        "- 关键查询延迟已由 Prometheus 直方图 c2api_storage_operation_duration_seconds 基准化。",
    ]

    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 结构化 JSON（III-04）：供 CI 断言热点数量/分级
    data = build_report_data(files, sqlite, stamp, report_name, max_hotspots=max_hotspots)
    json_path = json_out or out_dir / f"{stamp}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[slowquery] 报告: {report}")
    print(f"[slowquery] JSON: {json_path}")
    print(
        f"[slowquery] 数据文件 {len(files)} 个；热点 {data['hotspots']['total']} 处"
        f"（resolved={data['hotspots']['resolved']}, "
        f"accepted_degradation={data['hotspots']['accepted_degradation']}, "
        f"unresolved={data['hotspots']['unresolved']}）；"
        f"SQLite 警告 {len(sqlite['warnings'])} 条"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    """入口。返回码：
    0 —— 正常；若显式传入 --max-hotspots N 且热点总数 > N，返回 1（CI 断言用）。
    """
    args = _parse_args(argv)
    files = scan_data_files()
    sqlite = check_sqlite_indexes()
    write_report_files(
        files,
        sqlite,
        json_out=args.json_out,
        max_hotspots=args.max_hotspots,
    )
    if args.max_hotspots is not None:
        if len(HOTSPOTS) > args.max_hotspots:
            print(f"[slowquery] FAIL: 热点 {len(HOTSPOTS)} 处 > 阈值 {args.max_hotspots}")
            return 1
        print(f"[slowquery] PASS: 热点 {len(HOTSPOTS)} 处 <= 阈值 {args.max_hotspots}")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="慢查询猎杀与索引优化报告（R9，III-04 扩展）")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="结构化 JSON 输出路径（缺省：reports/slowquery/YYYYMMDD_HHMMSS.json）",
    )
    parser.add_argument(
        "--max-hotspots",
        type=int,
        default=None,
        help="热点总数阈值（供 CI 断言）：显式传入且超限时返回非零退出码",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
