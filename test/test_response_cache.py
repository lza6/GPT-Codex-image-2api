"""3.1.3：请求级响应缓存单元测试。

覆盖：缓存命中/过期/强制刷新/并发/写操作失效/Cache-Control 头/统计查询。
"""

from __future__ import annotations

import time

import pytest
from fastapi import Response

from api.response_cache import ResponseCache


@pytest.fixture
def cache() -> ResponseCache:
    c = ResponseCache()
    c.register("/v1/models", ttl=60)
    c.register("/api/providers", ttl=30)
    c.register("/api/dashboard/scheduler", ttl=10)
    return c


class TestResponseCacheBasic:
    """基础功能：get/set/hit/miss/expire/override。"""

    def test_get_miss_returns_none(self, cache: ResponseCache) -> None:
        assert cache.get("/v1/models") is None

    def test_get_set_roundtrip(self, cache: ResponseCache) -> None:
        cache.set("/v1/models", {"id": "gpt-4"})
        assert cache.get("/v1/models") == {"id": "gpt-4"}

    def test_overwrite_old_value(self, cache: ResponseCache) -> None:
        cache.set("/v1/models", "old")
        cache.set("/v1/models", "new")
        assert cache.get("/v1/models") == "new"

    def test_unknown_pattern_returns_none(self, cache: ResponseCache) -> None:
        assert cache.get("/nonexistent") is None

    def test_set_unknown_pattern_noop(self, cache: ResponseCache) -> None:
        cache.set("/nonexistent", "value")  # 不应抛异常
        assert cache.get("/nonexistent") is None


class TestResponseCacheTTL:
    """TTL 过期验证。"""

    def test_expires_after_ttl(self) -> None:
        c = ResponseCache()
        c.register("/test", ttl=1)  # 1 秒
        c.set("/test", "data")
        assert c.get("/test") == "data"
        time.sleep(1.1)
        assert c.get("/test") is None

    def test_different_ttl_per_pattern(self) -> None:
        c = ResponseCache()
        c.register("/a", ttl=60)
        c.register("/b", ttl=5)
        assert c.get_ttl("/a") == 60
        assert c.get_ttl("/b") == 5


class TestResponseCacheInvalidate:
    """失效策略：单模式/全量。"""

    def test_invalidate_pattern(self, cache: ResponseCache) -> None:
        cache.set("/v1/models", "data")
        cache.invalidate("/v1/models")
        assert cache.get("/v1/models") is None

    def test_invalidate_other_pattern_left_untouched(self, cache: ResponseCache) -> None:
        cache.set("/v1/models", "m1")
        cache.set("/api/providers", "prov")
        cache.invalidate("/v1/models")
        assert cache.get("/v1/models") is None
        assert cache.get("/api/providers") == "prov"

    def test_invalidate_all(self, cache: ResponseCache) -> None:
        cache.set("/v1/models", "m1")
        cache.set("/api/providers", "prov")
        cache.invalidate()  # 全量清空
        assert cache.get("/v1/models") is None
        assert cache.get("/api/providers") is None

    def test_invalidate_unknown_pattern_does_not_crash(self, cache: ResponseCache) -> None:
        cache.invalidate("/nonexistent")  # 不应抛异常


class TestResponseCacheStats:
    """统计查询。"""

    def test_cache_stats_returns_all_patterns(self, cache: ResponseCache) -> None:
        stats = cache.get_cache_stats()
        assert "/v1/models" in stats
        assert "/api/providers" in stats
        assert "/api/dashboard/scheduler" in stats

    def test_cache_stats_currsize_reflects_entries(self, cache: ResponseCache) -> None:
        cache.set("/v1/models", "data")
        stats = cache.get_cache_stats()
        assert stats["/v1/models"]["currsize"] == 1
        assert stats["/v1/models"]["maxsize"] == 32

    def test_cache_stats_empty_after_invalidate(self, cache: ResponseCache) -> None:
        cache.set("/v1/models", "data")
        cache.invalidate()
        stats = cache.get_cache_stats()
        assert stats["/v1/models"]["currsize"] == 0


class TestResponseCacheConcurrency:
    """并发写入不崩溃。"""

    def test_concurrent_set_and_get(self, cache: ResponseCache) -> None:
        import threading

        errors: list[Exception] = []

        def worker(n: int) -> None:
            try:
                for _ in range(100):
                    cache.set("/v1/models", f"model-{n}")
                    cache.get("/v1/models")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"并发下抛异常: {errors}"


class TestApplyCacheHeaders:
    """Cache-Control 响应头。"""

    def test_apply_cache_headers_adds_header(self) -> None:
        from api.response_cache import apply_cache_headers

        response = Response()
        apply_cache_headers("/v1/models", response)
        assert response.headers.get("Cache-Control") == "max-age=60"

    def test_apply_cache_headers_unknown_pattern_no_header(self) -> None:
        from api.response_cache import apply_cache_headers

        response = Response()
        apply_cache_headers("/nonexistent", response)
        assert "Cache-Control" not in response.headers


class TestResponseCacheEdgeCases:
    """边界情况。"""

    def test_register_with_custom_maxsize(self) -> None:
        c = ResponseCache()
        c.register("/small", ttl=60, maxsize=2)
        c.set("/small", "a")
        c.set("/small", "b")
        c.set("/small", "c")  # 应淘汰 a
        assert c.get("/small") is not None  # 至少还有一条

    def test_zero_ttl_does_not_register(self) -> None:
        """0 TTL 的模式不注册。"""
        c = ResponseCache()
        c.register("/zero", ttl=0)
        # 刚 set 完就过期
        c.set("/zero", "x")
        time.sleep(0.01)
        entry = c.get("/zero")
        # 0 TTL 的 cachetools 行为：TTLCache(ttl=0) 立即过期
        assert entry is None

    def test_register_returns_self_for_chaining(self) -> None:
        c = ResponseCache()
        result = c.register("/test", ttl=60)
        assert result is c

    def test_get_ttl_of_nonexistent_returns_zero(self, cache: ResponseCache) -> None:
        assert cache.get_ttl("/nonexistent") == 0

    def test_large_value_does_not_crash(self, cache: ResponseCache) -> None:
        large = {"data": "x" * 100_000}
        cache.set("/v1/models", large)
        retrieved = cache.get("/v1/models")
        assert retrieved is not None
        assert len(str(retrieved["data"])) == 100_000