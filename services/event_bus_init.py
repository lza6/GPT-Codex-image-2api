"""事件总线订阅注册：集中管理所有事件订阅关系。

在应用启动时调用一次，建立发布方 ↔ 订阅方的连接。
"""

from __future__ import annotations

import logging

from services.alert_service import send_alert
from services.event_bus import (
    ACCOUNT_INVALID,
    ACCOUNT_QUOTA_EXHAUSTED,
    ACCOUNT_RECOVERED,
    BACKUP_FAILURE,
    CIRCUIT_CLOSED,
    CIRCUIT_HALF_OPEN,
    CIRCUIT_OPEN,
    Event,
    event_bus,
)
from services.prometheus_metrics import record_circuit_breaker_transition

logger = logging.getLogger(__name__)

# 事件总线类型 → 告警服务事件名映射
_ALERT_EVENT_MAP: dict[str, str] = {
    CIRCUIT_OPEN: "circuit_breaker_open",
    CIRCUIT_CLOSED: "circuit_breaker_closed",
    CIRCUIT_HALF_OPEN: "circuit_breaker_half_open",
    ACCOUNT_INVALID: "account_invalid",
    ACCOUNT_RECOVERED: "account_recovered",
    ACCOUNT_QUOTA_EXHAUSTED: "quota_exhausted",
    BACKUP_FAILURE: "backup_failure",
}


def _alert_wrapper(event: Event) -> None:
    """将事件转换为告警调用。"""
    alert_event = _ALERT_EVENT_MAP.get(event.type, event.type)
    send_alert(alert_event, event.data)


def _metric_wrapper(event: Event) -> None:
    """将熔断事件转换为指标记录。"""
    data = event.data
    record_circuit_breaker_transition(
        from_state=data.get("from_state", "unknown"),
        to_state=data.get("to_state", "unknown"),
    )


_registered = False


def register_subscribers() -> None:
    """注册所有事件订阅者。幂等——只注册一次。"""
    global _registered
    if _registered:
        return
    _registered = True
    # 熔断器事件 → 告警
    event_bus.subscribe(CIRCUIT_OPEN, sync_handler=_alert_wrapper)
    event_bus.subscribe(CIRCUIT_CLOSED, sync_handler=_alert_wrapper)

    # 熔断器事件 → Prometheus 指标
    event_bus.subscribe(CIRCUIT_OPEN, sync_handler=_metric_wrapper)
    event_bus.subscribe(CIRCUIT_HALF_OPEN, sync_handler=_metric_wrapper)
    event_bus.subscribe(CIRCUIT_CLOSED, sync_handler=_metric_wrapper)

    # 账号事件 → 告警
    event_bus.subscribe(ACCOUNT_INVALID, sync_handler=_alert_wrapper)
    event_bus.subscribe(ACCOUNT_RECOVERED, sync_handler=_alert_wrapper)
    event_bus.subscribe(ACCOUNT_QUOTA_EXHAUSTED, sync_handler=_alert_wrapper)

    # 备份失败 → 告警
    event_bus.subscribe(BACKUP_FAILURE, sync_handler=_alert_wrapper)

    logger.info("事件总线订阅已注册（%d 个订阅者）", event_bus.subscriber_count)