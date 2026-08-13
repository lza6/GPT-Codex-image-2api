"""代理池管理器：账号级代理绑定、健康检查、自动切换。

移植自 codex2api auth/proxy_pool.go。
"""

from __future__ import annotations

import json
import random
import threading
import time
from collections.abc import Callable, Mapping
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
    source: str = "manual"  # manual/kookeey/import/free
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
        self._sticky: dict[str, str] = {}  # key → proxy url（按账号粘性绑定，随 save/load 持久化）
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
            sticky = data.get("sticky") if isinstance(data, dict) else None
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
                # v2.35：粘性绑定持久化（key → proxy url）；失效节点由 select_sticky 重绑
                if isinstance(sticky, dict):
                    self._sticky = {
                        str(k): str(v)
                        for k, v in sticky.items()
                        if str(k) and str(v) and str(v) in self._proxies
                    }
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
                json.dumps(
                    {"proxies": items, "sticky": dict(self._sticky)},
                    ensure_ascii=False,
                    indent=2,
                ),
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

    # ---- 按账号粘性选择（免费代理池） ----

    @staticmethod
    def _sticky_key(key: str) -> str:
        """粘性 key 归一化：email 小写、去空白。"""
        return str(key or "").strip().lower()

    def select_sticky(self, key: str = "") -> ProxyEntry | None:
        """按 key（账号 email）粘性绑定健康节点。

        - 已绑定且节点仍健康 → 返回原绑定（同一账号固定节点）
        - 已绑定但节点失效 → 删旧绑定，round-robin 重选并重绑
        - 未绑定 → round-robin 选健康节点并绑定
        - 池空 → 返回 None（调用方走回退链下一级）
        绑定关系随 save() 持久化，重启不丢。
        """
        normalized_key = self._sticky_key(key)
        with self._lock:
            if not self._healthy:
                return None
            bound_url = self._sticky.get(normalized_key)
            if bound_url and bound_url in self._healthy:
                return self._proxies.get(bound_url)
            if bound_url:
                self._sticky.pop(normalized_key, None)
            entry = self.select(ProxySelectionStrategy.ROUND_ROBIN)  # RLock 可重入
            if entry is None:
                return None
            self._sticky[normalized_key] = entry.url
        self.save()
        return entry

    # ---- 免费池清理 ----

    def prune_free(self, keep_alive: float | None = None, max_total: int | None = None) -> int:
        """移除 source==free 且不健康/超龄/超上限的条目。

        - 不健康（healthy=False 或 UNHEALTHY/ISOLATED）→ 移除
        - keep_alive（秒）：超过该时间未通过健康检查 → 移除（防止死代理堆积）
        - max_total：free 源条目超过上限时按成功率从低到高剔除多余条目
        只动 source==free，不误伤 manual/kookeey/import。返回移除数量。
        """
        removed = 0
        now = time.time()
        with self._lock:
            for url, entry in list(self._proxies.items()):
                if entry.source != "free":
                    continue
                drop = False
                if not entry.healthy or entry.status != ProxyHealthStatus.HEALTHY:
                    drop = True
                if keep_alive is not None and entry.last_check > 0 and now - entry.last_check > keep_alive:
                    drop = True
                if drop:
                    self._proxies.pop(url, None)
                    removed += 1
            if max_total is not None and max_total > 0:
                free_urls = [u for u, e in self._proxies.items() if e.source == "free"]
                if len(free_urls) > max_total:
                    excess = len(free_urls) - max_total
                    # 按成功率从低到高排序，剔除最差的 excess 个
                    ranked = sorted(free_urls, key=lambda u: self._proxies[u].success_rate)
                    for url in ranked[:excess]:
                        self._proxies.pop(url, None)
                        removed += 1
            self._rebuild_healthy()
        self.save()
        return removed

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


# =====================================================================
# 增量移植：账号分组代理池（一账号一 IP）+ 每节点图片并发限制 + provider 抽象
#
# 移植自 chatgpt2api1（同类项目）services/proxy_service.py 的：
#   ProxyGroupSelection / _account_group_proxy_reference / _resolve_proxy_group /
#   _proxy_node_has_image_capacity / _proxy_node_load_score / acquire_image_egress
#
# 设计：
#   - 账号 → account_groups[].id（group_id）→ proxy_group_id → proxy_groups 节点列表
#     → 随机选一个可用节点（跳过已达 image_concurrency_limit 的节点）
#   - 一账号一 IP：账号首次调度时绑定分组内随机可用节点，粘性持久化到 account.proxy；
#     节点被删后自动重选。
#   - 每节点图片并发限制：acquire_image_egress/release_image_egress 维护节点在途并发，
#     选节点时跳过已达并发的节点；达并发时 acquire 阻塞等待（默认不阻塞场景无需改动）。
#   - provider 抽象：节点 provider 字段（如 "kookeey"）由 config 驱动，不硬编码任何提供商。
#   - 默认关闭：config 未配置 proxy_groups/account_groups 时 enabled() 为 False，
#     所有方法返回空串/直连，保持向后兼容，不影响现有直连/全局代理逻辑。
# =====================================================================

DEFAULT_PROXY_NODE_IMAGE_CONCURRENCY_LIMIT = 30
MAX_PROXY_NODE_IMAGE_CONCURRENCY_LIMIT = 10000
PROXY_NODE_IMAGE_CONCURRENCY_FIELDS = (
    "image_concurrency_limit",
    "image_concurrency",
    "max_image_concurrency",
)


def _clean(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class ProxyNodeSelection:
    """一次代理组节点选择结果（等价于同类项目的 ProxyGroupSelection 精简版）。"""

    proxy_url: str = ""
    group_id: str = ""
    node_id: str = ""
    node_name: str = ""
    provider: str = ""
    image_concurrency_limit: int = 0
    image_egress_reserved: bool = False
    image_egress_wait_ms: int = 0

    @property
    def egress_key(self) -> str:
        if self.group_id and self.node_id:
            return f"group:{self.group_id}:{self.node_id}"
        return f"proxy:{_node_key_of_url(self.proxy_url)}"


def _node_key_of_url(proxy_url: str) -> str:
    """节点 URL 的稳定标识（大小写不敏感、去尾部斜杠）。"""
    return _clean(proxy_url).rstrip("/").lower()


def _proxy_node_id(node: Mapping[str, object], index: int) -> str:
    return _clean(node.get("id")) or _clean(node.get("name")) or f"node-{index + 1}"


def _proxy_group_node_key(group_id: str, node: Mapping[str, object], index: int) -> str:
    return f"group:{group_id}:{_proxy_node_id(node, index)}"


def proxy_node_image_concurrency_limit(
    node: Mapping[str, object],
    *,
    fallback: Mapping[str, object] | None = None,
) -> int:
    """节点图片并发上限（默认 30，上限 10000）。支持多个别名键，容错非法值。"""
    for source in (node, fallback):
        if source is None:
            continue
        for key in PROXY_NODE_IMAGE_CONCURRENCY_FIELDS:
            value = source.get(key)
            if value is None or value == "":
                continue
            try:
                return max(0, min(int(float(value)), MAX_PROXY_NODE_IMAGE_CONCURRENCY_LIMIT))
            except (OverflowError, TypeError, ValueError):
                return DEFAULT_PROXY_NODE_IMAGE_CONCURRENCY_LIMIT
    return DEFAULT_PROXY_NODE_IMAGE_CONCURRENCY_LIMIT


def _proxy_group_selection(group_id: str, node: Mapping[str, object], index: int) -> ProxyNodeSelection:
    node_id = _proxy_node_id(node, index)
    return ProxyNodeSelection(
        proxy_url=_clean(node.get("url")),
        group_id=group_id,
        node_id=node_id,
        node_name=_clean(node.get("name")) or node_id,
        provider=_clean(node.get("provider")),
        image_concurrency_limit=proxy_node_image_concurrency_limit(node),
    )


class AccountProxyPool:
    """账号级代理池：账号 → 账号分组 → 代理分组 → 节点 → 随机可用节点。

    默认关闭（config 未配置 proxy_groups / account_groups 时 enabled() 为 False），
    不改变现有直连或全局代理逻辑。
    """

    def __init__(self, config_store=None):
        if config_store is None:
            from services.config import config as _config
            config_store = _config
        self._config = config_store
        self._lock = threading.RLock()
        self._egress_inflight: dict[str, int] = {}
        self._egress_condition = threading.Condition(self._lock)

    # ---- 配置读取 ----

    def _config_dict_list(self, key: str) -> list[dict]:
        data = getattr(self._config, "data", None)
        if not isinstance(data, dict):
            try:
                data = self._config.get()
            except AttributeError:
                data = {}
        raw = data.get(key) if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def proxy_groups(self) -> list[dict]:
        return self._config_dict_list("proxy_groups")

    def account_groups(self) -> list[dict]:
        return self._config_dict_list("account_groups")

    def enabled(self) -> bool:
        """存在至少一个启用且有可用节点的代理分组时，视为开启。"""
        for group in self.proxy_groups():
            if group.get("enabled") is False:
                continue
            nodes = [
                n for n in group.get("nodes", [])
                if isinstance(n, dict) and n.get("enabled", True) and _clean(n.get("url"))
            ]
            if nodes:
                return True
        return False

    # ---- 账号 → 分组 → 代理引用 ----

    @staticmethod
    def account_group_id(account: Mapping[str, object] | None) -> str:
        if not isinstance(account, Mapping):
            return ""
        return _clean(account.get("group_id"))

    def _account_group(self, account: Mapping[str, object] | None) -> dict:
        group_id = self.account_group_id(account)
        if not group_id:
            return {}
        for group in self.account_groups():
            if _clean(group.get("id")) != group_id or group.get("enabled") is False:
                continue
            return dict(group)
        return {}

    def _account_proxy_reference(self, account: Mapping[str, object] | None) -> str:
        """账号所属分组的代理引用：可直接代理 URL，或 group:{proxy_group_id}。"""
        group = self._account_group(account)
        if not group:
            return ""
        proxy = _clean(group.get("proxy"))
        if proxy:
            return proxy
        proxy_group_id = _clean(group.get("proxy_group_id"))
        return f"group:{proxy_group_id}" if proxy_group_id else ""

    # ---- 代理组 → 节点选择 ----

    def _resolve_proxy_group(self, group_id: str) -> ProxyNodeSelection:
        """从代理分组随机选一个可用节点；全部达并发时退而求其次选负载最低节点。

        等价于同类项目 _resolve_proxy_group 的 reserve_image_egress=False 路径
        （选节点只看容量，不在此处预留；预留由 acquire_image_egress 负责）。
        """
        normalized = _clean(group_id)
        if not normalized:
            return ProxyNodeSelection()
        for group in self.proxy_groups():
            if _clean(group.get("id")) != normalized or group.get("enabled") is False:
                continue
            nodes = [
                node for node in group.get("nodes", [])
                if isinstance(node, dict) and node.get("enabled", True) and _clean(node.get("url"))
            ]
            if not nodes:
                return ProxyNodeSelection()
            indexed_nodes = list(enumerate(nodes))
            with self._egress_condition:
                available = [
                    (node_index, node)
                    for node_index, node in indexed_nodes
                    if self._proxy_node_has_image_capacity(normalized, node, node_index)
                ]
                if available:
                    selected_index, selected = random.choice(available)
                    return _proxy_group_selection(normalized, selected, selected_index)
                selected_index, selected = min(
                    indexed_nodes,
                    key=lambda item: self._proxy_node_load_score(normalized, item[1], item[0]),
                )
                return _proxy_group_selection(normalized, selected, selected_index)
        return ProxyNodeSelection()

    def _proxy_node_has_image_capacity(self, group_id: str, node: Mapping[str, object], index: int) -> bool:
        limit = proxy_node_image_concurrency_limit(node)
        if limit <= 0:
            return True
        # 与 acquire_image_egress/release_image_egress 同一 key 空间（proxy:{url}）
        key = f"proxy:{_node_key_of_url(str(node.get('url') or ''))}"
        return int(self._egress_inflight.get(key, 0)) < limit

    def _proxy_node_load_score(self, group_id: str, node: Mapping[str, object], index: int) -> tuple[float, int]:
        # 与 acquire_image_egress/release_image_egress 同一 key 空间（proxy:{url}）
        key = f"proxy:{_node_key_of_url(str(node.get('url') or ''))}"
        current = int(self._egress_inflight.get(key, 0))
        limit = proxy_node_image_concurrency_limit(node)
        if limit <= 0:
            return 0.0, current
        return current / max(1, limit), current

    def _node_in_group(self, group_id: str, proxy_url: str) -> bool:
        """账号已绑定代理 URL 是否仍属于该分组的启用节点（粘性校验，节点删除则重选）。"""
        normalized = _clean(group_id)
        target = _node_key_of_url(proxy_url)
        if not target:
            return False
        for group in self.proxy_groups():
            if _clean(group.get("id")) != normalized or group.get("enabled") is False:
                continue
            for node in group.get("nodes", []):
                if isinstance(node, dict) and node.get("enabled", True):
                    if _node_key_of_url(str(node.get("url") or "")) == target:
                        return True
        return False

    def _proxy_group_id_from_reference(self, ref: str) -> str:
        """从代理引用解析 proxy_group_id（"group:xxx" → "xxx"；直接 URL 返回空）。"""
        ref = _clean(ref)
        if ref.lower().startswith("group:"):
            return _clean(ref.split(":", 1)[1])
        return ""

    # ---- 对外主入口 ----

    def get_proxy_for_account(self, account: Mapping[str, object] | None) -> str:
        """为账号分配独立代理 URL（一账号一 IP，粘性）。

        账号已绑定且节点仍有效 → 返回原绑定（粘性）；
        未绑定 / 绑定节点已删除 → 从分组随机选可用节点；
        账号分组直接配置了代理 URL（不走节点池）→ 返回该 URL。
        未配置（enabled=False）、无分组或无可用节点时返回空串（调用方走原直连逻辑）。
        """
        if not self.enabled():
            return ""
        ref = self._account_proxy_reference(account)
        if not ref:
            return ""
        proxy_group_id = self._proxy_group_id_from_reference(ref)
        if not proxy_group_id:
            # 账号分组直接配置代理 URL（如 group.proxy），不做节点池选择
            return ref
        current = str((account or {}).get("proxy") or "").strip()
        if current and self._node_in_group(proxy_group_id, current):
            return current
        selection = self._resolve_proxy_group(proxy_group_id)
        return selection.proxy_url or ""

    # ---- 每节点图片并发限制（acquire/release） ----

    def _node_limit_for_proxy(self, proxy_url: str) -> int:
        target = _node_key_of_url(proxy_url)
        if not target:
            return 0
        for group in self.proxy_groups():
            if group.get("enabled") is False:
                continue
            for node in group.get("nodes", []):
                if isinstance(node, dict) and node.get("enabled", True):
                    if _node_key_of_url(str(node.get("url") or "")) == target:
                        return proxy_node_image_concurrency_limit(node)
        return 0

    def acquire_image_egress(self, proxy_url: str, *, deadline_monotonic: float | None = None) -> int:
        """为节点预留一个图片并发额度；已达并发则等待（最多等到 deadline）。

        返回等待毫秒数。limit<=0 或无该节点时不限并发，立即返回 0。
        """
        limit = self._node_limit_for_proxy(proxy_url)
        if limit <= 0:
            return 0
        key = f"proxy:{_node_key_of_url(proxy_url)}"
        started = time.perf_counter()
        with self._egress_condition:
            while int(self._egress_inflight.get(key, 0)) >= limit:
                remaining = (
                    deadline_monotonic - time.monotonic()
                    if deadline_monotonic is not None and deadline_monotonic > 0
                    else None
                )
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("image egress capacity timeout")
                self._egress_condition.wait(timeout=min(1.0, remaining) if remaining is not None else 1.0)
            self._egress_inflight[key] = int(self._egress_inflight.get(key, 0)) + 1
        return int((time.perf_counter() - started) * 1000)

    def release_image_egress(self, proxy_url: str) -> None:
        if self._node_limit_for_proxy(proxy_url) <= 0:
            return
        key = f"proxy:{_node_key_of_url(proxy_url)}"
        with self._egress_condition:
            current = int(self._egress_inflight.get(key, 0))
            if current <= 1:
                self._egress_inflight.pop(key, None)
            else:
                self._egress_inflight[key] = current - 1
            self._egress_condition.notify_all()

    # ---- 观测 ----

    def stats(self) -> dict[str, object]:
        with self._egress_condition:
            return {
                "enabled": self.enabled(),
                "proxy_groups": len(self.proxy_groups()),
                "account_groups": len(self.account_groups()),
                "nodes_inflight": dict(self._egress_inflight),
            }


# 全局单例（供 account_service 调度接入；默认关闭，无副作用）
account_proxy_pool = AccountProxyPool()