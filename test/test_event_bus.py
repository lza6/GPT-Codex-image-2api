"""事件总线单元测试。"""

from __future__ import annotations

import asyncio
import json
import time

from services.event_bus import (
    ACCOUNT_INVALID,
    ALL_EVENTS,
    CIRCUIT_OPEN,
    Event,
    EventBus,
)


def test_event_creation():
    """事件创建包含所有字段。"""
    ev = Event(type="test.event", data={"key": "val"})
    assert ev.type == "test.event"
    assert ev.data["key"] == "val"
    assert len(ev.id) == 16  # uuid hex[:16]
    assert ev.timestamp > 0


def test_event_to_dict():
    """事件序列化。"""
    ev = Event(type="test.event", data={"key": "val"})
    d = ev.to_dict()
    assert d["type"] == "test.event"
    assert d["data"]["key"] == "val"
    assert d["id"] == ev.id
    assert d["timestamp"] == ev.timestamp


def test_all_events_defined():
    """所有事件类型常量已定义且非空。"""
    assert len(ALL_EVENTS) >= 8
    for ev in ALL_EVENTS:
        assert isinstance(ev, str)
        assert len(ev) > 5


def test_subscribe_sync_handler():
    """订阅同步 handler，发布时被调用。"""
    bus = EventBus()
    received: list[Event] = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe("test.event", sync_handler=handler)
    ev = Event("test.event", {"msg": "hello"})
    bus.publish(ev)
    assert len(received) == 1
    assert received[0].data["msg"] == "hello"


def test_subscribe_async_handler():
    """订阅异步 handler，发布时调度到事件循环。"""
    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("test.event", async_handler=handler)
    ev = Event("test.event", {"msg": "hello"})
    bus.publish(ev)
    # 异步 handler 调度到事件循环，需要短暂等待
    time.sleep(0.05)
    assert len(received) == 1
    assert received[0].data["msg"] == "hello"


def test_unsubscribe_removes_handler():
    """取消订阅后 handler 不再被调用。"""
    bus = EventBus()
    count = [0]

    def handler(event: Event):
        count[0] += 1

    bus.subscribe("test.event", sync_handler=handler)
    bus.publish(Event("test.event"))
    assert count[0] == 1
    bus.unsubscribe("test.event", handler)
    bus.publish(Event("test.event"))
    assert count[0] == 1  # 不变


def test_different_event_types_independent():
    """不同事件类型互不影响。"""
    bus = EventBus()
    events: list[str] = []

    def handler_a(event: Event):
        events.append("a")

    def handler_b(event: Event):
        events.append("b")

    bus.subscribe("type.a", sync_handler=handler_a)
    bus.subscribe("type.b", sync_handler=handler_b)
    bus.publish(Event("type.a"))
    assert events == ["a"]
    bus.publish(Event("type.b"))
    assert events == ["a", "b"]


def test_handler_exception_does_not_block(monkeypatch):
    """handler 抛异常不阻塞其他 handler 执行。"""
    bus = EventBus(dead_letter_dir="data")
    order: list[int] = []

    def handler_1(event: Event):
        order.append(1)

    def handler_2(event: Event):
        raise ValueError("boom")

    def handler_3(event: Event):
        order.append(3)

    bus.subscribe("test.event", sync_handler=handler_1)
    bus.subscribe("test.event", sync_handler=handler_2)
    bus.subscribe("test.event", sync_handler=handler_3)
    bus.publish(Event("test.event"))
    assert order == [1, 3]  # handler_2 异常不阻塞 handler_3


def test_dead_letter_written_on_error(tmp_path):
    """handler 异常时写入死信队列。"""
    bus = EventBus(dead_letter_dir=str(tmp_path))

    def handler(event: Event):
        raise RuntimeError("crash")

    bus.subscribe("test.event", sync_handler=handler)
    bus.publish(Event("test.event", {"key": "val"}))

    dl_path = tmp_path / "event_dead_letter.jsonl"
    assert dl_path.exists()
    lines = dl_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 1
    record = json.loads(lines[0])
    assert record["event"]["type"] == "test.event"
    assert "crash" in record["error"]


def test_subscriber_count():
    """订阅者计数正确。"""
    bus = EventBus()
    assert bus.subscriber_count == 0

    def h1(event: Event):
        pass

    def h2(event: Event):
        pass

    bus.subscribe("a", sync_handler=h1)
    bus.subscribe("a", sync_handler=h2)
    bus.subscribe("b", sync_handler=h1)
    assert bus.subscriber_count == 3


def test_subscriber_info():
    """订阅者信息查询。"""
    bus = EventBus()

    def handler(event: Event):
        pass

    bus.subscribe("x", sync_handler=handler)
    bus.subscribe("y", sync_handler=handler)
    info = bus.subscriber_info()
    assert "x" in info
    assert "y" in info
    assert handler.__name__ in info["x"]


def test_publish_async_awaits_handlers():
    """publish_async 等待所有 handler 完成。"""
    bus = EventBus()
    results: list[int] = []

    async def handler(event: Event):
        await asyncio.sleep(0.01)
        results.append(1)

    bus.subscribe("test.event", async_handler=handler)
    asyncio.run(bus.publish_async(Event("test.event")))
    assert results == [1]


def test_global_event_bus_is_singleton():
    """全局 event_bus 是 EventBus 实例。"""
    from services.event_bus import event_bus as eb

    assert isinstance(eb, EventBus)


def test_constant_values_match():
    """事件类型常量值与预期一致。"""
    assert ACCOUNT_INVALID == "account.invalid"
    assert CIRCUIT_OPEN == "circuit.open"