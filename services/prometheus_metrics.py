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
import re
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

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

chatgpt2api_backup_failures_total = Counter(
    "chatgpt2api_backup_failures_total",
    "Total backup failures",
)

chatgpt2api_audit_actions_total = Counter(
    "chatgpt2api_audit_actions_total",
    "Admin audit actions by action and result",
    ["action", "result"],
)

chatgpt2api_circuit_breaker_transitions = Counter(
    "chatgpt2api_circuit_breaker_transitions",
    "Circuit breaker state transitions",
    ["from_state", "to_state"],
)

chatgpt2api_scheduler_pick_total = Counter(
    "chatgpt2api_scheduler_pick_total",
    "Scheduler picks by health tier and scheduler mode",
    ["tier", "mode"],
)

chatgpt2api_scheduler_mode_switch_total = Counter(
    "chatgpt2api_scheduler_mode_switch_total",
    "Adaptive scheduler mode switch count",
    ["from_mode", "to_mode"],
)

chatgpt2api_lifetime_risk = Gauge(
    "chatgpt2api_lifetime_risk",
    "Account lifetime risk level distribution",
    ["risk"],
)

# ---- 任务 2：新增 7 个指标（Provider 调度 / 配额 / 熔断 / 图片 / 会话池 / 上游延迟） ----

c2api_accounts_total = Gauge(
    "c2api_accounts_total",
    "Account count by provider and status",
    ["provider", "status"],
)

c2api_token_requests_total = Counter(
    "c2api_token_requests_total",
    "Token request count by provider and result",
    ["provider", "result"],
)

c2api_session_pool_size = Gauge(
    "c2api_session_pool_size",
    "Session pool size by provider",
    ["provider"],
)

c2api_circuit_breaker_state = Gauge(
    "c2api_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=half_open, 2=open)",
    ["provider", "name"],
)

c2api_image_tasks_total = Counter(
    "c2api_image_tasks_total",
    "Image task count by type and status",
    ["type", "status"],
)

c2api_quota_remaining = Gauge(
    "c2api_quota_remaining",
    "Account quota remaining",
    ["account"],
)

c2api_upstream_latency_seconds = Histogram(
    "c2api_upstream_latency_seconds",
    "Upstream latency by provider and endpoint",
    ["provider", "endpoint"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

# ---- III-04：存储操作延迟（慢查询基准化） ----
# 覆盖账号/密钥存储后端的 load/save/health_check 关键查询，
# 用于把「慢查询猎杀」报告的热点从静态审计推进到可观测基准化
# （Prometheus 直方图可看 P50/P95/P99，跨版本对比延迟漂移）。
c2api_storage_operation_duration_seconds = Histogram(
    "c2api_storage_operation_duration_seconds",
    "Storage backend operation duration in seconds",
    ["backend", "operation"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)


@contextmanager
def storage_operation_timer(backend: str, operation: str) -> Iterator[None]:
    """记录存储后端操作耗时的上下文管理器。

    用法：with storage_operation_timer("json", "save_accounts"): ...
    backend: json / database；operation: load_accounts / save_accounts /
    load_auth_keys / save_auth_keys / health_check。
    """
    start = perf_counter()
    try:
        yield
    finally:
        c2api_storage_operation_duration_seconds.labels(
            backend=backend,
            operation=operation,
        ).observe(perf_counter() - start)


def record_storage_operation(backend: str, operation: str, duration_seconds: float) -> None:
    """记录存储后端操作耗时（供非 context manager 场景手动埋点）。"""
    c2api_storage_operation_duration_seconds.labels(
        backend=backend,
        operation=operation,
    ).observe(duration_seconds)


# ---- 5.2：dashboard 端点请求延迟（可观测性升级） ----
# 按 endpoint label 区分看板各端点，观察 P50/P95/P99 定位慢接口。
c2api_dashboard_request_duration_seconds = Histogram(
    "c2api_dashboard_request_duration_seconds",
    "Dashboard endpoint request duration in seconds",
    ["endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)


def record_dashboard_request(endpoint: str, duration_seconds: float) -> None:
    """记录看板端点请求耗时（endpoint 为完整路由路径，如 /api/dashboard/overview）。"""
    c2api_dashboard_request_duration_seconds.labels(endpoint=endpoint).observe(duration_seconds)


_PATH_CARDINALITY_PATTERNS = (
    # 数字 ID → {id}（如 /api/accounts/refresh/progress/12345）
    (re.compile(r"/\d{5,}"), "/{id}"),
    # UUID 或 16-32 位 hex → {id}
    (re.compile(r"/[0-9a-f]{16,32}"), "/{id}"),
    (re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "/{id}"),
    # 长随机串（sha256-like）→ {id}
    (re.compile(r"/[A-Za-z0-9_-]{24,}"), "/{id}"),
)


def _normalize_path(path: str) -> str:
    """归一化动态路径，减少 Prometheus label 基数膨胀。

    将 /api/accounts/refresh/progress/12345 等动态路径归一化为
    /api/accounts/refresh/progress/{id}，避免每个唯一 ID 产生新 label 组合。
    """
    for pattern, replacement in _PATH_CARDINALITY_PATTERNS:
        path = pattern.sub(replacement, path)
    return path


def record_http_request(path: str, method: str, status: int, duration_seconds: float) -> None:
    """记录 HTTP 请求指标（path 自动归一化，防高基数 label 膨胀）。"""
    path = _normalize_path(path)
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


def record_circuit_breaker_transition(from_state: str, to_state: str) -> None:
    """记录熔断状态机转移。"""
    chatgpt2api_circuit_breaker_transitions.labels(from_state=from_state, to_state=to_state).inc()


def record_scheduler_pick(tier: str, mode: str) -> None:
    """记录调度选取分布（tier + 调度模式）。

    mode 为当前生效调度模式（自适应开启时为 adaptive_scheduler.current_mode，
    否则为 config.scheduler_mode），用于看板 A/B 对比各模式命中分布。
    """
    chatgpt2api_scheduler_pick_total.labels(tier=tier, mode=mode).inc()


def record_scheduler_mode_switch(from_mode: str, to_mode: str) -> None:
    """记录自适应调度模式切换（A/B 可观测：谁切到谁）。"""
    chatgpt2api_scheduler_mode_switch_total.labels(from_mode=from_mode, to_mode=to_mode).inc()


def update_lifetime_risk(risk_distribution: dict[str, int]) -> None:
    """更新寿命预测档位分布。"""
    for risk, count in risk_distribution.items():
        chatgpt2api_lifetime_risk.labels(risk=risk).set(count)


def _normalize_audit_action(action: str) -> str:
    """审计指标 action 归一化：把动态路径段（数字/UUID/长随机串）收敛为 {id}。

    动态端点（/api/accounts/refresh/progress/{id}、/api/images/download/{path} 等）
    若直接作为 Prometheus label，每个唯一路径都会产生新 label 组合，长期运行
    会无限膨胀（红队审查 R1）。归一化后 label 基数 = 路由模板数，可控。
    审计文件仍保留真实 path（精确可追溯），仅指标 label 归一化。
    """
    import re

    segments = str(action).split("/")
    normalized: list[str] = []
    for seg in segments:
        if not seg:
            normalized.append(seg)
            continue
        # UUID 或长数字/随机 id → {id}
        if re.fullmatch(r"[0-9a-f]{8,32}", seg) or seg.isdigit():
            normalized.append("{id}")
        else:
            normalized.append(seg)
    return "/".join(normalized)


def record_audit_action(action: str, result: str) -> None:
    """记录管理动作审计指标（3.2）。label 用归一化路由模板，防动态路径膨胀。"""
    chatgpt2api_audit_actions_total.labels(action=_normalize_audit_action(action), result=result).inc()


def record_image_task_completed() -> None:
    """记录图片任务完成，递减在途计数。"""
    chatgpt2api_image_tasks_inflight.dec()


# ---- 任务 2：record_* 函数（对应 7 个新指标） ----


def record_accounts_count(provider: str, status: str, count: int) -> None:
    """记录账号数量（按 provider 和 status）。"""
    c2api_accounts_total.labels(provider=provider, status=status).set(count)


def record_token_request(provider: str, result: str) -> None:
    """记录 Token 请求计数（按 provider 和 result）。"""
    c2api_token_requests_total.labels(provider=provider, result=result).inc()


def update_session_pool_size(provider: str, size: int) -> None:
    """更新会话池大小（按 provider）。"""
    c2api_session_pool_size.labels(provider=provider).set(size)


def record_circuit_breaker_state(provider: str, name: str, state: int) -> None:
    """记录熔断器状态（0=closed, 1=half_open, 2=open）。"""
    c2api_circuit_breaker_state.labels(provider=provider, name=name).set(state)


def record_image_task(type: str, status: str) -> None:
    """记录图片任务计数（按 type 和 status）。"""
    c2api_image_tasks_total.labels(type=type, status=status).inc()


def record_quota_remaining(account: str, quota: float) -> None:
    """记录账号配额剩余。"""
    c2api_quota_remaining.labels(account=account).set(quota)


def record_upstream_latency(provider: str, endpoint: str, duration_seconds: float) -> None:
    """记录上游请求延迟（按 provider 和 endpoint）。"""
    c2api_upstream_latency_seconds.labels(provider=provider, endpoint=endpoint).observe(duration_seconds)


def generate_metrics() -> tuple[bytes, str]:
    """生成 Prometheus 指标文本。"""
    registry = _create_registry()
    return generate_latest(registry), CONTENT_TYPE_LATEST
