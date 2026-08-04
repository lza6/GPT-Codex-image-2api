"""F2/A2：用量预测——按近期用量趋势线性外推号池配额耗尽时间，提前告警。

数据源：log_service 调用日志（近 N 天按天聚合成功调用数）+ account_service 当前
总剩余配额。线性外推日均消耗速率，估算"按当前速率多少天后配额耗尽"。

设计取舍（性能优先 + 简洁）：
- 近 7 天窗口日均消耗速率（足够平滑日内波动，又不被远古数据带偏）。
- 线性外推（v2.3.0 F2 线性版）；7 天趋势/加权版留待实测后升级。
- 仅统计正向配额账号（quota > 0），无限配额账号（quota=-1）不参与耗尽预测。
- 数据不足（无日志/无配额数据）时返回 insufficient_data，不瞎猜。
"""

from __future__ import annotations

import datetime
import time
from typing import Any

from services.log_service import log_service

# 预测窗口：近 N 天日均消耗速率
_FORECAST_WINDOW_DAYS = 7
# 提前告警阈值：预计耗尽天数 ≤ 此值时 should_alert=True
_DEFAULT_ALERT_THRESHOLD_DAYS = 3.0


def _parse_log_ts(item: dict[str, Any]) -> float:
    """复用 dashboard 的时间键兼容逻辑：time(text) / ts(json) / created_at。"""
    created = str(item.get("time") or item.get("ts") or item.get("created_at") or "")
    try:
        normalized = created[:19].replace("T", " ")
        return time.mktime(datetime.datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S").timetuple())
    except (ValueError, TypeError):
        return 0.0


def _daily_consumption(window_days: int) -> list[dict[str, Any]]:
    """近 window_days 天按天聚合成功调用数（含今天，今天可能不完整）。"""
    now = time.time()
    cutoff = now - window_days * 86400
    logs = log_service.list(limit=10000)
    # 按日期分桶
    buckets: dict[str, int] = {}
    for item in logs:
        ts = _parse_log_ts(item)
        if ts < cutoff:
            continue
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        status = str(item.get("status") or detail.get("status") or "success")
        if status == "failed":
            continue  # 失败调用不消耗配额
        day = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        buckets[day] = buckets.get(day, 0) + 1
    # 补零：窗口内无调用的天也计入（避免只算有量天导致速率虚高）
    series: list[dict[str, Any]] = []
    for offset in range(window_days - 1, -1, -1):
        day = datetime.datetime.fromtimestamp(now - offset * 86400).strftime("%Y-%m-%d")
        series.append({"date": day, "calls": buckets.get(day, 0)})
    return series


def _total_quota() -> tuple[int, int, int]:
    """返回 (正向配额总和, 正向配额账号数, 无限配额账号数)。

    quota=-1 视为无限配额（不参与耗尽预测）；quota<=0 视为已耗尽。
    """
    from services.account_service import account_service

    total = 0
    count = 0
    unlimited = 0
    for account in account_service.list_accounts() or []:
        try:
            quota = int((account or {}).get("quota") or 0)
        except (TypeError, ValueError):
            continue
        if quota == -1:
            unlimited += 1
        elif quota > 0:
            total += quota
            count += 1
    return total, count, unlimited


def forecast_quota_depletion(alert_threshold_days: float = _DEFAULT_ALERT_THRESHOLD_DAYS) -> dict[str, Any]:
    """线性外推号池配额耗尽时间。

    返回字段：
    - status: ok / insufficient_data / unlimited（全部无限配额）
    - daily_avg_consumption: 近 7 天日均消耗
    - total_remaining_quota: 当前正向配额总和
    - days_until_depletion: 预计耗尽天数（None = 无法估算/零消耗）
    - estimated_depletion_date: 预计耗尽日期（ISO，None 同上）
    - should_alert: 预计耗尽天数 ≤ 阈值
    - daily_series: 近 7 天按天消耗序列（前端画趋势图）
    """
    series = _daily_consumption(_FORECAST_WINDOW_DAYS)
    total_calls = sum(point["calls"] for point in series)
    daily_avg = total_calls / _FORECAST_WINDOW_DAYS

    total_quota, quota_accounts, unlimited_accounts = _total_quota()

    base: dict[str, Any] = {
        "daily_avg_consumption": round(daily_avg, 2),
        "total_remaining_quota": total_quota,
        "quota_accounts": quota_accounts,
        "window_days": _FORECAST_WINDOW_DAYS,
        "daily_series": series,
        # 审查 P2-2：三条返回路径统一带阈值，避免前端"阈值 undefined 天"
        "alert_threshold_days": alert_threshold_days,
    }

    if quota_accounts == 0:
        if unlimited_accounts > 0:
            # 存在无限配额账号（quota=-1），正常耗尽预测无意义
            return {**base, "status": "unlimited", "days_until_depletion": None, "estimated_depletion_date": None, "should_alert": False}
        # 号池为空 或 全部配额已耗尽（quota<=0）——审查 P2-3：与 unlimited 区分，
        # 语义是"已耗尽/无可用配额"而非"无限"，前端走 quota_exhausted 语义展示
        return {**base, "status": "exhausted", "days_until_depletion": 0, "estimated_depletion_date": None, "should_alert": False}

    if total_calls == 0:
        # 零消耗：不会在可预见未来耗尽
        return {**base, "status": "ok", "days_until_depletion": None, "estimated_depletion_date": None, "should_alert": False}

    days_left = total_quota / daily_avg if daily_avg > 0 else None
    depletion_date = None
    if days_left is not None:
        depletion_ts = time.time() + days_left * 86400
        depletion_date = datetime.datetime.fromtimestamp(depletion_ts).strftime("%Y-%m-%d")

    # R1a：配额已耗尽（days_left<=0，如账号刚被刷完但状态未及更新）不算"即将耗尽"预测——
    # 那属于 quota_exhausted 告警的职责；这里应返回 days=0 但不应 should_alert 触发
    # proactive 探活每周期重复发"耗尽"告警（语义是已耗尽而非即将耗尽）。
    # 前端对 should_alert 做横幅预警，days=0 时应显示"已耗尽"而非倒计时。
    should_alert = days_left is not None and 0 < days_left <= alert_threshold_days
    return {
        **base,
        "status": "ok",
        "days_until_depletion": round(days_left, 1) if days_left is not None else None,
        "estimated_depletion_date": depletion_date,
        "should_alert": should_alert,
        "alert_threshold_days": alert_threshold_days,
    }
