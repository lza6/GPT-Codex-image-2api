"""OTP 登录服务 + add_password_accounts OTP 降级分流单元测试。

纯单元验证（Mock），不触网。验证：
  - OTPLoginService.login 链路：authorize→OTP→取码→validate→exchange（mock session）
  - add_password_accounts：_login_with_password 返回 need_verification_code → 有 mail_credential 走 OTP、无则落 pending
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.app import create_app
from services.account_service import AccountService, account_service
from services.otp_login_service import OTPLoginService

_AUTH = {"Authorization": "Bearer chatgpt2api"}


class MemoryStorage:
    def __init__(self, accounts: list[dict[str, Any]] | None = None) -> None:
        self.accounts = list(accounts or [])

    def load_accounts(self) -> list[dict[str, Any]]:
        return list(self.accounts)

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        self.accounts = list(accounts)

    def load_auth_keys(self) -> list[dict[str, Any]]:
        return []

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        pass

    def health_check(self) -> dict[str, Any]:
        return {"ok": True}

    def get_backend_info(self) -> dict[str, Any]:
        return {"type": "memory"}


def _client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------- OTP 降级分流

class TestAddPasswordAccountsOTPFallback:
    def test_password_need_otp_with_mail_credential_triggers_otp(self, monkeypatch) -> None:
        """_login_with_password 返回 need_verification_code + 有 mail_credential → 走 OTP。"""
        service = AccountService(MemoryStorage())

        def _fake_password_login(email, password, proxy_url=""):
            return {"ok": False, "error": "need_verification_code", "detail": {"page": {"type": "email_otp_verification"}}}

        monkeypatch.setattr(service, "_login_with_password", _fake_password_login)

        otp_called: list[dict] = []

        def _fake_otp_login(email, password, *, mail_credential=None, proxy_url=""):
            otp_called.append({"email": email, "mail_credential": mail_credential})
            return {"ok": True, "access_token": "jwt-from-otp", "refresh_token": "rt-1", "id_token": "id-1",
                    "email": email, "source_type": "otp"}

        # 注入 stub 模块，让 account_service 内的懒加载 `from services.otp_login_service import otp_login_service` 拿到 stub
        class _Stub:
            @staticmethod
            def login(email, password, *, mail_credential=None, proxy_url=""):
                otp_called.append({"email": email, "mail_credential": mail_credential})
                return {"ok": True, "access_token": "jwt-from-otp", "refresh_token": "rt-1", "id_token": "id-1",
                        "email": email, "source_type": "otp"}
        stub_module = type(sys)("services.otp_login_service")
        stub_module.otp_login_service = _Stub()
        with patch.dict(sys.modules, {"services.otp_login_service": stub_module}):
            result = service.add_password_accounts([{
                "email": "otp@example.com", "password": "pw123",
                "mail_credential": {"client_id": "cid-1", "refresh_token": "M.rt-xxx"},
            }])

        assert result["added"] == 1
        assert result["pending"] == 0
        assert otp_called[0]["mail_credential"]["client_id"] == "cid-1"
        account = service.get_account("jwt-from-otp")
        assert account is not None
        assert account["source_type"] == "otp"

    def test_password_need_otp_without_mail_credential_falls_to_pending(self, monkeypatch) -> None:
        """_login_with_password 返回 need_verification_code + 无 mail_credential → 落 pending。"""
        service = AccountService(MemoryStorage())

        def _fake_password_login(email, password, proxy_url=""):
            return {"ok": False, "error": "need_verification_code", "detail": {}}

        monkeypatch.setattr(service, "_login_with_password", _fake_password_login)
        result = service.add_password_accounts([{"email": "otp2@example.com", "password": "pw123"}])

        assert result["pending"] == 1
        assert result["errors"][0]["error"] == "need_verification_code"
        account = service.get_account("pending:otp2@example.com")
        assert account is not None
        assert account["status"] == "待登录"

    def test_otp_login_exception_does_not_crash(self, monkeypatch) -> None:
        """OTP 链路抛异常 → 落 pending 不崩。"""
        service = AccountService(MemoryStorage())

        def _fake_password_login(email, password, proxy_url=""):
            return {"ok": False, "error": "need_verification_code", "detail": {}}

        def _raise(email, password, **kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(service, "_login_with_password", _fake_password_login)

        class _Stub:
            @staticmethod
            def login(email, password, **kwargs):
                raise RuntimeError("network down")
        stub_module = type(sys)("services.otp_login_service")
        stub_module.otp_login_service = _Stub()
        with patch.dict(sys.modules, {"services.otp_login_service": stub_module}):
            result = service.add_password_accounts([{
                "email": "otp3@example.com", "password": "pw123",
                "mail_credential": {"client_id": "cid", "refresh_token": "rt"},
            }])
        assert result["pending"] == 1
        assert "otp_login_exception" in result["errors"][0]["error"]


# ---------------------------------------------------------------- OTPLoginService 链路（Mock session）

class TestOTPLoginService:
    def test_missing_email_returns_error(self) -> None:
        svc = OTPLoginService()
        result = svc.login("", "pw", mail_credential={"client_id": "c", "refresh_token": "r"})
        assert result["ok"] is False
        assert result["error"] == "missing_email"

    def test_missing_mail_credential_returns_need_mail_credential(self) -> None:
        svc = OTPLoginService()
        result = svc.login("a@b.com", "pw", mail_credential=None)
        assert result["ok"] is False
        assert result["error"] == "need_mail_credential"

    def test_full_login_flow_mocked(self, monkeypatch) -> None:
        """Mock session 验证 authorize→取码→validate→exchange 全链路返回 token。"""
        svc = OTPLoginService()

        # Mock curl_cffi.requests.Session
        fake_session = MagicMock()
        # authorize GET：返回带 callback code 的 URL（跳过 OTP 直接拿 code）
        fake_resp = MagicMock()
        fake_resp.url = "https://platform.openai.com/auth/callback?code=AUTHCODE&state=st.123"
        fake_resp.status_code = 200
        fake_session.get.return_value = fake_resp
        # exchange POST
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.text = '{"access_token":"JWT","refresh_token":"RT","id_token":"ID","expires_in":3600}'
        token_resp.json.return_value = {"access_token": "JWT", "refresh_token": "RT", "id_token": "ID", "expires_in": 3600}
        fake_session.post.return_value = token_resp
        fake_session.cookies = MagicMock()

        monkeypatch.setattr("services.otp_login_service.requests.Session", lambda **kw: fake_session)

        result = svc.login(
            "x@y.com", "pw",
            mail_credential={"client_id": "c", "refresh_token": "r", "email": "x@y.com", "password": "pw"},
            use_cf_solver=False,  # 本测试不涉 cf_solver；True 会去连未启动的 cf_solver 空转超时
        )
        assert result["ok"] is True
        assert result["access_token"] == "JWT"
        assert result["refresh_token"] == "RT"
        assert result["id_token"] == "ID"
        assert result["source_type"] == "otp"
        assert result["email"] == "x@y.com"


# ---------------------------------------------------------------- API 端点透传 mail_credential

class TestAPIPassesMailCredential:
    def test_api_passes_mail_credential_to_add_password_accounts(self, monkeypatch) -> None:
        """POST /api/accounts 的 accounts payload 含 mail_credential → 透传到 add_password_accounts。"""
        received: list[dict] = []

        def _fake_add_password(creds):
            received.extend(creds)
            return {"added": 0, "skipped": 0, "pending": 0, "failed": 0, "errors": [], "items": []}

        monkeypatch.setattr(account_service, "add_password_accounts", _fake_add_password)
        client = _client()
        r = client.post(
            "/api/accounts",
            json={"accounts": [{
                "email": "z@y.com", "password": "pw",
                "mail_credential": {"client_id": "CID", "refresh_token": "RTX"},
            }]},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        assert received[0]["mail_credential"]["client_id"] == "CID"
