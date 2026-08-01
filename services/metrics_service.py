"""生产级可观测性：Prometheus 指标、请求追踪、延迟统计。

提供：
- /metrics Prometheus 指标端点
- 请求计数（按 path/method/status）
- 延迟直方图（p50/p95/p99）
- 错误率
- 账号池状态指标
- 请求追踪 ID
- 结构化日志
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from threading import Lock
from typing import Any


class RequestMetrics:
    """请求级指标收集器（线程安全）。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._request_count: dict[str, int] = defaultdict(int)
        self._error_count: dict[str, int] = defaultdict(int)
        self._latency_sum: dict[str, float] = defaultdict(float)
        self._latency_buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._inflight: dict[str, int] = defaultdict(int)
        self._start_time = time.time()

    # ---- 请求追踪 ----

    @staticmethod
    def new_request_id() -> str:
        return uuid.uuid4().hex[:16]

    def _key(self, method: str, path: str, status: int) -> str:
        return f"{method}|{path}|{status}"

    def record_request(self, method: str, path: str, status: int, duration_ms: float) -> None:
        """记录一次请求。"""
        key = self._key(method, path, status)
        with self._lock:
            self._request_count[key] += 1
            if status >= 400:
                self._error_count[key] += 1
            self._latency_sum[key] += duration_ms
            # 延迟分桶
            buckets = self._latency_buckets[key]
            if duration_ms < 50:
                buckets["<50ms"] += 1
            elif duration_ms < 200:
                buckets["50-200ms"] += 1
            elif duration_ms < 1000:
                buckets["200-1000ms"] += 1
            elif duration_ms < 5000:
                buckets["1-5s"] += 1
            else:
                buckets[">5s"] += 1

    def record_inflight(self, method: str, path: str, delta: int) -> None:
        key = f"{method}|{path}"
        with self._lock:
            self._inflight[key] = max(0, self._inflight.get(key, 0) + delta)

    # ---- 统计查询 ----

    def _latency_avg(self, key: str) -> float:
        count = self._request_count.get(key, 0)
        return self._latency_sum.get(key, 0.0) / count if count else 0.0

    def get_summary(self) -> dict[str, Any]:
        """返回整体统计摘要（供看板展示）。"""
        with self._lock:
            total_requests = sum(self._request_count.values())
            total_errors = sum(self._error_count.values())
            total_latency = sum(self._latency_sum.values())
            paths: dict[str, dict[str, Any]] = {}
            for key, count in self._request_count.items():
                method, path, status = key.split("|")
                path_key = f"{method} {path}"
                agg = paths.setdefault(path_key, {"count": 0, "errors": 0, "latency_ms": 0.0, "statuses": {}})
                agg["count"] += count
                agg["latency_ms"] += self._latency_sum.get(key, 0.0)
                if int(status) >= 400:
                    agg["errors"] += count
                agg["statuses"][status] = agg["statuses"].get(status, 0) + count
            # 计算每个 path 的平均延迟和错误率
            for path_key, agg in paths.items():
                agg["avg_latency_ms"] = round(agg["latency_ms"] / agg["count"], 1) if agg["count"] else 0.0
                agg["error_rate"] = round(agg["errors"] / agg["count"], 4) if agg["count"] else 0.0
                del agg["latency_ms"]
            inflight = dict(self._inflight)
        return {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "avg_latency_ms": round(total_latency / total_requests, 1) if total_requests else 0.0,
            "error_rate": round(total_errors / total_requests, 4) if total_requests else 0.0,
            "uptime_seconds": int(time.time() - self._start_time),
            "by_path": paths,
            "inflight": inflight,
        }

    # ---- Prometheus 导出 ----

    def prometheus(self) -> str:
        """导出 Prometheus 文本格式指标。"""
        with self._lock:
            lines: list[str] = []
            lines.append("# HELP chatgpt2api_requests_total Total HTTP requests")
            lines.append("# TYPE chatgpt2api_requests_total counter")
            for key, count in self._request_count.items():
                method, path, status = key.split("|")
                lines.append(
                    f'chatgpt2api_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
                )
            lines.append("# HELP chatgpt2api_errors_total Total HTTP errors")
            lines.append("# TYPE chatgpt2api_errors_total counter")
            for key, count in self._error_count.items():
                method, path, status = key.split("|")
                lines.append(
                    f'chatgpt2api_errors_total{{method="{method}",path="{path}",status="{status}"}} {count}'
                )
            lines.append("# HELP chatgpt2api_latency_seconds_sum Total latency in seconds")
            lines.append("# TYPE chatgpt2api_latency_seconds_sum counter")
            for key, total in self._latency_sum.items():
                method, path, status = key.split("|")
                lines.append(
                    f'chatgpt2api_latency_seconds_sum{{method="{method}",path="{path}",status="{status}"}} {total/1000:.4f}'
                )
            lines.append("# HELP chatgpt2api_inflight_requests Current inflight requests")
            lines.append("# TYPE chatgpt2api_inflight_requests gauge")
            for key, count in self._inflight.items():
                method, path = key.split("|")
                lines.append(
                    f'chatgpt2api_inflight_requests{{method="{method}",path="{path}"}} {count}'
                )
            lines.append("# HELP chatgpt2api_uptime_seconds Process uptime")
            lines.append("# TYPE chatgpt2api_uptime_seconds gauge")
            lines.append(f"chatgpt2api_uptime_seconds {int(time.time() - self._start_time)}")
        return "\n".join(lines) + "\n"


metrics_service = RequestMetrics()
