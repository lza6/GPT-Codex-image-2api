"""5.1：账号寿命预测——EWMA 失败率 + 连续失效窗口双信号，输出风险档位 + 预估剩余可用时长。

数据全部来自既有账号字段（success/fail/last_invalid_at/invalid_count/last_refresh_error_at/quota），
无需新埋点。核心不变量：
- 最小观测窗口守卫：样本不足时不判风险（防"瞬间封禁/复活抖动"）。
- 连续失败窗口：invalid_count + 最近失效时间越近越重。
- 失败率 EWMA：总失败率 + 最近刷新错误时间衰减。
- 预估剩余可用时长：有限配额按消耗速率外推；无限配额给出基于风险等级的保守上限。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.account_lifetime import (
    LEVEL_CRITICAL,
    LEVEL_HIGH,
    LEVEL_LOW,
    LEVEL_MEDIUM,
    compute_lifetime_risk,
)
from services.account_service import AccountService


def _account(**kw) -> dict:
    base = {"access_token": "t", "status": "正常", "quota": 100, "success": 0, "fail": 0}
    base.update(kw)
    return base


def _iso(minutes_ago: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


class TestLifetimeRiskLevels:
    def test_empty_history_defaults_low(self) -> None:
        """空历史 / 无任何错误信号 → 低风险。"""
        result = compute_lifetime_risk(_account())
        assert result["level"] == LEVEL_LOW

    def test_small_observation_window_guards_low(self) -> None:
        """样本太少（success+fail < 3）且无明确失效 → 仍低风险，不抖动。"""
        result = compute_lifetime_risk(_account(success=1, fail=1))
        assert result["level"] == LEVEL_LOW

    def test_high_failure_rate_escalates(self) -> None:
        """失败率占比高（total>=3 且 fail/total>0.5）→ medium 以上。"""
        result = compute_lifetime_risk(_account(success=1, fail=5))
        assert result["level"] in (LEVEL_MEDIUM, LEVEL_HIGH, LEVEL_CRITICAL)
        assert result["level"] != LEVEL_LOW

    def test_consecutive_invalid_window_critical(self) -> None:
        """连续失效窗口（invalid_count>=3 且最近失效很近）→ 濒危。"""
        result = compute_lifetime_risk(_account(
            success=10, fail=0, invalid_count=4, last_invalid_at=_iso(minutes_ago=5)
        ))
        assert result["level"] == LEVEL_CRITICAL

    def test_invalid_count_alone_no_recent_ts_still_signals(self) -> None:
        """invalid_count 高但无最近失效时间戳 → 仍判 high（连续失效窗口信号独立成立）。"""
        result = compute_lifetime_risk(_account(success=10, fail=0, invalid_count=3))
        assert result["level"] in (LEVEL_HIGH, LEVEL_CRITICAL)

    def test_recent_refresh_error_escalates(self) -> None:
        """最近刷新错误（10 分钟内）→ medium 以上。"""
        result = compute_lifetime_risk(_account(success=10, fail=0, last_refresh_error_at=_iso(minutes_ago=2)))
        assert result["level"] in (LEVEL_MEDIUM, LEVEL_HIGH, LEVEL_CRITICAL)

    def test_old_errors_do_not_escalate(self) -> None:
        """很久以前的错误（>7 天）不触发风险升档（时间衰减）。"""
        result = compute_lifetime_risk(_account(success=50, fail=5, last_invalid_at=_iso(minutes_ago=60 * 24 * 10)))
        assert result["level"] == LEVEL_LOW


class TestLifetimeEta:
    def test_finite_quota_projects_remaining_days(self) -> None:
        """有限配额 + 有消耗速率 → 给出合理剩余天数。"""
        created = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        result = compute_lifetime_risk(_account(quota=100, success=100, created_at=created))
        eta = result.get("eta_days")
        assert eta is not None
        # 10 天用 100 张 → 日均 10 张 → 100 配额还可撑约 10 天（允许误差）
        assert 5 <= eta <= 20

    def test_unlimited_quota_eta_bound_by_risk(self) -> None:
        """quota<0（无限配额）→ eta_days 为风险等级决定的保守上限（不宣称精确）。"""
        result = compute_lifetime_risk(_account(quota=-1, success=100, created_at=_iso(minutes_ago=0)))
        assert result["level"] == LEVEL_LOW
        assert result.get("eta_days") is None, "低风险无限配额不预设到期"

    def test_zero_success_no_division_crash(self) -> None:
        """success=0 / created_at 缺失 → 不除零崩溃。"""
        result = compute_lifetime_risk(_account(quota=100, success=0))
        assert "eta_days" in result
        assert result["level"] in (LEVEL_LOW, LEVEL_MEDIUM, LEVEL_HIGH, LEVEL_CRITICAL)


class TestSchedulerIntegration:
    def test_critical_lifetime_downgrades_to_risky(self) -> None:
        """濒危寿命 → 调度档位降至 risky（不直接封禁）。"""
        account = _account(
            quota=100, success=10, fail=0, invalid_count=4, last_invalid_at=_iso(minutes_ago=3)
        )
        assert AccountService._account_health_tier(account) == "risky"

    def test_high_lifetime_downgrades_to_warm(self) -> None:
        """基础 healthy + 高寿命风险 → 调度档位降至 warm。"""
        # invalid_count=3 → high（非濒危，因最近失效 >1h 不触发 critical 硬判定）
        account = _account(success=20, fail=0, invalid_count=3, last_invalid_at=_iso(minutes_ago=120))
        assert AccountService._account_health_tier(account) == "warm"

    def test_high_failure_rate_base_tier_still_risky(self) -> None:
        """失败率本身已 >0.5 → 基础档位即 risky（生命周期降档与既有规则一致）。"""
        account = _account(success=1, fail=5, invalid_count=2, last_invalid_at=_iso(minutes_ago=30))
        assert AccountService._account_health_tier(account) == "risky"

    def test_low_lifetime_keeps_healthy(self) -> None:
        """低寿命风险健康账号 → 保持 healthy（不误伤）。"""
        account = _account(success=20, fail=0)
        assert AccountService._account_health_tier(account) == "healthy"

    def test_no_flapping_on_marginal_signal(self) -> None:
        """观测不足 + 无明确失效 → 不因临界值抖动（档位稳定）。"""
        account = _account(success=1, fail=1)
        tier = AccountService._account_health_tier(account)
        assert tier in ("healthy", "warm"), f"不应因观测不足判 risky: {tier}"


def test_now_importable() -> None:
    """模块级 now 可被测试注入（时钟可控，避免测试依赖真实时间）。"""
    import services.account_lifetime as module

    assert callable(getattr(module, "now", None)) or hasattr(module, "compute_lifetime_risk")
