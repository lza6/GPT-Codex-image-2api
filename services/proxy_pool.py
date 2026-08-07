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


def parse_proxy_line(line: str) -> dict | None:
    """v2.9.0：解析单行代理字符串，支持多种格式。

    支持格式：
    - kookeey: host:port:user:pass-country  → http://user:pass@host:port (country=US)
    - host:port:user:pass                    → http://user:pass@host:port
    - host:port                              → http://host:port
    - http://user:pass@host:port             → 原样
    - socks5://host:port                     → 原样
    - socks5://user:pass@host:port           → 原样
    """
    line = (line or "").strip()
    if not line or line.startswith("#"):
        return None
    # 已带 scheme 的直接返回
    if "://" in line:
        return {"url": line, "host": "", "port": 0, "username": "", "password": "",
                "country": "", "protocol": line.split("://", 1)[0], "source": "import"}
    # kookeey 或 colon 格式
    country = ""
    # 先剥离 country 后缀（最后一段含 - 后非数字部分）
    parts = line.split(":")
    if len(parts) >= 3:
        # 检查最后一段是否有 country 后缀：user:pass-country
        last = parts[-1]
        if "-" in last and not last.split("-")[-1].isdigit():
            idx = last.rfind("-")
            country_candidate = last[idx + 1:].strip()
            if country_candidate and country_candidate.isalpha() and len(country_candidate) <= 6:
                country = country_candidate
                parts[-1] = last[:idx]
    if len(parts) == 4:
        host, port_str, username, password = parts
        protocol = "http"
    elif len(parts) == 2:
        host, port_str = parts
        username, password = "", ""
        protocol = "http"
    else:
        return None
    try:
        port = int(port_str)
    except ValueError:
        return None
    if not host:
        return None
    auth = f"{username}:{password}@" if username or password else ""
    url = f"{protocol}://{auth}{host}:{port}"
    return {"url": url, "host": host, "port": port, "username": username,
            "password": password, "country": country, "protocol": protocol, "source": "import"}


def parse_proxy_text(text: str) -> list[dict]:
    """v2.9.0：解析多行代理文本，返回结构化列表（去重）。"""
    seen_urls = set()
    result = []
    for line in (text or "").splitlines():
        parsed = parse_proxy_line(line)
        if not parsed:
            continue
        if parsed["url"] in seen_urls:
            continue
        seen_urls.add(parsed["url"])
        result.append(parsed)
    return result


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
    # v2.9.0：结构化字段（向后兼容，从 url 反解析）
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    country: str = ""
    protocol: str = "http"
    source: str = "manual"  # manual/kookeey/import
    label: str = ""
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
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "country": self.country,
            "protocol": self.protocol,
            "source": self.source,
            "label": self.label,
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
                    entry = ProxyEntry(
                        url=url,
                        weight=max(1, int(item.get("weight") or 1)),
                        host=str(item.get("host") or ""),
                        port=int(item.get("port") or 0),
                        username=str(item.get("username") or ""),
                        password=str(item.get("password") or ""),
                        country=str(item.get("country") or ""),
                        protocol=str(item.get("protocol") or "http"),
                        source=str(item.get("source") or "manual"),
                        label=str(item.get("label") or ""),
                    )
                    # v2.9.0：旧数据（无 host 字段）反解析填充
                    if not entry.host:
                        self._populate_structured_fields(entry)
                    self._proxies[url] = entry
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
                    {"url": e.url, "weight": e.weight,
                     "host": e.host, "port": e.port, "username": e.username,
                     "password": e.password, "country": e.country, "protocol": e.protocol,
                     "source": e.source, "label": e.label}
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
            entry = ProxyEntry(url=url, weight=max(1, weight))
            # v2.9.0：从 url 反解析 host/port
            self._populate_structured_fields(entry)
            self._proxies[url] = entry
            self._rebuild_healthy()
        self.save()

    def add_structured(self, parsed: dict, weight: int = 1) -> bool:
        """v2.9.0：按结构化字段添加代理（已解析 host/port/user/pass/country）。"""
        url = str(parsed.get("url") or "").strip()
        if not url:
            return False
        with self._lock:
            if url in self._proxies:
                return False
            entry = ProxyEntry(
                url=url,
                weight=max(1, weight),
                host=str(parsed.get("host") or ""),
                port=int(parsed.get("port") or 0),
                username=str(parsed.get("username") or ""),
                password=str(parsed.get("password") or ""),
                country=str(parsed.get("country") or ""),
                protocol=str(parsed.get("protocol") or "http"),
                source=str(parsed.get("source") or "import"),
                label=str(parsed.get("label") or ""),
            )
            self._proxies[url] = entry
            self._rebuild_healthy()
        self.save()
        return True

    def batch_import(self, text: str, weight: int = 1) -> dict:
        """v2.9.0：批量导入多行代理文本，返回 {imported, deduped, skipped}。"""
        parsed_list = parse_proxy_text(text)
        imported = 0
        skipped = 0
        for parsed in parsed_list:
            if self.add_structured(parsed, weight=weight):
                imported += 1
            else:
                skipped += 1
        return {"imported": imported, "deduped": len(parsed_list) - imported, "skipped": skipped}

    def _populate_structured_fields(self, entry: ProxyEntry) -> None:
        """从 url 反解析 host/port/user/pass（向后兼容旧数据）。"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(entry.url)
            entry.host = parsed.hostname or ""
            entry.port = parsed.port or 0
            entry.username = parsed.username or ""
            entry.password = parsed.password or ""
            entry.protocol = (parsed.scheme or "http").lower()
        except Exception:
            pass

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