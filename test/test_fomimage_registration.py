"""fomimage 自动注册子模块单元测试（v2.36.0，不触网，全 mock 网络）。

覆盖：
- temp-mail 验证码正则提取
- TempMailInbox.create/fetch_messages/poll_code（mock HTTP）
- FomimageRegisterEngine 密码/名字生成 + 注册流水线（mock 网络）
- coordinator：enabled=false 拒绝、入池去重、count_fomimage_accounts
- /api/registration/fomimage/* 鉴权
"""
from __future__ import annotations

import unittest
from unittest import mock

from services.registration.config import FomimageRegistrationConfig, get_fomimage_registration_config
from services.registration.fomimage.coordinator import count_fomimage_accounts
from services.registration.fomimage.engine import (
    FomimageRegisterEngine,
    _generate_random_name,
    _generate_random_password,
)
from services.registration.fomimage.temp_mail import TempMailInbox, extract_fromimage_code


class FromimageCodeExtractTests(unittest.TestCase):
    def test_subject_format(self) -> None:
        # 主题：`618068 is your FromImage AI email verification code`
        self.assertEqual(extract_fromimage_code("618068 is your FromImage AI email verification code"), "618068")
        self.assertEqual(extract_fromimage_code(" 123456 是你的 FromImage AI 邮箱验证码 "), "123456")
        self.assertIsNone(extract_fromimage_code("no code here"))
        self.assertIsNone(extract_fromimage_code(""))

    def test_html_stripped(self) -> None:
        text = "<html><body>729301 is your FromImage code</body></html>"
        self.assertEqual(extract_fromimage_code(text), "729301")


class PasswordGenerationTests(unittest.TestCase):
    def test_password_complexity(self) -> None:
        for _ in range(20):
            pw = _generate_random_password()
            self.assertGreaterEqual(len(pw), 14)
            self.assertLessEqual(len(pw), 18)
            self.assertTrue(any(c.isupper() for c in pw))
            self.assertTrue(any(c.islower() for c in pw))
            self.assertTrue(any(c.isdigit() for c in pw))
            self.assertTrue(any(c in "!@#$%^&*" for c in pw))

    def test_name_generation(self) -> None:
        for _ in range(20):
            name = _generate_random_name()
            self.assertTrue(name[0].isupper())
            self.assertTrue(name.isalpha())


class TempMailTests(unittest.TestCase):
    def _mock_session(self, create_resp=None, messages_resp=None):
        session = mock.Mock()
        create = mock.Mock(return_value=create_resp or mock.Mock(status_code=200, json=lambda: {"token": "T1", "mailbox": "abc@beiwoh.com"}))
        messages = mock.Mock(return_value=messages_resp or mock.Mock(status_code=200, json=lambda: {"mailbox": "abc@beiwoh.com", "messages": []}))
        session.post = mock.Mock(side_effect=lambda url, **kw: create(url) if "mailbox" in url and "messages" not in url else create(url))
        session.get = mock.Mock(side_effect=lambda url, **kw: messages(url))
        return session

    def test_create(self) -> None:
        inbox = TempMailInbox()
        with mock.patch.object(inbox, "_session") as sess:
            sess.post.return_value = mock.Mock(status_code=200, json=lambda: {"token": "T1", "mailbox": "abc@beiwoh.com"})
            email = inbox.create()
        self.assertEqual(email, "abc@beiwoh.com")
        self.assertEqual(inbox.token, "T1")

    def test_create_failure(self) -> None:
        inbox = TempMailInbox()
        with mock.patch.object(inbox, "_session") as sess:
            sess.post.return_value = mock.Mock(status_code=500, text="boom")
            with self.assertRaises(RuntimeError):
                inbox.create()

    def test_poll_code(self) -> None:
        inbox = TempMailInbox()
        inbox.token = "T1"
        with mock.patch.object(inbox, "_session") as sess, mock.patch("services.registration.fomimage.temp_mail.time.sleep"):
            sess.get.return_value = mock.Mock(
                status_code=200,
                json=lambda: {"mailbox": "abc@beiwoh.com", "messages": [{"_id": "m1", "subject": "618068 is your FromImage AI email verification code"}]},
            )
            code = inbox.poll_code(timeout=5)
        self.assertEqual(code, "618068")

    def test_poll_code_no_message_returns_none(self) -> None:
        inbox = TempMailInbox()
        inbox.token = "T1"
        with mock.patch.object(inbox, "_session") as sess, mock.patch("services.registration.fomimage.temp_mail.time.sleep"):
            sess.get.return_value = mock.Mock(status_code=200, json=lambda: {"messages": []})
            self.assertIsNone(inbox.poll_code(timeout=1))


class ConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = FomimageRegistrationConfig({})
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.pool_quota, 50)
        self.assertEqual(cfg.min_accounts, 3)

    def test_typed(self) -> None:
        cfg = FomimageRegistrationConfig({"enabled": True, "min_accounts": "2", "register_batch": "5"})
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.min_accounts, 2)
        self.assertEqual(cfg.register_batch, 5)

    def test_get_from_config(self) -> None:
        with mock.patch("services.config.config.data", {"registration": {"fomimage": {"enabled": True}}}):
            cfg = get_fomimage_registration_config()
        self.assertTrue(cfg.enabled)

    def test_email_sources_default_and_filter(self) -> None:
        cfg = FomimageRegistrationConfig({})
        self.assertEqual(cfg.email_sources, ["temp-mail"])
        cfg2 = FomimageRegistrationConfig({"email_sources": "temp-mail,22.do,luckmail,bad"})
        self.assertEqual(cfg2.email_sources, ["temp-mail", "22.do", "luckmail"])
        cfg3 = FomimageRegistrationConfig({"email_sources": ["22.do", "gptmail"]})
        self.assertEqual(cfg3.email_sources, ["22.do", "gptmail"])


class Do22SourceTests(unittest.TestCase):
    """22.do 源：create(create+login+applyToken) / poll_code（JWT Bearer 收码）。"""

    def _mock_session(self) -> mock.Mock:
        sess = mock.Mock()
        # create → email；login → ok；applyToken → JWT
        def _post(url, **kw):
            if "create" in url:
                return mock.Mock(status_code=200, json=lambda: {"data": {"email": "abc@tnbeta.com"}})
            if "login" in url:
                return mock.Mock(status_code=200, json=lambda: {"status": True})
            if "applyToken" in url:
                return mock.Mock(status_code=200, json=lambda: {"data": {"token": "JWT123"}})
            if "message" in url:
                return mock.Mock(
                    status_code=200,
                    json=lambda: {"data": [{"subject": "618068 is your FromImage AI email verification code"}]},
                )
            return mock.Mock(status_code=200, json=lambda: {})
        sess.post = mock.Mock(side_effect=_post)
        sess.cookies = mock.Mock(get_dict=lambda: {"email": "abc@tnbeta.com"})
        return sess

    def test_create(self) -> None:
        from services.registration.fomimage.mail_source import Do22MailSource

        src = Do22MailSource()
        with mock.patch.object(src, "session", self._mock_session()):
            email = src.create()
        self.assertEqual(email, "abc@tnbeta.com")
        self.assertEqual(src._token, "JWT123")

    def test_poll_code(self) -> None:
        from services.registration.fomimage.mail_source import Do22MailSource

        src = Do22MailSource()
        src.email = "abc@tnbeta.com"
        src._token = "JWT123"
        with mock.patch.object(src, "session", self._mock_session()), \
             mock.patch("services.registration.fomimage.mail_source.time.sleep"):
            code = src.poll_code(timeout=5)
        self.assertEqual(code, "618068")


class EngineTests(unittest.TestCase):
    def _fake_register_one_ok(self):
        return {"email": "a@b.com", "password": "pw", "access_token": "tok1", "balance": 50, "proxy": ""}

    def test_register_flow_with_mocks(self) -> None:
        cfg = FomimageRegistrationConfig({"enabled": True, "pool_quota": 50})
        engine = FomimageRegisterEngine(cfg)
        src = mock.Mock()
        src.email = "abc@beiwoh.com"
        src.poll_code.return_value = "123456"
        src.close = mock.Mock()
        # session 的 post 依 URL 返回
        sess = mock.Mock()
        sess.post.side_effect = lambda url, **kw: mock.Mock(
            status_code=200,
            json=lambda: {"token": "TOK"} if "sign-in" in url else ({"status": True} if "verify" in url else {"token": None}),
        )
        sess.get.return_value = mock.Mock(status_code=200, json=lambda: {"code": 0, "data": {"balance": 50}})
        src.session = sess

        with mock.patch.object(engine, "resolve_email_proxy", return_value=""), \
             mock.patch("services.registration.fomimage.engine.create_mailbox_source", return_value=src):
            result = engine.register_one()
        self.assertIsNotNone(result)
        self.assertEqual(result["access_token"], "TOK")
        self.assertEqual(result["balance"], 50)

    def test_register_one_verify_fail(self) -> None:
        cfg = FomimageRegistrationConfig({"enabled": True})
        engine = FomimageRegisterEngine(cfg)
        src = mock.Mock()
        src.email = "abc@beiwoh.com"
        src.poll_code.return_value = "123456"
        sess = mock.Mock()
        sess.post.side_effect = lambda url, **kw: mock.Mock(
            status_code=200 if "sign-up" in url else 500,
            json=lambda: {},
        )
        src.session = sess
        with mock.patch.object(engine, "resolve_email_proxy", return_value=""), \
             mock.patch("services.registration.fomimage.engine.create_mailbox_source", return_value=src):
            self.assertIsNone(engine.register_one())

    def test_register_batch(self) -> None:
        cfg = FomimageRegistrationConfig({"enabled": True})
        engine = FomimageRegisterEngine(cfg)
        with mock.patch.object(engine, "register_one", side_effect=[{"email": "a@b.com"}, None]), \
             mock.patch("services.registration.fomimage.engine.time.sleep"):
            result = engine.register(2)
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["failed"], 1)


class CoordinatorTests(unittest.TestCase):
    def test_disabled_register_rejected(self) -> None:
        from services.registration.fomimage.coordinator import fomimage_registration_coordinator

        with mock.patch("services.registration.config.get_fomimage_registration_config",
                        return_value=FomimageRegistrationConfig({"enabled": False})):
            result = fomimage_registration_coordinator.register(1)
        self.assertFalse(result["ok"])
        self.assertIn("未启用", result["error"])

    def test_count_fomimage_accounts(self) -> None:
        accounts = [
            {"provider": "fomimage", "access_token": "t1", "status": "正常"},
            {"provider": "fomimage", "access_token": "t2", "status": "禁用"},
            {"provider": "chatgpt", "access_token": "t3", "status": "正常"},
            {"provider": "fomimage", "access_token": "", "status": "正常"},
        ]
        with mock.patch("services.account_service.account_service") as svc:
            svc.list_accounts.return_value = accounts
            self.assertEqual(count_fomimage_accounts(), 1)

    def test_push_to_pool(self) -> None:
        from services.registration.fomimage.coordinator import _push_to_pool

        items = [
            {"email": "a@b.com", "password": "p", "access_token": "tok1", "balance": 50, "proxy": ""},
            {"email": "x@y.com", "password": "p", "access_token": "tok2", "balance": 30},
        ]
        with mock.patch("services.account_service.account_service") as svc:
            svc.add_account_items.return_value = {"added": 2}
            added = _push_to_pool(items, pool_quota=50)
        self.assertEqual(added, 2)
        # 记录都带 provider=fomimage + quota（去重由 add_account_items 按 token 负责）
        records = svc.add_account_items.call_args[0][0]
        self.assertEqual(len(records), 2)
        for rec in records:
            self.assertEqual(rec["provider"], "fomimage")
        self.assertEqual(records[0]["quota"], 50)
        self.assertEqual(records[1]["quota"], 30)


class RegistrationApiTests(unittest.TestCase):
    """端点挂载 + 鉴权 + 默认关闭行为（TestClient 走完整 app）。"""

    _AUTH = {"Authorization": "Bearer chatgpt2api"}

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        from api.app import create_app

        cls._client = TestClient(create_app())

    def test_register_requires_admin(self) -> None:
        resp = self._client.post("/api/registration/fomimage/register", json={"count": 1})
        self.assertIn(resp.status_code, (401, 403))

    def test_status_requires_admin(self) -> None:
        resp = self._client.get("/api/registration/fomimage/status")
        self.assertIn(resp.status_code, (401, 403))

    def test_status_default_disabled(self) -> None:
        resp = self._client.get("/api/registration/fomimage/status", headers=self._AUTH)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["enabled"])
        self.assertIn("fomimage_pool", body)
        self.assertIn("config", body)
        self.assertIn("stats", body)

    def test_register_default_disabled(self) -> None:
        resp = self._client.post("/api/registration/fomimage/register", json={"count": 1}, headers=self._AUTH)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIn("未启用", body["error"])


if __name__ == "__main__":
    unittest.main()
