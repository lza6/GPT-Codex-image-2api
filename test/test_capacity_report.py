"""5.2：容量规划报表——日均请求/活跃账号/单账号日均消耗/外推需新号数。

验证点：
- 数据源是聚合缓存（mock 断言 _collect_capacity 不调 log_service.list 全量扫描）。
- 边界：空数据 / 单账号 / 零增长率不除零崩溃。
- 字段对齐：days/avg_daily_requests/active_accounts/per_account_daily/growth_rate/suggested_new_accounts/series。
"""

from __future__ import annotations

import api.dashboard as dashboard


def _series(total_days: int, per_day: int) -> list[dict]:
    """构造近 N 天每日成功数序列（新→旧，最后一天为今天）。"""
    from datetime import datetime, timedelta

    today = datetime.now().date()
    return [
        {"date": (today - timedelta(days=total_days - 1 - i)).strftime("%Y-%m-%d"), "calls": per_day}
        for i in range(total_days)
    ]


class TestCapacityReport:
    def test_data_source_is_aggregation_cache(self, monkeypatch) -> None:
        """5.2 慢查询守卫：容量报表必须走聚合缓存，禁止全量扫 logs.jsonl。"""
        import services.log_service as log_service_module

        calls = {"n": 0}

        def _forbidden(*args, **kwargs):  # pragma: no cover - 触发即失败
            calls["n"] += 1
            raise AssertionError("capacity 不应调用 log_service.list 全量扫描")

        monkeypatch.setattr(log_service_module.log_service, "list", _forbidden)

        # 用真实聚合缓存（测试环境 data/ 为空态 → 走空数据处理路径）
        result = dashboard._collect_capacity(windows_days=7)
        assert isinstance(result, dict)
        assert calls["n"] == 0

    def test_empty_data_no_crash(self, monkeypatch) -> None:
        """空数据：不除零，返回 0 占位。"""
        import services.usage_agg as usage_agg_module

        class _EmptyAgg:
            def daily_success_series(self, window_days: int) -> list[dict]:
                return []

        monkeypatch.setattr(usage_agg_module, "usage_agg", _EmptyAgg())
        result = dashboard._collect_capacity(windows_days=7)
        assert result["avg_daily_requests"] == 0
        assert result["active_accounts"] == 0
        assert result["per_account_daily"] == 0
        assert result["suggested_new_accounts"] == 0
        assert result["series"] == []

    def test_single_account_zero_growth_no_crash(self, monkeypatch) -> None:
        """单账号 + 零增长率：不除零，suggested_new_accounts 为 0。"""
        import services.usage_agg as usage_agg_module

        class _Agg:
            def daily_success_series(self, window_days: int) -> list[dict]:
                return _series(total_days=7, per_day=10)

        monkeypatch.setattr(usage_agg_module, "usage_agg", _Agg())

        # 构造一个活跃账号（success>0）
        account = {"access_token": "t", "status": "正常", "quota": 100, "success": 70, "fail": 0}
        monkeypatch.setattr(dashboard.account_service, "list_accounts", lambda: [account])

        result = dashboard._collect_capacity(windows_days=7)
        assert result["active_accounts"] == 1
        assert result["per_account_daily"] > 0
        assert result["growth_rate"] == 0.0  # 前后半窗口日均一致 → 零增长
        # 目标=当前日均×2，缺口=当前日均，单号日均=当前日均 → 需新增 1 号
        assert result["suggested_new_accounts"] == 1

    def test_growth_rate_positive(self, monkeypatch) -> None:
        """增长后段高于前段 → growth_rate>0。"""
        import services.usage_agg as usage_agg_module

        class _Agg:
            def daily_success_series(self, window_days: int) -> list[dict]:
                series = _series(total_days=8, per_day=10)
                # 后 4 天翻倍
                for i in range(4, 8):
                    series[i]["calls"] = 20
                return series

        monkeypatch.setattr(usage_agg_module, "usage_agg", _Agg())
        monkeypatch.setattr(dashboard.account_service, "list_accounts", lambda: [])

        result = dashboard._collect_capacity(windows_days=8)
        assert result["growth_rate"] > 0

    def test_contract_fields(self, monkeypatch) -> None:
        """契约字段齐全且类型正确。"""
        import services.usage_agg as usage_agg_module

        class _Agg:
            def daily_success_series(self, window_days: int) -> list[dict]:
                return _series(total_days=7, per_day=5)

        monkeypatch.setattr(usage_agg_module, "usage_agg", _Agg())
        monkeypatch.setattr(dashboard.account_service, "list_accounts", lambda: [])

        result = dashboard._collect_capacity(windows_days=7)
        for key in ("days", "avg_daily_requests", "active_accounts", "per_account_daily", "growth_rate", "suggested_new_accounts", "series"):
            assert key in result, f"缺字段 {key}"
        assert result["days"] == 7
        assert isinstance(result["series"], list)
