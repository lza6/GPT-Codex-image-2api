"""日志 API 路由测试（任务 3）。

测试 /api/logs/aggregate、/api/logs/export、/api/logs/slow-queries 三个端点。
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app

client = TestClient(create_app())
AUTH_HEADER = {"Authorization": "Bearer chatgpt2api"}


def test_aggregate_logs() -> None:
    mock_result = [{"type": "call", "count": 10}, {"type": "account", "count": 5}]
    with patch("api.logs.log_service.multi_dimension_aggregate", return_value=mock_result):
        resp = client.get("/api/logs/aggregate?group_by=type&period=day", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["type"] == "call"
    assert data[0]["count"] == 10


def test_aggregate_logs_unauthorized() -> None:
    resp = client.get("/api/logs/aggregate")
    assert resp.status_code == 401


def test_aggregate_logs_with_dates() -> None:
    mock_result = [{"type": "call", "count": 3}]
    with patch("api.logs.log_service.multi_dimension_aggregate", return_value=mock_result) as mock:
        resp = client.get(
            "/api/logs/aggregate?group_by=type&period=day&start_date=2026-01-01&end_date=2026-01-31",
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 200
    # 验证 filter 传参正确
    _, kwargs = mock.call_args
    assert kwargs["period"] == "day"
    assert kwargs["group_by"] == ["type"]


def test_export_logs_csv() -> None:
    mock_csv = "id,time,type,summary\nabc,2026-01-01,call,test\n"
    with patch("api.logs.log_service.export_csv_paginated", return_value=mock_csv):
        resp = client.get("/api/logs/export?format=csv&page=1&page_size=100", headers=AUTH_HEADER)
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/json") or resp.text == mock_csv


def test_export_logs_json() -> None:
    mock_json = [{"id": "abc", "type": "call", "time": "2026-01-01"}]
    with patch("api.logs.log_service.export_json", return_value=mock_json):
        resp = client.get("/api/logs/export?format=json&page=1&page_size=10", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == "abc"


def test_export_logs_with_fields() -> None:
    mock_json = [{"id": "abc", "type": "call"}]
    with patch("api.logs.log_service.export_json", return_value=mock_json) as mock:
        resp = client.get(
            "/api/logs/export?format=json&fields=id,type&page=1&page_size=10",
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 200
    _, kwargs = mock.call_args
    assert kwargs["fields"] == ["id", "type"]


def test_export_logs_unauthorized() -> None:
    resp = client.get("/api/logs/export?format=csv")
    assert resp.status_code == 401


def test_slow_queries() -> None:
    mock_items = [
        {"name": "GET /v1/chat/completions", "trace_id": "abc", "duration_ms": 15000.0, "status": "slow"},
    ]
    with patch("api.logs.log_service.list_slow_queries", return_value=mock_items):
        resp = client.get("/api/logs/slow-queries?threshold_ms=5000", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "GET /v1/chat/completions"


def test_slow_queries_with_date_range() -> None:
    mock_items: list[dict] = []
    with patch("api.logs.log_service.list_slow_queries", return_value=mock_items) as mock:
        resp = client.get(
            "/api/logs/slow-queries?start_date=2026-01-01&end_date=2026-01-31&threshold_ms=3000",
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 200
    _, kwargs = mock.call_args
    assert kwargs["threshold_ms"] == 3000


def test_slow_queries_unauthorized() -> None:
    resp = client.get("/api/logs/slow-queries")
    assert resp.status_code == 401


def test_slow_queries_invalid_threshold() -> None:
    resp = client.get("/api/logs/slow-queries?threshold_ms=50", headers=AUTH_HEADER)
    assert resp.status_code == 422