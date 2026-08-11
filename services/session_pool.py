"""上游 HTTP Session 池：跨请求复用 curl_cffi Session，复用 TCP/TLS 连接。

解决问题：每次请求新建 Session 导致 TLS 握手开销 ×N，高并发下延迟尾巴长。
方案：按 (代理配置, impersonate) 缓存 Session，复用底层连接（curl_cffi 内部即 keep-alive）。

v2.17.0 四优化：
1. 连接健康预检（health_check）：从池中取出连接时发送轻量 HEAD 请求验证，减少断连请求失败
2. 动态冷却期（dynamic_cooldown）：根据错误率调整缩容冷却期，错误率越高冷却期越长
3. 连接 TTL（connection_ttl）：连接最大存活时间，到期自动重建，避免上游 TIME_WAIT 堆积
4. 指数退避重连（exponential_backoff）：连接失败后重试间隔呈指数增长，减轻上游风暴压力
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from curl_cffi import requests

from services.proxy_service import proxy_settings
from services.session_cache import TieredSessionCache

logger = logging.getLogger(__name__)


# 全局三级缓存：L1 LRU(256) + TTL(300s) + L2 Redis + L3 存储层
# 缓存 proxysettings.get_profile() 等存储层查询结果


def _cache_metrics_callback(event: str, tier: int) -> None:
    """缓存指标回调，注入 Prometheus 计数器。"""
    try:
        from services.prometheus_metrics import record_session_cache_hit, record_session_cache_miss
        if event == "hit":
            record_session_cache_hit(tier)
        elif event == "miss":
            record_session_cache_miss()
    except Exception:
        pass


session_kwargs_cache = TieredSessionCache(
    maxsize=256,
    ttl=300,
    redis_client=None,  # 由 init() 按配置注入
    storage=None,
    metrics_callback=_cache_metrics_callback,
)


class SessionPool:
    """按代理配置缓存并复用 curl_cffi Session（线程安全，自适应扩容/缩容）。

    Session 是连接级复用（curl_cffi 底层基于 curl，自动 keep-alive），
    但保留独立的 cookie/会话状态。按 key 区分不同代理配置，避免上下文串扰。

    Phase 2（7.1）：自适应池大小——空闲连接不足时渐进扩容，
    连续错误时缩容（清理最旧连接），避免资源泄漏。

    v2.17.0 增强：
    - 健康预检：取出连接时轻量 HEAD 验证，断连自动重建
    - 动态冷却期：错误率越高缩容冷却期越长（1min~5min）
    - 连接 TTL：连接最大存活时间（默认 300s），到期自动重建
    - 指数退避重连：连接失败重试间隔 1s→2s→4s→...→cap
    """

    def __init__(
        self,
        ttl_seconds: float = 300.0,
        max_entries: int = 200,
        min_size: int = 5,
        # v2.17.0 新参数
        health_check_enabled: bool = True,
        health_check_timeout: float = 5.0,
        dynamic_cooldown_min: float = 60.0,
        dynamic_cooldown_max: float = 300.0,
        connection_ttl: float = 300.0,
        backoff_base: float = 1.0,
        backoff_cap: float = 16.0,
    ):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._min_size = min_size
        self._health_check_enabled = health_check_enabled
        self._health_check_timeout = health_check_timeout
        self._dynamic_cooldown_min = dynamic_cooldown_min
        self._dynamic_cooldown_max = dynamic_cooldown_max
        self._connection_ttl = connection_ttl
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._consecutive_errors = 0
        self._last_shrink_at = 0.0
        # v2.17.0：错误率追踪——记录最近 N 次操作的成功/失败用于动态冷却期
        self._error_history: list[bool] = []  # True=成功, False=失败
        # v2.17.0：池中 value 变为 (session, created_at, conn_created_at)
        self._sessions: dict[str, tuple[requests.Session, float, float]] = {}
        self._lock = threading.Lock()

    def _make_key(self, account: dict | None, impersonate: str, verify: bool, fp_key: str = "") -> str:
        """生成缓存 key：账号标识 + 代理配置 + impersonate + verify + 指纹标识。

        必须含账号标识：池化 Session 是共享对象，若同代理多账号共享同一 Session，
        一个实例写入的头部会污染另一个实例（第七轮 B1：Authorization 串号实证）。
        用 token 末 8 位做稳定标识（不泄露完整 token）。
        fp_key（第七轮新增）：调用方指纹标识（如 oai-device-id），
        同账号不同指纹的实例不会共享 Session，会话级头与 key 一致。

        v2.24.0 增强：三级缓存代理配置查询结果，避免每次 get() 重复查存储层。
        """
        proxy = ""
        try:
            token = str((account or {}).get("access_token") or "")
            profile_cache_key = f"proxy_profile:{token[-8:]}" if token else "proxy_profile:anon"
            cached_proxy = session_kwargs_cache.get(profile_cache_key)
            if cached_proxy is not None:
                proxy = cached_proxy
            else:
                profile = proxy_settings.get_profile(account=account)
                proxy = profile.proxy_url or "direct"
                session_kwargs_cache.set(profile_cache_key, proxy)
        except Exception:
            proxy = "direct"
        token = str((account or {}).get("access_token") or "")
        acct_id = token[-8:] if token else "anon"
        return f"{acct_id}|{proxy}|{impersonate}|{int(verify)}|{fp_key}"

    # ── v2.17.0 新方法 ──────────────────────────────────────────────

    def _record_result(self, success: bool) -> None:
        """记录一次操作结果（成功/失败）到错误历史，用于动态冷却期计算。"""
        self._error_history.append(success)
        if len(self._error_history) > 100:
            self._error_history = self._error_history[-100:]

    def _error_rate(self) -> float:
        """计算最近错误率（0.0~1.0），空历史返回 0.0。"""
        if not self._error_history:
            return 0.0
        return sum(1 for s in self._error_history if not s) / len(self._error_history)

    def _cooldown_seconds(self) -> float:
        """动态冷却期：错误率越高冷却期越长，在 [min, max] 范围内线性映射。"""
        rate = self._error_rate()
        ratio = min(1.0, rate * 2.0)
        return self._dynamic_cooldown_min + (self._dynamic_cooldown_max - self._dynamic_cooldown_min) * ratio

    def _health_check(self, session: requests.Session) -> bool:
        """发送轻量 HEAD 请求验证连接健康。失败只记录和重建，不触发缩容。"""
        if not self._health_check_enabled:
            return True
        try:
            resp = session.head(
                "https://chatgpt.com/",
                timeout=self._health_check_timeout,
                headers={"Accept": "text/html,application/xhtml+xml"},
            )
            return resp is not None
        except Exception:
            return False

    def _backoff_sleep(self, attempt: int) -> None:
        """指数退避等待：base * 2^attempt, capped at backoff_cap。"""
        delay = min(self._backoff_cap, self._backoff_base * (2**attempt))
        if delay > 0:
            time.sleep(delay)

    def _create_session(self, key: str, account: dict | None, impersonate: str, verify: bool) -> requests.Session | None:
        """创建新 Session（带指数退避重试，最多 5 次）。"""
        last_error = None
        for attempt in range(5):
            try:
                session = requests.Session(
                    **proxy_settings.build_session_kwargs(account=account, impersonate=impersonate, verify=verify)
                )
                session._chatgpt2api_pooled = True  # type: ignore[attr-defined]
                session._pool_key = key  # type: ignore[attr-defined]
                session._pool_conn_created_at = time.monotonic()  # type: ignore[attr-defined]
                return session
            except Exception as exc:
                last_error = exc
                self._record_result(False)
                if attempt < 4:
                    self._backoff_sleep(attempt)
        logger.warning("session_pool 创建 Session 失败（重试 5 次后放弃）: %s", last_error)
        return None

    # ── 原有方法（增强） ────────────────────────────────────────────

    def _adaptive_grow(self) -> None:
        """空闲连接不足时渐进扩容（每次扩容 10 或 50% 取大值）。"""
        current = len(self._sessions)
        if current >= self._max_entries or current < self._min_size:
            return
        self._max_entries = min(self._max_entries + 10, int(self._max_entries * 1.5))

    def _adaptive_shrink(self) -> None:
        """连续错误时缩容：清理最旧的 20% 连接，动态冷却期（v2.17.0 改）。"""
        now = time.monotonic()
        cool = self._cooldown_seconds()
        if now - self._last_shrink_at < cool:
            return
        self._last_shrink_at = now
        with self._lock:
            if len(self._sessions) <= self._min_size:
                return
            remove_count = max(1, len(self._sessions) // 5)
            sorted_items = sorted(self._sessions.items(), key=lambda x: x[1][1])
            for key, _ in sorted_items[:remove_count]:
                cached = self._sessions.pop(key, None)
                if cached:
                    try:
                        cached[0].close()
                    except Exception:
                        pass
        # 发布会话降级事件
        try:
            from services.event_bus import SESSION_DEGRADED, Event, event_bus
            event_bus.publish(Event(SESSION_DEGRADED, {
                "pool_size": len(self._sessions),
                "max_entries": self._max_entries,
                "consecutive_errors": self._consecutive_errors,
                "removed_count": remove_count,
            }))
        except Exception:
            pass

    def get(self, account: dict | None = None, impersonate: str = "chrome110", verify: bool = True, fp_key: str = "") -> requests.Session:
        """获取（或创建并缓存）一个 Session。

        v2.17.0 增强：
        - 健康预检：从池中取出时轻量 HEAD 验证，断连自动重建
        - 连接 TTL：连接最大存活时间到期自动重建
        - 指数退避：创建失败时 1s→2s→4s→8s→16s 重试
        """
        key = self._make_key(account, impersonate, verify, fp_key)

        # Phase 1：尝试从池中获取（锁内）
        cached = None
        with self._lock:
            entry = self._sessions.get(key)
            if entry is not None:
                session, created_at, conn_created_at = entry
                now = time.monotonic()
                ttl_expired = (now - created_at) >= self._ttl
                conn_expired = (now - conn_created_at) >= self._connection_ttl
                if not ttl_expired and not conn_expired:
                    cached = (session, created_at, conn_created_at)
                else:
                    # TTL 或连接 TTL 过期，移除后关闭
                    self._sessions.pop(key, None)
                    try:
                        session.close()
                    except Exception:
                        pass

        # Phase 2：健康预检（锁外，避免阻塞其他 get）
        if cached is not None:
            session, _, _ = cached
            if self._health_check(session):
                self._record_result(True)
                return session
            # 健康检查失败——从池中移除
            self._record_result(False)
            with self._lock:
                existing = self._sessions.get(key)
                if existing is not None and existing[0] is session:
                    self._sessions.pop(key, None)
                    try:
                        session.close()
                    except Exception:
                        pass

        # Phase 3：创建新 Session（锁外，带指数退避）
        new_session = self._create_session(key, account, impersonate, verify)
        if new_session is None:
            raise RuntimeError("session_pool 创建 Session 失败（重试 5 次后放弃）")

        # Phase 4：入池（锁内，LRU 逐出 + 竞态防护）
        with self._lock:
            # LRU 逐出：超过上限时移除最旧条目
            if len(self._sessions) >= self._max_entries:
                oldest_key = min(self._sessions, key=lambda k: self._sessions[k][1])
                try:
                    self._sessions[oldest_key][0].close()
                except Exception:
                    pass
                self._sessions.pop(oldest_key, None)

            # 竞态防护：另一个线程可能已插入同 key Session
            existing = self._sessions.get(key)
            if existing is not None:
                try:
                    new_session.close()
                except Exception:
                    pass
                self._record_result(True)
                return existing[0]

            now = time.monotonic()
            self._sessions[key] = (new_session, now, getattr(new_session, "_pool_conn_created_at", now))
            self._adaptive_grow()

        self._record_result(True)
        return new_session

    def release(self, session: requests.Session) -> None:
        """归还池化 Session：不关闭底层连接，仅保留在池中供下次复用。

        供 OpenAIBackendAPI.close() 在检测到池化 Session 时调用。
        如果 Session 已被 remove() 提出池外（长轮询暂借），则重新入池；
        仍在池中则无需操作（连接复用依赖 curl keep-alive）。
        非池化 Session（无标记）由调用方直接 close()。
        """
        pool_key = getattr(session, "_pool_key", None)
        if pool_key is None:
            return
        now = time.monotonic()
        conn_created_at = getattr(session, "_pool_conn_created_at", now)
        with self._lock:
            if pool_key in self._sessions:
                return
            self._sessions[pool_key] = (session, now, conn_created_at)

    def remove(self, session: requests.Session) -> None:
        """从池中移除一个 Session（不 close），供长轮询等场景独享 Session。

        "偷出"语义（C6/P1-1）：同时摘掉 `_chatgpt2api_pooled` 与 `_pool_key` 标记。
        此后调用方 `OpenAIBackendAPI.close()` 检测到无池化标记 → 直接真 close 底层
        连接，不再归还池中。若不清标记，长轮询结束后 close()→release() 会把可能已
        淘汰的死连接重新放回池中，被后续请求复用（连接泄漏/状态不一致）。

        连续错误计数：每次 remove 视为一次错误信号，连续 3 次触发自适应缩容，
        清理最旧的 20% 连接以隔离故障。
        """
        self._consecutive_errors += 1
        if self._consecutive_errors >= 3:
            self._consecutive_errors = 0
            self._adaptive_shrink()
        with self._lock:
            for key, (sess, ts, _) in list(self._sessions.items()):
                if sess is session:
                    del self._sessions[key]
                    try:
                        session._chatgpt2api_pooled = False  # type: ignore[attr-defined]
                        session._pool_key = None  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    return

    def invalidate(self, account: dict | None = None, impersonate: str = "chrome110", verify: bool = True, fp_key: str = "") -> None:
        """使某配置的 Session 失效（如 token 失效后强制重建）。

        fp_key 为空时失效该账号全部指纹的 Session（前缀匹配）。
        """
        prefix = self._make_key(account, impersonate, verify, "")
        with self._lock:
            keys = [k for k in self._sessions if k == prefix or k.startswith(prefix)]
            for key in keys:
                cached = self._sessions.pop(key, None)
                if cached is not None:
                    try:
                        cached[0].close()
                    except Exception:
                        pass

    def close_all(self) -> None:
        with self._lock:
            for session, _, _ in self._sessions.values():
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
                "health_check_enabled": self._health_check_enabled,
                "connection_ttl": self._connection_ttl,
                "error_rate": self._error_rate(),
                "cooldown_seconds": self._cooldown_seconds(),
            }


# 全局 Session 池：5 分钟 TTL，最多缓存 200 个配置，最小保留 5 个连接
session_pool = SessionPool(ttl_seconds=300.0, max_entries=200, min_size=5)