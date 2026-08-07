"""kookeey 每号住宅 IP 构造器 + 多提供商注册表（地基）单元测试。

纯单元不触网。覆盖 v2.9.0 新增且此前欠测的路径：
  - kookeey_proxy_for：粘性 session（同 email 同 IP）、禁用/缺字段/空配置回退、自定义国家/端口/scheme
  - providers 注册表：normalize/is_valid/list/get 的真实语义（注册但未启用的 provider 保留标签）
"""
from __future__ import annotations

import hashlib

import services.proxy_service as ps
from services.providers import (
    get_provider,
    is_valid_provider,
    list_providers,
    normalize_provider,
)

_FULL_CFG = {
    "enabled": True,
    "scheme": "http",
    "gate_host": "gate.kookeey.info",
    "gate_port": 1000,
    "user_id": "UID",
    "security_username": "SUSER",
    "security_password": "SPASS",
    "country": "US",
}


def _set_kookeey(monkeypatch, cfg: dict) -> None:
    monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: cfg)


# ---------------------------------------------------------------- kookeey_proxy_for

class TestKookeeyProxyFor:
    def test_sticky_session_same_email_same_ip(self, monkeypatch) -> None:
        _set_kookeey(monkeypatch, dict(_FULL_CFG))
        url1 = ps.kookeey_proxy_for("a@x.com")
        url2 = ps.kookeey_proxy_for("a@x.com")
        url3 = ps.kookeey_proxy_for("b@x.com")
        assert url1 == url2  # 同 email → 同 session → 同住宅 IP
        assert url1 != url3  # 不同 email → 不同 session

    def test_url_format_and_session_derivation(self, monkeypatch) -> None:
        _set_kookeey(monkeypatch, dict(_FULL_CFG))
        url = ps.kookeey_proxy_for("A@x.com")  # 大小写归一
        expected_session = hashlib.md5(b"a@x.com").hexdigest()[:8]
        assert url == f"http://UID-SUSER:SPASS-US-{expected_session}@gate.kookeey.info:1000"

    def test_empty_config_returns_empty(self, monkeypatch) -> None:
        _set_kookeey(monkeypatch, {})
        assert ps.kookeey_proxy_for("a@x.com") == ""

    def test_disabled_returns_empty(self, monkeypatch) -> None:
        cfg = dict(_FULL_CFG)
        cfg["enabled"] = False
        _set_kookeey(monkeypatch, cfg)
        assert ps.kookeey_proxy_for("a@x.com") == ""

    def test_string_enabled_true_accepted(self, monkeypatch) -> None:
        cfg = dict(_FULL_CFG)
        cfg["enabled"] = "true"
        _set_kookeey(monkeypatch, cfg)
        assert ps.kookeey_proxy_for("a@x.com") != ""

    def test_missing_required_field_returns_empty(self, monkeypatch) -> None:
        cfg = dict(_FULL_CFG)
        cfg["security_password"] = ""  # 缺密码
        _set_kookeey(monkeypatch, cfg)
        assert ps.kookeey_proxy_for("a@x.com") == ""

    def test_custom_country_port_scheme(self, monkeypatch) -> None:
        cfg = dict(_FULL_CFG)
        cfg.update({"country": "JP", "gate_port": 2000, "scheme": "socks5"})
        _set_kookeey(monkeypatch, cfg)
        url = ps.kookeey_proxy_for("a@x.com")
        assert url.startswith("socks5://UID-SUSER:SPASS-JP-")
        assert url.endswith("@gate.kookeey.info:2000")

    def test_bad_port_falls_back_to_1000(self, monkeypatch) -> None:
        cfg = dict(_FULL_CFG)
        cfg["gate_port"] = "not-a-number"
        _set_kookeey(monkeypatch, cfg)
        assert ps.kookeey_proxy_for("a@x.com").endswith("@gate.kookeey.info:1000")

    def test_credentials_with_special_chars_url_encoded(self, monkeypatch) -> None:
        cfg = dict(_FULL_CFG)
        cfg["security_password"] = "p@ss:w/rd"  # 含 URL 保留字符 @ : /
        _set_kookeey(monkeypatch, cfg)
        url = ps.kookeey_proxy_for("a@x.com")
        assert "p%40ss%3Aw%2Frd" in url  # 被 percent-encode，代理 URL 不会被 @ : 截断
        assert "p@ss:w/rd" not in url


# ---------------------------------------------------------------- providers 注册表（地基）

class TestProvidersRegistry:
    def test_normalize_none_defaults_to_chatgpt(self) -> None:
        assert normalize_provider(None) == "chatgpt"

    def test_normalize_case_insensitive(self) -> None:
        assert normalize_provider("  CHATGPT ") == "chatgpt"

    def test_normalize_unregistered_falls_back_to_default(self) -> None:
        assert normalize_provider("some_unknown") == "chatgpt"

    def test_normalize_registered_but_disabled_preserved(self) -> None:
        # grok 已注册但 enabled=False：标签保留（不丢账号归属），可用性由 is_valid 拦截
        assert normalize_provider("grok") == "grok"

    def test_is_valid_provider(self) -> None:
        assert is_valid_provider("chatgpt") is True
        assert is_valid_provider("grok") is False  # 已注册但未启用
        assert is_valid_provider(None) is False
        assert is_valid_provider("nope") is False

    def test_list_enabled_only_excludes_grok(self) -> None:
        assert [p.name for p in list_providers(enabled_only=True)] == ["chatgpt"]

    def test_list_all_includes_disabled_grok(self) -> None:
        providers = {p.name: p for p in list_providers()}
        assert providers["chatgpt"].enabled is True
        assert providers["grok"].enabled is False

    def test_get_provider_unknown_returns_none(self) -> None:
        assert get_provider("does-not-exist") is None


# ---------------------------------------------------------------- kookeey-egress 端点
class TestKookeeyEgressEndpoint:
    """POST /api/proxies/kookeey-egress：探测账号经 kookeey 粘性代理的真实出口 IP。"""

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import api.proxy_pool as pp
        from api.proxy_pool import create_router

        app = FastAPI()
        app.include_router(create_router())
        return app, pp, TestClient(app)

    def test_missing_email_400(self) -> None:
        from unittest.mock import patch

        app, pp, client = self._client()
        with patch.object(pp, "require_admin", return_value={"role": "admin"}):
            r = client.post("/api/proxies/kookeey-egress", json={})
        assert r.status_code == 400

    def test_kookeey_disabled_returns_enabled_false(self) -> None:
        from unittest.mock import patch

        app, pp, client = self._client()
        with patch.object(pp, "require_admin", return_value={"role": "admin"}), \
             patch("services.proxy_service.kookeey_proxy_for", return_value=""):
            r = client.post("/api/proxies/kookeey-egress", json={"email": "a@x.com"})
        body = r.json()
        assert r.status_code == 200
        assert body["ok"] is False
        assert body["enabled"] is False

    def test_session_extracted_from_proxy_url(self) -> None:
        """粘性 session 应从代理 URL 正确解析出（供前端展示）。"""
        from unittest.mock import patch, MagicMock

        app, pp, client = self._client()
        proxy_url = "http://UID-SUSER:SPASS-US-ab12cd34@gate.kookeey.info:1000"
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"ip": "1.2.3.4"}
        fake_session = MagicMock()
        fake_session.get.return_value = fake_resp
        fake_session.__enter__ = lambda s: s
        fake_session.__exit__ = lambda *a: False
        with patch.object(pp, "require_admin", return_value={"role": "admin"}), \
             patch("services.proxy_service.kookeey_proxy_for", return_value=proxy_url), \
             patch("curl_cffi.requests.Session", return_value=fake_session):
            r = client.post("/api/proxies/kookeey-egress", json={"email": "a@x.com"})
        body = r.json()
        assert body["ok"] is True
        assert body["ip"] == "1.2.3.4"
        assert body["session"] == "ab12cd34"
