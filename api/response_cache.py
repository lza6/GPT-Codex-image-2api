from __future__ import annotations

from cachetools import TTLCache

from fastapi import Response


class ResponseCache:
    """请求级响应缓存：按路径模式注册 TTL，支持 Cache-Control 头与强制刷新。

    用法：
        cache = ResponseCache()
        cache.register("/v1/models", ttl=60)

        # 在端点中：
        if not refresh:
            hit = cache.get("/v1/models")
            if hit is not None:
                return hit
        result = compute()
        cache.set("/v1/models", result)
        return result
    """

    def __init__(self) -> None:
        self._caches: dict[str, TTLCache] = {}

    def register(self, path_pattern: str, ttl: int, maxsize: int = 32) -> ResponseCache:
        self._caches[path_pattern] = TTLCache(maxsize=maxsize, ttl=ttl)
        return self

    def get(self, pattern: str, key: str = "default") -> object | None:
        cache = self._caches.get(pattern)
        if cache is None:
            return None
        return cache.get(key)

    def set(self, pattern: str, value: object, key: str = "default") -> None:
        cache = self._caches.get(pattern)
        if cache is not None:
            cache[key] = value

    def get_ttl(self, pattern: str) -> int:
        cache = self._caches.get(pattern)
        if cache is None:
            return 0
        return int(cache.ttl)

    def invalidate(self, pattern: str | None = None) -> None:
        if pattern:
            cache = self._caches.get(pattern)
            if cache:
                cache.clear()
        else:
            for cache in self._caches.values():
                cache.clear()

    def get_cache_stats(self) -> dict[str, object]:
        """返回各模式缓存统计：当前条目数/最大容量/TTL。"""
        return {
            pattern: {
                "currsize": cache.currsize,
                "maxsize": cache.maxsize,
                "ttl": cache.ttl,
            }
            for pattern, cache in sorted(self._caches.items())
        }


# 注册端点 TTL
_response_cache = ResponseCache()
_response_cache.register("/v1/models", ttl=60)
_response_cache.register("/api/providers", ttl=30)
_response_cache.register("/api/dashboard/scheduler", ttl=10)
_response_cache.register("/api/accounts", ttl=5)
_response_cache.register("/api/dashboard/ops", ttl=15)
# V-02：只读高频端点扩展（均带写侧 invalidate，见对应端点/服务）
_response_cache.register("/api/logs", ttl=15)
_response_cache.register("/api/accounts/trash", ttl=15)
_response_cache.register("/api/dashboard/usage", ttl=15)
_response_cache.register("/api/dashboard/events", ttl=5)

# 暴露的引用（保持命名一致性，但实际是带注册的实例）
response_cache = _response_cache


def apply_cache_headers(pattern: str, response: Response) -> None:
    """为响应添加 Cache-Control 头（如果模式有对应 TTL）。"""
    ttl = response_cache.get_ttl(pattern)
    if ttl > 0:
        response.headers["Cache-Control"] = f"max-age={ttl}"