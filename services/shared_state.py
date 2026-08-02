"""多 worker 共享状态抽象层（D16）：Local/Redis 双实现。

解决多 worker 状态分裂：限流计数、聊天缓存、熔断器状态在各进程独立，
导致限流误差大、缓存命中率低、熔断不公平。

设计：
- SharedStateBackend 协议：get/set/delete/incr/expire 最小原语
- LocalBackend：进程内 dict（单 worker 默认，零依赖）
- RedisBackend：可选（REDIS_URL 配置 + redis 包可用时启用，否则降级 Local）
- get_shared_state()：按配置自动选择，Redis 不可用时静默降级 Local 并打日志

红线：多 worker 状态只走本层，禁止模块级可变全局变量跨请求持有。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class SharedStateBackend(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def incr(self, key: str, amount: int = 1, ttl_seconds: float | None = None) -> int: ...
    def exists(self, key: str) -> bool: ...
    def backend_name(self) -> str: ...


class LocalBackend:
    """进程内共享状态（单 worker 默认）。线程安全。"""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._lock = threading.RLock()

    def _expired(self, key: str) -> bool:
        item = self._data.get(key)
        if item is None:
            return True
        _, expires_at = item
        return expires_at is not None and time.monotonic() >= expires_at

    def get(self, key: str) -> Any:
        with self._lock:
            if self._expired(key):
                self._data.pop(key, None)
                return None
            return self._data[key][0]

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds else None
        with self._lock:
            self._data[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def incr(self, key: str, amount: int = 1, ttl_seconds: float | None = None) -> int:
        with self._lock:
            current = self.get(key) or 0
            new_value = int(current) + amount
            self.set(key, new_value, ttl_seconds)
            return new_value

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def backend_name(self) -> str:
        return "local"


class RedisBackend:
    """Redis 共享状态（可选，REDIS_URL 配置 + redis 包可用时启用）。"""

    def __init__(self, url: str) -> None:
        try:
            import redis  # type: ignore
        except ImportError as exc:
            raise RuntimeError("redis 包未安装，无法启用 Redis 共享状态（pip install redis）") from exc
        self._client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=3)
        self._client.ping()

    def get(self, key: str) -> Any:
        raw = self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        if ttl_seconds:
            self._client.setex(key, max(1, int(ttl_seconds)), payload)
        else:
            self._client.set(key, payload)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def incr(self, key: str, amount: int = 1, ttl_seconds: float | None = None) -> int:
        value = self._client.incrby(key, amount)
        if ttl_seconds:
            self._client.expire(key, max(1, int(ttl_seconds)))
        return int(value)

    def exists(self, key: str) -> bool:
        return bool(self._client.exists(key))

    def backend_name(self) -> str:
        return "redis"


_backend: SharedStateBackend | None = None
_backend_lock = threading.Lock()


def get_shared_state() -> SharedStateBackend:
    """按配置返回共享状态后端（单例）。Redis 配置但不可用时静默降级 Local。"""
    global _backend
    with _backend_lock:
        if _backend is not None:
            return _backend
        from services.config import config

        redis_url = str(getattr(config, "redis_url", "") or "").strip()
        if redis_url:
            try:
                _backend = RedisBackend(redis_url)
                logger.info("共享状态后端: redis (%s)", redis_url.split("@")[-1])
                return _backend
            except Exception as exc:  # noqa: BLE001 - 降级 Local 保可用性
                logger.warning("Redis 连接失败，降级 Local 共享状态: %s", exc)
        _backend = LocalBackend()
        return _backend


def reset_shared_state() -> None:
    """测试用：重置单例（不影响 Local 数据，仅下次重新按配置构建）。"""
    global _backend
    with _backend_lock:
        _backend = None
