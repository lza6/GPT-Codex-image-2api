"""上游 HTTP Session 池：跨请求复用 curl_cffi Session，复用 TCP/TLS 连接。

解决问题：每次请求新建 Session 导致 TLS 握手开销 ×N，高并发下延迟尾巴长。
方案：按 (代理配置, impersonate) 缓存 Session，复用底层连接（curl_cffi 内部即 keep-alive）。
"""

from __future__ import annotations

import threading
import time
from typing import Any

from curl_cffi import requests

from services.proxy_service import proxy_settings


class SessionPool:
    """按代理配置缓存并复用 curl_cffi Session（线程安全）。

    Session 是连接级复用（curl_cffi 底层基于 curl，自动 keep-alive），
    但保留独立的 cookie/会话状态。按 key 区分不同代理配置，避免上下文串扰。
    """

    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 200):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._sessions: dict[str, tuple[requests.Session, float]] = {}
        self._lock = threading.Lock()

    def _make_key(self, account: dict | None, impersonate: str, verify: bool) -> str:
        """生成缓存 key：代理配置 + impersonate + verify。"""
        proxy = ""
        try:
            profile = proxy_settings.get_profile(account=account)
            proxy = profile.proxy_url or "direct"
        except Exception:
            proxy = "direct"
        return f"{proxy}|{impersonate}|{int(verify)}"

    def get(self, account: dict | None = None, impersonate: str = "chrome110", verify: bool = True) -> requests.Session:
        """获取（或创建并缓存）一个 Session。"""
        key = self._make_key(account, impersonate, verify)
        now = time.monotonic()
        with self._lock:
            cached = self._sessions.get(key)
            if cached is not None:
                session, created_at = cached
                if now - created_at < self._ttl:
                    return session
                # 过期，关闭后重建
                try:
                    session.close()
                except Exception:
                    pass
                self._sessions.pop(key, None)

            # 清理过多条目（惰性）
            if len(self._sessions) >= self._max_entries:
                oldest_key = min(self._sessions, key=lambda k: self._sessions[k][1])
                try:
                    self._sessions[oldest_key][0].close()
                except Exception:
                    pass
                self._sessions.pop(oldest_key, None)

            session = requests.Session(
                **proxy_settings.build_session_kwargs(account=account, impersonate=impersonate, verify=verify)
            )
            self._sessions[key] = (session, now)
            return session

    def invalidate(self, account: dict | None = None, impersonate: str = "chrome110", verify: bool = True) -> None:
        """使某配置的 Session 失效（如 token 失效后强制重建）。"""
        key = self._make_key(account, impersonate, verify)
        with self._lock:
            cached = self._sessions.pop(key, None)
            if cached is not None:
                try:
                    cached[0].close()
                except Exception:
                    pass

    def close_all(self) -> None:
        with self._lock:
            for session, _ in self._sessions.values():
                try:
                    session.close()
                except Exception:
                    pass
            self._sessions.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pooled_sessions": len(self._sessions),
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl,
            }


# 全局 Session 池：5 分钟 TTL，最多缓存 200 个配置
session_pool = SessionPool(ttl_seconds=300.0, max_entries=200)
