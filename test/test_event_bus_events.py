"""事件总线事件发布与订阅测试：覆盖 4 个业务事件。

测试目标：
- ACCOUNT_QUOTA_LOW：模拟 account_service quota 扣减后发布事件
- PROVIDER_HEALTH_CHANGED：模拟 provider_scheduler 状态变化发布事件
- IMAGE_TASK_COMPLETED：模拟 image_task_service 完成/失败后发布事件
- SESSION_DEGRADED：模拟 session_pool 缩容退化为发布事件
"""

from __future__ import annotations

from services.event_bus import (
    ACCOUNT_QUOTA_LOW,
    IMAGE_TASK_COMPLETED,
    PROVIDER_HEALTH_CHANGED,
    SESSION_DEGRADED,
    Event,
    EventBus,
)


def test_account_quota_low_publish():
    """ACCOUNT_QUOTA_LOW：模拟 account_service quota 扣减后发布事件。

    验证：订阅者收到正确的事件类型和数据载荷。
    """
    bus = EventBus()
    received: list[Event] = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe(ACCOUNT_QUOTA_LOW, sync_handler=handler)

    bus.publish(Event(ACCOUNT_QUOTA_LOW, {
        "token_suffix": "abcd1234",
        "remaining_quota": 5,
        "threshold": 10,
        "plan_type": "free",
    }))

    assert len(received) == 1
    assert received[0].type == ACCOUNT_QUOTA_LOW
    assert received[0].data["token_suffix"] == "abcd1234"
    assert received[0].data["remaining_quota"] == 5
    assert received[0].data["threshold"] == 10
    assert received[0].data["plan_type"] == "free"


def test_provider_health_changed_publish():
    """PROVIDER_HEALTH_CHANGED：模拟 provider_scheduler 状态变化发布事件。

    验证：订阅者收到 provider 健康状态变更事件。
    """
    bus = EventBus()
    received: list[Event] = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe(PROVIDER_HEALTH_CHANGED, sync_handler=handler)

    bus.publish(Event(PROVIDER_HEALTH_CHANGED, {
        "provider": "openai",
        "from_state": "healthy",
        "to_state": "warm",
        "reason": "circuit_breaker_open",
    }))

    assert len(received) == 1
    assert received[0].type == PROVIDER_HEALTH_CHANGED
    assert received[0].data["provider"] == "openai"
    assert received[0].data["from_state"] == "healthy"
    assert received[0].data["to_state"] == "warm"
    assert received[0].data["reason"] == "circuit_breaker_open"


def test_image_task_completed_publish():
    """IMAGE_TASK_COMPLETED：模拟 image_task_service 完成/失败后发布事件。

    验证：成功和失败两种场景下事件均正确发布。
    """
    bus = EventBus()
    received: list[Event] = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe(IMAGE_TASK_COMPLETED, sync_handler=handler)

    # 成功场景
    bus.publish(Event(IMAGE_TASK_COMPLETED, {
        "task_id": "img_001",
        "mode": "generation",
        "model": "dall-e-3",
        "status": "success",
        "account_email": "user@example.com",
        "duration_ms": 3500,
    }))

    assert len(received) == 1
    assert received[0].type == IMAGE_TASK_COMPLETED
    assert received[0].data["task_id"] == "img_001"
    assert received[0].data["status"] == "success"
    assert received[0].data["duration_ms"] == 3500

    # 失败场景
    bus.publish(Event(IMAGE_TASK_COMPLETED, {
        "task_id": "img_002",
        "mode": "edit",
        "model": "dall-e-2",
        "status": "error",
        "account_email": "",
        "duration_ms": 1200,
    }))

    assert len(received) == 2
    assert received[1].type == IMAGE_TASK_COMPLETED
    assert received[1].data["task_id"] == "img_002"
    assert received[1].data["status"] == "error"
    assert received[1].data["duration_ms"] == 1200


def test_session_degraded_publish():
    """SESSION_DEGRADED：模拟 session_pool 缩容退化为发布事件。

    验证：订阅者收到会话池退化事件，包含池大小/最大容量/连续错误数。
    """
    bus = EventBus()
    received: list[Event] = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe(SESSION_DEGRADED, sync_handler=handler)

    bus.publish(Event(SESSION_DEGRADED, {
        "pool_size": 15,
        "max_entries": 200,
        "consecutive_errors": 3,
    }))

    assert len(received) == 1
    assert received[0].type == SESSION_DEGRADED
    assert received[0].data["pool_size"] == 15
    assert received[0].data["max_entries"] == 200
    assert received[0].data["consecutive_errors"] == 3