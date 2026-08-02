"""Prometheus 指标（prometheus-client 库）。

支持多 Worker：用 prometheus_client 的 multiprocess 模式。
核心指标：
- http_requests_total{path,method,status}
- http_request_duration_seconds{path} (histogram)
- chatgpt2api_account_pool_size{tier}
- chatgpt2api_upstream_requests_total{model,result}
- chatgpt2api_upstream_duration_seconds{model}
- chatgpt2api_image_tasks_inflight
"""

from __future__ import annotations

import os
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

# 多 Worker 支持：prometheus_client 需要 PROMETHEUS_MULTIPROC_DIR 环境变量
_MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR", "")


def _create_registry() -> CollectorRegistry:
    """创建指标注册表。

    多 Worker 模式：用 multiprocess 从共享目录聚合所有 worker 指标。
    单进程模式：用默认注册表（指标注册在这里）。
    """
    if _MULTIPROC_DIR:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return registry
    # 单进程：返回默认注册表（指标都注册在这里）
    from prometheus_client import REGISTRY
    return REGISTRY


# 核心指标定义（使用默认注册表，prometheus_client 自动处理多进程聚合）
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["path", "method", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

chatgpt2api_account_pool_size = Gauge(
    "chatgpt2api_account_pool_size",
    "Account pool size by health tier",
    ["tier"],
)

chatgpt2api_upstream_requests_total = Counter(
    "chatgpt2api_upstream_requests_total",
    "Total upstream requests",
    ["model", "result"],
)

chatgpt2api_upstream_duration_seconds = Histogram(
    "chatgpt2api_upstream_duration_seconds",
    "Upstream request duration in seconds",
    ["model"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)

chatgpt2api_image_tasks_inflight = Gauge(
    "chatgpt2api_image_tasks_inflight",
    "Current image tasks inflight",
)


def record_http_request(path: str, method: str, status: int, duration_seconds: float) -> None:
    """记录 HTTP 请求指标。"""
    http_requests_total.labels(path=path, method=method, status=str(status)).inc()
    http_request_duration_seconds.labels(path=path).observe(duration_seconds)


def record_upstream_request(model: str, result: str, duration_seconds: float) -> None:
    """记录上游请求指标。"""
    chatgpt2api_upstream_requests_total.labels(model=model, result=result).inc()
    chatgpt2api_upstream_duration_seconds.labels(model=model).observe(duration_seconds)


def update_account_pool_size(tiers: dict[str, int]) -> None:
    """更新账号池健康档位数量。"""
    for tier, count in tiers.items():
        chatgpt2api_account_pool_size.labels(tier=tier).set(count)


def update_image_tasks_inflight(count: int) -> None:
    """更新在途图片任务数。"""
    chatgpt2api_image_tasks_inflight.set(count)


def generate_metrics() -> tuple[bytes, str]:
    """生成 Prometheus 指标文本。"""
    registry = _create_registry()
    return generate_latest(registry), CONTENT_TYPE_LATEST
