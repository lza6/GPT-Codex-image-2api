"""代理池管理器：账号级代理绑定、健康检查、自动切换。

移植自 codex2api auth/proxy_pool.go。
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ProxyHealthStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    ISOLATED = "isolated"


class ProxySelectionStrategy(Enum):
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    LEAST_CONNECTIONS = "least_connections"


@dataclass
class ProxyEntry:
    url: str
    healthy: bool = True
    last_check: float = 0.0
    latency_ms: float = 0.0
    success_rate: float = 1.0
    weight: int = 1
    active_conns: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    status: ProxyHealthStatus = ProxyHealthStatus.HEALTHY
    isolated_at: float = 0.0
    consecutive_failures: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "healthy": self.healthy,
            "last_check": self.last_check,
            "latency_ms": round(self.latency_ms, 1),
            "success_rate": round(self.success_rate, 3),
            "weight": self.weight,
            "active_conns": self.active_conns,
            "total_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "status": self.status.value,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass
class ProxyPoolConfig:
    strategy: ProxySelectionStrategy = ProxySelectionStrategy.ROUND_ROBIN
    check_interval: float = 30.0
    timeout: float = 10.0
    isolation_threshold: int = 3
    isolation_duration: float = 300.0
    health_check_url: str = "http://www.gstatic.com/generate_204"


class ProxyPool:
    """代理池管理器：管理多个代理的健康状态和选择策略。"""

    def __init__(self, config: ProxyPoolConfig | None = None, persist_path: Path | None = None):
        self.config = config or ProxyPoolConfig()
        self._proxies: dict[str, ProxyEntry] = {}
        self._healthy: list[str] = []
        self._lock = threading.RLock()
        self._round_robin_idx = 0
        self._stop_event = threading.Event()
        self._health_thread: threading.Thread | None = None
        self._on_health_check: Callable | None = None
        self._on_isolation: Callable | None = None
        self._on_recovery: Callable | None = None
        self._persist_path = persist_path
        if persist_path is not None:
            self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        """从磁盘加载代理配置。"""
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else data.get("proxies", [])
            with self._lock:
                for item in items:
                    url = str(item.get("url") or "").strip()
                    if not url:
                        continue
                    self._proxies[url] = ProxyEntry(url=url, weight=max(1, int(item.get("weight") or 1)))
                self._rebuild_healthy()
        except Exception as exc:
            print(f"[proxy-pool] 加载持久化配置失败: {exc}")

    def save(self) -> None:
        """把当前代理配置写入磁盘。"""
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                items = [
                    {"url": e.url, "weight": e.weight}
                    for e in self._proxies.values()
                ]
            self._persist_path.write_text(
                json.dumps({"proxies": items}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[proxy-pool] 保存持久化配置失败: {exc}")

    # ---- 代理管理 ----

    def add(self, url: str, weight: int = 1) -> None:
        if not url:
            return
        with self._lock:
            if url in self._proxies:
                return
            self._proxies[url] = ProxyEntry(url=url, weight=max(1, weight))
            self._rebuild_healthy()
        self.save()

    def remove(self, url: str) -> None:
        with self._lock:
            self._proxies.pop(url, None)
            self._rebuild_healthy()
        self.save()

    def update_weight(self, url: str, weight: int) -> None:
        with self._lock:
            entry = self._proxies.get(url)
            if entry:
                with entry._lock:
                    entry.weight = max(1, weight)
        self.save()

    def get_all(self) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in self._proxies.values()]

    def get_stats(self) -> dict:
        with self._lock:
            total = len(self._proxies)
            healthy = len(self._healthy)
            isolated = sum(1 for e in self._proxies.values() if e.status == ProxyHealthStatus.ISOLATED)
            return {
                "total": total,
                "healthy": healthy,
                "isolated": isolated,
                "unhealthy": total - healthy - isolated,
                "strategy": self.config.strategy.value,
            }

    # ---- 代理选择 ----

    def select(self, strategy: ProxySelectionStrategy | None = None) -> ProxyEntry | None:
        with self._lock:
            if not self._healthy:
                return None
            s = strategy or self.config.strategy
            if s == ProxySelectionStrategy.WEIGHTED:
                return self._select_weighted()
            elif s == ProxySelectionStrategy.LEAST_CONNECTIONS:
                return self._select_least_connections()
            return self._select_round_robin()

    def _select_round_robin(self) -> ProxyEntry | None:
        if not self._healthy:
            return None
        self._round_robin_idx = (self._round_robin_idx + 1) % len(self._healthy)
        return self._proxies.get(self._healthy[self._round_robin_idx])

    def _select_weighted(self) -> ProxyEntry | None:
        if not self._healthy:
            return None
        import random
        total = sum(max(1, self._proxies[u].weight) for u in self._healthy)
        r = random.randint(0, total - 1)
        cumulative = 0
        for url in self._healthy:
            entry = self._proxies[url]
            cumulative += max(1, entry.weight)
            if r < cumulative:
                return entry
        return self._proxies.get(self._healthy[-1])

    def _select_least_connections(self) -> ProxyEntry | None:
        if not self._healthy:
            return None
        best = None
        min_score = float("inf")
        for url in self._healthy:
            entry = self._proxies[url]
            conns = entry.active_conns
            rate = max(0.1, entry.success_rate)
            score = conns / rate
            if score < min_score:
                min_score = score
                best = entry
        return best

    # ---- 健康反馈 ----

    def mark_success(self, url: str) -> None:
        with self._lock:
            entry = self._proxies.get(url)
            if not entry:
                return
            with entry._lock:
                entry.total_requests += 1
                entry.consecutive_failures = 0
                entry.success_rate = entry.success_rate * 0.9 + 0.1
                if entry.status == ProxyHealthStatus.ISOLATED:
                    entry.status = ProxyHealthStatus.HEALTHY
                    entry.isolated_at = 0.0
                    if self._on_recovery:
                        self._on_recovery(entry)
            self._rebuild_healthy()

    def mark_failure(self, url: str) -> None:
        with self._lock:
            entry = self._proxies.get(url)
            if not entry:
                return
            with entry._lock:
                entry.total_requests += 1
                entry.failed_requests += 1
                entry.consecutive_failures += 1
                entry.success_rate = entry.success_rate * 0.9
                if entry.consecutive_failures >= self.config.isolation_threshold:
                    entry.status = ProxyHealthStatus.ISOLATED
                    entry.isolated_at = time.time()
                    entry.healthy = False
                    if self._on_isolation:
                        self._on_isolation(entry)
            self._rebuild_healthy()

    def _rebuild_healthy(self) -> None:
        self._healthy = [
            url for url, entry in self._proxies.items()
            if entry.healthy and entry.status == ProxyHealthStatus.HEALTHY
        ]

    def _rebuild_healthy_if_needed(self) -> None:
        with self._lock:
            self._rebuild_healthy()

    # ---- 健康检查 ----

    def start_health_check(self) -> None:
        if self._health_thread and self._health_thread.is_alive():
            return
        self._stop_event.clear()
        self._health_thread = threading.Thread(target=self._health_loop, daemon=True, name="proxy-health")
        self._health_thread.start()

    def stop_health_check(self) -> None:
        self._stop_event.set()
        if self._health_thread:
            self._health_thread.join(timeout=5)

    def _health_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self.config.check_interval)
            with self._lock:
                for url, entry in list(self._proxies.items()):
                    self._check_single(entry)
            # 恢复过期的隔离代理
            self._recover_isolated()

    def _check_single(self, entry: ProxyEntry) -> None:
        start = time.time()
        try:
            import urllib.request
            proxy_handler = urllib.request.ProxyHandler({"http": entry.url, "https": entry.url})
            opener = urllib.request.build_opener(proxy_handler)
            opener.open(self.config.health_check_url, timeout=self.config.timeout)
            latency = (time.time() - start) * 1000
            with entry._lock:
                entry.healthy = True
                entry.last_check = time.time()
                entry.latency_ms = latency
                entry.consecutive_failures = 0
                if entry.status == ProxyHealthStatus.ISOLATED:
                    entry.status = ProxyHealthStatus.HEALTHY
                    entry.isolated_at = 0.0
            if self._on_health_check:
                self._on_health_check(entry)
        except Exception:
            with entry._lock:
                entry.consecutive_failures += 1
                if entry.consecutive_failures >= self.config.isolation_threshold:
                    entry.healthy = False
                    entry.status = ProxyHealthStatus.UNHEALTHY
            if self._on_health_check:
                self._on_health_check(entry)
        self._rebuild_healthy_if_needed()

    def _recover_isolated(self) -> None:
        now = time.time()
        with self._lock:
            for entry in self._proxies.values():
                if entry.status == ProxyHealthStatus.ISOLATED and entry.isolated_at > 0:
                    if now - entry.isolated_at >= self.config.isolation_duration:
                        entry.healthy = True
                        entry.status = ProxyHealthStatus.HEALTHY
                        entry.isolated_at = 0.0
                        if self._on_recovery:
                            self._on_recovery(entry)
            self._rebuild_healthy()


# 全局单例（持久化到 data/proxies.json）
def _default_persist_path() -> Path:
    try:
        from services.config import DATA_DIR
        return DATA_DIR / "proxies.json"
    except Exception:
        return Path("data") / "proxies.json"


proxy_pool = ProxyPool(persist_path=_default_persist_path())