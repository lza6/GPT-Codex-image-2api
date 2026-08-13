"""统一账号出口代理解析 resolve_account_proxy 单元测试（全 mock，不触网）。

覆盖回退链：kookeey → free_pool(粘性) → 全局代理 → 直连。
"""
from __future__ import annotations

from unittest.mock import patch

import services.proxy_service as ps
from services.proxy_pool import ProxyEntry, ProxyPool


def _free_settings(enabled: bool = True, sticky: bool = True) -> dict:
    return {
        "enabled": enabled,
        "refresh_interval_min": 30,
        "max_pool_size": 200,
        "min_healthy": 5,
        "sticky_by_account": sticky,
        "precheck_url": "https://api.ipify.org",
        "timeout_sec": 10,
        "sources": [],
    }


def _kookeey_cfg(enabled: bool = True, proxy_enabled: bool = True) -> dict:
    return {
        "enabled": enabled,
        "scheme": "http",
        "gate_host": "gate.kookeey.info",
        "gate_port": 1000,
        "user_id": "UID",
        "security_username": "SUSER",
        "security_password": "SPASS",
        "country": "US",
        "proxy_enabled": proxy_enabled,
    }


def _entry(url: str) -> ProxyEntry:
    return ProxyEntry(url=url, host="free1", port=1000, protocol="http", source="free", healthy=True)


class TestResolveAccountProxy:
    def test_kookeey_enabled_has_priority(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: _kookeey_cfg())
        with patch("services.proxy_pool.proxy_pool.select_sticky") as m:
            url = ps.resolve_account_proxy("a@x.com")
        m.assert_not_called()  # kookeey 优先，不碰免费池
        assert "gate.kookeey.info" in url

    def test_kookeey_disabled_skips_to_free_pool(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: _kookeey_cfg(proxy_enabled=False))
        monkeypatch.setattr(ps.config, "get_free_proxy_settings", lambda: _free_settings(enabled=True))
        with patch("services.proxy_pool.proxy_pool.select_sticky", return_value=_entry("http://free1:1000")) as m:
            url = ps.resolve_account_proxy("a@x.com")
        assert url == "http://free1:1000"
        m.assert_called_once_with("a@x.com")

    def test_kookeey_missing_credentials_skips(self, monkeypatch) -> None:
        cfg = _kookeey_cfg()
        cfg.pop("gate_host", None)  # 缺凭据 → kookeey_proxy_for 返回空
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: cfg)
        monkeypatch.setattr(ps.config, "get_free_proxy_settings", lambda: _free_settings(enabled=True))
        with patch("services.proxy_pool.proxy_pool.select_sticky", return_value=_entry("http://free1:1000")):
            url = ps.resolve_account_proxy("a@x.com")
        assert url == "http://free1:1000"

    def test_free_pool_returns_sticky(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {})
        monkeypatch.setattr(ps.config, "get_free_proxy_settings", lambda: _free_settings(enabled=True))
        with patch("services.proxy_pool.proxy_pool.select_sticky", return_value=_entry("http://free1:1000")) as m:
            url = ps.resolve_account_proxy("a@x.com")
        assert url == "http://free1:1000"
        m.assert_called_once_with("a@x.com")

    def test_free_pool_empty_falls_back_to_global(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {})
        monkeypatch.setattr(ps.config, "get_free_proxy_settings", lambda: _free_settings(enabled=True))
        monkeypatch.setattr(ps.config, "get_proxy_settings", lambda: "http://global:8080")
        with patch("services.proxy_pool.proxy_pool.select_sticky", return_value=None):
            url = ps.resolve_account_proxy("a@x.com")
        assert url == "http://global:8080"

    def test_free_disabled_skips_sticky_to_global(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {})
        monkeypatch.setattr(ps.config, "get_free_proxy_settings", lambda: _free_settings(enabled=False))
        monkeypatch.setattr(ps.config, "get_proxy_settings", lambda: "http://global:8080")
        with patch("services.proxy_pool.proxy_pool.select_sticky") as m:
            url = ps.resolve_account_proxy("a@x.com")
        m.assert_not_called()
        assert url == "http://global:8080"

    def test_sticky_by_account_false_skips_free_pool(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {})
        monkeypatch.setattr(ps.config, "get_free_proxy_settings", lambda: _free_settings(enabled=True, sticky=False))
        monkeypatch.setattr(ps.config, "get_proxy_settings", lambda: "http://global:8080")
        with patch("services.proxy_pool.proxy_pool.select_sticky") as m:
            url = ps.resolve_account_proxy("a@x.com")
        m.assert_not_called()
        assert url == "http://global:8080"

    def test_all_empty_returns_direct(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {})
        monkeypatch.setattr(ps.config, "get_free_proxy_settings", lambda: _free_settings(enabled=False))
        monkeypatch.setattr(ps.config, "get_proxy_settings", lambda: "")
        assert ps.resolve_account_proxy("a@x.com") == ""

    def test_sticky_same_key_same_url(self, monkeypatch) -> None:
        """粘性：两次解析同 email 返回同 URL（通过真实 select_sticky 绑定）。"""
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {})
        monkeypatch.setattr(ps.config, "get_free_proxy_settings", lambda: _free_settings(enabled=True))
        pool = ProxyPool()
        pool.add_structured({
            "url": "http://node1:1000", "host": "node1", "port": 1000, "protocol": "http", "source": "free",
        }, weight=1)
        with patch("services.proxy_pool.proxy_pool.select_sticky", side_effect=pool.select_sticky):
            url1 = ps.resolve_account_proxy("a@x.com")
            url2 = ps.resolve_account_proxy("a@x.com")
        assert url1 and url1 == url2

    def test_sticky_persistence_save_load(self, monkeypatch, tmp_path) -> None:
        """粘性持久化：save→load 后同 email 仍解析到同 URL。"""
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {})
        monkeypatch.setattr(ps.config, "get_free_proxy_settings", lambda: _free_settings(enabled=True))
        path = tmp_path / "proxies.json"
        pool = ProxyPool(persist_path=path)
        pool.add_structured({
            "url": "http://node1:1000", "host": "node1", "port": 1000, "protocol": "http", "source": "free",
        }, weight=1)
        with patch("services.proxy_pool.proxy_pool.select_sticky", side_effect=pool.select_sticky):
            url1 = ps.resolve_account_proxy("a@x.com")
        assert url1

        pool2 = ProxyPool(persist_path=path)  # 模拟重启
        with patch("services.proxy_pool.proxy_pool.select_sticky", side_effect=pool2.select_sticky):
            url2 = ps.resolve_account_proxy("a@x.com")
        assert url2 == url1


# ---------------------------------------------------------------- _proxy_is_kookeey


class TestProxyIsKookeey:
    def test_matches_gate_host(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {"gate_host": "gate.kookeey.info"})
        assert ps._proxy_is_kookeey("http://UID-SUSER:SPASS-US-ab12cd34@gate.kookeey.info:1000") is True

    def test_not_kookeey_when_host_differs(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {"gate_host": "gate.kookeey.info"})
        assert ps._proxy_is_kookeey("http://free1:1000") is False

    def test_no_kookeey_config_false(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {})
        assert ps._proxy_is_kookeey("http://anything:1000") is False

    def test_empty_url_false(self, monkeypatch) -> None:
        monkeypatch.setattr(ps.config, "get_kookeey_settings", lambda: {"gate_host": "gate.kookeey.info"})
        assert ps._proxy_is_kookeey("") is False
