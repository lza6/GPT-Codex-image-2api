"""阶段 3/5 新增端点测试：熔断状态 + 驱逐失效 token。

不依赖真实上游，用 TestClient + 内存账号池验证契约。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def _client():
    import sys
    sys.path.insert(0, str(ROOT_DIR))
    from fastapi.testclient import TestClient

    from api.app import create_app
    return TestClient(create_app())


def _auth_headers() -> dict[str, str]:
    import os
    key = os.environ.get("CHATGPT2API_AUTH_KEY", "test-auth-key")
    return {"Authorization": f"Bearer {key}"}


class CircuitBreakerEndpointTests(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT_DIR))

    def test_circuit_breakers_requires_auth(self):
        client = _client()
        resp = client.get("/api/dashboard/circuit_breakers")
        self.assertIn(resp.status_code, (401, 403), "未鉴权应拒绝")

    def test_circuit_breakers_reports_open_only(self):
        from services.circuit_breaker import circuit_breaker_registry
        client = _client()
        token = "endpoint-open-token-12345678"
        breaker = circuit_breaker_registry.get(token)
        for _ in range(5):
            breaker.record_failure()
        try:
            resp = client.get("/api/dashboard/circuit_breakers", headers=_auth_headers())
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIn("breakers", body)
            self.assertGreaterEqual(body.get("total_open", 0), 1)
            suffix = token[-8:]
            self.assertIn(suffix, body["breakers"], "open 账号应按 token 末8位上报")
            self.assertEqual(body["breakers"][suffix]["state"], "open")
        finally:
            circuit_breaker_registry.remove(token)


class EvictStaleEndpointTests(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT_DIR))

    def test_evict_stale_requires_admin(self):
        client = _client()
        resp = client.post("/api/accounts/evict_stale")
        self.assertIn(resp.status_code, (401, 403), "未鉴权应拒绝")

    def test_evict_stale_returns_counts(self):
        client = _client()
        resp = client.post("/api/accounts/evict_stale", headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("stale", body)
        self.assertIn("evicted", body)
        self.assertIsInstance(body["stale"], int)
        self.assertIsInstance(body["evicted"], int)


if __name__ == "__main__":
    unittest.main()
