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
        from fastapi.testclient import TestClient

        from api.app import create_app

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
        from services.log_service import LoggedCall, log_service
        from services.metrics_service import get_request_id, set_request_id

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
        """/metrics 带鉴权返回 200 且包含核心指标名（S3 起需鉴权，防公网暴露）。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from fastapi.testclient import TestClient

        from api.app import create_app

        app = create_app()
        client = TestClient(app)
        resp = client.get("/metrics", headers={"Authorization": "Bearer chatgpt2api"})
        self.assertEqual(resp.status_code, 200, "/metrics 带鉴权应返回 200")
        text = resp.text
        for metric in ("http_requests_total", "http_request_duration_seconds", "chatgpt2api_account_pool_size", "chatgpt2api_image_tasks_inflight"):
            self.assertIn(metric, text, f"/metrics 应含指标 {metric}")

    def test_metrics_requires_auth_or_loopback(self):
        """/metrics 要求 auth-key（S3 起强制鉴权），无鉴权访问被拒，防止公网暴露内部状态。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from fastapi.testclient import TestClient

        from api.app import create_app

        app = create_app()
        client = TestClient(app)
        # 无鉴权访问应被拒（401/403）
        resp = client.get("/metrics")
        self.assertIn(resp.status_code, (401, 403), "/metrics 无鉴权应拒绝")


class MetricsSummaryTests(unittest.TestCase):
    """2.4 看板 metrics_summary 聚合接口。"""

    def test_metrics_summary_returns_p95(self):
        """/api/dashboard/metrics_summary 返回请求速率/错误率/P95。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from fastapi.testclient import TestClient

        from api.app import create_app

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


class DashboardStreamCompletenessTests(unittest.TestCase):
    """S6 真实缺口：SSE 应推送完整看板数据（ops/usage/metrics_summary），而非仅 health+latency。

    说明：SSE 是无限流，TestClient 无法增量读取首帧（portal 阻塞）。
    因此直接测试 payload 构建函数 `_build_stream_payload()` 的返回键——
    这是 SSE 每帧数据的唯一来源，断言它等价于断言 SSE 帧内容，且可真正 RED/GREEN。
    """

    @classmethod
    def _payload(cls) -> dict:
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from api.dashboard import _build_stream_payload
        return _build_stream_payload()

    def test_sse_payload_contains_ops(self):
        """SSE 帧应含 ops（CPU/内存/磁盘），供资源卡片实时更新。"""
        payload = self._payload()
        self.assertIn("ops", payload, "SSE payload 应含 ops 键（否则资源卡片只能 30s 轮询更新）")

    def test_sse_payload_contains_usage(self):
        """SSE 帧应含 usage（24h 调用量），供用量卡片实时更新。"""
        payload = self._payload()
        self.assertIn("usage", payload, "SSE payload 应含 usage 键")

    def test_sse_payload_contains_metrics_summary(self):
        """SSE 帧应含 metrics_summary（请求速率/P95），供指标卡片实时更新。"""
        payload = self._payload()
        self.assertIn("metrics_summary", payload, "SSE payload 应含 metrics_summary 键")
        self.assertIn("p95_latency_ms", payload["metrics_summary"], "metrics_summary 应含 p95_latency_ms")


if __name__ == "__main__":
    unittest.main()
