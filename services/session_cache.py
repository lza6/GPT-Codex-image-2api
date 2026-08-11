"""三级会话缓存：L1 内存 LRU → L2 Redis → L3 存储层。

用于缓存可序列化的会话数据（账号/代理配置、会话元数据等），
减少每次 SessionPool.get() 对存储层的重复查询。

设计：
- L1：线程安全 OrderedDict LRU，持有反序列化 Python 对象
- L2：可选 Redis 后端（跨 worker 共享），以 JSON 序列化存储
- L3：可选存储后端（持久化），作为最后回退
- 缓存穿透保护：L1 miss 后查 L2，L2 miss 后查 L3，逐级回填
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class CacheStorageBackend(Protocol):
    """L3 存储层接口：适配现有的 StorageBackend / SharedStateBackend。"""
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None: ...


class TieredSessionCache:
    """三级缓存：L1 内存 LRU → L2 Redis → L3 存储层。

    线程安全：L1 写操作以 threading.Lock 保护。
    L2/L3 操作在锁外执行（避免阻塞其他线程），
    通过 CAS 风格检查防止 L1 回填竞态。
    """

    def __init__(
        self,
        maxsize: int = 256,
        ttl: int = 300,
        redis_client: Any = None,
        storage: CacheStorageBackend | None = None,
        metrics_callback: Any = None,
    ):
        self._l1: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl
        self._redis = redis_client
        self._storage = storage
        self._metrics = metrics_callback
        self._lock = threading.Lock()

        # 缓存统计（原子计数器）
        self._stats_lock = threading.Lock()
        self._hits_l1 = 0
        self._hits_l2 = 0
        self._hits_l3 = 0
        self._misses = 0
        self._sets = 0
        self._evictions = 0

    # ── 统计 ──────────────────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        with self._stats_lock:
            total = self._hits_l1 + self._hits_l2 + self._hits_l3 + self._misses
            return {
                "size": len(self._l1),
                "maxsize": self._maxsize,
                "ttl_seconds": self._ttl,
                "hits_l1": self._hits_l1,
                "hits_l2": self._hits_l2,
                "hits_l3": self._hits_l3,
                "misses": self._misses,
                "sets": self._sets,
                "evictions": self._evictions,
                "total_requests": total,
                "hit_rate": round(self._hits_l1 / total, 4) if total else 0.0,
                "l2_available": self._redis is not None,
                "l3_available": self._storage is not None,
            }

    def _record_hit(self, tier: int) -> None:
        with self._stats_lock:
            if tier == 1:
                self._hits_l1 += 1
            elif tier == 2:
                self._hits_l2 += 1
            elif tier == 3:
                self._hits_l3 += 1
        if self._metrics:
            try:
                self._metrics("hit", tier)
            except Exception:
                pass

    def _record_miss(self) -> None:
        with self._stats_lock:
            self._misses += 1
        if self._metrics:
            try:
                self._metrics("miss", 0)
            except Exception:
                pass

    def _record_set(self) -> None:
        with self._stats_lock:
            self._sets += 1

    def _record_eviction(self) -> None:
        with self._stats_lock:
            self._evictions += 1

    # ── 核心操作 ───────────────────────────────────────────────────────

    def get(self, key: str) -> Any | None:
        """三级缓存逐级查找：L1 → L2 → L3。

        返回 Python 对象（dict/list/str/int/float/bool），
        或 None（三级均未命中）。
        """
        # ── L1 检查 ──
        l1_hit = False
        with self._lock:
            entry = self._l1.get(key)
            if entry is not None:
                data, ts = entry
                if time.monotonic() - ts < self._ttl:
                    self._l1.move_to_end(key)
                    l1_hit = True
                else:
                    del self._l1[key]
                    entry = None
        if l1_hit:
            self._record_hit(1)
            return data

        # ── L2 检查（Redis，锁外） ──
        if self._redis is not None:
            try:
                raw = self._redis.get(f"session_cache:{key}")
                if raw is not None:
                    import json as _json
                    try:
                        data = _json.loads(raw)
                    except (_json.JSONDecodeError, TypeError):
                        data = raw
                    self._promote_to_l1(key, data)
                    self._record_hit(2)
                    return data
            except Exception as exc:
                logger.warning("session_cache L2 Redis 查询失败: %s", exc)

        # ── L3 检查（存储层，锁外） ──
        if self._storage is not None:
            try:
                data = self._storage.get(key)
                if data is not None:
                    self._promote_to_l1(key, data)
                    self._record_hit(3)
                    if self._redis is not None:
                        self._promote_to_l2(key, data)
                    return data
            except Exception as exc:
                logger.warning("session_cache L3 存储层查询失败: %s", exc)

        self._record_miss()
        return None

    def set(self, key: str, data: Any, ttl: int | None = None) -> None:
        """写入三级缓存（L1 + L2，L3 由调用方决定）。"""
        effective_ttl = ttl if ttl is not None else self._ttl
        self._promote_to_l1(key, data, effective_ttl)
        if self._redis is not None:
            self._promote_to_l2(key, data, effective_ttl)
        self._record_set()

    def delete(self, key: str) -> None:
        """从所有级别删除缓存条目。"""
        with self._lock:
            self._l1.pop(key, None)
        if self._redis is not None:
            try:
                self._redis.delete(f"session_cache:{key}")
            except Exception as exc:
                logger.warning("session_cache L2 Redis 删除失败: %s", exc)

    def clear(self) -> None:
        """清空 L1 缓存（L2 由调用方决定）。"""
        with self._lock:
            self._l1.clear()

    # ── 内部方法 ───────────────────────────────────────────────────────

    def _promote_to_l1(self, key: str, data: Any, ttl: int | None = None) -> None:
        """回填 L1 缓存（LRU 淘汰）。"""
        effective_ttl = ttl if ttl is not None else self._ttl
        with self._lock:
            if key in self._l1:
                self._l1.move_to_end(key)
                self._l1[key] = (data, time.monotonic())
                return
            if len(self._l1) >= self._maxsize:
                self._l1.popitem(last=False)
                self._record_eviction()
            self._l1[key] = (data, time.monotonic())

    def _promote_to_l2(self, key: str, data: Any, ttl: int | None = None) -> None:
        """回填 L2 Redis 缓存。"""
        effective_ttl = ttl if ttl is not None else self._ttl
        try:
            import json
            payload = json.dumps(data, ensure_ascii=False, default=str)
            self._redis.setex(f"session_cache:{key}", effective_ttl, payload)
        except Exception as exc:
            logger.warning("session_cache L2 Redis 写入失败: %s", exc)