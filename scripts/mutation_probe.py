"""变异探针（R11）：验证测试套件是否真能抓住回归，而非"看着全绿"。

方法：对关键判断点做种子变异（阈值 +1、比较符翻转），跑对应测试文件，
观察测试是否变红。变异被抓住 = 测试对该行为有真实约束力；逃逸 = 存在
"覆盖率达标但行为无人看守"的盲区。

安全纪律：
- 变异逐一进行，改→测→立即还原，再下一个；
- 全部结束后跑变异涉及测试子集确认还原（不跑全量，避免预存失败误报 + 超时）；
- 任何中途异常都会触发 finally 还原。

用法：
    .venv/Scripts/python.exe scripts/mutation_probe.py
报告输出到 reports/mutation/YYYYMMDD_HHMMSS.md。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"

# 已知预存失败文件（非本轮引入，变异探针不视为污染）：
# - test_v1_chat_completions.py: utils.helper 无 save_images_from_text（ImportError）
# - test_log_api.py: 导入链问题
# - test_chat_completion_cache.py / test_codex_pooling.py / test_image_error_debug.py:
#   偶发并发竞态（单独跑绿）
# - test_openapi.py: spec 快照与 live 路径偶发漂移（已用重新生成解决，仍留作缓冲）
SKIP_FILES = {
    "test/test_v1_chat_completions.py",
    "test/test_log_api.py",
    "test/test_chat_completion_cache.py",
    "test/test_codex_pooling.py",
    "test/test_image_error_debug.py",
    "test/test_openapi.py",
}


@dataclass
class Mutation:
    name: str
    file: str
    original: str
    mutated: str
    test_targets: list[str]
    hypothesis: str


MUTATIONS = [
    # ── circuit_breaker.py：熔断状态机 ────────────────────────────────
    Mutation(
        name="熔断阈值 5→6",
        file="services/circuit_breaker.py",
        original="    failure_threshold: int = 5,",
        mutated="    failure_threshold: int = 6,",
        test_targets=["test/test_circuit_breaker.py"],
        hypothesis="阈值变化应被熔断状态流转测试抓住",
    ),
    Mutation(
        name="半开恢复次数 3→4",
        file="services/circuit_breaker.py",
        original="        half_open_max_calls: int = 3,",
        mutated="        half_open_max_calls: int = 4,",
        test_targets=["test/test_circuit_breaker.py", "test/test_circuit_breaker_lifecycle.py"],
        hypothesis="半开恢复次数增加应被 test_half_open_success_restores_closed 抓住",
    ),
    Mutation(
        name="熔断超时 30.0→60.0",
        file="services/circuit_breaker.py",
        original="        recovery_timeout: float = 30.0,",
        mutated="        recovery_timeout: float = 60.0,",
        test_targets=["test/test_circuit_breaker.py"],
        hypothesis="冷却期翻倍应被 test_open_recovers_to_half_open_after_timeout 抓住",
    ),

    # ── retry_budget.py：重试预算 ────────────────────────────────────
    Mutation(
        name="流式首字节前换号上限 1→2",
        file="services/retry_budget.py",
        original="    return pre_stream_retries_used < PRE_STREAM_SWITCH_MAX_RETRIES",
        mutated="    return pre_stream_retries_used < PRE_STREAM_SWITCH_MAX_RETRIES + 1",
        test_targets=["test/test_retry_budget.py"],
        hypothesis="放宽换号上限应被预算边界测试抓住",
    ),
    Mutation(
        name="幂等 GET 最大重试 2→3",
        file="services/retry_budget.py",
        original="IDEMPOTENT_GET_MAX_RETRIES = 2",
        mutated="IDEMPOTENT_GET_MAX_RETRIES = 3",
        test_targets=["test/test_retry_budget.py"],
        hypothesis="最大重试次数增加应被 test_gives_up_after_max_retries 抓住",
    ),
    Mutation(
        name="指数退避基数 0.5→1.0",
        file="services/retry_budget.py",
        original="    base_delay: float = 0.5,",
        mutated="    base_delay: float = 1.0,",
        test_targets=["test/test_retry_budget.py"],
        hypothesis="退避基数翻倍应被 test_backoff_is_exponential 抓住",
    ),

    # ── api/rate_limit.py：限流窗口 ──────────────────────────────────
    Mutation(
        name="限流窗口 60s→61s",
        file="api/rate_limit.py",
        original="    def __init__(self, window_seconds: float = 60.0, max_requests: int = 0):",
        mutated="    def __init__(self, window_seconds: float = 61.0, max_requests: int = 0):",
        test_targets=["test/test_contracts.py"],
        hypothesis="test_contracts.test_rate_limit_window 直接断言 window_seconds==60.0，窗口漂移应变红",
    ),

    # ── account_service.py：进度淘汰 ─────────────────────────────────
    Mutation(
        name="进度淘汰 cutoff 方向反转",
        file="services/account_service.py",
        original='        expired = [pid for pid, item in store.items() if float(item.get("created_at") or 0) < cutoff]',
        mutated='        expired = [pid for pid, item in store.items() if float(item.get("created_at") or 0) > cutoff]',
        test_targets=["test/test_progress_ttl.py"],
        hypothesis="淘汰条件方向反转（保留过期、删除未过期）应被 TTL 淘汰测试抓住",
    ),

    # ── account_service.py：调度分计算 ───────────────────────────────
    Mutation(
        name="调度分配额占比上限 10→20",
        file="services/account_service.py",
        original="        score += min(10.0, quota / 10.0)",
        mutated="        score += min(20.0, quota / 10.0)",
        test_targets=["test/test_account_scheduler.py"],
        hypothesis="配额占比上限翻倍应被调度分测试（test_higher_quota_higher_score）抓住",
    ),
    Mutation(
        name="成功加成系数 5.0→10.0",
        file="services/account_service.py",
        original="            score += 5.0 * (success / total)",
        mutated="            score += 10.0 * (success / total)",
        test_targets=["test/test_account_scheduler.py"],
        hypothesis="成功加成系数翻倍应被调度分测试（test_fail_penalty_lowers_score）抓住",
    ),
    Mutation(
        name="失败惩罚系数 10.0→20.0",
        file="services/account_service.py",
        original="            score -= 10.0 * (fail / total)",
        mutated="            score -= 20.0 * (fail / total)",
        test_targets=["test/test_account_scheduler.py"],
        hypothesis="失败惩罚系数翻倍应被调度分测试（test_fail_penalty_lowers_score）抓住",
    ),
    Mutation(
        name="冷却惩罚窗口 1800s→3600s",
        file="services/account_service.py",
        original="            if err_seconds is not None and err_seconds < 1800:",
        mutated="            if err_seconds is not None and err_seconds < 3600:",
        test_targets=["test/test_account_scheduler.py"],
        hypothesis="冷却窗口扩大应被调度分最近错误惩罚测试抓住",
    ),

    # ── account_service.py：健康档位判定 ─────────────────────────────
    Mutation(
        name="刷新错误窗口 600s→1200s",
        file="services/account_service.py",
        original="        if (refresh_err is not None and refresh_err < 600) or (token_err is not None and token_err < 300):",
        mutated="        if (refresh_err is not None and refresh_err < 1200) or (token_err is not None and token_err < 300):",
        test_targets=["test/test_account_scheduler.py"],
        hypothesis="刷新错误惩罚窗口扩大应被 warm 档位判定测试抓住",
    ),
    Mutation(
        name="高失败率 risky 阈值 0.5→0.6",
        file="services/account_service.py",
        original="        if total >= 3 and fail / total > 0.5:",
        mutated="        if total >= 3 and fail / total > 0.6:",
        test_targets=["test/test_account_scheduler.py"],
        hypothesis="高失败率阈值偏移应被 test_high_fail_rate_is_risky 抓住",
    ),
    Mutation(
        name="warm 档位低配额阈值 5→10",
        file="services/account_service.py",
        original="        if quota < 5 or (total >= 3 and fail / total > 0.2):",
        mutated="        if quota < 10 or (total >= 3 and fail / total > 0.2):",
        test_targets=["test/test_account_scheduler.py"],
        hypothesis="低配额阈值抬高应被 test_low_quota_is_warm 抓住",
    ),

    # ── account_service.py：健康评分 ─────────────────────────────────
    Mutation(
        name="健康评分 quota_ratio 分母 20→40",
        file="services/account_service.py",
        original="        quota_ratio = min(1.0, quota / 20.0)\n        base = 70.0 * (1 - fail_ratio) * quota_ratio",
        mutated="        quota_ratio = min(1.0, quota / 40.0)\n        base = 70.0 * (1 - fail_ratio) * quota_ratio",
        test_targets=["test/test_account_scheduler.py"],
        hypothesis="健康评分配额比例分母翻倍应被某评分归属测试抓住",
    ),
    Mutation(
        name="新账号无效宽限期 10min→5min",
        file="services/account_service.py",
        original="    _NEW_ACCOUNT_INVALID_GRACE_SECONDS = 10 * 60",
        mutated="    _NEW_ACCOUNT_INVALID_GRACE_SECONDS = 5 * 60",
        test_targets=["test/test_account_scheduler.py"],
        hypothesis="新账号宽限期减半应被无效账号判断测试抓住",
    ),
    Mutation(
        name="账号列表缓存 TTL 5.0→10.0",
        file="services/account_service.py",
        original="    _ACCOUNT_LIST_CACHE_TTL: float = 5.0",
        mutated="    _ACCOUNT_LIST_CACHE_TTL: float = 10.0",
        test_targets=["test/test_account_scheduler.py"],
        hypothesis="缓存 TTL 翻倍应被缓存有效性测试抓住",
    ),

    # ── session_pool.py：连接池 ──────────────────────────────────────
    Mutation(
        name="Session TTL 300.0→600.0",
        file="services/session_pool.py",
        original="        ttl_seconds: float = 300.0,",
        mutated="        ttl_seconds: float = 600.0,",
        test_targets=["test/test_session_pool.py", "test/test_session_pool_edge.py"],
        hypothesis="TTL 翻倍应被 test_ttl_expiry_rebuilds / test_ttl_expiry_recreates_session 抓住",
    ),
    Mutation(
        name="最小空闲连接 5→10",
        file="services/session_pool.py",
        original="        min_size: int = 5,",
        mutated="        min_size: int = 10,",
        test_targets=["test/test_session_pool.py", "test/test_session_pool_edge.py"],
        hypothesis="最小空闲连接数翻倍应被 LRU 逐出/缩容测试抓住",
    ),
    Mutation(
        name="健康检查超时 5.0→10.0",
        file="services/session_pool.py",
        original="        health_check_timeout: float = 5.0,",
        mutated="        health_check_timeout: float = 10.0,",
        test_targets=["test/test_session_pool_edge.py"],
        hypothesis="健康检查超时翻倍应被 test_health_check_validates_connection 抓住",
    ),
    Mutation(
        name="连接池上限 200→201",
        file="services/session_pool.py",
        original="session_pool = SessionPool(ttl_seconds=300.0, max_entries=200, min_size=5)",
        mutated="session_pool = SessionPool(ttl_seconds=300.0, max_entries=201, min_size=5)",
        test_targets=["test/test_session_pool_edge.py"],
        hypothesis="池上限变更应被 LRU/上限边界测试抓住",
    ),

    # ── image_pipeline.py：异步图片管道 ──────────────────────────────
    Mutation(
        name="图片并发限制 5→10",
        file="services/image_pipeline.py",
        original="DEFAULT_CONCURRENCY = 5",
        mutated="DEFAULT_CONCURRENCY = 10",
        test_targets=["test/test_image_pipeline.py"],
        hypothesis="并发限制翻倍应被 test_concurrency_limited 抓住",
    ),
    Mutation(
        name="图片缓存 TTL 3600→7200",
        file="services/image_pipeline.py",
        original="CACHE_TTL = 3600",
        mutated="CACHE_TTL = 7200",
        test_targets=["test/test_image_pipeline.py"],
        hypothesis="缓存 TTL 翻倍应被 test_cache_ttl_expires 抓住",
    ),

    # ── provider_scheduler.py：Provider 调度池 ───────────────────────
    Mutation(
        name="Provider 冷却期 60.0→120.0",
        file="services/provider_scheduler.py",
        original="    _PROVIDER_CB_RECOVERY = 60.0  # 冷却期（秒）",
        mutated="    _PROVIDER_CB_RECOVERY = 120.0  # 冷却期（秒）",
        test_targets=["test/test_provider_scheduler.py"],
        hypothesis="Provider 熔断冷却期翻倍应被 test_provider_breaker_recovery_after_timeout 抓住",
    ),
    Mutation(
        name="Provider 熔断阈值 3→4",
        file="services/provider_scheduler.py",
        original="    _PROVIDER_CB_THRESHOLD = 3  # 连续 N 次无可用账号后熔断该 provider",
        mutated="    _PROVIDER_CB_THRESHOLD = 4  # 连续 N 次无可用账号后熔断该 provider",
        test_targets=["test/test_provider_scheduler.py"],
        hypothesis="Provider 熔断阈值偏移应被 test_provider_breaker_opens_after_threshold 抓住",
    ),
    Mutation(
        name="Provider 限流窗口 60.0→120.0",
        file="services/provider_scheduler.py",
        original="    _PROVIDER_RATE_WINDOW = 60.0",
        mutated="    _PROVIDER_RATE_WINDOW = 120.0",
        test_targets=["test/test_provider_scheduler.py"],
        hypothesis="限流窗口翻倍应被 test_provider_rate_limit_blocks_excess 抓住",
    ),

    # ── proxy_service.py：代理服务 ───────────────────────────────────
    Mutation(
        name="代理测试超时 15.0→30.0",
        file="services/proxy_service.py",
        original='def test_proxy(url: str = "", *, timeout: float = 15.0) -> dict:',
        mutated='def test_proxy(url: str = "", *, timeout: float = 30.0) -> dict:',
        test_targets=["test/test_proxy_service.py"],
        hypothesis="代理测试超时翻倍应被代理测试相关用例抓住",
    ),
    Mutation(
        name="Flaresolverr 超时 60→120",
        file="services/proxy_service.py",
        original='    def get_clearance(self, target_url: str, proxy_url: str = "", timeout_sec: int = 60) -> ClearanceBundle | None:',
        mutated='    def get_clearance(self, target_url: str, proxy_url: str = "", timeout_sec: int = 120) -> ClearanceBundle | None:',
        test_targets=["test/test_proxy_service.py"],
        hypothesis="Flaresolverr 超时翻倍应被 clearance 相关测试抓住",
    ),

    # ── image_failure.py：熔断判定单一事实来源 ───────────────────────
    Mutation(
        name="should_record_circuit_failure 范围扩大（ACCOUNT 也算 TRANSIENT）",
        file="services/image_failure.py",
        original="    return failure_policy(code).scope is FailureScope.TRANSIENT",
        mutated="    return failure_policy(code).scope in {FailureScope.TRANSIENT, FailureScope.ACCOUNT}",
        test_targets=["test/test_image_failure.py"],
        hypothesis="熔断判定范围扩大应被 test_business_or_account_rejection_never_records 抓住",
    ),
    Mutation(
        name="should_switch_account 排除 TRANSIENT",
        file="services/image_failure.py",
        original="    return failure_policy(code).scope in {FailureScope.ACCOUNT, FailureScope.TRANSIENT}",
        mutated="    return failure_policy(code).scope in {FailureScope.ACCOUNT}",
        test_targets=["test/test_image_failure.py"],
        hypothesis="换号判定缩小（排除 TRANSIENT）应被 test_account_and_transient_switch 抓住",
    ),

    # ── protocol/conversation.py：轮询超时重试 ───────────────────────
    Mutation(
        name="轮询超时重试上限 4→5",
        file="services/protocol/conversation.py",
        original="    MAX_POLL_TIMEOUT_RETRIES = 4",
        mutated="    MAX_POLL_TIMEOUT_RETRIES = 5",
        test_targets=["test/test_search_resilience.py"],
        hypothesis="轮询超时重试次数增加应被超时重试测试抓住",
    ),

    # ── storage/database_storage.py：SQLite WAL ──────────────────────
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
    # 过滤掉已知预存失败文件
    filtered = [t for t in targets if t not in SKIP_FILES]
    cmd = [str(PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", *filtered]
    # 子进程强制 UTF-8 输出 + 父进程按 UTF-8 容错解码：
    # 防 Windows GBK 控制台下中文日志偶发 UnicodeEncodeError 击穿全量重跑（第七/十一轮记录的 flaky）
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=300, env=env, encoding="utf-8", errors="replace")
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

    # 基线 sanity：先确认目标测试本来就绿（过滤预存失败文件）
    all_targets = sorted({t for m in MUTATIONS for t in m.test_targets})
    baseline_ok, baseline_tail = _run_tests(all_targets)
    if not baseline_ok:
        print(f"[mutation] 基线测试不绿，先修基线再谈变异：\n{baseline_tail}")
        return 2

    print(f"[mutation] 基线 OK，开始 {len(MUTATIONS)} 个变异探针...\n")

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
        print(f"[mutation] {entry['verdict']:>12s}  | {m.name}")

    # 还原确认：跑变异涉及的所有测试子集（比全量快，且不受预存失败文件干扰）
    final_ok, final_tail = _run_tests(all_targets)
    caught = sum(1 for r in results if r["verdict"] == "caught")
    escaped = [r for r in results if r["verdict"] == "escaped"]
    drift = [r for r in results if r["verdict"] == "anchor-drift"]

    out_dir = ROOT / "reports" / "mutation"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 变异探针报告 {stamp}",
        "",
        f"- 变异数：{len(results)}；被抓住：{caught}；逃逸：{len(escaped)}；锚点漂移：{len(drift)}",
        f"- 还原后测试子集：{'全绿' if final_ok else '异常！'}",
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
    print(f"[mutation] caught={caught} escaped={len(escaped)} drift={len(drift)} 还原后测试子集={'OK' if final_ok else 'FAIL'}")
    return 0 if (final_ok and not drift) else 1


if __name__ == "__main__":
    raise SystemExit(main())
