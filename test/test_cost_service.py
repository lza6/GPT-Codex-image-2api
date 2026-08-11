"""5.1.2：成本优化服务单测。

验证点：
- 正常返回：usage_agg / provider_scheduler / kookeey_service 三组合并
- 各组件异常降级（不崩，输出占位）
- 无 kookeey 配置时 kookeey_traffic.need_config
- 字段契约齐全
"""

from __future__ import annotations

from unittest.mock import MagicMock


class TestCostOverview:
    def test_normal_returns(self, monkeypatch) -> None:
        """正常返回：三组合并，字段齐全。"""
        # mock usage_agg
        mock_agg = MagicMock()
        mock_agg.totals.return_value = {
            "total_requests": 100,
            "total_success": 95,
            "total_fail": 5,
            "by_type": {"调用": {"success": 95, "fail": 5}, "文生图": {"success": 10, "fail": 0}},
        }
        mock_agg.daily_success_series.return_value = [{"date": "2026-08-05", "calls": 10}, {"date": "2026-08-06", "calls": 15}]
        monkeypatch.setattr("services.usage_agg.usage_agg", mock_agg)

        # mock provider_scheduler
        mock_scheduler = MagicMock()
        mock_scheduler.get_provider_stats.return_value = [
            {"name": "chatgpt", "display_name": "ChatGPT", "total_accounts": 10, "available_accounts": 8, "quota_remaining": 100},
        ]
        monkeypatch.setattr("services.provider_scheduler.provider_scheduler", mock_scheduler)

        # mock account_service
        mock_account = MagicMock()
        mock_account.list_accounts.return_value = []
        monkeypatch.setattr("services.cost_service.account_service", mock_account)

        # mock kookeey_service
        mock_kookeey = MagicMock()
        mock_kookeey.get_traffic_overview.return_value = {
            "ok": True,
            "balance_mb": 500,
            "today_use_mb": 10,
            "month_use_mb": 200,
            "package": {"traffic_left_gb": 10, "traffic_total_gb": 20, "expire_time": 1700000000},
        }
        monkeypatch.setattr("services.kookeey_service.kookeey_service", mock_kookeey)

        from services.cost_service import cost_service

        result = cost_service.get_cost_overview()
        assert result["total_requests"] == 100
        assert result["total_success"] == 95
        assert result["total_fail"] == 5
        assert len(result["by_type"]) == 2
        assert len(result["provider_distribution"]) == 1
        assert result["provider_distribution"][0]["name"] == "chatgpt"
        assert result["kookeey_traffic"] is not None
        assert result["kookeey_traffic"]["balance_mb"] == 500
        assert len(result["daily_trend"]) == 2

    def test_kookeey_not_configured(self, monkeypatch) -> None:
        """kookeey 未配置：need_config 降级，不报错。"""
        mock_agg = MagicMock()
        mock_agg.totals.return_value = {"total_requests": 0, "total_success": 0, "total_fail": 0, "by_type": {}}
        mock_agg.daily_success_series.return_value = []
        monkeypatch.setattr("services.usage_agg.usage_agg", mock_agg)

        mock_scheduler = MagicMock()
        mock_scheduler.get_provider_stats.return_value = []
        monkeypatch.setattr("services.provider_scheduler.provider_scheduler", mock_scheduler)
        mock_account = MagicMock()
        mock_account.list_accounts.return_value = []
        monkeypatch.setattr("services.cost_service.account_service", mock_account)

        mock_kookeey = MagicMock()
        mock_kookeey.get_traffic_overview.return_value = {"ok": False, "need_config": True, "error": "未配置 developer_token / access_id"}
        monkeypatch.setattr("services.kookeey_service.kookeey_service", mock_kookeey)

        from services.cost_service import cost_service

        result = cost_service.get_cost_overview()
        assert result["total_requests"] == 0
        assert result["kookeey_traffic"] is not None
        assert result["kookeey_traffic"]["need_config"] is True

    def test_usage_agg_exception_graceful(self, monkeypatch) -> None:
        """usage_agg 异常：不崩，返回占位数据。"""
        mock_agg = MagicMock()
        mock_agg.totals.side_effect = RuntimeError("模拟异常")
        monkeypatch.setattr("services.usage_agg.usage_agg", mock_agg)

        mock_scheduler = MagicMock()
        mock_scheduler.get_provider_stats.return_value = []
        monkeypatch.setattr("services.provider_scheduler.provider_scheduler", mock_scheduler)
        mock_account = MagicMock()
        mock_account.list_accounts.return_value = []
        monkeypatch.setattr("services.cost_service.account_service", mock_account)

        mock_kookeey = MagicMock()
        mock_kookeey.get_traffic_overview.return_value = {"ok": False, "need_config": True}
        monkeypatch.setattr("services.kookeey_service.kookeey_service", mock_kookeey)

        from services.cost_service import cost_service

        result = cost_service.get_cost_overview()
        assert result["total_requests"] == 0
        assert result["total_success"] == 0
        assert result["total_fail"] == 0
        assert result["by_type"] == {}

    def test_contract_fields(self, monkeypatch) -> None:
        """契约字段齐全。"""
        from services.cost_service import cost_service

        mock_agg = MagicMock()
        mock_agg.totals.return_value = {"total_requests": 0, "total_success": 0, "total_fail": 0, "by_type": {}}
        mock_agg.daily_success_series.return_value = []
        monkeypatch.setattr("services.usage_agg.usage_agg", mock_agg)

        mock_scheduler = MagicMock()
        mock_scheduler.get_provider_stats.return_value = []
        monkeypatch.setattr("services.provider_scheduler.provider_scheduler", mock_scheduler)
        mock_account = MagicMock()
        mock_account.list_accounts.return_value = []
        monkeypatch.setattr("services.cost_service.account_service", mock_account)

        mock_kookeey = MagicMock()
        mock_kookeey.get_traffic_overview.return_value = {"ok": False, "need_config": True}
        monkeypatch.setattr("services.kookeey_service.kookeey_service", mock_kookeey)

        result = cost_service.get_cost_overview()
        for key in ("total_requests", "total_success", "total_fail", "by_type", "provider_distribution", "kookeey_traffic", "daily_trend"):
            assert key in result, f"缺字段 {key}"