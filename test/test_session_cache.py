"""三级缓存 TieredSessionCache 单元测试。

覆盖：
- L1 命中/未命中/过期/LRU 淘汰
- L2 Redis 命中（mock）
- L3 存储层命中（mock）
- 并发安全
- Redis 降级（Redis 不可用时静默回退 L1）
- 统计端点数据正确
- 集成：SessionPool._make_key 走缓存路径
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from services.session_cache import TieredSessionCache


def _cache(maxsize: int = 16, ttl: int = 300) -> TieredSessionCache:
    return TieredSessionCache(maxsize=maxsize, ttl=ttl)


class FakeRedis:
    """模拟 Redis 客户端（用于 L2 测试）。"""
    def __init__(self):
        self._data: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        val, expires = entry
        if expires < time.time():
            del self._data[key]
            return None
        return val

    def setex(self, key: str, ttl: int, value: str) -> None:
        self._data[key] = (value, time.time() + ttl)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def ping(self) -> bool:
        return True


class FakeStorage:
    """模拟 L3 存储层。"""
    def __init__(self):
        self._data: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        return self._data.get(key)

    def set(self, key: str, value: object, ttl_seconds: float | None = None) -> None:
        self._data[key] = value


# ── L1 基础测试 ──────────────────────────────────────────────────────


def test_l1_hit():
    cache = _cache()
    cache.set("k1", {"a": 1})
    result = cache.get("k1")
    assert result == {"a": 1}
    assert cache.stats()["hits_l1"] == 1


def test_l1_miss():
    cache = _cache()
    result = cache.get("nonexistent")
    assert result is None
    assert cache.stats()["misses"] == 1


def test_l1_expiry():
    cache = _cache(ttl=1)
    cache.set("k1", "v1")
    time.sleep(1.5)
    result = cache.get("k1")
    assert result is None


def test_l1_lru_eviction():
    cache = _cache(maxsize=3, ttl=300)
    for i in range(3):
        cache.set(f"k{i}", f"v{i}")
    # 第 4 个触发 LRU 淘汰最老的 k0
    cache.set("k3", "v3")
    stats = cache.stats()
    assert stats["evictions"] >= 1
    assert cache.get("k0") is None  # 被淘汰
    assert cache.get("k3") == "v3"


def test_l1_get_refreshes_lru():
    """get 命中后该 key 应移到末尾，不被优先淘汰。"""
    cache = _cache(maxsize=2, ttl=300)
    cache.set("k1", "v1")
    cache.set("k2", "v2")
    cache.get("k1")  # 刷新 LRU 顺序
    cache.set("k3", "v3")  # 淘汰 k2（最久未用）
    assert cache.get("k1") == "v1"
    assert cache.get("k2") is None


# ── L2 测试 ──────────────────────────────────────────────────────────


def test_l2_hit():
    redis = FakeRedis()
    cache = TieredSessionCache(maxsize=16, ttl=300, redis_client=redis)
    # 直接写入 Redis（存 JSON 字符串）
    import json
    redis.setex("session_cache:k2", 300, json.dumps("redis-val"))
    result = cache.get("k2")
    # L2 返回的是 JSON 反序列化后的值
    assert result == "redis-val"
    stats = cache.stats()
    assert stats["hits_l2"] == 1
    # L1 应已回填
    assert cache.get("k2") == "redis-val"
    assert cache.stats()["hits_l1"] == 1


def test_l2_unavailable_falls_back():
    """Redis 不可用时静默降级，不走 L2。"""
    cache = TieredSessionCache(maxsize=16, ttl=300, redis_client=FakeRedis())
    # 替换为会抛异常的 "redis"
    cache._redis = MagicMock()
    cache._redis.get.side_effect = RuntimeError("connection refused")
    cache.set("k1", "v1")
    # 应能从 L1 命中（不受 L2 异常影响）
    assert cache.get("k1") == "v1"
    assert cache.stats()["hits_l1"] >= 1


# ── L3 测试 ──────────────────────────────────────────────────────────


def test_l3_hit():
    storage = FakeStorage()
    cache = TieredSessionCache(maxsize=16, ttl=300, storage=storage)
    storage.set("k3", "storage-val")
    result = cache.get("k3")
    assert result == "storage-val"
    stats = cache.stats()
    assert stats["hits_l3"] == 1
    # L1 应已回填
    assert cache.get("k3") == "storage-val"
    assert cache.stats()["hits_l1"] == 1


def test_l3_miss_falls_back():
    """L3 未命中 → miss。"""
    cache = _cache()
    assert cache.get("anything") is None


# ── L1+L2+L3 三级联动 ────────────────────────────────────────────────


def test_three_tier_fallback():
    """L1 miss → L2 miss → L3 hit → 回填 L1+L2。"""
    storage = FakeStorage()
    redis = FakeRedis()
    cache = TieredSessionCache(maxsize=16, ttl=300, redis_client=redis, storage=storage)
    storage.set("tier3", "from-storage")
    result = cache.get("tier3")
    assert result == "from-storage"
    stats = cache.stats()
    assert stats["hits_l3"] == 1
    # L1 已回填
    assert cache.get("tier3") == "from-storage"
    assert cache.stats()["hits_l1"] == 1
    # L2 已回填
    import json
    raw = redis.get("session_cache:tier3")
    assert raw is not None
    assert json.loads(raw) == "from-storage"


# ── delete / clear ───────────────────────────────────────────────────


def test_delete_removes_from_all_tiers():
    redis = FakeRedis()
    storage = FakeStorage()
    cache = TieredSessionCache(maxsize=16, ttl=300, redis_client=redis, storage=storage)
    cache.set("del-key", "value")
    storage.set("del-key", "value")
    cache.delete("del-key")
    # 在 get 之前检查 L2 已删除（get 会重新回填）
    assert redis.get("session_cache:del-key") is None, "L2 应已删除"
    # L1 已删除，get 应从 L3 回填
    assert cache.get("del-key") == "value"
    # 存储层不受影响
    assert storage.get("del-key") == "value"


def test_clear_empties_l1():
    cache = _cache()
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


# ── 并发安全 ──────────────────────────────────────────────────────────


def test_concurrent_get_set_thread_safe():
    cache = _cache(maxsize=32, ttl=300)
    errors: list[Exception] = []

    def worker(n: int) -> None:
        try:
            for i in range(50):
                key = f"k{i % 10}"
                cache.set(key, n)
                cache.get(key)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors, f"并发错误: {errors}"


# ── 统计 ──────────────────────────────────────────────────────────────


def test_stats_accurate():
    cache = _cache(maxsize=16, ttl=300)
    cache.set("a", 1)
    cache.get("a")  # L1 hit
    cache.get("a")  # L1 hit
    cache.get("miss")  # miss
    stats = cache.stats()
    assert stats["hits_l1"] == 2
    assert stats["misses"] == 1
    assert stats["total_requests"] == 3
    assert stats["hit_rate"] == round(2.0 / 3.0, 4)
    assert stats["sets"] == 1
    assert stats["l2_available"] is False
    assert stats["l3_available"] is False


# ── 指标回调 ──────────────────────────────────────────────────────────


def test_metrics_callback_invoked():
    calls: list[tuple[str, int]] = []

    def cb(event: str, tier: int) -> None:
        calls.append((event, tier))

    cache = TieredSessionCache(maxsize=16, ttl=300, metrics_callback=cb)
    cache.set("k", "v")
    cache.get("k")  # L1 hit → cb("hit", 1)
    cache.get("miss")  # miss → cb("miss", 0)
    assert ("hit", 1) in calls
    assert ("miss", 0) in calls


# ── 集成：SessionPool._make_key 走缓存路径（不需要真实账号） ─────


def test_make_key_uses_cache():
    """_make_key 调用 tiered cache 缓存 proxy 查询结果（不重复调 get_profile）。"""
    from services.session_pool import SessionPool
    from services.session_cache import TieredSessionCache
    # 此处不能直接 import session_kwargs_cache（它可能被其他测试 import 时已创建）
    # 改为直接构造一个 TieredSessionCache 注入到 pool 的缓存路径
    # 测试验证：SessionPool._make_key 通过 session_kwargs_cache 缓存 proxy 查询结果

    pool = SessionPool(max_entries=5, health_check_enabled=False)
    acct = {"access_token": "tok-integration-test-aaaa"}

    # 清空全局缓存
    from services import session_pool as sp_mod
    sp_mod.session_kwargs_cache.clear()

    get_profile_calls: list[str] = []

    with patch("services.session_pool.proxy_settings") as ps:
        def tracking_get_profile(**kwargs):
            get_profile_calls.append("called")
            return type("P", (), {"proxy_url": ""})()
        ps.get_profile = tracking_get_profile
        ps.build_session_kwargs.return_value = {}

        # 第一次：应调用 get_profile
        k1 = pool._make_key(account=acct, impersonate="chrome110", verify=True)
        assert len(get_profile_calls) == 1

        # 第二次：应走缓存，不调用 get_profile
        k2 = pool._make_key(account=acct, impersonate="chrome110", verify=True)
        assert len(get_profile_calls) == 1  # 仍为 1 次

        assert k1 == k2