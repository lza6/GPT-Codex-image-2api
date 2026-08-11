"""事件总线订阅注册：集中管理所有事件订阅关系。

在应用启动时调用一次，建立发布方 ↔ 订阅方的连接。
"""

from __future__ import annotations

import logging

from services.alert_service import send_alert
from services.event_bus import (
    ACCOUNT_INVALID,
    ACCOUNT_QUOTA_EXHAUSTED,
    ACCOUNT_QUOTA_LOW,
    ACCOUNT_RECOVERED,
    BACKUP_CHECKSUM_MISMATCH,
    BACKUP_FAILURE,
    CIRCUIT_CLOSED,
    CIRCUIT_HALF_OPEN,
    CIRCUIT_OPEN,
    CONFIG_CHANGED,
    IMAGE_TASK_COMPLETED,
    SESSION_DEGRADED,
    Event,
    event_bus,
)
from services.log_service import LOG_TYPE_ACCOUNT, log_service
from services.prometheus_metrics import (
    record_circuit_breaker_transition,
    record_image_task_completed,
)

logger = logging.getLogger(__name__)

# 事件总线类型 → 告警服务事件名映射
_ALERT_EVENT_MAP: dict[str, str] = {
    CIRCUIT_OPEN: "circuit_breaker_open",
    CIRCUIT_CLOSED: "circuit_breaker_closed",
    CIRCUIT_HALF_OPEN: "circuit_breaker_half_open",
    ACCOUNT_INVALID: "account_invalid",
    ACCOUNT_RECOVERED: "account_recovered",
    ACCOUNT_QUOTA_EXHAUSTED: "quota_exhausted",
    ACCOUNT_QUOTA_LOW: "quota_low",
    BACKUP_FAILURE: "backup_failure",
    BACKUP_CHECKSUM_MISMATCH: "backup_checksum_mismatch",
    SESSION_DEGRADED: "session_degraded",
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


def _image_task_completed_wrapper(event: Event) -> None:
    """图片任务完成：记录日志 + 递减在途指标。"""
    data = event.data
    task_id = data.get("task_id", "unknown")
    result = data.get("result", "unknown")
    log_service.add(
        LOG_TYPE_ACCOUNT,
        f"image_task_completed:{task_id}",
        {"task_id": task_id, "result": result, **data},
    )
    record_image_task_completed()


def _config_changed_wrapper(event: Event) -> None:
    """配置变更事件：记录日志。"""
    data = event.data
    mtime = data.get("mtime", "unknown")
    log_service.add(
        LOG_TYPE_ACCOUNT,
        "config_changed",
        {"event": "config_changed", "mtime": mtime, "reloaded_at": data.get("reloaded_at")},
    )
    logger.info("配置已变更（mtime: %s）", mtime)


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
    # 备份完整性校验失败（内容损坏）→ 告警
    event_bus.subscribe(BACKUP_CHECKSUM_MISMATCH, sync_handler=_alert_wrapper)

    # 账号配额低 → 告警
    event_bus.subscribe(ACCOUNT_QUOTA_LOW, sync_handler=_alert_wrapper)

    # 图片任务完成 → 日志 + 指标
    event_bus.subscribe(IMAGE_TASK_COMPLETED, sync_handler=_image_task_completed_wrapper)

    # 会话降级 → 告警
    event_bus.subscribe(SESSION_DEGRADED, sync_handler=_alert_wrapper)

    # 配置变更 → 日志
    event_bus.subscribe(CONFIG_CHANGED, sync_handler=_config_changed_wrapper)

    # PROVIDER_HEALTH_CHANGED：由提供方通过 dashboard SSE 推送，无需事件总线

    logger.info("事件总线订阅已注册（%d 个订阅者）", event_bus.subscriber_count)