"""性能看板端点测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app

_AUTH = {"Authorization": "Bearer chatgpt2api"}


def _client() -> TestClient:
    return TestClient(create_app())


class TestPerformanceDashboard:
    def test_latency_endpoint_returns_200(self):
        r = _client().get("/api/dashboard/latency", headers=_AUTH)
        assert r.status_code == 200

    def test_latency_contains_required_fields(self):
        r = _client().get("/api/dashboard/latency", headers=_AUTH)
        body = r.json()
        assert "total_requests" in body
        assert "avg_latency_ms" in body
        assert "error_rate" in body
        assert "by_path" in body

    def test_metrics_summary_returns_200(self):
        r = _client().get("/api/dashboard/metrics_summary", headers=_AUTH)
        assert r.status_code == 200

    def test_latency_requires_auth(self):
        r = _client().get("/api/dashboard/latency")
        assert r.status_code == 401
