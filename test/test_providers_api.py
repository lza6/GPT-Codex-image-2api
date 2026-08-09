"""/api/providers 端点测试：无认证/授权/列表返回三场景。

纯单元不触网。覆盖：
  - 无 Authorization 头 → 401
  - 无效 Authorization → 401
  - 有效管理员密钥 → 200 + 正确结构
  - 返回列表包含所有已注册提供商（含 disabled grok）
  - 每个 provider 含 name/display_name/enabled/description
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app

_AUTH = {"Authorization": "Bearer chatgpt2api"}


def _client() -> TestClient:
    return TestClient(create_app())


class TestProvidersApi:
    """GET /api/providers 端点三场景。"""

    def test_no_auth_returns_401(self) -> None:
        """无 Authorization 头应返回 401。"""
        client = _client()
        r = client.get("/api/providers")
        assert r.status_code == 401

    def test_invalid_auth_returns_401(self) -> None:
        """无效 Authorization 应返回 401。"""
        client = _client()
        r = client.get("/api/providers", headers={"Authorization": "Bearer bad-token"})
        assert r.status_code == 401

    def test_valid_auth_returns_200(self) -> None:
        """有效管理员密钥应返回 200。"""
        client = _client()
        r = client.get("/api/providers", headers=_AUTH)
        assert r.status_code == 200, r.text

    def test_providers_contain_required_fields(self) -> None:
        """每个 provider 应包含 name/display_name/enabled/description 四个字段。"""
        client = _client()
        r = client.get("/api/providers", headers=_AUTH)
        body = r.json()
        assert "providers" in body
        assert isinstance(body["providers"], list)
        for p in body["providers"]:
            assert "name" in p
            assert "display_name" in p
            assert "enabled" in p
            assert "description" in p

    def test_list_all_includes_disabled_grok(self) -> None:
        """默认返回全部已注册提供商，含 disabled 的 grok。"""
        client = _client()
        r = client.get("/api/providers", headers=_AUTH)
        providers = {p["name"]: p for p in r.json()["providers"]}
        assert "chatgpt" in providers
        assert providers["chatgpt"]["enabled"] is True
        assert "grok" in providers
        assert providers["grok"]["enabled"] is False

    def test_chatgpt_is_first_provider(self) -> None:
        """chatgpt 应为默认首个提供商。"""
        client = _client()
        r = client.get("/api/providers", headers=_AUTH)
        providers = r.json()["providers"]
        assert providers[0]["name"] == "chatgpt"