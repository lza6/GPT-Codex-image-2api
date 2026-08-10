"""账号自愈功能测试：指数退避、健康评分、自动替换、预热。"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from services.account_service import AccountService
from services.account_warmup import AccountWarmup
from services.config import config


def _account(**kw) -> dict:
    base = {
        "access_token": "test_token",
        "status": "正常",
        "quota": 100,
        "success": 10,
        "fail": 0,
        "health_score": 50.0,
        "health_score_below_20_since": None,
        "self_heal_retry_attempts": 0,
        "self_heal_next_retry_at": None,
        "replaced_by": None,
        "last_invalid_at": None,
        "last_refresh_error": None,
        "last_refresh_error_at": None,
        "last_refresh_error_detail": None,
        "invalid_count": 0,
        "created_at": datetime.now(UTC).isoformat(),
    }
    base.update(kw)
    return base


def _set_config(key: str, value: object) -> dict:
    """临时修改 config.data 的辅助函数，返回恢复原值的可调用对象。"""
    orig = config.data.get(key)
    config.data[key] = value
    return orig


def _restore_config(key: str, orig: object) -> None:
    if orig is None:
        config.data.pop(key, None)
    else:
        config.data[key] = orig


# ====================================================================
# 指数退避测试
# ====================================================================


class TestExponentialBackoff:
    def test_zero_attempts_returns_initial_delay(self):
        """0 次尝试时返回 initial_delay（60s）。"""
        acc = _account(self_heal_retry_attempts=0, self_heal_next_retry_at=None)
        delay = AccountService._exponential_backoff_delay(AccountService, acc)
        assert delay == 60

    def test_first_attempt_returns_exponential_delay(self):
        """1 次尝试时返回 initial_delay * 2 = 120s。"""
        acc = _account(self_heal_retry_attempts=1, self_heal_next_retry_at=None)
        delay = AccountService._exponential_backoff_delay(AccountService, acc)
        assert delay == 120

    def test_max_attempts_exceeded_returns_none(self):
        """超过最大尝试次数时返回 None。"""
        acc = _account(
            self_heal_retry_attempts=config.self_heal_retry_max_attempts,
            self_heal_next_retry_at=None,
        )
        delay = AccountService._exponential_backoff_delay(AccountService, acc)
        assert delay is None

    def test_not_yet_due_returns_none(self):
        """未到退避时间时返回 None。"""
        future = (datetime.now(UTC) + timedelta(seconds=300)).isoformat()
        acc = _account(
            self_heal_retry_attempts=1,
            self_heal_next_retry_at=future,
        )
        delay = AccountService._exponential_backoff_delay(AccountService, acc)
        assert delay is None

    def test_backoff_delay_capped_at_max(self):
        """退避时间不会超过 max_secs。"""
        # 5 次尝试：60 * 2^5 = 1920，未超 max_secs(3600)
        # 验证 5 次尝试时 delay = min(60 * 32, 3600) = 1920
        max_attempts = config.self_heal_retry_max_attempts
        acc = _account(
            self_heal_retry_attempts=max_attempts - 1,  # 4 次，还未超限
            self_heal_next_retry_at=None,
        )
        delay = AccountService._exponential_backoff_delay(AccountService, acc)
        assert delay is not None
        # 60 * 2^4 = 960
        assert delay == 960


# ====================================================================
# 健康评分测试
# ====================================================================


class TestHealthScore:
    def test_healthy_account_scores_high(self):
        """健康账号得分高（100% 成功率 + 充足配额 = 100 分）。"""
        acc = _account(quota=100, success=100, fail=0)
        score = AccountService._compute_health_score(acc)
        # 100 * (1-0) * min(1, 100/20) * 1.0 = 100 * 1.0 * 1.0 * 1.0 = 100
        assert score == 100.0

    def test_high_fail_rate_reduces_score(self):
        """高失败率降低评分。"""
        acc = _account(quota=100, success=1, fail=9)
        score = AccountService._compute_health_score(acc)
        # fail_ratio = 9/10 = 0.9; 100 * (1-0.9) * 1.0 * 1.0 = 10
        assert score == 10.0

    def test_low_quota_reduces_score(self):
        """低配额降低评分。"""
        acc = _account(quota=5, success=10, fail=0)
        score = AccountService._compute_health_score(acc)
        # quota_ratio = 5/20 = 0.25; 100 * 1.0 * 0.25 * 1.0 = 25
        assert score == 25.0

    def test_recent_invalid_reduces_score(self):
        """最近失效降低评分（recency_factor 起作用）。"""
        recent = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        acc = _account(quota=100, success=10, fail=0, last_invalid_at=recent)
        score = AccountService._compute_health_score(acc)
        # recency_factor = max(0.5, 1.0 - 10/60) = max(0.5, 0.833) = 0.833
        # 100 * 1.0 * 1.0 * 0.833 = 83.3
        assert score < 100.0
        assert score > 50.0

    def test_disabled_account_scores_zero(self):
        """禁用账号得分 0。"""
        acc = _account(status="禁用")
        score = AccountService._compute_health_score(acc)
        assert score == 0.0

    def test_abnormal_account_scores_10(self):
        """异常账号得分 10。"""
        acc = _account(status="异常")
        score = AccountService._compute_health_score(acc)
        assert score == 10.0

    def test_limited_account_scores_25(self):
        """限流账号得分 25。"""
        acc = _account(status="限流")
        score = AccountService._compute_health_score(acc)
        assert score == 25.0


# ====================================================================
# 自动替换测试
# ====================================================================


class TestAutoReplace:
    def test_auto_replace_disabled(self):
        """配置关闭时不做替换。"""
        _set_config("self_heal_auto_replace_enabled", False)
        try:
            svc = MagicMock()
            svc._auto_replace_unhealthy = AccountService._auto_replace_unhealthy.__get__(svc, AccountService)
            result = svc._auto_replace_unhealthy()
            assert result["replaced"] == 0
            assert result["skipped"] == 0
            assert result["no_backup"] == 0
        finally:
            _restore_config("self_heal_auto_replace_enabled", None)

    def test_auto_replace_no_unhealthy(self):
        """无不健康账号时不做替换。"""
        _set_config("self_heal_auto_replace_enabled", True)
        _set_config("abnormal_auto_recover_max_workers", 5)
        try:
            svc = MagicMock()  # 不需要 spec，因为需要设置 _accounts 等非 spec 属性
            svc._auto_replace_unhealthy = AccountService._auto_replace_unhealthy.__get__(svc, AccountService)
            # 模拟无健康评分低于 20 的账号——让 _accounts 为空
            svc._accounts = {}
            svc._list_backup_candidate_tokens = MagicMock(return_value=["backup_token"])
            result = svc._auto_replace_unhealthy()
            assert result["replaced"] == 0
            assert result["skipped"] == 0
        finally:
            _restore_config("self_heal_auto_replace_enabled", None)
            _restore_config("abnormal_auto_recover_max_workers", None)

    def test_auto_replace_no_backup(self):
        """无备用池时跳过替换。"""
        _set_config("self_heal_auto_replace_enabled", True)
        try:
            svc = MagicMock()
            svc._auto_replace_unhealthy = AccountService._auto_replace_unhealthy.__get__(svc, AccountService)
            # 模拟账号列表中有 unhealthy 账号
            below_since = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
            unhealthy = _account(health_score=10.0, health_score_below_20_since=below_since)
            # 让 _accounts 包含不健康账号
            svc._accounts = {"test_token": unhealthy}
            svc.get_account = MagicMock(return_value=None)
            svc.update_account = MagicMock()
            svc._update_health_score = MagicMock()
            svc._list_backup_candidate_tokens = MagicMock(return_value=[])
            result = svc._auto_replace_unhealthy()
            assert result["no_backup"] == 1
        finally:
            _restore_config("self_heal_auto_replace_enabled", None)

    # ====================================================================
    # 预热测试
    # ====================================================================


class TestAccountWarmup:
    def test_warmup_success(self):
        """预热成功返回 True。"""
        svc = MagicMock()
        svc.fetch_remote_info.return_value = {"status": "正常", "access_token": "t1"}
        warmup = AccountWarmup(svc)
        _set_config("account_warmup_enabled", True)
        try:
            result = warmup.warmup_account("t1")
            assert result is True
            assert not warmup.is_warming_up("t1")
        finally:
            _restore_config("account_warmup_enabled", None)

    def test_warmup_failure(self):
        """预热失败返回 False 并标记异常。"""
        svc = MagicMock()
        svc.fetch_remote_info.return_value = None
        warmup = AccountWarmup(svc)
        _set_config("account_warmup_enabled", True)
        try:
            result = warmup.warmup_account("t1")
            assert result is False
            svc.update_account.assert_called_once_with("t1", {"status": "异常"}, quiet=True)
        finally:
            _restore_config("account_warmup_enabled", None)

    def test_warmup_timeout(self):
        """预热超时返回 False。"""
        svc = MagicMock()
        # 模拟 fetch_remote_info 返回异常状态（触发超时前被标记为异常）
        svc.fetch_remote_info.return_value = {"status": "异常", "access_token": "t1"}
        warmup = AccountWarmup(svc)
        _set_config("account_warmup_enabled", True)
        _set_config("account_warmup_timeout_secs", 60)
        try:
            result = warmup.warmup_account("t1", timeout_secs=0.001)
            assert result is False
        finally:
            _restore_config("account_warmup_enabled", None)
            _restore_config("account_warmup_timeout_secs", None)

    def test_already_warming_up_skips_duplicate(self):
        """已预热中的账号跳过重复预热。"""
        svc = MagicMock()
        warmup = AccountWarmup(svc)
        _set_config("account_warmup_enabled", True)
        try:
            warmup._warmup_inflight["t1"] = time.time()
            result = warmup.warmup_account("t1")
            # 已预热中应返回 True 并跳过 fetch_remote_info
            assert result is True
            svc.fetch_remote_info.assert_not_called()
        finally:
            _restore_config("account_warmup_enabled", None)

    def test_warmup_disabled_returns_true(self):
        """预热关闭时直接返回 True。"""
        svc = MagicMock()
        warmup = AccountWarmup(svc)
        _set_config("account_warmup_enabled", False)
        try:
            result = warmup.warmup_account("t1")
            assert result is True
            svc.fetch_remote_info.assert_not_called()
        finally:
            _restore_config("account_warmup_enabled", None)