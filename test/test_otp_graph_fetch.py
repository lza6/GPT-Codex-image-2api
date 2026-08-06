"""OTP 取件：微软 Graph 直连（优先）/98faka（兜底）+ passwordless 触发 + 邮件时间 UTC 单元测试。

纯 Mock 不触网。覆盖 v2.9.0 新增且此前欠测的路径：
  - _fetch_otp_code dispatcher：Graph 成功 / token 换不出回退 98faka / Graph 读到箱无码不双轮询
  - _graph_access_token / _graph_list_mails（归一化）/ 全文兜底
  - _trigger_passwordless_otp（200/非200/异常）
  - _mail_time（naive/Z/偏移/非法 → UTC aware）
  - _extract_otp_code（关键词/裸数字/HTML/空）
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import services.otp_login_service as otp
from services.otp_login_service import (
    GRAPH_MESSAGES_URL,
    GRAPH_SCOPE,
    GRAPH_TOKEN_URL,
    MAIL_API_BASE,
    OTPLoginService,
)


class _Resp:
    def __init__(self, status: int = 200, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload if self._payload is not None else json.loads(self.text)


class _FakeTime:
    """可控时钟：time() 返回当前值，sleep(s) 直接拨快，避免轮询测试真等 90s。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, secs: float) -> None:
        self.now += secs


def _mail(received: str = "2026-08-07T20:00:00Z", preview: str = "", subject: str = "OpenAI", msg_id: str = "m1") -> dict:
    return {
        "id": msg_id,
        "subject": subject,
        "receivedDateTime": received,
        "from": {"emailAddress": {"address": "no-reply@openai.com"}},
        "bodyPreview": preview,
    }


_AFTER = datetime(2026, 8, 7, 19, 59, 59, tzinfo=UTC)  # 邮件 20:00:00 在其后 1s，落在窗口内


# ---------------------------------------------------------------- Graph token / 列表归一化

class TestGraphBasics:
    def test_graph_access_token_success(self, monkeypatch) -> None:
        def fake_post(url, data=None, headers=None, proxies=None, timeout=None):
            assert url == GRAPH_TOKEN_URL
            assert data["grant_type"] == "refresh_token"
            assert data["refresh_token"] == "rt-1"
            assert data["scope"] == GRAPH_SCOPE
            return _Resp(200, {"access_token": "AT-1"})

        monkeypatch.setattr(otp.requests, "post", fake_post)
        assert OTPLoginService._graph_access_token("cid", "rt-1") == "AT-1"

    def test_graph_access_token_http_error_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setattr(otp.requests, "post", lambda *a, **k: _Resp(400, {"error": "invalid_grant"}))
        assert OTPLoginService._graph_access_token("cid", "bad") == ""

    def test_graph_access_token_exception_returns_empty(self, monkeypatch) -> None:
        def _boom(*a, **k):
            raise RuntimeError("conn refused")

        monkeypatch.setattr(otp.requests, "post", _boom)
        assert OTPLoginService._graph_access_token("cid", "rt") == ""

    def test_graph_list_mails_normalizes_shape(self, monkeypatch) -> None:
        monkeypatch.setattr(otp.requests, "get", lambda *a, **k: _Resp(200, {"value": [_mail(preview="p")] }))
        mails = OTPLoginService()._graph_list_mails("AT")
        assert mails[0]["from_address"] == "no-reply@openai.com"
        assert mails[0]["received_time"] == "2026-08-07T20:00:00Z"
        assert mails[0]["subject"] == "OpenAI"
        assert mails[0]["body_preview"] == "p"
        assert mails[0]["id"] == "m1"

    def test_graph_list_mails_missing_from_tolerated(self, monkeypatch) -> None:
        item = {"id": "m9", "subject": "s", "receivedDateTime": "2026-08-07T20:00:00Z", "bodyPreview": ""}
        monkeypatch.setattr(otp.requests, "get", lambda *a, **k: _Resp(200, {"value": [item]}))
        mails = OTPLoginService()._graph_list_mails("AT")
        assert mails[0]["from_address"] == ""


# ---------------------------------------------------------------- dispatcher：Graph 优先 / 98faka 兜底

class TestFetchDispatcher:
    def test_graph_success_preview_code_no_faka(self, monkeypatch) -> None:
        calls = {"faka": 0}
        monkeypatch.setattr(otp, "time", _FakeTime())

        def fake_post(url, **kw):
            if url == GRAPH_TOKEN_URL:
                return _Resp(200, {"access_token": "AT"})
            calls["faka"] += 1
            return _Resp(200, {})

        monkeypatch.setattr(otp.requests, "post", fake_post)
        monkeypatch.setattr(otp.requests, "get", lambda *a, **k: _Resp(200, {"value": [_mail(preview="code: 654321")]}))

        code = OTPLoginService()._fetch_otp_code({"client_id": "c", "refresh_token": "r"}, _AFTER)
        assert code == "654321"
        assert calls["faka"] == 0  # Graph 成功则不碰 98faka

    def test_graph_full_body_fallback_when_preview_no_code(self, monkeypatch) -> None:
        monkeypatch.setattr(otp, "time", _FakeTime())
        monkeypatch.setattr(otp.requests, "post", lambda *a, **k: _Resp(200, {"access_token": "AT"}))

        def fake_get(url, **kw):
            if url == GRAPH_MESSAGES_URL:
                return _Resp(200, {"value": [_mail(preview="no digits here")]})
            return _Resp(200, {"body": {"content": "Your verification code is 112233"}})  # 单封正文

        monkeypatch.setattr(otp.requests, "get", fake_get)
        code = OTPLoginService()._fetch_otp_code({"client_id": "c", "refresh_token": "r"}, _AFTER)
        assert code == "112233"

    def test_graph_token_fail_falls_back_to_98faka(self, monkeypatch) -> None:
        faka = {"emails": 0}
        monkeypatch.setattr(otp, "time", _FakeTime())

        def fake_post(url, json=None, data=None, **kw):
            if url == GRAPH_TOKEN_URL:
                return _Resp(400, {"error": "invalid_grant"})
            if url == f"{MAIL_API_BASE}/api/emails":
                faka["emails"] += 1
                return _Resp(200, {"code": 200, "data": [{
                    "id": "m1", "subject": "OpenAI", "received_time": "2026-08-07T20:00:00Z",
                    "from_address": "no-reply@openai.com"}]})
            if url == f"{MAIL_API_BASE}/api/email-body":
                return _Resp(200, {"body_html": "code: 778899"})
            return _Resp(200, {})

        monkeypatch.setattr(otp.requests, "post", fake_post)
        code = OTPLoginService()._fetch_otp_code(
            {"client_id": "c", "refresh_token": "r", "email": "x@y.com", "password": "pw"}, _AFTER)
        assert code == "778899"
        assert faka["emails"] >= 1

    def test_graph_no_mail_returns_none_without_double_poll(self, monkeypatch) -> None:
        calls = {"faka": 0}
        monkeypatch.setattr(otp, "time", _FakeTime())

        def fake_post(url, **kw):
            if url == GRAPH_TOKEN_URL:
                return _Resp(200, {"access_token": "AT"})
            calls["faka"] += 1
            return _Resp(200, {})

        monkeypatch.setattr(otp.requests, "post", fake_post)
        monkeypatch.setattr(otp.requests, "get", lambda *a, **k: _Resp(200, {"value": []}))  # 收件箱空

        code = OTPLoginService()._fetch_otp_code({"client_id": "c", "refresh_token": "r"}, _AFTER)
        assert code is None
        assert calls["faka"] == 0  # Graph 读到箱但没码 → 不回退双轮询

    def test_no_credential_goes_straight_to_98faka(self, monkeypatch) -> None:
        monkeypatch.setattr(otp, "time", _FakeTime())
        graph_called = {"n": 0}

        def fake_post(url, json=None, data=None, **kw):
            if url == GRAPH_TOKEN_URL:
                graph_called["n"] += 1
                return _Resp(200, {"access_token": "AT"})
            if url == f"{MAIL_API_BASE}/api/emails":
                return _Resp(200, {"code": 200, "data": [{
                    "id": "m1", "subject": "OpenAI", "received_time": "2026-08-07T20:00:00Z",
                    "from_address": "no-reply@openai.com"}]})
            if url == f"{MAIL_API_BASE}/api/email-body":
                return _Resp(200, {"body_html": "009988"})
            return _Resp(200, {})

        monkeypatch.setattr(otp.requests, "post", fake_post)
        code = OTPLoginService()._fetch_otp_code({"email": "x@y.com", "password": "pw"}, _AFTER)  # 无 client_id
        assert code == "009988"
        assert graph_called["n"] == 0


# ---------------------------------------------------------------- passwordless 触发发码

class TestTriggerPasswordlessOTP:
    def _svc(self, monkeypatch):
        monkeypatch.setattr(otp, "build_sentinel_token", lambda s, d, w: ("sent", "sc"))
        return OTPLoginService()

    def test_success_200(self, monkeypatch) -> None:
        svc = self._svc(monkeypatch)
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        session.post.return_value = resp
        assert svc._trigger_passwordless_otp(session, "dev-1") is True
        args, kwargs = session.post.call_args
        assert "passwordless/send-otp" in args[0]

    def test_non_200_returns_false(self, monkeypatch) -> None:
        svc = self._svc(monkeypatch)
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 429
        session.post.return_value = resp
        assert svc._trigger_passwordless_otp(session, "dev-1") is False

    def test_exception_returns_false(self, monkeypatch) -> None:
        svc = self._svc(monkeypatch)
        session = MagicMock()
        session.post.side_effect = RuntimeError("net down")
        assert svc._trigger_passwordless_otp(session, "dev-1") is False


# ---------------------------------------------------------------- _mail_time UTC 修复 + 文本提码

class TestMailTimeUTC:
    def test_naive_treated_as_utc(self) -> None:
        d = OTPLoginService._mail_time({"received_time": "2026-08-07T20:00:00"})
        assert d.tzinfo is not None and d == datetime(2026, 8, 7, 20, 0, 0, tzinfo=UTC)

    def test_z_suffix(self) -> None:
        assert OTPLoginService._mail_time({"received_time": "2026-08-07T20:00:00Z"}) == datetime(2026, 8, 7, 20, 0, 0, tzinfo=UTC)

    def test_offset_normalized_to_utc(self) -> None:
        assert OTPLoginService._mail_time({"received_time": "2026-08-07T22:00:00+02:00"}) == datetime(2026, 8, 7, 20, 0, 0, tzinfo=UTC)

    def test_invalid_returns_epoch_utc(self) -> None:
        d = OTPLoginService._mail_time({"received_time": "garbage"})
        assert d == datetime.fromtimestamp(0, UTC) and d.tzinfo is not None

    def test_date_key_fallback(self) -> None:
        d = OTPLoginService._mail_time({"date": "2026-08-07T20:00:00Z"})
        assert d == datetime(2026, 8, 7, 20, 0, 0, tzinfo=UTC)


class TestExtractCodeFromText:
    def test_bare_digits(self) -> None:
        assert OTPLoginService._extract_otp_code("123456") == "123456"

    def test_keyword_with_colon(self) -> None:
        assert OTPLoginService._extract_otp_code("Your code: 654321") == "654321"

    def test_html_stripped(self) -> None:
        assert OTPLoginService._extract_otp_code("<p>code:</p><b>998877</b>") == "998877"

    def test_empty_returns_none(self) -> None:
        assert OTPLoginService._extract_otp_code("") is None

    def test_no_digits_returns_none(self) -> None:
        assert OTPLoginService._extract_otp_code("no code here") is None
