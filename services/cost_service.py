"""5.1.2：成本优化服务——全链路成本追踪与概览。

数据源（均走聚合缓存，不触全量扫日志）：
- 每账号 Token 消耗 → usage_agg.totals 的 by_type 分布（按 summary 聚合）
- 每 Provider 成本 → provider_scheduler.get_provider_stats 的账号分布
- 代理成本 → kookeey_service.get_traffic_overview 流量 + 余额
- 成本概览 → 以上三组合并

设计取舍（性能优先 + 简洁）：
- 成本为估算值（基于调用次数占比 + 流量使用），不追踪真实货币消耗。
- 无 kookeey 配置时降级显示"未配置"，不报错不阻断。
- 所有数据只读聚合缓存，不触全量扫描。
"""

from __future__ import annotations

import logging
from typing import Any

from services.account_service import account_service

logger = logging.getLogger(__name__)


class CostService:
    """全链路成本追踪服务，单例模式。"""

    def get_cost_overview(self) -> dict[str, Any]:
        """成本概览：总调用/按类型分布/Provider 占比/代理流量。

        返回字段：
        - total_requests: 累计总请求数
        - total_success: 累计成功数
        - total_fail: 累计失败数
        - by_type: 按类型分布 {summary: {success, fail}}
        - provider_distribution: 各 Provider 账号数/可用账号数占比
        - kookeey_traffic: 代理流量概览（kookeey 配置时）
        - daily_trend: 近 7 天按天成功调用趋势
        """
        result: dict[str, Any] = {
            "total_requests": 0,
            "total_success": 0,
            "total_fail": 0,
            "by_type": {},
            "provider_distribution": [],
            "kookeey_traffic": None,
            "daily_trend": [],
        }

        # 1. 用量聚合缓存
        try:
            from services.usage_agg import usage_agg

            totals = usage_agg.totals()
            result["total_requests"] = totals.get("total_requests", 0)
            result["total_success"] = totals.get("total_success", 0)
            result["total_fail"] = totals.get("total_fail", 0)
            result["by_type"] = totals.get("by_type", {})

            # 近 7 天趋势
            result["daily_trend"] = usage_agg.daily_success_series(7)
        except Exception:
            logger.warning("usage_agg 读取失败", exc_info=True)

        # 2. Provider 分布
        try:
            from services.provider_scheduler import provider_scheduler

            accounts = account_service.list_accounts()
            provider_stats = provider_scheduler.get_provider_stats(accounts)
            result["provider_distribution"] = [
                {
                    "name": ps["name"],
                    "display_name": ps["display_name"],
                    "total_accounts": ps["total_accounts"],
                    "available_accounts": ps["available_accounts"],
                    "quota_remaining": ps["quota_remaining"],
                }
                for ps in provider_stats
            ]
        except Exception:
            logger.warning("provider_stats 读取失败", exc_info=True)

        # 3. kookeey 代理流量
        try:
            from services.kookeey_service import kookeey_service

            traffic = kookeey_service.get_traffic_overview()
            if traffic.get("ok"):
                result["kookeey_traffic"] = {
                    "balance_mb": traffic.get("balance_mb"),
                    "today_use_mb": traffic.get("today_use_mb"),
                    "month_use_mb": traffic.get("month_use_mb"),
                    "package": traffic.get("package"),
                }
            elif traffic.get("need_config"):
                result["kookeey_traffic"] = {"need_config": True}
            else:
                result["kookeey_traffic"] = {"error": traffic.get("error", "未知错误")}
        except Exception:
            logger.warning("kookeey 流量读取失败", exc_info=True)

        return result


# 全局单例
cost_service = CostService()