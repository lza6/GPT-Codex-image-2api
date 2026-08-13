"""免费代理池抓取器单元测试（全 mock，不触网）。

覆盖：
  - parse_ipport_text 裸/带 scheme/坏行/protocol 过滤
  - parse_geonode_json 映射/缺字段丢弃/protocol 过滤
  - parse_source 未知 format
  - FreeProxySource frozen
  - _precheck mock 成功失败
  - _inject 去重 + 超上限剔除 + source=free 注入
  - _fetch_once 单源异常不中断
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from services.free_proxy_fetcher import (
    FreeProxyFetcher,
    FreeProxySource,
    parse_geonode_json,
    parse_ipport_text,
    parse_source,
)
from services.proxy_pool import ProxyPool


class FakeConfig:
    """最小 config provider：get_free_proxy_settings 返回注入的 settings。"""

    def __init__(self, settings: dict) -> None:
        self._settings = settings

    def get_free_proxy_settings(self) -> dict:
        return self._settings


def _settings(**overrides) -> dict:
    base = {
        "enabled": True,
        "refresh_interval_min": 30,
        "max_pool_size": 200,
        "min_healthy": 5,
        "sticky_by_account": True,
        "precheck_url": "https://api.ipify.org",
        "timeout_sec": 10,
        "sources": [],
    }
    base.update(overrides)
    return base


# ====================================================================
# 纯解析函数
# ====================================================================


class TestParseIpportText:
    def test_bare_host_port(self) -> None:
        parsed = parse_ipport_text("1.2.3.4:8080\n5.6.7.8:3128", ("http",))
        assert [p["url"] for p in parsed] == ["http://1.2.3.4:8080", "http://5.6.7.8:3128"]
        assert all(p["source"] == "free" for p in parsed)

    def test_with_scheme_line(self) -> None:
        parsed = parse_ipport_text("http://9.9.9.9:80", ("http",))
        assert parsed and parsed[0]["url"] == "http://9.9.9.9:80"

    def test_bad_lines_dropped(self) -> None:
        parsed = parse_ipport_text("1.2.3.4\n# comment\n\nnot-a-proxy", ("http",))
        assert parsed == []

    def test_protocol_filter(self) -> None:
        text = "1.2.3.4:8080\nsocks5://7.7.7.7:1080\nhttp://8.8.8.8:80"
        parsed = parse_ipport_text(text, ("http",))
        urls = [p["url"] for p in parsed]
        assert "http://1.2.3.4:8080" in urls
        assert "http://8.8.8.8:80" in urls
        assert not any("socks" in u for u in urls)

    def test_dedup(self) -> None:
        parsed = parse_ipport_text("1.2.3.4:8080\n1.2.3.4:8080", ("http",))
        assert len(parsed) == 1


class TestParseGeonodeJson:
    def test_maps_fields(self) -> None:
        payload = '{"data": [{"ip": "1.1.1.1", "port": "80", "protocols": ["http"], "country": "US"}]}'
        parsed = parse_geonode_json(payload, ("http",))
        assert parsed == [{
            "url": "http://1.1.1.1:80", "host": "1.1.1.1", "port": 80,
            "username": "", "password": "", "country": "US", "protocol": "http", "source": "free",
        }]

    def test_missing_fields_dropped(self) -> None:
        payload = '{"data": [{"ip": "1.1.1.1"}, {"port": "80"}, {"ip": "2.2.2.2", "port": "abc"}]}'
        assert parse_geonode_json(payload, ("http",)) == []

    def test_protocol_filter(self) -> None:
        payload = '{"data": [{"ip": "1.1.1.1", "port": "80", "protocols": ["socks5"]}, {"ip": "2.2.2.2", "port": "81", "protocols": ["http", "socks4"]}]}'
        parsed = parse_geonode_json(payload, ("http",))
        assert [p["host"] for p in parsed] == ["2.2.2.2"]

    def test_invalid_json_returns_empty(self) -> None:
        assert parse_geonode_json("not json", ("http",)) == []
        assert parse_geonode_json("", ("http",)) == []

    def test_missing_data_key_returns_empty(self) -> None:
        assert parse_geonode_json('{"total": 0}', ("http",)) == []


class TestParseSource:
    def test_unknown_format_returns_empty(self) -> None:
        src = FreeProxySource(name="x", url="http://x", format="yaml")
        assert parse_source("anything", src) == []

    def test_ipport_dispatch(self) -> None:
        src = FreeProxySource(name="x", url="http://x", format="ipport")
        assert parse_source("1.2.3.4:80", src)[0]["url"] == "http://1.2.3.4:80"

    def test_json_dispatch(self) -> None:
        src = FreeProxySource(name="x", url="http://x", format="json")
        payload = '{"data": [{"ip": "1.1.1.1", "port": "80", "protocols": ["http"]}]}'
        assert parse_source(payload, src)[0]["host"] == "1.1.1.1"


class TestFreeProxySourceFrozen:
    def test_frozen(self) -> None:
        src = FreeProxySource(name="x", url="http://x", format="ipport")
        with pytest.raises(Exception):
            src.name = "y"  # type: ignore[misc] - frozen dataclass 运行时禁止赋值

    def test_defaults(self) -> None:
        src = FreeProxySource(name="x", url="http://x", format="json")
        assert src.protocols == ("http",)
        assert src.enabled is True


# ====================================================================
# FreeProxyFetcher（全 mock）
# ====================================================================


class TestPrecheck:
    def test_precheck_success_returns_ip(self) -> None:
        fetcher = FreeProxyFetcher(config_provider=FakeConfig(_settings()))
        resp = Mock(status_code=200)
        resp.text = "9.9.9.9"
        session = Mock()
        session.get.return_value = resp
        with patch.object(fetcher, "_session", return_value=session):
            ok, ip = fetcher._precheck_and_ip("http://1.2.3.4:80", 10)
        assert ok is True
        assert ip == "9.9.9.9"
        session.get.assert_called_once()

    def test_precheck_failure(self) -> None:
        fetcher = FreeProxyFetcher(config_provider=FakeConfig(_settings()))
        session = Mock()
        session.get.side_effect = ConnectionError("proxy unreachable")
        with patch.object(fetcher, "_session", return_value=session):
            ok, _ip = fetcher._precheck_and_ip("http://1.2.3.4:80", 10)
        assert ok is False

    def test_precheck_empty_url_false(self) -> None:
        fetcher = FreeProxyFetcher(config_provider=FakeConfig(_settings()))
        assert fetcher._precheck("", 10) is False


class TestInject:
    def _fetcher_with_pool(self, max_pool_size=200) -> tuple[FreeProxyFetcher, ProxyPool]:
        pool = ProxyPool()  # persist_path=None，不落盘
        fetcher = FreeProxyFetcher(
            config_provider=FakeConfig(_settings(max_pool_size=max_pool_size)),
            pool=pool,
        )
        return fetcher, pool

    def test_inject_adds_source_free_and_prechecks(self) -> None:
        fetcher, pool = self._fetcher_with_pool()
        with patch.object(fetcher, "_precheck_and_ip", return_value=(True, "9.9.9.9")):
            result = fetcher._inject([
                {"url": "http://1.1.1.1:80", "host": "1.1.1.1", "port": 80, "protocol": "http"},
                {"url": "http://2.2.2.2:80", "host": "2.2.2.2", "port": 80, "protocol": "http"},
            ])
        assert result["injected"] == 2
        assert result["skipped"] == 0
        entries = pool.get_all()
        assert len(entries) == 2
        assert all(e["source"] == "free" for e in entries)
        assert {e["label"] for e in entries} == {"9.9.9.9"}

    def test_inject_precheck_failure_skipped(self) -> None:
        fetcher, pool = self._fetcher_with_pool()
        with patch.object(fetcher, "_precheck_and_ip", return_value=(False, "")):
            result = fetcher._inject([{"url": "http://1.1.1.1:80", "host": "1.1.1.1", "port": 80, "protocol": "http"}])
        assert result["injected"] == 0
        assert result["skipped"] == 1
        assert pool.get_all() == []

    def test_inject_dedup_existing_skipped(self) -> None:
        fetcher, pool = self._fetcher_with_pool()
        pool.add_structured({"url": "http://1.1.1.1:80", "host": "1.1.1.1", "port": 80, "protocol": "http"}, weight=1)
        with patch.object(fetcher, "_precheck_and_ip", return_value=(True, "9.9.9.9")):
            result = fetcher._inject([{"url": "http://1.1.1.1:80", "host": "1.1.1.1", "port": 80, "protocol": "http"}])
        assert result["injected"] == 0
        assert result["skipped"] == 1

    def test_inject_prunes_above_max_pool(self) -> None:
        fetcher, pool = self._fetcher_with_pool(max_pool_size=1)
        with patch.object(fetcher, "_precheck_and_ip", return_value=(True, "9.9.9.9")):
            fetcher._inject([
                {"url": "http://1.1.1.1:80", "host": "1.1.1.1", "port": 80, "protocol": "http"},
                {"url": "http://2.2.2.2:80", "host": "2.2.2.2", "port": 80, "protocol": "http"},
            ])
        assert len(pool.get_all()) == 1  # 超上限剔除到 1 条

    def test_inject_respects_existing_manual_entry(self) -> None:
        fetcher, pool = self._fetcher_with_pool()
        pool.add_structured({"url": "http://9.9.9.9:80", "host": "9.9.9.9", "port": 80, "protocol": "http"}, weight=1)
        with patch.object(fetcher, "_precheck_and_ip", return_value=(True, "9.9.9.9")):
            result = fetcher._inject([{"url": "http://9.9.9.9:80", "host": "9.9.9.9", "port": 80, "protocol": "http"}])
        assert result["injected"] == 0
        assert pool.get_all()[0]["source"] == "import"  # 不覆盖已有条目


class TestFetchOnce:
    def _settings_with_sources(self) -> dict:
        return _settings(sources=[
            {"name": "src-a", "enabled": True, "format": "ipport", "protocols": ["http"], "url": "http://a/"},
            {"name": "src-b", "enabled": True, "format": "json", "protocols": ["http"], "url": "http://b/"},
        ])

    def test_fetch_once_single_source_failure_does_not_abort(self) -> None:
        pool = ProxyPool()
        fetcher = FreeProxyFetcher(config_provider=FakeConfig(self._settings_with_sources()), pool=pool)
        # src-a 抓取抛异常；src-b 成功
        def _fake_fetch(url, timeout):
            if "a" in url:
                raise RuntimeError("boom")
            return '{"data": [{"ip": "1.1.1.1", "port": "80", "protocols": ["http"]}]}'

        with patch.object(fetcher, "_fetch_url", side_effect=_fake_fetch), \
             patch.object(fetcher, "_precheck_and_ip", return_value=(True, "9.9.9.9")):
            stats = fetcher._fetch_once()
        assert stats["fetched"] == 1  # 只有 src-b 成功
        assert stats["sources_ok"] == 1
        assert stats["injected"] == 1
        assert len(pool.get_all()) == 1

    def test_fetch_once_disabled_returns_zeros(self) -> None:
        fetcher = FreeProxyFetcher(config_provider=FakeConfig(_settings(enabled=False, sources=[{"name": "a", "url": "http://a", "format": "ipport"}])))
        assert fetcher._fetch_once() == {"sources_ok": 0, "fetched": 0, "injected": 0, "precheck_passed": 0}

    def test_fetch_once_ignores_disabled_source(self) -> None:
        settings = _settings(sources=[
            {"name": "off", "enabled": False, "format": "ipport", "protocols": ["http"], "url": "http://off/"},
        ])
        fetcher = FreeProxyFetcher(config_provider=FakeConfig(settings), pool=ProxyPool())
        with patch.object(fetcher, "_fetch_url", side_effect=AssertionError("disabled source must not be fetched")):
            stats = fetcher._fetch_once()
        assert stats["fetched"] == 0

    def test_fetch_once_empty_sources(self) -> None:
        fetcher = FreeProxyFetcher(config_provider=FakeConfig(_settings()), pool=ProxyPool())
        assert fetcher._fetch_once()["fetched"] == 0


class TestThreadLifecycle:
    def test_start_stop_idempotent(self) -> None:
        fetcher = FreeProxyFetcher(config_provider=FakeConfig(_settings(enabled=False)))
        fetcher.start()
        fetcher.start()  # 幂等
        assert fetcher._thread is not None
        fetcher.stop()
        assert not fetcher._thread.is_alive()
