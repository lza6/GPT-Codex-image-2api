"""属性基测试（hypothesis）：调度分/健康档位/预测选取/加权选取。"""

from __future__ import annotations

import random
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis.strategies import (
    booleans,
    builds,
    floats,
    integers,
    just,
    lists,
    none,
    one_of,
    sampled_from,
    text,
)

from services.account_service import AccountService


# ============================================================
# Mock storage
# ============================================================


class MemoryStorage:
    """内存存储后端，不对持久化做任何假设。"""

    def __init__(self, accounts: list[dict[str, Any]] | None = None) -> None:
        self.accounts = accounts or []

    def load_accounts(self) -> list[dict[str, Any]]:
        return self.accounts

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        self.accounts = accounts


def _make_account(**kw: Any) -> dict:
    base: dict[str, Any] = {
        "access_token": "test_token",
        "status": "正常",
        "quota": 100,
        "success": 0,
        "fail": 0,
        "last_refresh_error_at": None,
        "last_token_refresh_error_at": None,
        "last_used_at": None,
    }
    base.update(kw)
    return base


# ============================================================
# Strategies
# ============================================================

quota_strategy = integers(min_value=0, max_value=1_000_000)
count_strategy = integers(min_value=0, max_value=10_000)
statuses = sampled_from(["正常", "禁用", "异常", "限流"])
bad_inputs = one_of(none(), just(""), just(42), just([]))


# ============================================================
# _account_dispatch_score
# ============================================================


class TestDispatchScoreProperties:
    """_account_dispatch_score 属性测试：分数范围、单调性、确定性。"""

    @given(quota=quota_strategy, success=count_strategy, fail=count_strategy)
    def test_score_is_finite(self, quota: int, success: int, fail: int) -> None:
        """有效 dict 返回有限浮点数。"""
        acc = _make_account(quota=quota, success=success, fail=fail)
        score = AccountService._account_dispatch_score(acc)
        assert isinstance(score, float)
        assert score > -1e6

    @given(bad=bad_inputs)
    def test_non_dict_returns_floor(self, bad: Any) -> None:
        """非 dict → -100.0。"""
        assert AccountService._account_dispatch_score(bad) == -100.0

    @given(quota=quota_strategy)
    def test_higher_quota_never_lowers_score(self, quota: int) -> None:
        """更大 quota 不降低分数。"""
        high = min(quota + 1, 1_000_000)
        s_low = AccountService._account_dispatch_score(_make_account(quota=quota))
        s_high = AccountService._account_dispatch_score(_make_account(quota=high))
        assert s_high >= s_low

    @given(success=count_strategy, fail=count_strategy)
    def test_more_fail_never_raises_score(self, success: int, fail: int) -> None:
        """更多失败不提高分数。"""
        assume(success + fail > 0)
        base = _make_account(quota=100, success=success, fail=fail)
        more = _make_account(quota=100, success=success, fail=fail + 1)
        s_base = AccountService._account_dispatch_score(base)
        s_more = AccountService._account_dispatch_score(more)
        assert s_more <= s_base

    @given(quota=quota_strategy)
    def test_healthy_beats_risky(self, quota: int) -> None:
        """healthy 档位分数 > risky 档位分数（同 quota 下）。"""
        h = AccountService._account_dispatch_score(_make_account(quota=quota), tier="healthy")
        r = AccountService._account_dispatch_score(_make_account(quota=quota), tier="risky")
        assert h > r

    @given(quota=quota_strategy)
    def test_healthy_beats_warm_beats_risky(self, quota: int) -> None:
        """healthy > warm > risky（同 quota 下）。"""
        h = AccountService._account_dispatch_score(_make_account(quota=quota), tier="healthy")
        w = AccountService._account_dispatch_score(_make_account(quota=quota), tier="warm")
        r = AccountService._account_dispatch_score(_make_account(quota=quota), tier="risky")
        assert h > w > r

    @given(quota=quota_strategy, success=count_strategy, fail=count_strategy)
    def test_deterministic(self, quota: int, success: int, fail: int) -> None:
        """相同输入产生相同分数。"""
        acc = _make_account(quota=quota, success=success, fail=fail)
        s1 = AccountService._account_dispatch_score(acc)
        s2 = AccountService._account_dispatch_score(acc)
        assert s1 == s2

    @given(quota=quota_strategy, success=count_strategy, fail=count_strategy)
    def test_score_in_reasonable_range(self, quota: int, success: int, fail: int) -> None:
        """分数在合理范围内。"""
        acc = _make_account(quota=quota, success=success, fail=fail)
        score = AccountService._account_dispatch_score(acc)
        assert -100.0 <= score <= 200.0

    def test_new_account_without_errors_scores_high(self) -> None:
        """无错误且高配额 → 接近档位上限。"""
        acc = _make_account(quota=1000, success=50, fail=0)
        score = AccountService._account_dispatch_score(acc, tier="healthy")
        # 基础 100 + 配额 10( capped) + 成功加成 5 = 115 左右
        assert 100.0 <= score <= 120.0


# ============================================================
# _account_health_tier
# ============================================================


class TestHealthTierProperties:
    """_account_health_tier_base 属性测试：档位值域、边界条件、确定性。"""

    @given(status=statuses, quota=quota_strategy)
    def test_tier_in_valid_set(self, status: str, quota: int) -> None:
        """档位始终 ∈ {healthy, warm, risky}。"""
        tier = AccountService._account_health_tier_base(_make_account(status=status, quota=quota))
        assert tier in {"healthy", "warm", "risky"}

    @given(status=sampled_from(["禁用", "异常"]))
    def test_disabled_or_abnormal_is_risky(self, status: str) -> None:
        """禁用/异常 → risky。"""
        assert AccountService._account_health_tier_base(_make_account(status=status)) == "risky"

    @given(status=just("限流"))
    def test_limited_is_risky(self, status: str) -> None:
        """限流 → risky。"""
        assert AccountService._account_health_tier_base(_make_account(status="限流")) == "risky"

    @given(quota=integers(min_value=5, max_value=1_000_000))
    def test_healthy_account_returns_healthy(self, quota: int) -> None:
        """正常+高配额+无失败+total>=3 → healthy。"""
        tier = AccountService._account_health_tier_base(
            _make_account(quota=quota, success=50, fail=0)
        )
        assert tier == "healthy"

    @given(fail=integers(min_value=3, max_value=1000))
    def test_high_fail_rate_is_risky(self, fail: int) -> None:
        """高失败率（>50% 且 total>=3）→ risky。"""
        acc = _make_account(quota=100, success=0, fail=fail)
        assert AccountService._account_health_tier_base(acc) == "risky"

    @given(quota=integers(min_value=0, max_value=4))
    def test_low_quota_is_not_healthy(self, quota: int) -> None:
        """低配额 → risky 或 warm（非 healthy）。"""
        tier = AccountService._account_health_tier_base(
            _make_account(quota=quota, success=50, fail=0)
        )
        assert tier in {"risky", "warm"}

    def test_zero_quota_risky(self) -> None:
        """quota=0 → risky。"""
        assert AccountService._account_health_tier_base(_make_account(quota=0)) == "risky"

    @given(bad=bad_inputs)
    def test_non_dict_returns_risky(self, bad: Any) -> None:
        """非 dict → risky。"""
        assert AccountService._account_health_tier_base(bad) == "risky"

    @given(status=statuses, quota=quota_strategy, fail=count_strategy, success=count_strategy)
    def test_deterministic(self, status: str, quota: int, fail: int, success: int) -> None:
        """相同输入产生相同档位。"""
        acc = _make_account(status=status, quota=quota, fail=fail, success=success)
        assert AccountService._account_health_tier_base(acc) == AccountService._account_health_tier_base(acc)

    @given(fail=count_strategy, success=count_strategy)
    def test_moderate_fail_rate_is_warm(self, fail: int, success: int) -> None:
        """中等失败率（20%-50% 且 total>=3）→ warm。

        用整数不等式与实现 `fail/total > 0.2` 完全对齐，
        避免 hypothesis 浮点边界与实现浮点舍入不一致导致的偶发失败。
        """
        assume(success > 0 and fail > 0)
        total = fail + success
        assume(total >= 3)
        assume(fail * 5 > total)  # fail/total > 0.2 ⇔ 5*fail > total
        assume(fail * 2 <= total)  # fail/total <= 0.5 ⇔ 2*fail <= total
        acc = _make_account(quota=100, success=success, fail=fail)
        tier = AccountService._account_health_tier_base(acc)
        assert tier == "warm", f"fail={fail} total={total}, tier={tier}"


# ============================================================
# _weighted_pick
# ============================================================


class TestWeightedPickProperties:
    """_weighted_pick 属性测试：返回元素、概率偏斜、异常安全。"""

    @staticmethod
    def _service(accounts: list[dict] | None = None) -> AccountService:
        svc = AccountService(MemoryStorage(accounts or []))
        return svc

    @given(tokens=lists(text(min_size=1, max_size=10), min_size=1, max_size=10))
    def test_returns_element_from_list(self, tokens: list[str]) -> None:
        """返回列表中的元素。"""
        svc = self._service()
        for t in tokens:
            svc._accounts[t] = _make_account(access_token=t)
        picked = svc._weighted_pick(tokens)
        assert picked in tokens

    def test_single_element(self) -> None:
        """单元素列表返回该元素。"""
        svc = self._service()
        svc._accounts["t1"] = _make_account(access_token="t1")
        assert svc._weighted_pick(["t1"]) == "t1"

    @given(tokens=lists(text(min_size=1, max_size=5), min_size=2, max_size=5))
    def test_returns_string(self, tokens: list[str]) -> None:
        """总是返回字符串。"""
        svc = self._service()
        for t in tokens:
            svc._accounts[t] = _make_account(access_token=t)
        assert isinstance(svc._weighted_pick(tokens), str)

    def test_high_score_picked_more_often(self) -> None:
        """高调度分账号被选中的概率显著更高。"""
        random.seed(42)
        svc = self._service()
        svc._accounts["good"] = _make_account(access_token="good", quota=10000, success=100, fail=0)
        svc._accounts["bad"] = _make_account(
            access_token="bad", quota=0, success=0, fail=100, status="限流"
        )
        counts = {"good": 0, "bad": 0}
        for _ in range(2000):
            picked = svc._weighted_pick(["good", "bad"])
            counts[picked] += 1
        assert counts["good"] > counts["bad"], f"good={counts['good']}, bad={counts['bad']}"

    def test_ghost_token_does_not_raise(self) -> None:
        """列表中账号不在 _accounts 中时不抛异常。"""
        svc = self._service()
        picked = svc._weighted_pick(["ghost"])
        assert picked == "ghost"

    @given(tokens=lists(text(min_size=1, max_size=10), min_size=1, max_size=10))
    def test_all_equal_scores_no_exception(self, tokens: list[str]) -> None:
        """等分账号不抛异常。"""
        svc = self._service()
        for t in tokens:
            svc._accounts[t] = _make_account(access_token=t, quota=100, success=10, fail=0)
        picked = svc._weighted_pick(tokens)
        assert picked in tokens


# ============================================================
# _pick_predictive
# ============================================================


class TestPickPredictiveProperties:
    """_pick_predictive 属性测试：返回元素、配额偏好、异常安全。"""

    @staticmethod
    def _service(accounts: list[dict] | None = None) -> AccountService:
        return AccountService(MemoryStorage(accounts or []))

    @given(tokens=lists(text(min_size=1, max_size=10), min_size=1, max_size=10))
    def test_returns_element_from_list(self, tokens: list[str]) -> None:
        """返回列表中的元素。"""
        svc = self._service()
        for t in tokens:
            svc._accounts[t] = _make_account(access_token=t)
        picked = svc._pick_predictive(tokens)
        assert picked in tokens

    def test_raises_on_empty_list(self) -> None:
        """空列表抛 RuntimeError。"""
        with pytest.raises(RuntimeError):
            self._service()._pick_predictive([])

    def test_single_element(self) -> None:
        """单元素列表返回该元素。"""
        svc = self._service()
        svc._accounts["t1"] = _make_account(access_token="t1")
        assert svc._pick_predictive(["t1"]) == "t1"

    @given(quota=quota_strategy, success=count_strategy, fail=count_strategy)
    def test_higher_quota_preferred(self, quota: int, success: int, fail: int) -> None:
        """同成功/失败计数下，更高配额账号优先被选。"""
        assume(quota > 0)
        svc = self._service()
        now = "2026-01-01 12:00:00"
        svc._accounts["low"] = _make_account(
            access_token="low", quota=quota, success=success, fail=fail, last_used_at=now,
        )
        svc._accounts["high"] = _make_account(
            access_token="high", quota=quota + 1000, success=success, fail=fail, last_used_at=now,
        )
        picked = svc._pick_predictive(["low", "high"])
        assert picked == "high"

    @given(tokens=lists(text(min_size=1, max_size=5), min_size=2, max_size=5))
    def test_returns_string(self, tokens: list[str]) -> None:
        """总是返回字符串。"""
        svc = self._service()
        for t in tokens:
            svc._accounts[t] = _make_account(access_token=t)
        assert isinstance(svc._pick_predictive(tokens), str)

    @given(quota=quota_strategy)
    def test_no_history_picks_high_quota(self, quota: int) -> None:
        """无历史数据（success=0, fail=0）时选高配额账号。"""
        assume(quota > 0)
        svc = self._service()
        now = "2026-01-01 12:00:00"
        svc._accounts["low"] = _make_account(access_token="low", quota=quota, last_used_at=now)
        svc._accounts["high"] = _make_account(access_token="high", quota=quota + 500, last_used_at=now)
        picked = svc._pick_predictive(["low", "high"])
        assert picked == "high"

    def test_quota_zero_avoids_negative(self) -> None:
        """quota=0 的账号不会被选，除非列表中只有它。"""
        svc = self._service()
        svc._accounts["a"] = _make_account(access_token="a", quota=0, success=5, fail=0, last_used_at="2026-01-01 12:00:00")
        svc._accounts["b"] = _make_account(access_token="b", quota=100, success=5, fail=0, last_used_at="2026-01-01 12:00:00")
        picked = svc._pick_predictive(["a", "b"])
        assert picked == "b"  # 有正 quota 的账号被选


# ============================================================
# 确保文件不为空
# ============================================================


def test_module_loads() -> None:
    """模块加载验证。"""
    assert True