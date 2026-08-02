"""全局限流中间件：滑动窗口 RPM 限制，防止突发流量打崩上游导致账号全封。

参考 codex2api 的 GlobalRPM 配置：0 = 不限流。
配置项（config.json 或环境变量）：
- rate_limit_rpm: 全局每分钟请求数上限（0 = 不限，默认 0）
- rate_limit_per_ip_rpm: 单 IP 每分钟请求数上限（0 = 不限，默认 0）
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class SlidingWindowLimiter:
    """滑动窗口限流器：按 key 记录每分钟请求时间戳，超出上限拒绝。

    D16：计数走共享状态层（Local 进程内 dict / Redis 跨进程），
    多 worker 部署配 redis_url 后限流计数全局一致（原各进程独立，误差随 worker 数放大）。
    """

    def __init__(self, window_seconds: float = 60.0, max_requests: int = 0):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self._records: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _use_shared(self) -> bool:
        from services.config import config

        return bool(config.redis_url)

    def check(self, key: str) -> bool:
        """尝试记录一次请求，返回 True 表示允许，False 表示超限。"""
        if self.max_requests <= 0:
            return True
        if self._use_shared():
            return self._check_shared(key)
        now = time.monotonic()
        with self._lock:
            records = self._records[key]
            cutoff = now - self.window_seconds
            while records and records[0] < cutoff:
                records.popleft()
            if len(records) >= self.max_requests:
                return False
            records.append(now)
            return True

    def _check_shared(self, key: str) -> bool:
        """共享层固定窗口近似（incr + TTL）：跨 worker 计数一致。

        与 LocalBackend 滑窗语义不同：窗口切换瞬间前一窗口计数清零，
        边界允许最多 2×max_requests 突刺（固定窗口近似固有取舍，非精确滑窗）。
        需要精确限流时改用 Redis ZSET 滑窗日志（登记后续迭代）。
        """
        from services.shared_state import get_shared_state

        window_slot = int(time.time() // self.window_seconds)
        shared_key = f"ratelimit:{key}:{window_slot}"
        count = get_shared_state().incr(shared_key, 1, ttl_seconds=self.window_seconds * 2)
        return count <= self.max_requests

    def clear(self, key: str) -> None:
        with self._lock:
            self._records.pop(key, None)


def resolve_client_ip(client_host: str, headers: dict[str, str], trusted_proxies: list[str]) -> str:
    """按 trusted_proxies 白名单解析真实客户端 IP（D3 XFF 伪造防护）。

    只有连接来源 IP 在白名单（可信反向代理）时才信任 XFF 首跳；
    否则忽略 XFF，直接用连接 IP——防攻击者伪造 XFF 绕过按 IP 限流。
    """
    xff = str(headers.get("x-forwarded-for") or "").strip()
    if xff and client_host in set(trusted_proxies):
        first_hop = xff.split(",")[0].strip()
        if first_hop:
            return first_hop
    return client_host or "unknown"


def _get_client_ip(request: Request) -> str:
    from services.config import config

    client_host = request.client.host if request.client else "unknown"
    return resolve_client_ip(client_host, request.headers, config.trusted_proxies)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于配置的限流中间件。初始化时从 config 读取参数。

    _per_ip 设上限并惰性清理，防止恶意 IP 洪泛导致内存无限增长。
    """

    _MAX_IP_ENTRIES = 10000

    def __init__(self, app, *, global_rpm: int = 0, per_ip_rpm: int = 0):
        super().__init__(app)
        self.global_rpm = max(0, int(global_rpm or 0))
        self.per_ip_rpm = max(0, int(per_ip_rpm or 0))
        self._global = SlidingWindowLimiter(max_requests=self.global_rpm)
        self._per_ip: dict[str, SlidingWindowLimiter] = {}
        self._per_ip_lock = Lock()

    def _prune_ip_limiters(self) -> None:
        """当 IP 条目超限时，清空最旧的一半，防止内存无限增长。"""
        if len(self._per_ip) <= self._MAX_IP_ENTRIES:
            return
        # 简单策略：超限直接清空一半（惰性 GC，这些 IP 窗口本已过期）
        keys = list(self._per_ip.keys())
        for key in keys[: len(keys) // 2]:
            self._per_ip.pop(key, None)

    async def dispatch(self, request: Request, call_next):
        # 只对 API 请求限流，静态资源不限
        if not request.url.path.startswith(("/v1/", "/api/")):
            return await call_next(request)

        if self.global_rpm > 0:
            if not self._global.check("global"):
                return JSONResponse(
                    status_code=429,
                    content={"error": {"message": "rate limit exceeded", "type": "rate_limit_error", "param": None, "code": "rate_limit_global"}},
                    headers={"Retry-After": "1"},
                )

        if self.per_ip_rpm > 0:
            ip = _get_client_ip(request)
            with self._per_ip_lock:
                self._prune_ip_limiters()
                limiter = self._per_ip.get(ip)
                if limiter is None:
                    limiter = SlidingWindowLimiter(max_requests=self.per_ip_rpm)
                    self._per_ip[ip] = limiter
            if not limiter.check(ip):
                return JSONResponse(
                    status_code=429,
                    content={"error": {"message": "per-ip rate limit exceeded", "type": "rate_limit_error", "param": None, "code": "rate_limit_ip"}},
                    headers={"Retry-After": "1"},
                )

        return await call_next(request)
