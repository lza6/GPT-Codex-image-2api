"""轻量级事件总线：解耦模块间直接函数调用。

设计：
- 同步/异步双模式发布，无外部依赖
- 订阅方注册 sync_handler 或 async_handler（或两者）
- 死信队列：handler 抛异常时写入 data/event_dead_letter.jsonl
- 线程安全（sync_handler 用 threading.Lock 保护）
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 事件类型常量
# ---------------------------------------------------------------------------

# 账号事件
ACCOUNT_INVALID = "account.invalid"
ACCOUNT_RECOVERED = "account.recovered"
ACCOUNT_QUOTA_EXHAUSTED = "account.quota_exhausted"
# 熔断器事件
CIRCUIT_OPEN = "circuit.open"
CIRCUIT_HALF_OPEN = "circuit.half_open"
CIRCUIT_CLOSED = "circuit.closed"
# 备份事件
BACKUP_FAILURE = "backup.failure"
# 配置事件
CONFIG_CHANGED = "config.changed"

# 所有事件列表（用于初始化/校验）
ALL_EVENTS = frozenset({
    ACCOUNT_INVALID, ACCOUNT_RECOVERED, ACCOUNT_QUOTA_EXHAUSTED,
    CIRCUIT_OPEN, CIRCUIT_HALF_OPEN, CIRCUIT_CLOSED,
    BACKUP_FAILURE,
    CONFIG_CHANGED,
})

# ---------------------------------------------------------------------------
# 事件定义
# ---------------------------------------------------------------------------


@dataclass
class Event:
    """事件载体。"""
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# 事件总线
# ---------------------------------------------------------------------------


class EventBus:
    """轻量级事件总线。

    用法::
        bus = EventBus()
        bus.subscribe("circuit.open", sync_handler=my_sync_handler)
        bus.publish(Event("circuit.open", {"key": "val"}))
    """

    def __init__(self, dead_letter_dir: str | Path | None = None) -> None:
        self._sync_handlers: dict[str, list[Callable[[Event], None]]] = {}
        self._async_handlers: dict[str, list[Callable[[Event], Awaitable[None]]]] = {}
        self._lock = threading.Lock()
        self._dead_letter_path: Path | None = None
        if dead_letter_dir:
            path = Path(dead_letter_dir) / "event_dead_letter.jsonl"
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._dead_letter_path = path
            except OSError:
                pass

    # ------------------------------------------------------------------
    # 订阅 / 取消订阅
    # ------------------------------------------------------------------

    def subscribe(
        self,
        event_type: str,
        sync_handler: Callable[[Event], None] | None = None,
        async_handler: Callable[[Event], Awaitable[None]] | None = None,
    ) -> None:
        """订阅事件。

        sync_handler：同步回调，publish() 时在当前线程执行。
        async_handler：异步回调，publish() 时调度到事件循环。
        """
        if sync_handler is None and async_handler is None:
            raise ValueError("必须提供 sync_handler 或 async_handler")
        if sync_handler is not None:
            with self._lock:
                self._sync_handlers.setdefault(event_type, []).append(sync_handler)
        if async_handler is not None:
            with self._lock:
                self._async_handlers.setdefault(event_type, []).append(async_handler)

    def unsubscribe(
        self,
        event_type: str,
        handler: Callable,
    ) -> None:
        """取消订阅。"""
        with self._lock:
            for store in (self._sync_handlers, self._async_handlers):
                handlers = store.get(event_type, [])
                try:
                    handlers.remove(handler)
                except ValueError:
                    pass

    # ------------------------------------------------------------------
    # 发布（同步）
    # ------------------------------------------------------------------

    def publish(self, event: Event) -> None:
        """同步发布：sync handler 当前线程执行，async handler 调度到事件循环。

        绝不抛异常——handler 异常写入死信队列。
        """
        sync_handlers: list[Callable] = []
        async_handlers: list[Callable] = []
        with self._lock:
            sync_handlers = list(self._sync_handlers.get(event.type, []))
            async_handlers = list(self._async_handlers.get(event.type, []))

        # 同步 handler 当前线程执行
        for handler in sync_handlers:
            try:
                handler(event)
            except Exception as exc:
                logger.warning("事件总线 sync_handler 异常 [%s]: %s", event.type, exc)
                self._write_dead_letter(event, handler, exc)

        # 异步 handler 调度到事件循环
        for handler in async_handlers:
            try:
                try:
                    asyncio.get_running_loop()  # noqa: F841 — 仅用于检测事件循环是否运行
                    asyncio.ensure_future(self._safe_async_handler(event, handler))
                except RuntimeError:
                    # 没有事件循环时直接同步执行异步 handler
                    try:
                        asyncio.run(handler(event))
                    except Exception as exc:
                        logger.warning("事件总线 async_handler 同步回退异常 [%s]: %s", event.type, exc)
                        self._write_dead_letter(event, handler, exc)
            except Exception as exc:
                logger.warning("事件总线 async_handler 调度异常 [%s]: %s", event.type, exc)
                self._write_dead_letter(event, handler, exc)

    # ------------------------------------------------------------------
    # 发布（异步）
    # ------------------------------------------------------------------

    async def publish_async(self, event: Event) -> None:
        """异步发布：await 所有 handler（sync handler 在线程池执行）。"""
        sync_handlers: list[Callable] = []
        async_handlers: list[Callable] = []
        with self._lock:
            sync_handlers = list(self._sync_handlers.get(event.type, []))
            async_handlers = list(self._async_handlers.get(event.type, []))

        loop = asyncio.get_running_loop()

        # 同步 handler 扔线程池
        for handler in sync_handlers:
            try:
                await loop.run_in_executor(None, handler, event)
            except Exception as exc:
                logger.warning("事件总线 publish_async sync_handler 异常 [%s]: %s", event.type, exc)
                self._write_dead_letter(event, handler, exc)

        # 异步 handler 直接 await
        for handler in async_handlers:
            try:
                await handler(event)
            except Exception as exc:
                logger.warning("事件总线 publish_async async_handler 异常 [%s]: %s", event.type, exc)
                self._write_dead_letter(event, handler, exc)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _safe_async_handler(self, event: Event, handler: Callable) -> None:
        try:
            await handler(event)
        except Exception as exc:
            logger.warning("事件总线 async_handler 异常 [%s]: %s", event.type, exc)
            self._write_dead_letter(event, handler, exc)

    def _write_dead_letter(self, event: Event, handler: Callable, exc: Exception) -> None:
        if self._dead_letter_path is None:
            return
        try:
            record = {
                "event": event.to_dict(),
                "handler": getattr(handler, "__name__", str(handler)),
                "error": str(exc)[:512],
                "written_at": time.time(),
            }
            with open(self._dead_letter_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 死信写入也失败就不写了

    # ------------------------------------------------------------------
    # 统计 / 调试
    # ------------------------------------------------------------------

    @property
    def subscriber_count(self) -> int:
        """返回总订阅数。"""
        with self._lock:
            return sum(len(v) for v in self._sync_handlers.values()) + \
                sum(len(v) for v in self._async_handlers.values())

    def subscriber_info(self) -> dict[str, list[str]]:
        """返回各事件类型订阅者名称列表（调试用）。"""
        info: dict[str, list[str]] = {}
        with self._lock:
            for event_type, handlers in self._sync_handlers.items():
                info.setdefault(event_type, []).extend(
                    h.__name__ for h in handlers
                )
            for event_type, handlers in self._async_handlers.items():
                info.setdefault(event_type, []).extend(
                    h.__name__ for h in handlers
                )
        return info


# 全局单例
event_bus = EventBus(dead_letter_dir="data")