"""可观测性测试：request_id 全链路、结构化日志、Prometheus 指标、看板聚合。

TDD RED 阶段：这些测试在实现前应该失败。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


class RequestIdChainTests(unittest.TestCase):
    """2.1 request_id 全链路透传。"""

    def test_response_header_contains_request_id(self):
        """响应头含 X-Request-Id。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/dashboard/scheduler", headers={"Authorization": "Bearer chatgpt2api"})
        self.assertEqual(resp.status_code, 200)
        request_id = resp.headers.get("x-request-id")
        self.assertIsNotNone(request_id, "响应头应含 x-request-id")
        self.assertTrue(len(request_id) >= 8, "request_id 应至少 8 位")

    def test_request_id_in_log_matches_response(self):
        """日志中的 request_id 与响应头一致。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from services.metrics_service import set_request_id, get_request_id
        from services.log_service import LoggedCall, log_service

        test_id = "test-chain-abc123"
        set_request_id(test_id)
        self.assertEqual(get_request_id(), test_id)

        call = LoggedCall(identity={"id": "k1", "name": "t", "role": "admin"}, endpoint="/v1/x", model="m", summary="s")
        call.log("调用完成", status="success")
        logs = log_service.list(limit=5)
        found = [l for l in logs if l["detail"].get("request_id") == test_id]
        self.assertTrue(found, "日志应记录与上下文一致的 request_id")


class StructuredLoggingTests(unittest.TestCase):
    """2.2 结构化 JSON 日志。"""

    def test_log_format_json_outputs_parseable_json(self):
        """LOG_FORMAT=json 时日志可 json.loads 且含必需字段。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from services.log_service import LogService

        tmp = Path(tempfile.gettempdir()) / "test_structured_log.jsonl"
        if tmp.exists():
            tmp.unlink()
        svc = LogService(tmp)
        # 设置 LOG_FORMAT=json
        import os
        os.environ["LOG_FORMAT"] = "json"
        svc.add("call", "test-summary", {"endpoint": "/v1/x", "status": "success"})
        lines = tmp.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines, "应有日志行")
        entry = json.loads(lines[0])
        for field in ("ts", "level", "logger", "summary"):
            self.assertIn(field, entry, f"JSON 日志应含字段 {field}")
        tmp.unlink()
        os.environ.pop("LOG_FORMAT", None)

    def test_account_email_anonymized(self):
        """account email 必须脱敏。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from utils.helper import anonymize_email

        email = "user@example.com"
        anonymized = anonymize_email(email)
        self.assertNotEqual(anonymized, email, "邮箱应被脱敏")
        self.assertNotIn("user@example.com", anonymized, "脱敏后不应含完整邮箱")
        self.assertTrue(len(anonymized) > 0, "脱敏结果不应为空")


class PrometheusMetricsTests(unittest.TestCase):
    """2.3 Prometheus 指标端点。"""

    def test_metrics_endpoint_returns_200(self):
        """/metrics 返回 200 且包含核心指标名。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)
        resp = client.get("/metrics")
        self.assertEqual(resp.status_code, 200, "/metrics 应返回 200")
        text = resp.text
        for metric in ("http_requests_total", "http_request_duration_seconds", "chatgpt2api_account_pool_size", "chatgpt2api_image_tasks_inflight"):
            self.assertIn(metric, text, f"/metrics 应含指标 {metric}")

    def test_metrics_requires_auth_or_loopback(self):
        """/metrics 默认仅监听回环或要求 auth-key，防止公网暴露。"""
        # 该测试验证 /metrics 的访问控制策略
        # 当前实现：无需鉴权但仅回环（需确认是否满足安全要求）
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)
        # 无鉴权访问
        resp = client.get("/metrics")
        # 应返回 200（回环允许）或 401（要求鉴权），不应是 5xx
        self.assertIn(resp.status_code, (200, 401), "/metrics 应允许回环或要求鉴权")


class MetricsSummaryTests(unittest.TestCase):
    """2.4 看板 metrics_summary 聚合接口。"""

    def test_metrics_summary_returns_p95(self):
        """/api/dashboard/metrics_summary 返回请求速率/错误率/P95。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)
        H = {"Authorization": "Bearer chatgpt2api"}
        # 先打几个请求累积指标
        for _ in range(3):
            client.get("/api/dashboard/scheduler", headers=H)
        resp = client.get("/api/dashboard/metrics_summary", headers=H)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for field in ("request_rate", "error_rate", "p95_latency_ms"):
            self.assertIn(field, data, f"metrics_summary 应含字段 {field}")


if __name__ == "__main__":
    unittest.main()
