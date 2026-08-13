"""Grok 注册子模块单元测试（不触网、不依赖活服务）。

覆盖：
- 邮箱池解析/acquire/release/consume
- grok 验证码正则提取
- GrokRegistrationConfig 默认值与类型钳制
- coordinator 在 enabled=false 时拒绝注册
- gRPC 消息编码
- 代理组解析（空/未知 id 返回直连）
- device_mint 缺 patchright 依赖时安全降级返回 None
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.registration.config import GrokRegistrationConfig, get_registration_config
from services.registration.email_pool import EmailPool, parse_pool_line
from services.registration.grok.device_mint import sso_to_device
from services.registration.grok.email_service import extract_grok_code
from services.registration.grok.engine import (
    _encode_grpc_message,
    _encode_grpc_message_verify,
    resolve_proxy_for_group,
)


class EmailPoolTests(unittest.TestCase):
    def test_parse_valid_line(self) -> None:
        entry = parse_pool_line("a@b.com----pw----cid----rt")
        self.assertEqual(entry, {"email": "a@b.com", "password": "pw", "client_id": "cid", "refresh_token": "rt"})

    def test_parse_invalid_line(self) -> None:
        self.assertIsNone(parse_pool_line("no-at-sign----pw"))
        self.assertIsNone(parse_pool_line(""))
        self.assertIsNone(parse_pool_line(None))

    def test_acquire_release_consume(self) -> None:
        pool = EmailPool()
        pool.reload(["a@b.com----pw----cid----rt", "x@y.com----p2----c2----r2"])
        self.assertEqual(pool.count(), 2)
        first = pool.acquire()
        self.assertIsNotNone(first)
        # busy 后同条目不能再 acquire
        second = pool.acquire()
        self.assertEqual(second["email"], "x@y.com")
        self.assertIsNone(pool.acquire())
        # release 归还后可再取
        pool.release(first["email"])
        again = pool.acquire()
        self.assertEqual(again["email"], first["email"])
        # consume 后永久移除
        pool.consume(again["email"])
        self.assertEqual(pool.count(), 1)
        self.assertIsNone(pool.acquire())

    def test_reload_filters_consumed(self) -> None:
        pool = EmailPool()
        pool.reload(["a@b.com----pw----c----r"])
        entry = pool.acquire()
        pool.consume(entry["email"])
        # 重载后已消耗的邮箱不再出现
        pool.reload(["a@b.com----pw----c----r", "x@y.com----p----c----r"])
        self.assertEqual(pool.count(), 1)
        self.assertEqual(pool.acquire()["email"], "x@y.com")


class GrokCodeTests(unittest.TestCase):
    def test_extract_code(self) -> None:
        self.assertEqual(extract_grok_code("SZ0-0SW xAI confirmation code"), "SZ00SW")
        self.assertEqual(extract_grok_code("Your code: ABC-123\nPlease verify"), "ABC123")

    def test_extract_code_strips_html(self) -> None:
        self.assertEqual(extract_grok_code("<p>code: AB1-23C</p>"), "AB123C")

    def test_extract_code_none(self) -> None:
        self.assertIsNone(extract_grok_code("no code here"))
        self.assertIsNone(extract_grok_code(""))


class RegistrationConfigTests(unittest.TestCase):
    def test_defaults_disabled(self) -> None:
        cfg = GrokRegistrationConfig(None)
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.min_accounts, 5)
        self.assertEqual(cfg.register_batch, 3)
        self.assertEqual(cfg.check_interval_minutes, 30)
        self.assertEqual(cfg.email_provider, "luckmail")
        self.assertEqual(cfg.email_pool, [])

    def test_clamp_minimums(self) -> None:
        cfg = GrokRegistrationConfig({"min_accounts": 0, "register_batch": -3, "check_interval_minutes": "abc"})
        self.assertEqual(cfg.min_accounts, 1)
        self.assertEqual(cfg.register_batch, 1)
        self.assertEqual(cfg.check_interval_minutes, 30)

    def test_to_dict_masks_secrets(self) -> None:
        cfg = GrokRegistrationConfig({"yescaptcha_key": "secret-key", "luckmail_api_key": "lm-secret"})
        d = cfg.to_dict()
        self.assertTrue(d["yescaptcha_key_configured"])
        self.assertNotIn("secret-key", str(d))
        self.assertNotIn("lm-secret", str(d))

    def test_get_from_config_data(self) -> None:
        """get_registration_config 从 config.data 热读取 registration.grok。"""
        from services.config import config

        original = config.data
        try:
            config.data = {"registration": {"grok": {"enabled": True, "min_accounts": 9}}}
            cfg = get_registration_config()
            self.assertTrue(cfg.enabled)
            self.assertEqual(cfg.min_accounts, 9)
        finally:
            config.data = original


class EngineUtilTests(unittest.TestCase):
    def test_grpc_message_encoding(self) -> None:
        msg = _encode_grpc_message(1, "test@example.com")
        # 5 字节前缀（0x00 + 4 字节长度）
        self.assertEqual(msg[:1], b"\x00")
        self.assertIn(b"test@example.com", msg)

    def test_grpc_verify_encoding(self) -> None:
        msg = _encode_grpc_message_verify("a@b.com", "ABC123")
        self.assertEqual(msg[:1], b"\x00")
        self.assertIn(b"ABC123", msg)

    def test_proxy_group_resolution_empty(self) -> None:
        self.assertEqual(resolve_proxy_for_group(""), "")
        self.assertEqual(resolve_proxy_for_group("no-such-group"), "")


class DeviceMintTests(unittest.TestCase):
    def test_sso_to_device_returns_none_without_patchright(self) -> None:
        """patchright 缺失 + 授权未确认 → 安全降级返回 None（不抛异常、不触网）。"""
        from services.registration.grok import device_mint as dm

        calls: list[str] = []

        def fake_http(url, method="GET", form=None, timeout=40, proxy=""):
            if "device/code" in url:
                calls.append("device")
                return 200, {"device_code": "dc123", "verification_uri_complete": "https://auth.x.ai/device", "interval": 1}
            calls.append("token")
            return 400, {"error": "access_denied", "error_description": "denied"}

        with (
            patch.object(dm, "_http_json", side_effect=fake_http),
            patch.object(dm.time, "sleep", return_value=None),
            patch.dict("sys.modules", {"patchright": None}),
        ):
            result = sso_to_device("sso-token")
        self.assertIsNone(result)
        self.assertEqual(calls, ["device", "token"])


class EngineRegisterFlowTests(unittest.TestCase):
    """register_one 全链路（mock 网络）：发码 → 收码 → Turnstile → 提交 → SSO 提取。"""

    class _FakeEmailService:
        """池模式假邮箱：create 返回固定邮箱，fetch 返回固定 grok 验证码。"""

        def __init__(self) -> None:
            self.consumed: str | None = None
            self.released: str | None = None

        def create_email(self, proxy=""):
            return {"provider": "pool", "email": "a@b.com", "mail_credential": {}}, "a@b.com"

        def fetch_first_email(self, token_like, proxy=""):
            return "SZ0-0SW xAI confirmation code"

        def release_email(self, email):
            self.released = email

        def consume_email(self, email):
            self.consumed = email

    class _FakeSession:
        """curl_cffi Session 假实现：warmup/发码/提交都返回 200，cookie 里有 SSO。"""

        _cookies = {"__cf_bm": "cfbm", "sso": "sso-from-cookie"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, **kwargs):
            resp = unittest.mock.Mock()
            resp.status_code = 200
            resp.text = "<html>ok</html>"
            resp.headers = {}
            return resp

        def post(self, url, **kwargs):
            resp = unittest.mock.Mock()
            resp.status_code = 200
            resp.text = '<a href="https://auth.x.ai/set-cookie?q=abc123">redirect</a>'
            resp.headers = {"set-cookie": "sso=from-header; Path=/"}
            return resp

        @property
        def cookies(self):
            return _CookieJar(self._cookies)

    def _engine_with_discovery(self, action_id: str | None):
        from services.registration.config import GrokRegistrationConfig
        from services.registration.grok import engine as eng

        cfg = GrokRegistrationConfig({"enabled": True, "yescaptcha_key": "kc"})
        engine = eng.GrokRegisterEngine(cfg)
        engine._discovered = {"site_key": "0x4aaaa", "state_tree": "tree", "action_id": action_id}
        return engine

    def test_register_one_success(self) -> None:
        from services.registration.grok import engine as eng

        engine = self._engine_with_discovery("7f" + "a" * 40)
        fake_email = self._FakeEmailService()

        with (
            patch.object(eng.cffi_requests, "Session", return_value=self._FakeSession()),
            patch.object(eng.TurnstileService, "create_task", return_value="task-1"),
            patch.object(eng.TurnstileService, "get_response", return_value="ts-token"),
            patch.object(eng.time, "sleep", return_value=None),
        ):
            result = engine.register_one(fake_email, proxy="")

        self.assertIsNotNone(result)
        self.assertEqual(result["email"], "a@b.com")
        self.assertEqual(result["sso"], "sso-from-cookie")
        self.assertEqual(fake_email.consumed, "a@b.com")
        self.assertIsNone(fake_email.released)

    def test_register_one_fails_when_code_missing(self) -> None:
        from services.registration.grok import engine as eng

        engine = self._engine_with_discovery("7f" + "a" * 40)
        fake_email = self._FakeEmailService()
        fake_email.fetch_first_email = lambda token_like, proxy="": None  # 收不到验证码

        with (
            patch.object(eng.cffi_requests, "Session", return_value=self._FakeSession()),
            patch.object(eng.time, "sleep", return_value=None),
        ):
            result = engine.register_one(fake_email, proxy="")

        self.assertIsNone(result)
        self.assertEqual(fake_email.released, "a@b.com")  # 失败归还邮箱


class _CookieJar:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._store.get(name, default)


class CoordinatorTests(unittest.TestCase):
    def test_register_rejected_when_disabled(self) -> None:
        from services.registration.coordinator import RegistrationCoordinator

        coord = RegistrationCoordinator()
        with patch("services.config.config.data", {"registration": {}}, create=True):
            result = coord.register(count=2)
        self.assertFalse(result["ok"])
        self.assertIn("未启用", result["error"])

    def test_count_grok_accounts_filters(self) -> None:
        from services.registration.coordinator import count_grok_accounts

        fake_accounts = [
            {"provider": "grok", "access_token": "tok1", "status": "正常"},
            {"provider": "grok", "access_token": "tok2", "status": "异常"},   # 不可用
            {"provider": "grok", "access_token": "", "status": "正常"},       # 无 token
            {"provider": "chatgpt", "access_token": "tok3", "status": "正常"},  # 非 grok
            {"provider": "grok", "status": "正常"},                           # 无 token 字段
        ]
        with patch("services.account_service.account_service.list_accounts", return_value=fake_accounts):
            self.assertEqual(count_grok_accounts(), 1)

    def test_register_inner_writes_pool(self) -> None:
        """_register_inner：引擎返回的 SSO 以 provider=grok 写入号池。"""
        from services.registration.coordinator import RegistrationCoordinator
        from services.registration.grok import engine as eng

        coord = RegistrationCoordinator()
        fake_result = {
            "success": 1,
            "failed": 0,
            "items": [{"sso": "sso-1", "email": "a@b.com", "password": "pw"}],
            "errors": [],
        }
        captured: list[dict] = []

        def fake_add(items):
            captured.extend(items)
            return {"added": len(items), "skipped": 0, "items": []}

        with (
            patch("services.config.config.data", {"registration": {"grok": {"enabled": True, "min_accounts": 3}}}, create=True),
            patch.object(eng.GrokRegisterEngine, "register", return_value=fake_result),
            patch("services.account_service.account_service.add_account_items", side_effect=fake_add),
        ):
            result = coord._register_inner(count=1)

        self.assertTrue(result["ok"])
        self.assertEqual(result["pool_added"], 1)
        self.assertEqual(captured[0]["provider"], "grok")
        self.assertEqual(captured[0]["access_token"], "sso-1")
        self.assertEqual(captured[0]["email"], "a@b.com")
        self.assertEqual(captured[0]["source_type"], "grok_registration")

    def test_push_to_pool_empty(self) -> None:
        from services.registration.coordinator import _push_to_pool

        with patch("services.account_service.account_service.add_account_items") as mock_add:
            self.assertEqual(_push_to_pool([]), 0)
        mock_add.assert_not_called()

    def test_status_shape(self) -> None:
        from services.registration.coordinator import RegistrationCoordinator

        coord = RegistrationCoordinator()
        with (
            patch("services.config.config.data", {"registration": {"grok": {"enabled": True, "min_accounts": 3}}}, create=True),
            patch("services.account_service.account_service.list_accounts", return_value=[{"provider": "grok", "access_token": "t", "status": "正常"}]),
        ):
            status = coord.status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["grok_pool"]["available"], 1)
        self.assertEqual(status["grok_pool"]["min_accounts"], 3)
        self.assertTrue(status["grok_pool"]["need_replenish"])


class RegistrationApiTests(unittest.TestCase):
    """端点挂载 + 鉴权 + 默认关闭行为（TestClient 走完整 app）。"""

    _AUTH = {"Authorization": "Bearer chatgpt2api"}

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        from api.app import create_app

        cls._client = TestClient(create_app())

    def test_status_requires_auth(self) -> None:
        resp = self._client.get("/api/registration/status")
        self.assertIn(resp.status_code, (401, 403))

    def test_register_requires_auth(self) -> None:
        resp = self._client.post("/api/registration/grok/register", json={"count": 2})
        self.assertIn(resp.status_code, (401, 403))

    def test_status_default_disabled(self) -> None:
        resp = self._client.get("/api/registration/status", headers=self._AUTH)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["enabled"])
        self.assertIn("grok_pool", body)
        self.assertIn("email_pool", body)
        self.assertIn("stats", body)

    def test_register_default_disabled(self) -> None:
        resp = self._client.post("/api/registration/grok/register", json={"count": 2}, headers=self._AUTH)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIn("未启用", body["error"])


if __name__ == "__main__":
    unittest.main()
