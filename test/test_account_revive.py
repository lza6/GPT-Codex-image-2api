"""4.2 救号流程化：revive 服务端入口 + API 端点 + 离线救号脚本 dry-run。

覆盖：
- service.revive_accounts：分类（库内无账号/已正常/无取件凭证）、limit、并发限流、
  成功事件 account_recovered 发出、failed 明细、skipped 标记落库。
- POST /api/accounts/revive：契约（revived/failed/skipped）、require_admin 鉴权、
  空 token 400、救号成功入审计。
- scripts/revive_abnormal.py --dry-run：可救/不可救分类、不联网、revive_skipped 标记落库。
纯 mock 不触网。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from services.account_service import AccountService, config
from services.event_bus import ACCOUNT_RECOVERED, event_bus

_AUTH = {"Authorization": "Bearer chatgpt2api"}

ROOT = Path(__file__).resolve().parents[1]


class MemoryStorage:
    """与 test_otp_login.py 一致的内存存储桩。"""

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


def _abnormal_account(token: str, email: str, **extra: Any) -> dict[str, Any]:
    base = {
        "access_token": token,
        "status": "异常",
        "email": email,
        "invalid_count": 2,
    }
    base.update(extra)
    return base


def _client() -> TestClient:
    return TestClient(create_app())


def _load_revive_script():
    path = ROOT / "scripts" / "revive_abnormal.py"
    spec = importlib.util.spec_from_file_location("revive_abnormal_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- service.revive_accounts

class TestReviveAccountsService:
    def test_empty_tokens_returns_contract(self) -> None:
        svc = _service()
        assert svc.revive_accounts([]) == {"revived": 0, "failed": [], "skipped": []}
        assert svc.revive_accounts([" ", ""]) == {"revived": 0, "failed": [], "skipped": []}

    def test_skips_unknown_account(self) -> None:
        svc = _service()
        result = svc.revive_accounts(["ghost-token"])
        assert result["revived"] == 0
        assert result["failed"] == []
        assert result["skipped"] == [{"email": "st-token", "reason": "库内无账号"}]

    def test_skips_already_normal(self) -> None:
        svc = _service([_abnormal_account("t-ok", "a@x.com", status="正常")])
        result = svc.revive_accounts(["t-ok"])
        assert result["skipped"] == [{"email": "a@x.com", "reason": "账号已正常"}]

    def test_skips_no_credential_and_marks_flag(self) -> None:
        """无 refresh_token 且无 password → 跳过并落 revive_skipped 标记。"""
        svc = _service([_abnormal_account("t-noc", "n@x.com")])
        result = svc.revive_accounts(["t-noc"])
        assert result["skipped"] == [{"email": "n@x.com", "reason": "无取件凭证"}]
        acct = svc.get_account("t-noc")
        assert acct is not None
        assert acct["revive_skipped"] is True
        assert acct["revive_skip_reason"] == "无取件凭证"

    def test_success_returns_contract_and_publishes_event(self, monkeypatch) -> None:
        svc = _service([_abnormal_account("t-1", "u@x.com", refresh_token="rt-1")])
        monkeypatch.setattr(
            svc, "recover_abnormal_accounts",
            lambda acc_tokens: {"recovered": 1, "failed": 0, "skipped": 0,
                                "password_relogin_triggered": 0, "items": []},
        )
        received: list = []
        event_bus.subscribe(ACCOUNT_RECOVERED, sync_handler=received.append)
        try:
            result = svc.revive_accounts(["t-1"])
        finally:
            event_bus.unsubscribe(ACCOUNT_RECOVERED, received.append)
        assert result == {"revived": 1, "failed": [], "skipped": []}
        assert len(received) == 1
        data = received[0].data
        assert data["email"] == "u@x.com"
        assert data["token_suffix"]
        assert data["source"] == "manual_revive"

    def test_recover_exception_records_failed(self, monkeypatch) -> None:
        svc = _service([_abnormal_account("t-1", "e@x.com", refresh_token="rt")])

        def _raise(_tokens):
            raise RuntimeError("network down")

        monkeypatch.setattr(svc, "recover_abnormal_accounts", _raise)
        result = svc.revive_accounts(["t-1"])
        assert result["revived"] == 0
        assert result["failed"] == [{"email": "e@x.com", "error": "exception:RuntimeError:network down"}]

    def test_recover_failed_counts_as_failed(self, monkeypatch) -> None:
        svc = _service([_abnormal_account("t-1", "f@x.com", refresh_token="rt")])
        monkeypatch.setattr(
            svc, "recover_abnormal_accounts",
            lambda acc_tokens: {"recovered": 0, "failed": 1, "skipped": 0,
                                "password_relogin_triggered": 0, "items": []},
        )
        result = svc.revive_accounts(["t-1"])
        assert result["revived"] == 0
        assert result["failed"] == [{"email": "f@x.com", "error": "恢复失败"}]

    def test_password_relogin_triggered_counts_as_failed(self, monkeypatch) -> None:
        svc = _service([_abnormal_account("t-1", "p@x.com", refresh_token="rt", password="pw")])
        monkeypatch.setattr(
            svc, "recover_abnormal_accounts",
            lambda acc_tokens: {"recovered": 0, "failed": 0, "skipped": 0,
                                "password_relogin_triggered": 1, "items": []},
        )
        result = svc.revive_accounts(["t-1"])
        assert result["revived"] == 0
        assert result["failed"][0]["error"] == "已触发密码重登（异步等待结果）"

    def test_limit_slices_revivable(self, monkeypatch) -> None:
        accounts = [_abnormal_account(f"t-{i}", f"u{i}@x.com", refresh_token=f"rt-{i}") for i in range(5)]
        svc = _service(accounts)
        called: list[list[str]] = []
        monkeypatch.setattr(
            svc, "recover_abnormal_accounts",
            lambda acc_tokens: called.append(acc_tokens) or {"recovered": 1, "failed": 0, "skipped": 0,
                                                             "password_relogin_triggered": 0, "items": []},
        )
        result = svc.revive_accounts([f"t-{i}" for i in range(5)], limit=2)
        assert result["revived"] == 2
        assert called == [["t-0"], ["t-1"]]

    def test_concurrency_limited_to_image_account_concurrency(self, monkeypatch) -> None:
        """5 个可救账号同时活跃数不得超过 image_account_concurrency（默认 3）。"""
        accounts = [_abnormal_account(f"t-{i}", f"u{i}@x.com", refresh_token=f"rt-{i}") for i in range(5)]
        svc = _service(accounts)
        lock = threading.Lock()
        state = {"active": 0, "peak": 0}
        monkeypatch.setitem(config.data, "image_account_concurrency", 3)

        def _slow_recover(acc_tokens):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.05)
            with lock:
                state["active"] -= 1
            return {"recovered": 1, "failed": 0, "skipped": 0, "password_relogin_triggered": 0, "items": []}

        monkeypatch.setattr(svc, "recover_abnormal_accounts", _slow_recover)
        result = svc.revive_accounts([f"t-{i}" for i in range(5)])
        assert result["revived"] == 5
        assert state["peak"] <= 3


# ---------------------------------------------------------------- POST /api/accounts/revive

class TestReviveAPI:
    def test_requires_admin(self) -> None:
        r = _client().post("/api/accounts/revive", json={"access_tokens": ["t"]})
        assert r.status_code == 401

    def test_empty_tokens_rejected(self) -> None:
        r = _client().post("/api/accounts/revive", json={"access_tokens": []}, headers=_AUTH)
        assert r.status_code == 400

    def test_missing_body_field_rejected(self) -> None:
        r = _client().post("/api/accounts/revive", json={}, headers=_AUTH)
        assert r.status_code == 400

    def test_success_contract(self, monkeypatch) -> None:
        from services.account_service import account_service
        monkeypatch.setattr(
            account_service, "revive_accounts",
            lambda tokens: {
                "revived": 1,
                "failed": [{"email": "f@x.com", "error": "恢复失败"}],
                "skipped": [{"email": "s@x.com", "reason": "无取件凭证"}],
            },
        )
        r = _client().post("/api/accounts/revive", json={"access_tokens": ["t1", "t2"]}, headers=_AUTH)
        assert r.status_code == 200, r.text
        assert r.json() == {
            "revived": 1,
            "failed": [{"email": "f@x.com", "error": "恢复失败"}],
            "skipped": [{"email": "s@x.com", "reason": "无取件凭证"}],
        }

    def test_dedup_tokens(self, monkeypatch) -> None:
        from services.account_service import account_service
        captured: list[list[str]] = []
        monkeypatch.setattr(
            account_service, "revive_accounts",
            lambda tokens: captured.append(tokens) or {"revived": 0, "failed": [], "skipped": []},
        )
        r = _client().post(
            "/api/accounts/revive",
            json={"access_tokens": ["t1", " t1 ", "t2"]},
            headers=_AUTH,
        )
        assert r.status_code == 200
        assert captured[0] == ["t1", "t2"]

    def test_audit_recorded_when_revived(self, monkeypatch) -> None:
        from services.account_service import account_service
        monkeypatch.setattr(
            account_service, "revive_accounts",
            lambda tokens: {"revived": 2, "failed": [], "skipped": []},
        )
        audit_calls: list[dict] = []
        from services import audit_service as audit_mod
        monkeypatch.setattr(audit_mod.audit_service, "record", lambda **kw: audit_calls.append(kw))
        r = _client().post("/api/accounts/revive", json={"access_tokens": ["t1"]}, headers=_AUTH)
        assert r.status_code == 200
        matches = [c for c in audit_calls if c.get("action") == "accounts.revive"]
        assert matches
        assert matches[0]["result"] == "success"
        assert matches[0]["operator"]  # 当前 admin
        assert matches[0]["detail"]["revived"] == 2

    def test_no_audit_when_nothing_revived(self, monkeypatch) -> None:
        from services.account_service import account_service
        monkeypatch.setattr(
            account_service, "revive_accounts",
            lambda tokens: {"revived": 0, "failed": [{"email": "f@x.com", "error": "x"}], "skipped": []},
        )
        audit_calls: list[dict] = []
        from services import audit_service as audit_mod
        monkeypatch.setattr(audit_mod.audit_service, "record", lambda **kw: audit_calls.append(kw))
        r = _client().post("/api/accounts/revive", json={"access_tokens": ["t1"]}, headers=_AUTH)
        assert r.status_code == 200
        assert not [c for c in audit_calls if c.get("action") == "accounts.revive"]


# ---------------------------------------------------------------- scripts/revive_abnormal.py --dry-run

class _FakeAcctSvc:
    """脚本测试用账号服务桩：get_account / update_account。"""

    def __init__(self, accounts: dict[str, dict] | None = None) -> None:
        self.accounts: dict[str, dict] = dict(accounts or {})
        self.updated: list[tuple[str, dict]] = []

    def get_account(self, token: str) -> dict | None:
        return self.accounts.get(token)

    def update_account(self, token: str, updates: dict, quiet: bool = False) -> dict | None:
        self.updated.append((token, updates))
        acct = self.accounts.get(token)
        if acct is not None:
            acct.update(updates)
        return acct


def _rec(email: str, token: str, **extra: Any) -> dict[str, Any]:
    base = {"email": email, "access_token": token}
    base.update(extra)
    return base


class TestReviveScriptDryRun:
    def _load(self):
        return _load_revive_script()

    def test_classify_splits_revivable_and_skipped(self) -> None:
        mod = self._load()
        svc = _FakeAcctSvc({
            "tok-ok": _abnormal_account("tok-ok", "ok@x.com"),
            "tok-normal": _abnormal_account("tok-normal", "normal@x.com", status="正常"),
            "tok-nocr": _abnormal_account("tok-nocr", "nocr@x.com"),
        })
        recs = [
            _rec("ok@x.com", "tok-ok", client_id="c", ms_rt="r", outlook_pw="p", gpt_pw="g"),
            _rec("normal@x.com", "tok-normal", client_id="c", ms_rt="r", outlook_pw="p", gpt_pw="g"),
            _rec("ghost@x.com", "tok-ghost", client_id="c", ms_rt="r", outlook_pw="p", gpt_pw="g"),
            _rec("nocr@x.com", "tok-nocr", gpt_pw="g"),
        ]
        result = mod.classify_recs(svc, recs)
        assert [rec["email"] for _, rec in result["revivable"]] == ["ok@x.com"]
        reasons = {rec["email"]: reason for _, rec, reason in result["skipped"]}
        assert reasons == {
            "normal@x.com": "账号已正常",
            "ghost@x.com": "库内无账号",
            "nocr@x.com": "无取件凭证",
        }

    def test_dry_run_marks_skipped_flag_only_for_no_credential(self) -> None:
        mod = self._load()
        svc = _FakeAcctSvc({
            "tok-normal": _abnormal_account("tok-normal", "normal@x.com", status="正常"),
            "tok-nocr": _abnormal_account("tok-nocr", "nocr@x.com"),
        })
        recs = [
            _rec("normal@x.com", "tok-normal", client_id="c", ms_rt="r", outlook_pw="p"),
            _rec("nocr@x.com", "tok-nocr", gpt_pw="g"),
        ]
        mod.classify_recs(svc, recs)
        # 仅无取件凭证账号被标记 revive_skipped；已正常/库内无账号不标记
        assert svc.accounts["tok-nocr"]["revive_skipped"] is True
        assert svc.accounts["tok-nocr"]["revive_skip_reason"] == "无取件凭证"
        assert "revive_skipped" not in svc.accounts["tok-normal"]
        marked = [token for token, _ in svc.updated]
        assert marked == ["tok-nocr"]

    def test_main_dry_run_does_not_call_login(self, monkeypatch, tmp_path) -> None:
        """--dry-run 走 main()：输出分类、标记 revive_skipped、不触网（login 不被调用）。"""
        mod = self._load()
        payload = tmp_path / "recover_payload.json"
        payload.write_text(json.dumps([
            _rec("ok@x.com", "tok-ok", client_id="c", ms_rt="r", outlook_pw="p", gpt_pw="g"),
            _rec("nocr@x.com", "tok-nocr", gpt_pw="g"),
        ]), encoding="utf-8")
        svc = _FakeAcctSvc({
            "tok-ok": _abnormal_account("tok-ok", "ok@x.com"),
            "tok-nocr": _abnormal_account("tok-nocr", "nocr@x.com"),
        })
        monkeypatch.setattr(mod, "RECOVER_FILE", str(payload))
        monkeypatch.setattr(mod, "account_service", svc)
        login_calls: list = []
        monkeypatch.setattr(mod.otp_login_service, "login",
                            lambda *a, **k: login_calls.append(1) or {"ok": False})
        monkeypatch.setattr(sys, "argv", ["revive_abnormal.py", "--dry-run"])
        with patch("sys.stdout"):
            mod.main()
        assert login_calls == []  # 不联网
        assert svc.accounts["tok-nocr"].get("revive_skipped") is True
        assert "revive_skipped" not in svc.accounts["tok-ok"]
