"""调度器边界测试（阶段 7，D13）：调度分确定性/档位迁移/tie-break。"""

from __future__ import annotations

import pytest

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

    def test_quota_boundary_four_is_warm_five_is_healthy(self):
        """配额阈值边界：quota=4 → warm，quota=5 → healthy（同成功无失败）。"""
        assert AccountService._account_health_tier(_account(quota=4, success=20, fail=0)) == "warm"
        assert AccountService._account_health_tier(_account(quota=5, success=20, fail=0)) == "healthy"

    def test_quota_boundary_ten_is_still_healthy(self):
        """配额阈值未被抬高：quota=5~10 区间仍为 healthy（若阈值抬到10则变 warm）。"""
        assert AccountService._account_health_tier(_account(quota=7, success=20, fail=0)) == "healthy"
        assert AccountService._account_health_tier(_account(quota=9, success=20, fail=0)) == "healthy"


class TestHealthScoreBoundaries:
    """健康评分数值边界：quota_ratio 分母 20.0 的精确断言。"""

    def test_health_score_quota_ratio_denominator_is_20(self):
        """quota=20 → quota_ratio=1.0；quota=10 → 0.5；quota=40 → 1.0（封顶）。"""
        s20 = AccountService.get_account_health_score(_account(quota=20, success=10, fail=0))
        s10 = AccountService.get_account_health_score(_account(quota=10, success=10, fail=0))
        s40 = AccountService.get_account_health_score(_account(quota=40, success=10, fail=0))
        # 无失败：base = 70 * 1.0 * quota_ratio
        assert s20 == pytest.approx(70.0)
        assert s10 == pytest.approx(35.0)
        assert s40 == pytest.approx(70.0)  # 封顶 1.0
        # 若分母漂移到 40：quota=20 将只给 0.5 → 35.0，变红

    def test_health_score_quota_ratio_zero_quota(self):
        """quota=0 → quota_ratio=0 → 分数 0。"""
        s = AccountService.get_account_health_score(_account(quota=0, success=10, fail=0))
        assert s == 0.0


class TestDispatchScoreCooldownWindow:
    """冷却惩罚窗口 1800s 的精确边界断言。"""

    @staticmethod
    def _with_refresh_err(seconds_ago: float) -> dict:
        import time

        return _account(
            quota=100,
            success=10,
            fail=0,
            last_refresh_error_at=time.time() - seconds_ago,
        )

    def test_cooldown_penalty_window_is_1800(self):
        """1800s 以内最近错误惩罚、1800s 以外不惩罚。"""
        # 1780s 前（<1800）：应受惩罚，分数低于无错误
        within = AccountService._account_dispatch_score(self._with_refresh_err(1780))
        clean = AccountService._account_dispatch_score(_account(quota=100, success=10, fail=0))
        assert within < clean
        # 2000s 前（>1800）：不再惩罚，分数与无错误相同
        beyond = AccountService._account_dispatch_score(self._with_refresh_err(2000))
        assert beyond == clean
        # 若窗口漂移到 3600：2000s 前将受惩罚 → 变红

    def test_cooldown_penalty_weighs_by_recency(self):
        """越近的惩罚越重：100s 前的惩罚 > 1700s 前的惩罚。"""
        near = AccountService._account_dispatch_score(self._with_refresh_err(100))
        far = AccountService._account_dispatch_score(self._with_refresh_err(1700))
        assert near < far


class TestDispatchScoreExactValues:
    """调度分精确数值断言（变异探针锚点）：系数翻倍必变红。"""

    def test_quota_ceiling_is_exactly_10(self):
        """quota=200 → 配额占比贡献 10.0（封顶 10，非 20）。"""
        s = AccountService._account_dispatch_score(_account(quota=200, success=0, fail=0), tier="healthy")
        # base 100 + quota_cap 10 = 110
        assert s == pytest.approx(110.0)

    def test_success_bonus_coefficient_is_5(self):
        """success=fail 全成功 → 加成 5.0。"""
        s = AccountService._account_dispatch_score(_account(quota=100, success=10, fail=0), tier="healthy")
        # 100 + min(10,10)=10 + 5.0*(10/10)=5 → 115
        assert s == pytest.approx(115.0)

    def test_fail_penalty_coefficient_is_10(self):
        """全失败 → 惩罚 10.0。"""
        s = AccountService._account_dispatch_score(_account(quota=100, success=0, fail=10), tier="healthy")
        # 100 + 10 - 10.0*(10/10)=10 → 100
        assert s == pytest.approx(100.0)

    def test_refresh_error_window_is_600(self):
        """800s 前的刷新错误不再降档（窗口 600，非 1200）。"""
        import time

        acc = _account(quota=100, success=20, fail=0, last_refresh_error_at=time.time() - 800)
        assert AccountService._account_health_tier(acc) == "healthy"

    def test_high_fail_rate_threshold_is_half(self):
        """fail/(fail+success)=0.6 → risky（阈值 0.5，非 0.6）。"""
        acc = _account(quota=100, success=4, fail=6)
        assert AccountService._account_health_tier(acc) == "risky"

    def test_new_account_invalid_grace_is_600_seconds(self):
        """新账号无效宽限期精确断言。"""
        assert AccountService._NEW_ACCOUNT_INVALID_GRACE_SECONDS == 600

    def test_account_list_cache_ttl_is_5_seconds(self):
        """账号列表缓存 TTL 精确断言。"""
        assert AccountService._ACCOUNT_LIST_CACHE_TTL == 5.0
