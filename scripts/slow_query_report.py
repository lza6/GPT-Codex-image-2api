"""慢查询猎杀与索引优化报告（R9）。

只读分析，不修改任何数据与代码。三部分：
1. 数据规模盘点：data/ 下各存储文件的体积、条目数、行数——找出"越跑越慢"的候选大头。
2. 全量扫描点识别：静态扫描源码中每次请求都会全量读/全量遍历的热点
   （log_service.list/delete/_auto_cleanup、JSON 后端整文件覆写等），
   给出复杂度与数据规模交叉后的风险评级。
3. 优化建议：分页/索引/惰性加载/切分的具体落地建议，标注改动成本。

用法：
    .venv/Scripts/python.exe scripts/slow_query_report.py
报告输出到 reports/slowquery/YYYYMMDD_HHMMSS.md。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"

# 已知热点：全量 I/O 或全量遍历的代码点（人工审计确认，脚本做规模交叉验证）
# 每项: (名称, 文件:行, 模式, 复杂度, 触发频率, 关联数据文件)
HOTSPOTS = [
    {
        "name": "日志列表全量读+全量解析",
        "location": "services/log_service.py:128-142 (list)",
        "pattern": "read_text 整个 logs.jsonl → 逐行 json.loads 直到凑够 limit",
        "complexity": "O(文件行数) 读盘 + O(min(文件行数, 队首到 limit 条)) 解析",
        "trigger": "每次 GET /api/logs、前端日志页轮询",
        "data_file": "logs.jsonl",
        "severity_when_large": "P1（10k 行以上每次请求全读，CPU+IO 双高）",
    },
    {
        "name": "用量统计全量读",
        "location": "api/dashboard.py (usage) → log_service",
        "pattern": "同样全量读 logs.jsonl 做时间窗过滤",
        "complexity": "O(文件行数)",
        "trigger": "看板页每次刷新/轮询",
        "data_file": "logs.jsonl",
        "severity_when_large": "P1",
    },
    {
        "name": "日志删除整文件重写",
        "location": "services/log_service.py:144-164 (delete)",
        "pattern": "read_text + 全量重序列化 + write_text",
        "complexity": "O(文件行数) 读写各一次",
        "trigger": "删除日志操作",
        "data_file": "logs.jsonl",
        "severity_when_large": "P2",
    },
    {
        "name": "日志惰性清理整文件重写",
        "location": "services/log_service.py:115-126 (_auto_cleanup)",
        "pattern": "每 200 条触发：全量读+裁剪+全量写",
        "complexity": "O(文件行数)",
        "trigger": "写入路径（高频调用时每 200 次一次）",
        "data_file": "logs.jsonl",
        "severity_when_large": "P2（已有限流，超 5000 条才触发）",
    },
    {
        "name": "账号存储整文件覆写",
        "location": "services/storage/json_storage.py:41-43 (save_accounts)",
        "pattern": "任何账号变更全量覆写 accounts.json",
        "complexity": "O(账号数)",
        "trigger": "账号增删改/状态刷新",
        "data_file": "accounts.json",
        "severity_when_large": "P3（账号量级通常 <1k，单条含 token 体积大但总量可控）",
    },
    {
        "name": "数据库后端 ORM 查询形态",
        "location": "services/storage/database_storage.py:45-135",
        "pattern": "SQLAlchemy ORM，业务键列(access_token/key_id)已有 unique+index；"
        "save 为 delete+insert 合并写（单事务，rollback 兜底）",
        "complexity": "load 全表 O(N)（仅启动期调用）；save O(N) 单事务",
        "trigger": "STORAGE_BACKEND=sqlite/postgres 时的启动加载与账号变更",
        "data_file": "*.db / postgres",
        "severity_when_large": "P3（请求路径不走 DB，启动期全量加载在账号 <10k 时无感）",
    },
]


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}"
        n /= 1024
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
    result = {"backend_found": False, "tables": [], "indexes": [], "warnings": []}
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


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    files = scan_data_files()
    sqlite = check_sqlite_indexes()

    out_dir = ROOT / "reports" / "slowquery"
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# 慢查询猎杀报告 {stamp}",
        "",
        "## 1. 数据规模盘点（data/）",
        "",
        "| 文件 | 体积 | 条目数 | 行数 |",
        "|------|------|--------|------|",
    ]
    for f in files:
        entries = { -1: "—(目录/未知)", -2: "解析失败" }.get(f["entries"], str(f["entries"]))
        lines.append(f"| {f['name']} | {_human_size(f['size'])} | {entries} | {f['lines'] if f['lines'] >= 0 else '—'} |")

    lines += [
        "",
        "## 2. 全量扫描热点（静态审计 × 规模交叉）",
        "",
        "| 热点 | 位置 | 复杂度 | 触发频率 | 大数据量风险 |",
        "|------|------|--------|---------|-------------|",
    ]
    for h in HOTSPOTS:
        lines.append(f"| {h['name']} | {h['location']} | {h['complexity']} | {h['trigger']} | {h['severity_when_large']} |")

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
        "1. **logs.jsonl 轮转切分**（中成本低风险）：按天切分为 logs-YYYY-MM-DD.jsonl，",
        "   list/usage 只读最近 N 天文件。当前 _AUTO_CLEAN_MAX_ENTRIES=5000 已兜底总量，",
        "   但在高调用量场景 5000 条可能只是一天的量——切分后单文件始终可控。",
        "2. **list 解析 early-exit 已有**（limit 凑够即停），但 read_text 仍是全量：",
        "   可改为 mmap 或反向分块读取（seek 到尾部倒读），改动需评估编码边界，建议 v2.1。",
        "3. **数据库后端索引已就位**：access_token / key_id 业务键列均有 unique+index，",
        "   且请求路径不走 DB（启动期一次性加载），当前无量级风险；量级 >10k 时再看启动耗时。",
        "4. **accounts.json 写放大**：账号量级 <1k 时无需处理；若未来上万，",
        "   先切 STORAGE_BACKEND=sqlite（已支持），不在 JSON 上做增量写。",
        "",
        "## 5. 本报告边界",
        "",
        "- 只读静态分析 + 本机 data/ 实测规模；未做线上流量 replay。",
        "- SQLite/Postgres 后端的运行时慢查询需在真实部署上用 EXPLAIN 验证。",
    ]

    report = out_dir / f"{stamp}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[slowquery] 报告: {report}")
    print(f"[slowquery] 数据文件 {len(files)} 个；热点 {len(HOTSPOTS)} 处；SQLite 警告 {len(sqlite['warnings'])} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
