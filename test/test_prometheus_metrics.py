"""Prometheus 新指标测试（任务 2）。

测试 7 个新增指标的各 record_* 函数，直接解析 generate_latest 输出验证。
"""

from __future__ import annotations

from prometheus_client import REGISTRY, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from services.prometheus_metrics import (
    c2api_accounts_total,
    c2api_circuit_breaker_state,
    c2api_image_tasks_total,
    c2api_quota_remaining,
    c2api_session_pool_size,
    c2api_token_requests_total,
    c2api_upstream_latency_seconds,
    chatgpt2api_scheduler_mode_switch_total,
    chatgpt2api_scheduler_pick_total,
    record_accounts_count,
    record_circuit_breaker_state,
    record_image_task,
    record_quota_remaining,
    record_scheduler_mode_switch,
    record_scheduler_pick,
    record_token_request,
    record_upstream_latency,
    update_session_pool_size,
)


def _get_sample(metric_name: str, labels: dict[str, str]) -> float | None:
    """从 generate_latest 输出中查找指定指标 label 组合的样本值。"""
    output = generate_latest(REGISTRY).decode()
    for family in text_string_to_metric_families(output):
        for sample in family.samples:
            if sample.name == metric_name and sample.labels == labels:
                return sample.value
    return None


def _clear_registry() -> None:
    """清理指标样本，避免跨测试 label 残留。"""
    for metric in (c2api_accounts_total, c2api_token_requests_total, c2api_session_pool_size,
                   c2api_circuit_breaker_state, c2api_image_tasks_total, c2api_quota_remaining,
                   c2api_upstream_latency_seconds, chatgpt2api_scheduler_pick_total,
                   chatgpt2api_scheduler_mode_switch_total):
        metric._metrics.clear()


def test_record_accounts_count() -> None:
    _clear_registry()
    record_accounts_count("openai", "active", 10)
    record_accounts_count("openai", "limited", 3)
    record_accounts_count("azure", "active", 5)
    assert _get_sample("c2api_accounts_total", {"provider": "openai", "status": "active"}) == 10.0
    assert _get_sample("c2api_accounts_total", {"provider": "openai", "status": "limited"}) == 3.0
    assert _get_sample("c2api_accounts_total", {"provider": "azure", "status": "active"}) == 5.0


def test_record_token_request() -> None:
    _clear_registry()
    record_token_request("openai", "success")
    record_token_request("openai", "success")
    record_token_request("openai", "rate_limited")
    record_token_request("azure", "success")
    assert _get_sample("c2api_token_requests_total", {"provider": "openai", "result": "success"}) == 2.0
    assert _get_sample("c2api_token_requests_total", {"provider": "openai", "result": "rate_limited"}) == 1.0
    assert _get_sample("c2api_token_requests_total", {"provider": "azure", "result": "success"}) == 1.0


def test_update_session_pool_size() -> None:
    _clear_registry()
    update_session_pool_size("openai", 25)
    update_session_pool_size("azure", 10)
    assert _get_sample("c2api_session_pool_size", {"provider": "openai"}) == 25.0
    assert _get_sample("c2api_session_pool_size", {"provider": "azure"}) == 10.0


def test_record_circuit_breaker_state() -> None:
    _clear_registry()
    record_circuit_breaker_state("openai", "chat-completions", 0)
    record_circuit_breaker_state("openai", "image-gen", 1)
    record_circuit_breaker_state("azure", "chat-completions", 2)
    assert _get_sample("c2api_circuit_breaker_state", {"provider": "openai", "name": "chat-completions"}) == 0.0
    assert _get_sample("c2api_circuit_breaker_state", {"provider": "openai", "name": "image-gen"}) == 1.0
    assert _get_sample("c2api_circuit_breaker_state", {"provider": "azure", "name": "chat-completions"}) == 2.0


def test_record_image_task() -> None:
    _clear_registry()
    record_image_task("generation", "success")
    record_image_task("generation", "success")
    record_image_task("generation", "failed")
    record_image_task("edit", "success")
    assert _get_sample("c2api_image_tasks_total", {"type": "generation", "status": "success"}) == 2.0
    assert _get_sample("c2api_image_tasks_total", {"type": "generation", "status": "failed"}) == 1.0
    assert _get_sample("c2api_image_tasks_total", {"type": "edit", "status": "success"}) == 1.0


def test_record_quota_remaining() -> None:
    _clear_registry()
    record_quota_remaining("account-a", 100.5)
    record_quota_remaining("account-b", 0.0)
    assert _get_sample("c2api_quota_remaining", {"account": "account-a"}) == 100.5
    assert _get_sample("c2api_quota_remaining", {"account": "account-b"}) == 0.0


def test_record_upstream_latency() -> None:
    _clear_registry()
    record_upstream_latency("openai", "chat/completions", 1.5)
    record_upstream_latency("openai", "chat/completions", 2.3)
    record_upstream_latency("azure", "images/generations", 4.0)
    # Histogram: 验证 +Inf bucket 计数包含所有观测值
    assert _get_sample("c2api_upstream_latency_seconds_count", {"provider": "openai", "endpoint": "chat/completions"}) == 2.0
    assert _get_sample("c2api_upstream_latency_seconds_count", {"provider": "azure", "endpoint": "images/generations"}) == 1.0


def test_record_scheduler_pick_with_mode() -> None:
    """III-02：调度选取指标带 mode 标签（A/B 对比命中分布）。"""
    _clear_registry()
    record_scheduler_pick("healthy", "round_robin")
    record_scheduler_pick("healthy", "weighted_random")
    record_scheduler_pick("healthy", "weighted_random")
    record_scheduler_pick("warm", "weighted_random")
    assert _get_sample("chatgpt2api_scheduler_pick_total", {"tier": "healthy", "mode": "round_robin"}) == 1.0
    assert _get_sample("chatgpt2api_scheduler_pick_total", {"tier": "healthy", "mode": "weighted_random"}) == 2.0
    assert _get_sample("chatgpt2api_scheduler_pick_total", {"tier": "warm", "mode": "weighted_random"}) == 1.0


def test_record_scheduler_mode_switch() -> None:
    """III-02：自适应调度模式切换指标（from_mode -> to_mode）。"""
    _clear_registry()
    record_scheduler_mode_switch("weighted_random", "least_load")
    record_scheduler_mode_switch("weighted_random", "least_load")
    record_scheduler_mode_switch("least_load", "predictive")
    assert _get_sample("chatgpt2api_scheduler_mode_switch_total", {"from_mode": "weighted_random", "to_mode": "least_load"}) == 2.0
    assert _get_sample("chatgpt2api_scheduler_mode_switch_total", {"from_mode": "least_load", "to_mode": "predictive"}) == 1.0