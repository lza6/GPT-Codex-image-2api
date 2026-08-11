"""kookeey 每号住宅 IP 构造器 + 多提供商注册表（地基）单元测试。

纯单元不触网。覆盖 v2.9.0 新增且此前欠测的路径：
  - kookeey_proxy_for：粘性 session（同 email 同 IP）、禁用/缺字段/空配置回退、自定义国家/端口/scheme
  - providers 注册表：normalize/is_valid/list/get 的真实语义（注册但未启用的 provider 保留标签）
"""
from __future__ import annotations

import hashlib

import pytest

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
    "proxy_enabled": True,
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

    def test_proxy_enabled_default_false_returns_empty(self, monkeypatch) -> None:
        """proxy_enabled 默认 False，kookeey_proxy_for 返回空串（不用于请求出口）。"""
        cfg = dict(_FULL_CFG)
        cfg["enabled"] = True
        cfg["proxy_enabled"] = False
        _set_kookeey(monkeypatch, cfg)
        assert ps.kookeey_proxy_for("a@x.com") == ""

    def test_proxy_enabled_true_returns_url(self, monkeypatch) -> None:
        """proxy_enabled=True 时正常返回代理 URL。"""
        cfg = dict(_FULL_CFG)
        cfg["enabled"] = True
        cfg["proxy_enabled"] = True
        _set_kookeey(monkeypatch, cfg)
        assert ps.kookeey_proxy_for("a@x.com") != ""

    def test_proxy_enabled_missing_defaults_to_false(self, monkeypatch) -> None:
        """config 中无 proxy_enabled 字段时等价于 False。"""
        cfg = dict(_FULL_CFG)
        cfg["enabled"] = True
        cfg.pop("proxy_enabled", None)
        _set_kookeey(monkeypatch, cfg)
        assert ps.kookeey_proxy_for("a@x.com") == ""


# ---------------------------------------------------------------- providers 注册表（地基）

class TestProvidersRegistry:
    def test_normalize_none_defaults_to_chatgpt(self) -> None:
        assert normalize_provider(None) == "chatgpt"

    def test_normalize_case_insensitive(self) -> None:
        assert normalize_provider("  CHATGPT ") == "chatgpt"

    def test_normalize_unregistered_falls_back_to_default(self) -> None:
        assert normalize_provider("some_unknown") == "chatgpt"

    def test_normalize_registered_provider_preserved(self) -> None:
        # grok 已注册且已启用：标签保留（不丢账号归属）
        assert normalize_provider("grok") == "grok"

    def test_is_valid_provider(self) -> None:
        assert is_valid_provider("chatgpt") is True
        assert is_valid_provider("grok") is True  # Phase 4：grok 已启用
        assert is_valid_provider(None) is False
        assert is_valid_provider("nope") is False

    def test_list_enabled_only_includes_grok(self) -> None:
        assert [p.name for p in list_providers(enabled_only=True)] == ["chatgpt", "grok"]

    def test_list_all_includes_grok(self) -> None:
        providers = {p.name: p for p in list_providers()}
        assert providers["chatgpt"].enabled is True
        assert providers["grok"].enabled is True

    def test_grok_meta_complete(self) -> None:
        """grok 元数据齐全：display_name/models/capabilities。"""
        meta = get_provider("grok")
        assert meta is not None
        assert meta.display_name == "Grok"
        assert len(meta.models) > 0
        assert "grok-3-image" in meta.models
        assert "image" in meta.capabilities

    def test_get_provider_unknown_returns_none(self) -> None:
        assert get_provider("does-not-exist") is None


# ---------------------------------------------------------------- kookeey-egress 端点
@pytest.fixture(scope="module")
def _kookeey_egress_client():
    """模块级缓存 TestClient 避免每次新建 FastAPI 应用。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.proxy_pool as pp
    from api.proxy_pool import create_router

    app = FastAPI()
    app.include_router(create_router())
    return pp, TestClient(app)


class TestKookeeyEgressEndpoint:
    """POST /api/proxies/kookeey-egress：探测账号经 kookeey 粘性代理的真实出口 IP。"""

    @pytest.fixture(autouse=True)
    def _inject_client(self, _kookeey_egress_client):
        self._pp, self._client = _kookeey_egress_client

    def test_missing_email_400(self) -> None:
        from unittest.mock import patch

        with patch.object(self._pp, "require_admin", return_value={"role": "admin"}):
            r = self._client.post("/api/proxies/kookeey-egress", json={})
        assert r.status_code == 400

    def test_kookeey_disabled_returns_enabled_false(self) -> None:
        from unittest.mock import patch

        with patch.object(self._pp, "require_admin", return_value={"role": "admin"}), \
             patch("services.proxy_service.kookeey_proxy_for", return_value=""):
            r = self._client.post("/api/proxies/kookeey-egress", json={"email": "a@x.com"})
        body = r.json()
        assert r.status_code == 200
        assert body["ok"] is False
        assert body["enabled"] is False

    def test_session_extracted_from_proxy_url(self) -> None:
        """粘性 session 应从代理 URL 正确解析出（供前端展示）。"""
        from unittest.mock import MagicMock, patch

        proxy_url = "http://UID-SUSER:SPASS-US-ab12cd34@gate.kookeey.info:1000"
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"ip": "1.2.3.4"}
        fake_session = MagicMock()
        fake_session.get.return_value = fake_resp
        fake_session.__enter__ = lambda s: s
        fake_session.__exit__ = lambda *a: False
        with patch.object(self._pp, "require_admin", return_value={"role": "admin"}), \
             patch("services.proxy_service.kookeey_proxy_for", return_value=proxy_url), \
             patch("curl_cffi.requests.Session", return_value=fake_session):
            r = self._client.post("/api/proxies/kookeey-egress", json={"email": "a@x.com"})
        body = r.json()
        assert body["ok"] is True
        assert body["ip"] == "1.2.3.4"
        assert body["session"] == "ab12cd34"


# ---------------------------------------------------------------- kookeey balance 端点
@pytest.fixture(scope="module")
def _kookeey_balance_client():
    """模块级缓存 TestClient 避免每次新建 FastAPI 应用。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.kookeey as ak
    from api.kookeey import create_router

    app = FastAPI()
    app.include_router(create_router())
    return ak, TestClient(app)


class TestKookeeyBalanceEndpoint:
    """GET /api/kookeey/balance：kookeey 账户余额（分）。"""

    @pytest.fixture(autouse=True)
    def _inject_client(self, _kookeey_balance_client):
        self._ak, self._client = _kookeey_balance_client

    def test_balance_need_config(self) -> None:
        """未配置 developer_token/access_id → need_config。"""
        from unittest.mock import patch

        from services.kookeey_service import KookeeyConfig
        # 全量跑时其它测试的 app lifespan 会把 config.json 的 kookeey 配置灌入共享单例
        # （api/app.py lifespan `kookeey_service.update_config`），导致本测试走「已配置」分支——
        # 显式重置单例配置为空，保证测试自包含、不依赖单例初始态
        with patch.object(self._ak.kookeey_service, "_config", KookeeyConfig()), \
             patch.object(self._ak, "require_admin", return_value={"role": "admin"}):
            r = self._client.get("/api/kookeey/balance")
        body = r.json()
        assert r.status_code == 200
        assert body["ok"] is False
        assert body["need_config"] is True

    def test_balance_configured(self) -> None:
        """已配置 → 返回余额数据。"""
        from unittest.mock import patch

        fake_result = {"ok": True, "balance_cents": 10000, "uncount_cents": 500}
        with patch.object(self._ak, "require_admin", return_value={"role": "admin"}), \
             patch.object(self._ak.kookeey_service, "get_account_balance", return_value=fake_result):
            r = self._client.get("/api/kookeey/balance")
        body = r.json()
        assert r.status_code == 200
        assert body["ok"] is True
        assert body["balance_cents"] == 10000
        assert body["uncount_cents"] == 500


# ---------------------------------------------------------------- 单 IP 使用画像 + 流量接口
class TestKookeeyIpUsageBoard:
    """kookeey 单 IP（按账号 session）使用画像：记录/探测回填/排行榜。"""

    def test_record_and_leaderboard(self) -> None:
        from services.kookeey_service import KookeeyService

        svc = KookeeyService()
        svc.record_ip_usage("a@x.com", True, bytes=500_000)
        svc.record_ip_usage("a@x.com", True, bytes=1_200_000)
        svc.record_ip_usage("a@x.com", False)
        svc.record_ip_usage("b@x.com", True, bytes=300_000)
        board = svc.get_ip_usage_board()
        assert board["used_ip_count"] == 2
        top = board["leaderboard"][0]
        assert top["email"] == "a@x.com"
        assert top["requests"] == 2
        assert top["fail"] == 1
        assert top["session"] == svc._session_for("a@x.com")
        assert top["total_bytes"] == 1_700_000
        assert top["estimated_mb"] == round(1_700_000 / (1024 * 1024), 3)
        # b 号只有 300KB
        b_row = board["leaderboard"][1]
        assert b_row["email"] == "b@x.com"
        assert b_row["total_bytes"] == 300_000
        # 全量合计
        assert board["total_bytes"] == 2_000_000
        assert board["estimated_mb"] == round(2_000_000 / (1024 * 1024), 3)

    def test_update_ip_probe_fills_last_ip(self) -> None:
        from services.kookeey_service import KookeeyService

        svc = KookeeyService()
        svc.update_ip_probe("c@x.com", "9.9.9.9")
        board = svc.get_ip_usage_board()
        row = next(r for r in board["leaderboard"] if r["email"] == "c@x.com")
        assert row["last_ip"] == "9.9.9.9"
        assert row["last_probe_at"] != ""

    def test_empty_email_ignored(self) -> None:
        from services.kookeey_service import KookeeyService

        svc = KookeeyService()
        svc.record_ip_usage("", True)
        svc.update_ip_probe("  ", "1.1.1.1")
        assert svc.get_ip_usage_board()["used_ip_count"] == 0


class TestKookeeyTrafficApi:
    """kookeey 官方开发者 API（流量/余额）：未配置 token 时给 need_config。"""

    def test_traffic_overview_need_config(self) -> None:
        from services.kookeey_service import KookeeyService

        svc = KookeeyService()  # 未配置 developer_token/access_id
        r = svc.get_traffic_overview()
        assert r["ok"] is False
        assert r["need_config"] is True

    def test_account_balance_need_config(self) -> None:
        from services.kookeey_service import KookeeyService

        svc = KookeeyService()
        r = svc.get_account_balance()
        assert r["ok"] is False
        assert r["need_config"] is True

    def test_sign_matches_document_example(self) -> None:
        from services.kookeey_service import _sign

        # 文档口径：HMAC-SHA1(key,'g=1&ts=1609430400') hex → base64
        sig = _sign([("g", "1"), ("ts", "1609430400")], "1234567ABCDEFG")
        assert sig == "YzVkMjQxYjVmNjA2MWExMjAwYWYxMzUxM2I1YTY4YWYyOWIxMzA5NA=="


class TestPerAccountQuota:
    """逐账号额度明细（/api/dashboard/quota 数据源）。"""

    def test_structure(self) -> None:
        from services.usage_forecast import per_account_quota

        q = per_account_quota()
        for key in ("total_remaining", "total_accounts", "unlimited_accounts",
                    "restoring_soon_count", "restoring_soon", "accounts"):
            assert key in q
        assert isinstance(q["accounts"], list)
        assert q["total_accounts"] == len(q["accounts"])
