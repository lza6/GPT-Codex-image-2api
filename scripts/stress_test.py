"""极限施压与防穿透测试（R8）。

设计目标（对应用户指令"极端情况下系统会不会崩溃、数据会不会错乱"）：
1. 并发突刺：多线程对关键只读端点施压，进程不能死、错误率不能高、延迟不能失控。
2. 内存监控：压测期间采样进程 RSS，判断是否存在明显内存泄漏趋势。
3. 慢存储注入：对 JSON 存储的读写加人为延迟（mock），验证在存储变慢时
   看板端点仍能在预算内响应或至少不挂起请求（防穿透）。
4. 存储写一致性：并发写 storage 后读回，校验数据不错乱、不丢写。

用法：
    .venv/Scripts/python.exe scripts/stress_test.py
    .venv/Scripts/python.exe scripts/stress_test.py --requests 300 --concurrency 20 --budget-ms 800

报告输出到 reports/stress/YYYYMMDD_HHMMSS.md 与 .json（reports/ 已 gitignore）。

注意：本脚本使用 TestClient 进程内压测（不监听端口，不影响生产实例），
并发模型为线程池——FastAPI 同步端点经 run_in_threadpool 执行，与生产一致。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

# 保证以仓库根目录运行；鉴权 key 仅用进程内 TestClient，不落盘、不触网
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "stress-test-only-key-0123456789")

AUTH_HEADERS = {"Authorization": "Bearer stress-test-only-key-0123456789"}

# 参与压测的关键只读端点（均为看板/管理面高频入口）
# 注意：/api/logs?limit=200 会全量读日志文件（log_service.list 无 early-exit 上限），
# 是存储 I/O 密集端点，慢存储注入主要作用在它身上。
ENDPOINTS = [
    "/api/dashboard/stats",
    "/api/dashboard/scheduler",
    "/api/dashboard/usage",
    "/api/dashboard/latency",
    "/api/accounts",
    "/api/logs?limit=200",
]

# 判定阈值（可被 CLI 覆盖）
DEFAULT_MAX_ERROR_RATE = 0.01  # 5xx 比例上限（网络层之外的硬错误）
DEFAULT_P99_BUDGET_MS = 1500.0  # 常规施压 p99 预算
DEFAULT_SLOW_P99_BUDGET_MS = 4000.0  # 慢存储注入下 p99 预算（放宽但不允许挂死）
DEFAULT_MAX_RSS_GROWTH_MB = 256.0  # 压测首尾 RSS 增长上限


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except Exception:
        return -1.0


def _make_client():
    from fastapi.testclient import TestClient

    from api.app import create_app

    return TestClient(create_app())


class LatencyRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.latencies: list[float] = []
        self.statuses: list[int] = []

    def record(self, status: int, latency_ms: float) -> None:
        with self._lock:
            self.statuses.append(status)
            self.latencies.append(latency_ms)


def _p99(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * 0.99))
    return ordered[idx]


def run_spike(client, requests: int, concurrency: int) -> dict:
    """并发突刺：混合端点打满线程池。"""
    recorder = LatencyRecorder()
    rss_before = _rss_mb()
    started = time.perf_counter()

    def hit(i: int) -> None:
        path = ENDPOINTS[i % len(ENDPOINTS)]
        t0 = time.perf_counter()
        try:
            resp = client.get(path, headers=AUTH_HEADERS)
            status = resp.status_code
        except Exception:
            status = -1  # 客户端侧异常（连接失败等），计入硬错误
        recorder.record(status, (time.perf_counter() - t0) * 1000)

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(hit, range(requests)))

    wall = time.perf_counter() - started
    rss_after = _rss_mb()
    hard_errors = sum(1 for s in recorder.statuses if s == -1 or s >= 500)
    return {
        "requests": requests,
        "concurrency": concurrency,
        "wall_seconds": round(wall, 2),
        "throughput_rps": round(requests / wall, 1) if wall > 0 else 0,
        "hard_errors": hard_errors,
        "error_rate": round(hard_errors / max(requests, 1), 4),
        "p50_ms": round(statistics.median(recorder.latencies), 1) if recorder.latencies else 0,
        "p99_ms": round(_p99(recorder.latencies), 1),
        "rss_before_mb": round(rss_before, 1),
        "rss_after_mb": round(rss_after, 1),
        "rss_growth_mb": round(rss_after - rss_before, 1) if rss_before > 0 else -1,
        "status_histogram": {str(s): recorder.statuses.count(s) for s in sorted(set(recorder.statuses))},
    }


def run_slow_storage(client, requests: int, concurrency: int, delay_ms: int) -> dict:
    """慢存储注入：给日志文件的全量读取加延迟，验证存储变慢时不挂死。

    说明：请求路径上的存储 I/O 热点是 log_service（/api/logs、/api/dashboard/usage
    每次全量读 logs.jsonl）；账号数据在启动时一次性加载进内存，请求路径不再读盘。
    因此注入点选 Path.read_text（log_service 的唯一读取通道），而非启动期的
    JSONStorageBackend._load_json_list。
    """
    original_read_text = Path.read_text
    marker = "logs.jsonl"
    hits = {"count": 0}
    hits_lock = threading.Lock()

    def slowed_read_text(self, *args, **kwargs):
        if marker in str(self):
            with hits_lock:
                hits["count"] += 1
            time.sleep(delay_ms / 1000)
        return original_read_text(self, *args, **kwargs)

    Path.read_text = slowed_read_text
    try:
        result = run_spike(client, requests, concurrency)
    finally:
        Path.read_text = original_read_text
    result["slow_storage_injected"] = hits["count"] > 0
    result["injected_hits"] = hits["count"]
    result["injected_delay_ms"] = delay_ms
    return result


def run_storage_consistency(writes: int, concurrency: int) -> dict:
    """并发写 JSON 存储：校验文件不写坏（最终可解析为合法 JSON 数组）。

    说明：JSON 后端为整文件覆写语义（save_accounts 全量替换），并发写下
    "最后一个写赢"是设计行为；本检查关注的是极端并发下文件是否损坏（半写状态），
    以及写路径是否抛未处理异常——这是"数据错乱"的实际红线。
    """
    from services.storage.json_storage import JSONStorageBackend

    tmp_dir = ROOT / "data" / "stress_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / "consistency.json"
    store = JSONStorageBackend(target)
    errors: list[str] = []

    def write_one(i: int) -> None:
        try:
            store.save_accounts([{"id": f"acc_{i % 10}", "seq": i, "ts": time.time()}])
        except Exception as exc:  # noqa: BLE001 - 记录所有并发写异常
            errors.append(f"write {i}: {exc!r}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(write_one, range(writes)))

    file_ok = True
    detail = ""
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            file_ok = False
            detail = "顶层不是 list"
        elif data and "seq" not in data[0]:
            file_ok = False
            detail = "写入结构缺失 seq 字段"
    except Exception as exc:  # noqa: BLE001
        file_ok = False
        detail = f"JSON 损坏（半写状态）: {exc!r}"

    try:
        target.unlink(missing_ok=True)
        tmp_dir.rmdir()
    except OSError:
        pass

    return {
        "writes": writes,
        "concurrency": concurrency,
        "write_errors": errors[:5],
        "write_error_count": len(errors),
        "file_valid_json_after_storm": file_ok,
        "detail": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ChatGPT2API 极限施压与防穿透测试")
    parser.add_argument("--requests", type=int, default=300, help="每轮请求总数")
    parser.add_argument("--concurrency", type=int, default=20, help="并发线程数")
    parser.add_argument("--budget-ms", type=float, default=DEFAULT_P99_BUDGET_MS, help="常规 p99 预算")
    parser.add_argument("--slow-delay-ms", type=int, default=120, help="慢存储注入的单次读延迟")
    parser.add_argument("--slow-budget-ms", type=float, default=DEFAULT_SLOW_P99_BUDGET_MS, help="慢存储 p99 预算")
    args = parser.parse_args()

    print("[stress] 初始化 TestClient ...")
    client = _make_client()

    checks: list[dict] = []

    print(f"[stress] 1/3 并发突刺: {args.requests} 请求 × {args.concurrency} 线程")
    spike = run_spike(client, args.requests, args.concurrency)
    checks.append({
        "name": "并发突刺-错误率",
        "pass": spike["error_rate"] <= DEFAULT_MAX_ERROR_RATE,
        "actual": spike["error_rate"],
        "budget": DEFAULT_MAX_ERROR_RATE,
    })
    checks.append({
        "name": "并发突刺-p99延迟",
        "pass": spike["p99_ms"] <= args.budget_ms,
        "actual": spike["p99_ms"],
        "budget": args.budget_ms,
    })
    if spike["rss_growth_mb"] >= 0:
        checks.append({
            "name": "并发突刺-RSS增长",
            "pass": spike["rss_growth_mb"] <= DEFAULT_MAX_RSS_GROWTH_MB,
            "actual": spike["rss_growth_mb"],
            "budget": DEFAULT_MAX_RSS_GROWTH_MB,
        })

    print(f"[stress] 2/3 慢存储注入: 读延迟 {args.slow_delay_ms}ms")
    slow = run_slow_storage(client, max(args.requests // 2, 50), args.concurrency, args.slow_delay_ms)
    checks.append({
        "name": "慢存储-p99延迟(不挂死)",
        "pass": slow["p99_ms"] <= args.slow_budget_ms,
        "actual": slow["p99_ms"],
        "budget": args.slow_budget_ms,
    })
    checks.append({
        "name": "慢存储-错误率",
        "pass": slow["error_rate"] <= DEFAULT_MAX_ERROR_RATE,
        "actual": slow["error_rate"],
        "budget": DEFAULT_MAX_ERROR_RATE,
    })

    print("[stress] 3/3 存储并发写一致性")
    consistency = run_storage_consistency(max(args.requests, 100), args.concurrency)
    checks.append({
        "name": "存储-并发写后文件可解析",
        "pass": consistency["file_valid_json_after_storm"],
        "actual": consistency["detail"] or "valid",
        "budget": "valid json",
    })

    passed = sum(1 for c in checks if c["pass"])
    overall = passed == len(checks)

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "reports" / "stress"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": stamp,
        "overall_pass": overall,
        "checks": checks,
        "spike": spike,
        "slow_storage": slow,
        "storage_consistency": consistency,
    }
    (out_dir / f"{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 极限施压报告 {stamp}",
        "",
        f"- 总体：{'PASS' if overall else 'FAIL'}（{passed}/{len(checks)} 项通过）",
        "",
        "## 判定项",
        "",
        "| 检查 | 结果 | 实际 | 预算 |",
        "|------|------|------|------|",
    ]
    for c in checks:
        lines.append(f"| {c['name']} | {'PASS' if c['pass'] else 'FAIL'} | {c['actual']} | {c['budget']} |")
    lines += [
        "",
        "## 并发突刺详情",
        "",
        f"- 吞吐：{spike['throughput_rps']} req/s（墙钟 {spike['wall_seconds']}s）",
        f"- 状态分布：{spike['status_histogram']}",
        f"- p50={spike['p50_ms']}ms p99={spike['p99_ms']}ms",
        f"- RSS：{spike['rss_before_mb']}MB → {spike['rss_after_mb']}MB（增长 {spike['rss_growth_mb']}MB）",
        "",
        "## 慢存储注入详情",
        "",
        f"- 注入成功：{slow['slow_storage_injected']}（命中 {slow.get('injected_hits', 0)} 次日志读 × {slow['injected_delay_ms']}ms）",
        f"- p50={slow['p50_ms']}ms p99={slow['p99_ms']}ms 错误率={slow['error_rate']}",
        "",
        "## 存储一致性详情",
        "",
        f"- 并发写 {consistency['writes']} 次（{consistency['concurrency']} 线程），异常 {consistency['write_error_count']} 个",
        f"- 压后文件可解析：{consistency['file_valid_json_after_storm']} {consistency['detail']}",
    ]
    report_path = out_dir / f"{stamp}.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[stress] 报告: {report_path}")
    print(f"[stress] 总体: {'PASS' if overall else 'FAIL'} ({passed}/{len(checks)})")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
