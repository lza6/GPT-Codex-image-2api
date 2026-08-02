"""调度器边界测试（阶段 7，D13）：调度分确定性/档位迁移/tie-break。"""

from __future__ import annotations

from services.account_service import AccountService


def _account(**kw) -> dict:
    base = {"access_token": "t", "status": "正常", "quota": 100, "success": 0, "fail": 0}
    base.update(kw)
    return base


class TestDispatchScore:
    def test_deterministic_same_input_same_output(self):
        acc = _account(quota=50, success=10, fail=2)
        s1 = AccountService._account_dispatch_score(acc)
        s2 = AccountService._account_dispatch_score(acc)
        assert s1 == s2

    def test_non_dict_returns_floor(self):
        assert AccountService._account_dispatch_score(None) == -100.0
        assert AccountService._account_dispatch_score("x") == -100.0

    def test_higher_quota_higher_score(self):
        low = AccountService._account_dispatch_score(_account(quota=10))
        high = AccountService._account_dispatch_score(_account(quota=100))
        assert high > low

    def test_fail_penalty_lowers_score(self):
        good = AccountService._account_dispatch_score(_account(success=10, fail=0))
        bad = AccountService._account_dispatch_score(_account(success=0, fail=10))
        assert good > bad

    def test_healthy_tier_beats_risky(self):
        healthy = AccountService._account_dispatch_score(_account(quota=100), tier="healthy")
        risky = AccountService._account_dispatch_score(_account(quota=100), tier="risky")
        assert healthy > risky


class TestHealthTier:
    def test_disabled_or_abnormal_is_risky(self):
        assert AccountService._account_health_tier(_account(status="禁用")) == "risky"
        assert AccountService._account_health_tier(_account(status="异常")) == "risky"

    def test_zero_quota_is_risky(self):
        assert AccountService._account_health_tier(_account(quota=0)) == "risky"

    def test_healthy_account(self):
        assert AccountService._account_health_tier(_account(quota=100, success=20, fail=0)) == "healthy"

    def test_high_fail_rate_is_risky(self):
        assert AccountService._account_health_tier(_account(quota=100, success=1, fail=10)) == "risky"

    def test_low_quota_is_warm(self):
        assert AccountService._account_health_tier(_account(quota=3, success=20, fail=0)) == "warm"
