"""G6-S1 独立 metrics token + 测试（api/dashboard.py /metrics 端点）。

覆盖：
- 未配置 CHATGPT2API_METRICS_TOKEN：auth-key 鉴权 200（保持向后兼容）
- 配置后：带 metrics_token 200、带 auth-key 401（token 优先、auth-key 不放行）
- ?token= 查询参数同样按 metrics_token 校验
- 无任何凭据 401
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app

_AUTH_KEY = "chatgpt2api"
_METRICS_TOKEN = "metric-token-abc-123"


def _client() -> TestClient:
    return TestClient(create_app())


def test_metrics_without_token_env_uses_auth_key() -> None:
    """未配置 metrics_token 时，auth-key 仍可访问 /metrics（向后兼容）。"""
    r = _client().get("/metrics", headers={"Authorization": f"Bearer {_AUTH_KEY}"})
    assert r.status_code == 200
    assert "content-type" in r.headers or "Content-Type" in r.headers


def test_metrics_with_token_env_requires_metrics_token(monkeypatch) -> None:
    """配置 metrics_token 后，metrics_token 可访问，auth-key 被拒。"""
    monkeypatch.setenv("CHATGPT2API_METRICS_TOKEN", _METRICS_TOKEN)
    client = _client()
    ok = client.get("/metrics", headers={"Authorization": f"Bearer {_METRICS_TOKEN}"})
    assert ok.status_code == 200
    denied = client.get("/metrics", headers={"Authorization": f"Bearer {_AUTH_KEY}"})
    assert denied.status_code == 401
    no_cred = client.get("/metrics")
    assert no_cred.status_code == 401


def test_metrics_token_query_param(monkeypatch) -> None:
    """?token= 查询参数按 metrics_token 校验。"""
    monkeypatch.setenv("CHATGPT2API_METRICS_TOKEN", _METRICS_TOKEN)
    client = _client()
    ok = client.get(f"/metrics?token={_METRICS_TOKEN}")
    assert ok.status_code == 200
    denied = client.get("/metrics?token={_AUTH_KEY}")
    assert denied.status_code == 401


def test_metrics_token_bad_bearer() -> None:
    """metrics_token 配置后，错误 token 也 401。"""
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    r = client.get("/metrics", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401
