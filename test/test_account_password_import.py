"""账号密码（邮箱----密码）导入：自动登录抓 token 入库，失败保留待登录凭据。

验收：
  1. POST /api/accounts 收到无 access_token 的纯 email+password payload → 分流 add_password_accounts
  2. 有 access_token 的 payload 仍走原 add_account_items，行为不变
  3. add_password_accounts：登录成功 → 正常入库（token 作 key，保留 email/password/source_type=password）
  4. 登录失败（OTP/风控/网络）→ 以 `pending:{email}` 占位入库（status=待登录，quota=0，保留凭据+login_error）
  5. list_tokens 过滤 pending 占位 key，避免误刷/误调度
  6. 缺 email/password 的项跳过；同 email 重复导入跳过
  7. 待登录账号可通过 re_login_accounts 重新触发密码登录
用 monkeypatch / MemoryStorage 隔离，不污染真实账号池。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from api.app import create_app
from services.account_service import AccountService, account_service

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


def _service(accounts: list[dict[str, Any]] | None = None) -> AccountService:
    return AccountService(MemoryStorage(accounts))


def _client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------- 分流

class TestCreateAccountsDispatch:
    def test_pure_credentials_dispatch_to_password_import(self, monkeypatch) -> None:
        """accounts 里无 access_token 的纯 email+password → add_password_accounts。"""
        received: list[dict] = []
        monkeypatch.setattr(
            account_service, "add_password_accounts",
            lambda creds: received.append(creds) or {"added": 0, "skipped": 0, "pending": 0,
                                                     "failed": 0, "errors": [], "items": []},
        )
        client = _client()
        r = client.post(
            "/api/accounts",
            json={"tokens": [], "accounts": [{"email": "a@b.com", "password": "pw123", "source_type": "password"}]},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        assert len(received) == 1
        assert received[0][0]["email"] == "a@b.com"
        assert received[0][0]["password"] == "pw123"

    def test_pure_credentials_without_tokens_not_rejected(self, monkeypatch) -> None:
        """纯凭据导入不再因 tokens 为空而 400，返回 pending/failed 统计。"""
        monkeypatch.setattr(
            account_service, "add_password_accounts",
            lambda creds: {"added": 0, "skipped": 0, "pending": 1, "failed": 1, "errors": [], "items": account_service.list_accounts()},
        )
        client = _client()
        r = client.post(
            "/api/accounts",
            json={"accounts": [{"email": "a@b.com", "password": "pw123"}]},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        assert r.json()["pending"] == 1

    def test_token_payload_unchanged(self, monkeypatch) -> None:
        """带 access_token 的 payload 仍走 add_account_items，不触密码导入。"""
        seen: list[list[dict]] = []
        monkeypatch.setattr(account_service, "add_account_items", lambda items: seen.append(items) or {"added": 1, "skipped": 0, "items": []})
        monkeypatch.setattr(account_service, "refresh_accounts", lambda tokens: {"refreshed": 0, "errors": [], "items": []})
        monkeypatch.setattr(account_service, "add_password_accounts", lambda creds: {"added": 0, "skipped": 0, "pending": 0, "failed": 0, "errors": [], "items": []})
        client = _client()
        r = client.post(
            "/api/accounts",
            json={"tokens": [], "accounts": [{"access_token": "tok-1", "email": "a@b.com"}]},
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        assert len(seen) == 1
        assert seen[0][0]["access_token"] == "tok-1"

    def test_mixed_input_dispatches_both(self, monkeypatch) -> None:
        """混合输入：token payload 走原路径，纯凭据走密码导入。"""
        cred_seen: list[dict] = []
        monkeypatch.setattr(account_service, "add_account_items", lambda items: {"added": 1, "skipped": 0, "items": []})
        monkeypatch.setattr(account_service, "refresh_accounts", lambda tokens: {"refreshed": 0, "errors": [], "items": []})
        monkeypatch.setattr(
            account_service, "add_password_accounts",
            lambda creds: cred_seen.extend(creds) or {"added": 0, "skipped": 0, "pending": 1, "failed": 1, "errors": [], "items": []},
        )
        client = _client()
        r = client.post(
            "/api/accounts",
            json={
                "tokens": [],
                "accounts": [
                    {"access_token": "tok-1"},
                    {"email": "x@y.com", "password": "pw1"},
                ],
            },
            headers=_AUTH,
        )
        assert r.status_code == 200, r.text
        assert cred_seen[0]["email"] == "x@y.com"


# ---------------------------------------------------------------- add_password_accounts

class TestAddPasswordAccounts:
    def test_success_stores_token_and_credentials(self, monkeypatch) -> None:
        service = _service()
        monkeypatch.setattr(
            service, "_login_with_password",
            lambda email, password, proxy_url="": {
                "ok": True, "email": email, "access_token": "jwt-new", "refresh_token": "rt-1",
                "id_token": "id-1", "source_type": "password", "expires_at": 9999999999,
            },
        )
        result = service.add_password_accounts([{"email": "ok@example.com", "password": "pw123"}])

        assert result["added"] == 1
        assert result["pending"] == 0
        assert result["failed"] == 0
        account = service.get_account("jwt-new")
        assert account is not None
        assert account["email"] == "ok@example.com"
        assert account["password"] == "pw123"
        assert account["source_type"] == "password"
        assert account["status"] == "正常"

    def test_failure_stores_pending_with_credentials(self, monkeypatch) -> None:
        """登录失败（need_verification_code 等）→ pending:{email} 占位入库，保留凭据+原因。"""
        service = _service()
        monkeypatch.setattr(
            service, "_login_with_password",
            lambda email, password, proxy_url="": {"ok": False, "error": "need_verification_code", "detail": {"page": {"type": "email_otp_verification"}}},
        )
        result = service.add_password_accounts([{"email": "otp@example.com", "password": "pw123"}])

        assert result["added"] == 0
        assert result["pending"] == 1
        assert result["failed"] == 1
        assert result["errors"][0]["email"] == "otp@example.com"
        assert result["errors"][0]["error"] == "need_verification_code"

        account = service.get_account("pending:otp@example.com")
        assert account is not None
        assert account["status"] == "待登录"
        assert account["quota"] == 0
        assert account["email"] == "otp@example.com"
        assert account["password"] == "pw123"
        assert account["login_error"] == "need_verification_code"

    def test_login_exception_stored_as_pending(self, monkeypatch) -> None:
        service = _service()

        def _boom(email, password, proxy_url=""):
            raise RuntimeError("connect timeout")

        monkeypatch.setattr(service, "_login_with_password", _boom)
        result = service.add_password_accounts([{"email": "net@example.com", "password": "pw"}])

        assert result["pending"] == 1
        assert "login_exception" in result["errors"][0]["error"]
        assert service.get_account("pending:net@example.com")["login_error"].startswith("login_exception")

    def test_missing_email_or_password_skipped(self, monkeypatch) -> None:
        service = _service()
        monkeypatch.setattr(service, "_login_with_password", lambda email, password, proxy_url="": {"ok": True, "access_token": "x"})
        result = service.add_password_accounts([
            {"email": "", "password": "pw"},
            {"email": "a@b.com", "password": ""},
            {"email": "ok@example.com", "password": "pw"},
        ])
        assert result["added"] == 1
        assert result["skipped"] == 0  # 缺字段的项被忽略，不计 skipped

    def test_duplicate_email_skipped(self, monkeypatch) -> None:
        service = _service()
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            service, "_login_with_password",
            lambda email, password, proxy_url="": calls.append((email, password)) or {
                "ok": True, "email": email, "access_token": f"jwt-{email[:1]}",
            },
        )
        service.add_password_accounts([
            {"email": "dup@example.com", "password": "pw1"},
            {"email": "DUP@example.com", "password": "pw2"},
        ])
        assert len(calls) == 1
        assert calls[0] == ("dup@example.com", "pw1")

    def test_existing_email_skipped(self, monkeypatch) -> None:
        service = _service([{"access_token": "existing-tok", "email": "have@example.com", "status": "正常"}])
        monkeypatch.setattr(service, "_login_with_password", lambda email, password, proxy_url="": {"ok": True, "access_token": "never"})
        result = service.add_password_accounts([{"email": "have@example.com", "password": "pw"}])
        assert result["added"] == 0
        assert result["skipped"] == 1
        assert service.get_account("existing-tok") is not None


# ---------------------------------------------------------------- pending 保护

class TestPendingProtection:
    def test_list_tokens_excludes_pending(self) -> None:
        service = _service([
            {"access_token": "real-tok", "email": "a@b.com", "status": "正常"},
            {"access_token": "pending:otp@example.com", "email": "otp@example.com", "status": "待登录"},
        ])
        assert "real-tok" in service.list_tokens()
        assert "pending:otp@example.com" not in service.list_tokens()

    def test_pending_account_relogin_targetable(self, monkeypatch) -> None:
        """待登录账号可用 re_login_accounts 触发密码重登。"""
        service = _service([
            {"access_token": "pending:otp@example.com", "email": "otp@example.com", "password": "pw", "status": "待登录"},
        ])
        started: list[tuple] = []
        monkeypatch.setattr(service, "_password_re_login_thread", lambda *a, **k: started.append(a) or None)
        result = service.re_login_accounts(["pending:otp@example.com"])
        assert result["relogined"] == 1
        assert started and started[0][0] == "pending:otp@example.com"
