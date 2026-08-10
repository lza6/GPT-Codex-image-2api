"""v2.14.0：异常账号根因可溯源闭环回归测试。

验证点：
- _record_invalid_token_seen 保存原始 error 到 last_refresh_error_detail。
- remove_invalid_token 后续调用不得覆盖 detail（保留根因）。
- _record_refresh_success 清零 detail（恢复后清空）。
- _normalize_account 正确归一化 detail 字段。
"""

from __future__ import annotations

from services.account_service import AccountService, config
from services.storage.json_storage import JSONStorageBackend


def _make_svc(tmp_path) -> AccountService:
    storage = JSONStorageBackend(tmp_path / "accounts.json")
    svc = AccountService(storage)
    token = "abnormal-root-cause-token"
    svc._accounts[token] = {
        "access_token": token,
        "status": "正常",
        "quota": 100,
        "success": 0,
        "fail": 0,
        "invalid_count": 0,
    }
    return svc, token


class TestAbnormalRootCause:
    def test_record_invalid_preserves_detail(self, tmp_path):
        """_record_invalid_token_seen 保存原始错误到 last_refresh_error_detail。"""
        svc, token = _make_svc(tmp_path)
        raw_err = "InvalidAccessTokenError: 401 token_revoked by upstream"
        svc._record_invalid_token_seen(token, "refresh_accounts", raw_err, defer_invalid_removal=False)
        acct = svc.get_account(token)
        assert acct is not None
        assert acct["last_refresh_error_detail"] == raw_err
        assert acct["last_refresh_error"] == raw_err

    def test_remove_invalid_token_does_not_overwrite_detail(self, tmp_path):
        """remove_invalid_token 后续调用不得覆盖已保存的 detail。"""
        svc, token = _make_svc(tmp_path)
        # 先记录原始错误
        raw_err = "InvalidAccessTokenError: 401 token_revoked by upstream"
        svc._record_invalid_token_seen(token, "fetch_remote_info", raw_err, defer_invalid_removal=False)
        # 关闭自动移除，走标记异常分支
        old_auto_remove = config.data.get("auto_remove_invalid_accounts", False)
        config.data["auto_remove_invalid_accounts"] = False
        # 模拟 fetch_remote_info 后续 remove_invalid_token(event-only)
        svc.remove_invalid_token(token, "fetch_remote_info:invalid_access_token", quiet=True)
        acct = svc.get_account(token)
        assert acct is not None
        assert acct["status"] == "异常"
        # detail 必须保留原始错误，不被 event 覆盖
        assert acct["last_refresh_error_detail"] == raw_err
        # last_refresh_error 可能被 event 更新，但 detail 独立保留
        assert acct["last_refresh_error"] is not None

    def test_remove_invalid_token_without_prior_detail_falls_back_to_event(self, tmp_path):
        """无前置 _record_invalid_token_seen 时，detail 回退到 event（向后兼容旧数据）。"""
        svc, token = _make_svc(tmp_path)
        # 关闭自动移除
        config.data["auto_remove_invalid_accounts"] = False
        svc.remove_invalid_token(token, "evict_stale", quiet=True)
        acct = svc.get_account(token)
        assert acct is not None
        # 旧数据无 detail 时，回退到 event 保证页面不再显示"未知错误"
        assert acct["last_refresh_error"] == "evict_stale"
        assert acct["last_refresh_error_detail"] is None  # 无前置 detail，保持 None

    def test_refresh_success_clears_detail(self, tmp_path):
        """_record_refresh_success 清零 detail（恢复后清空根因）。"""
        svc, token = _make_svc(tmp_path)
        raw_err = "InvalidAccessTokenError: 401 token_revoked"
        svc._record_invalid_token_seen(token, "refresh_accounts", raw_err, defer_invalid_removal=False)
        assert svc.get_account(token)["last_refresh_error_detail"] == raw_err
        # 刷新成功应清零
        svc._record_refresh_success(token)
        acct = svc.get_account(token)
        assert acct["last_refresh_error_detail"] is None
        assert acct["last_refresh_error"] is None
        assert acct["invalid_count"] == 0

    def test_apply_refreshed_tokens_clears_detail(self, tmp_path):
        """token 轮换成功（refresh_token 换新 access_token）也应清零 detail。"""
        svc, token = _make_svc(tmp_path)
        raw_err = "oauth_refresh_http_400: invalid_grant"
        svc._record_invalid_token_seen(token, "keepalive", raw_err, defer_invalid_removal=False)
        # 模拟 refresh_token 成功轮换
        svc._apply_refreshed_tokens(token, {
            "access_token": "new-rotated-token",
            "refresh_token": "new-rt",
            "id_token": "",
        }, "refresh_token_keepalive")
        # 旧 token 已被 alias 指向新 token
        resolved = svc.resolve_access_token(token)
        acct = svc.get_account(resolved)
        assert acct is not None
        assert acct["last_refresh_error_detail"] is None
        assert acct["last_refresh_error"] is None

    def test_normalize_account_handles_detail_field(self, tmp_path):
        """_normalize_account 正确归一化 detail 字段（None / 字符串）。"""
        svc, _ = _make_svc(tmp_path)
        # 字符串 detail
        norm1 = svc._normalize_account({"access_token": "x", "last_refresh_error_detail": "some error"})
        assert norm1["last_refresh_error_detail"] == "some error"
        # 空值归 None
        norm2 = svc._normalize_account({"access_token": "y", "last_refresh_error_detail": None})
        assert norm2["last_refresh_error_detail"] is None
        # 缺失字段归 None
        norm3 = svc._normalize_account({"access_token": "z"})
        assert norm3["last_refresh_error_detail"] is None
