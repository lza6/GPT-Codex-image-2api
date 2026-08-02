"""变异探针（R11）：验证测试套件是否真能抓住回归，而非"看着全绿"。

方法：对关键判断点做种子变异（阈值 +1、比较符翻转），跑对应测试文件，
观察测试是否变红。变异被抓住 = 测试对该行为有真实约束力；逃逸 = 存在
"覆盖率达标但行为无人看守"的盲区。

安全纪律：
- 变异逐一进行，改→测→立即还原，再下一个；
- 全部结束后跑全量测试确认 182 passed 恢复；
- 任何中途异常都会触发 finally 还原。

用法：
    .venv/Scripts/python.exe scripts/mutation_probe.py
报告输出到 reports/mutation/YYYYMMDD_HHMMSS.md。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"


@dataclass
class Mutation:
    name: str
    file: str
    original: str
    mutated: str
    test_targets: list[str]
    hypothesis: str


MUTATIONS = [
    Mutation(
        name="熔断阈值 5→6",
        file="services/circuit_breaker.py",
        original="    failure_threshold: int = 5,",
        mutated="    failure_threshold: int = 6,",
        test_targets=["test/test_circuit_breaker.py"],
        hypothesis="阈值变化应被熔断状态流转测试抓住",
    ),
    Mutation(
        name="流式首字节前换号上限 1→2",
        file="services/retry_budget.py",
        original="    return pre_stream_retries_used < PRE_STREAM_SWITCH_MAX_RETRIES",
        mutated="    return pre_stream_retries_used < PRE_STREAM_SWITCH_MAX_RETRIES + 1",
        test_targets=["test/test_retry_budget.py"],
        hypothesis="放宽换号上限应被预算边界测试抓住",
    ),
    Mutation(
        name="限流窗口 60s→61s",
        file="api/rate_limit.py",
        original="    def __init__(self, window_seconds: float = 60.0, max_requests: int = 0):",
        mutated="    def __init__(self, window_seconds: float = 61.0, max_requests: int = 0):",
        test_targets=["test/test_contracts.py"],
        hypothesis="test_contracts.test_rate_limit_window 直接断言 window_seconds==60.0，窗口漂移应变红",
    ),
    Mutation(
        name="进度淘汰 cutoff 方向反转",
        file="services/account_service.py",
        original='        expired = [pid for pid, item in store.items() if float(item.get("created_at") or 0) < cutoff]',
        mutated='        expired = [pid for pid, item in store.items() if float(item.get("created_at") or 0) > cutoff]',
        test_targets=["test/test_progress_ttl.py"],
        hypothesis="淘汰条件方向反转（保留过期、删除未过期）应被 TTL 淘汰测试抓住",
    ),
    Mutation(
        name="连接池上限 200→201",
        file="services/session_pool.py",
        original='session_pool = SessionPool(ttl_seconds=300.0, max_entries=200)',
        mutated='session_pool = SessionPool(ttl_seconds=300.0, max_entries=201)',
        test_targets=["test/test_session_pool_edge.py"],
        hypothesis="池上限变更应被 LRU/上限边界测试抓住",
    ),
    Mutation(
        name="SQLite WAL 开关反转（wal_mode 不生效）",
        file="services/storage/database_storage.py",
        original='            if wal_mode:\n                conn.execute(text("PRAGMA journal_mode=WAL"))',
        mutated='            if not wal_mode:\n                conn.execute(text("PRAGMA journal_mode=WAL"))',
        test_targets=["test/test_database_storage.py"],
        hypothesis="WAL 开关逻辑反转应被 test_sqlite_wal_mode_enabled_by_default 抓住",
    ),
]


def _run_tests(targets: list[str]) -> tuple[bool, str]:
    cmd = [str(PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", *targets]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    output = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(output.strip().splitlines()[-4:])
    return proc.returncode == 0, tail


def _purge_pyc(file: str) -> None:
    """清除被变异文件的 pyc 缓存。

    第七轮实证：变异期间子进程 pytest import 该模块会缓存"变异版" pyc，
    还原源文件后 pyc 仍是变异版 → 后续 import 读旧缓存（默认值 5 实测为 6）。
    每次 apply/revert 后必须清缓存，否则探针自身污染后续测试。
    """
    pycache = (ROOT / file).parent / "__pycache__"
    stem = Path(file).stem
    if pycache.exists():
        for pyc in pycache.glob(f"{stem}.*.pyc"):
            pyc.unlink(missing_ok=True)


def apply_mutation(m: Mutation) -> None:
    path = ROOT / m.file
    text = path.read_text(encoding="utf-8")
    if m.original not in text:
        raise RuntimeError(f"变异锚点不存在: {m.file} -> {m.original!r}（代码已漂移，需更新探针）")
    if text.count(m.original) != 1:
        raise RuntimeError(f"变异锚点不唯一: {m.file} -> {m.original!r}")
    path.write_text(text.replace(m.original, m.mutated, 1), encoding="utf-8")
    _purge_pyc(m.file)


def revert_mutation(m: Mutation) -> None:
    path = ROOT / m.file
    text = path.read_text(encoding="utf-8")
    if m.mutated in text:
        path.write_text(text.replace(m.mutated, m.original, 1), encoding="utf-8")
    _purge_pyc(m.file)


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    results: list[dict] = []

    # 基线 sanity：先确认目标测试本来就绿
    all_targets = sorted({t for m in MUTATIONS for t in m.test_targets})
    baseline_ok, baseline_tail = _run_tests(all_targets)
    if not baseline_ok:
        print(f"[mutation] 基线测试不绿，先修基线再谈变异：\n{baseline_tail}")
        return 2

    for m in MUTATIONS:
        entry = {"name": m.name, "file": m.file, "hypothesis": m.hypothesis}
        try:
            apply_mutation(m)
            green_after, tail = _run_tests(m.test_targets)
            entry["verdict"] = "escaped" if green_after else "caught"
            entry["tail"] = tail
        except RuntimeError as exc:
            entry["verdict"] = "anchor-drift"
            entry["tail"] = str(exc)
        finally:
            revert_mutation(m)
        results.append(entry)
        print(f"[mutation] {m.name}: {entry['verdict']}")

    # 还原确认：全量
    final_ok, final_tail = _run_tests(["test/"])
    caught = sum(1 for r in results if r["verdict"] == "caught")
    escaped = [r for r in results if r["verdict"] == "escaped"]
    drift = [r for r in results if r["verdict"] == "anchor-drift"]

    out_dir = ROOT / "reports" / "mutation"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 变异探针报告 {stamp}",
        "",
        f"- 变异数：{len(results)}；被抓住：{caught}；逃逸：{len(escaped)}；锚点漂移：{len(drift)}",
        f"- 还原后全量测试：{'182+ 全绿' if final_ok else '异常！' }",
        "",
        "| 变异 | 文件 | 判定 | 假设 |",
        "|------|------|------|------|",
    ]
    for r in results:
        verdict_zh = {"caught": "✅ 被抓住", "escaped": "⚠️ 逃逸", "anchor-drift": "❌ 锚点漂移"}[r["verdict"]]
        lines.append(f"| {r['name']} | {r['file']} | {verdict_zh} | {r['hypothesis']} |")
    lines.append("")
    for r in results:
        lines += [f"## {r['name']}", "", "```", r["tail"], "```", ""]
    if escaped:
        lines += [
            "## 逃逸处置建议",
            "",
            "逃逸意味着该行为改动不会导致任何测试变红。处置：为对应行为补一条",
            "直接断言阈值/边界的测试（不要只断言'不抛异常'），然后重跑本探针确认被抓住。",
            "",
        ]
    report = out_dir / f"{stamp}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[mutation] 报告: {report}")
    print(f"[mutation] caught={caught} escaped={len(escaped)} drift={len(drift)} 还原后全量={'OK' if final_ok else 'FAIL'}")
    return 0 if (final_ok and not drift) else 1


if __name__ == "__main__":
    raise SystemExit(main())
