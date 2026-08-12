"""5.2 可观测性：dashboard 端点 latency histogram 测试。

验证 /api/dashboard/* 端点在 metrics_sample_rate > 0 时记录
c2api_dashboard_request_duration_seconds{endpoint}；采样关闭（=0）时
零开销跳过观测调用（mock 验证 + /metrics 直查双保险）。
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from api.app import create_app
from services.prometheus_metrics import c2api_dashboard_request_duration_seconds

_AUTH = {"Authorization": "Bearer chatgpt2api"}


def _client() -> TestClient:
    return TestClient(create_app())


def _sample_value(metric_name: str, labels: dict[str, str]) -> float | None:
    """从默认注册表查找指定指标名 + label 组合的样本值。"""
    output = generate_latest(REGISTRY).decode()
    for family in text_string_to_metric_families(output):
        for sample in family.samples:
            if sample.name == metric_name and sample.labels == labels:
                return sample.value
    return None


def _metrics_contains(metric_prefix: str) -> bool:
    """默认注册表输出中是否含指定指标前缀（含 _count/_sum/_bucket 系列）。"""
    output = generate_latest(REGISTRY).decode()
    for family in text_string_to_metric_families(output):
        for sample in family.samples:
            if sample.name.startswith(metric_prefix):
                return True
    return False


def _clear_dashboard_histogram() -> None:
    """清空 dashboard histogram 样本，避免跨测试 label 残留。"""
    c2api_dashboard_request_duration_seconds._metrics.clear()


def test_dashboard_request_records_histogram(monkeypatch) -> None:
    """采样开启时 dashboard 端点记录 histogram（直查默认注册表）。"""
    monkeypatch.setenv("CHATGPT2API_METRICS_SAMPLE_RATE", "1.0")
    _clear_dashboard_histogram()
    r = _client().get("/api/dashboard/latency", headers=_AUTH)
    assert r.status_code == 200
    assert (
        _sample_value(
            "c2api_dashboard_request_duration_seconds_count",
            {"endpoint": "/api/dashboard/latency"},
        )
        == 1.0
    ), "采样开启时未记录 /api/dashboard/latency 的 histogram count"


def test_metrics_endpoint_exposes_histogram(monkeypatch) -> None:
    """/metrics 端点输出包含 c2api_dashboard_request_duration_seconds。"""
    monkeypatch.setenv("CHATGPT2API_METRICS_SAMPLE_RATE", "1.0")
    _clear_dashboard_histogram()
    client = _client()
    assert client.get("/api/dashboard/ops", headers=_AUTH).status_code == 200
    text = client.get("/metrics", headers=_AUTH).text
    assert "c2api_dashboard_request_duration_seconds" in text
    assert 'endpoint="/api/dashboard/ops"' in text


def test_record_dashboard_request_called_when_sampling_on(monkeypatch) -> None:
    """采样开启时 record_dashboard_request 被调用，且 endpoint label 正确（mock）。"""
    monkeypatch.setenv("CHATGPT2API_METRICS_SAMPLE_RATE", "1.0")
    with patch("services.prometheus_metrics.record_dashboard_request") as mock:
        r = _client().get("/api/dashboard/metrics_summary", headers=_AUTH)
        assert r.status_code == 200
        mock.assert_called_once()
        assert mock.call_args.args[0] == "/api/dashboard/metrics_summary"
        assert mock.call_args.args[1] >= 0.0


def test_no_record_when_sample_rate_zero(monkeypatch) -> None:
    """metrics_sample_rate=0 时不调用 record 且 /metrics 无该指标（零开销）。"""
    monkeypatch.setenv("CHATGPT2API_METRICS_SAMPLE_RATE", "0.0")
    _clear_dashboard_histogram()
    with patch("services.prometheus_metrics.record_dashboard_request") as mock:
        r = _client().get("/api/dashboard/latency", headers=_AUTH)
        assert r.status_code == 200
        mock.assert_not_called()
    assert not _metrics_contains("c2api_dashboard_request_duration_seconds"), \
        "采样关闭时不应出现 dashboard histogram"


def test_record_dashboard_request_manual_observation() -> None:
    """record_dashboard_request 直接观测产生 count/sum 样本（复用既有 histogram 工具）。"""
    _clear_dashboard_histogram()
    from services.prometheus_metrics import record_dashboard_request

    record_dashboard_request("/api/dashboard/overview", 0.42)
    assert (
        _sample_value(
            "c2api_dashboard_request_duration_seconds_count",
            {"endpoint": "/api/dashboard/overview"},
        )
        == 1.0
    )
    assert (
        _sample_value(
            "c2api_dashboard_request_duration_seconds_sum",
            {"endpoint": "/api/dashboard/overview"},
        )
        == 0.42
    )
