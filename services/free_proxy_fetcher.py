"""免费代理池抓取器：从纯 API 免费源抓取、解析、预检并注入 ProxyPool。

kookeey 付费住宅代理的低成本替代。架构：
  config.free_proxy → FreeProxyFetcher 守护线程 → 4 源抓取
  → parse_* → 去重 → 连通性预检 → ProxyPool.add_structured(source="free")
  → _health_loop 持续校准 → resolve_account_proxy(email) 按账号粘性分配

安全红线：凭据走免费代理有泄露风险。free_proxy.enabled 默认 false，
登录/OTP 路径默认优先 kookeey（若开启）；本模块仅在显式开启时工作，
默认关闭时 start() 为无副作用空操作（零行为变化）。
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 抓取统一超时上限（秒），单源可覆盖
DEFAULT_FETCH_TIMEOUT = 15


@dataclass(frozen=True)
class FreeProxySource:
    """一个免费代理源描述。

    format: "ipport"（ip:port 文本行）| "json"（geonode 结构）
    protocols: 允许的代理协议（默认仅 http，过滤 socks 等）
    """

    name: str
    url: str
    format: str  # "ipport" | "json"
    protocols: tuple[str, ...] = ("http",)
    enabled: bool = True


def _normalized_protocols(protocols) -> tuple[str, ...]:
    if isinstance(protocols, (list, tuple)):
        return tuple(str(p).strip().lower() for p in protocols if str(p).strip())
    return ("http",)


def parse_ipport_text(text: str, protocols=("http",)) -> list[dict]:
    """解析 ip:port 文本（复用 parse_proxy_line），过滤协议。返回结构化列表（去重）。"""
    from services.proxy_pool import parse_proxy_line

    allowed = set(_normalized_protocols(protocols))
    seen: set[str] = set()
    result: list[dict] = []
    for line in (text or "").splitlines():
        parsed = parse_proxy_line(line)
        if not parsed:
            continue
        if parsed["protocol"].lower() not in allowed:
            continue
        url = parsed["url"]
        if url in seen:
            continue
        seen.add(url)
        parsed["source"] = "free"
        result.append(parsed)
    return result


def parse_geonode_json(text: str, protocols=("http",)) -> list[dict]:
    """解析 geonode JSON（data[].ip/port/protocols/country）。缺字段条目丢弃。"""
    allowed = set(_normalized_protocols(protocols))
    try:
        data = json.loads(text or "")
    except (ValueError, TypeError):
        return []
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    result: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip") or "").strip()
        port = str(item.get("port") or "").strip()
        if not ip or not port.isdigit():
            continue
        raw_protocols = item.get("protocols")
        item_protocols = (
            [str(p).strip().lower() for p in raw_protocols if str(p).strip()]
            if isinstance(raw_protocols, list)
            else ["http"]
        )
        if not item_protocols or not any(p in allowed for p in item_protocols):
            continue
        url = f"http://{ip}:{port}"
        if url in seen:
            continue
        seen.add(url)
        result.append({
            "url": url,
            "host": ip,
            "port": int(port),
            "username": "",
            "password": "",
            "country": str(item.get("country") or "").strip(),
            "protocol": "http",
            "source": "free",
        })
    return result


def parse_source(payload: str, src: FreeProxySource) -> list[dict]:
    """按 src.format 分派解析；未知 format 返回 [] + warning。"""
    fmt = str(src.format or "").strip().lower()
    if fmt == "ipport":
        return parse_ipport_text(payload, src.protocols)
    if fmt == "json":
        return parse_geonode_json(payload, src.protocols)
    logger.warning("[free-proxy] 未知 format=%r，跳过源 %s", fmt, src.name)
    return []


class FreeProxyFetcher:
    """免费代理池抓取守护线程。

    - start()/stop()：守护线程，启动立即抓一次，再按 refresh_interval_min 周期抓取
    - 配置热加载：每次周期读 config.get_free_proxy_settings()，改 enabled 无需重启
    - 单源失败不中断，仅 warning 记录；整体不抛
    - 可注入 config_provider / pool / session_factory 便于测试（全 mock，不触网）
    """

    def __init__(
        self,
        config_provider: Any | None = None,
        pool: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._config = config_provider
        self._pool = pool
        self._session_factory = session_factory
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._last_stats: dict = field(default_factory=lambda: {"sources_ok": 0, "fetched": 0, "injected": 0})

    # ---- 配置 / 依赖 ----

    def _settings(self) -> dict:
        try:
            if self._config is not None:
                settings = self._config.get_free_proxy_settings()
            else:
                from services.config import config

                settings = config.get_free_proxy_settings()
        except Exception:
            settings = {}
        return settings if isinstance(settings, dict) else {}

    def _pool_instance(self):
        if self._pool is not None:
            return self._pool
        from services.proxy_pool import proxy_pool

        return proxy_pool

    def _session(self) -> Any:
        """抓取/预检用 curl_cffi Session（可注入 mock factory）。"""
        if self._session_factory is not None:
            return self._session_factory()
        from curl_cffi.requests import Session

        return Session(impersonate="edge101")

    # ---- 线程生命周期 ----

    def start(self) -> None:
        """启动守护线程；已启动时幂等。默认关闭时线程空转（无副作用）。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="free-proxy-fetch")
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._thread is not None:
                self._thread.join(timeout=5)

    def _loop(self) -> None:
        # 启动立即抓一次
        try:
            self._last_stats = self._fetch_once()
            logger.info(
                "[free-proxy-fetch] 首抓完成 sources_ok=%d fetched=%d injected=%d",
                self._last_stats.get("sources_ok", 0),
                self._last_stats.get("fetched", 0),
                self._last_stats.get("injected", 0),
            )
        except Exception:
            logger.warning("[free-proxy-fetch] 首抓异常", exc_info=True)
        while not self._stop_event.is_set():
            interval_min = self._refresh_interval()
            self._stop_event.wait(max(1, interval_min) * 60)
            if self._stop_event.is_set():
                break
            if not self._enabled():
                continue  # 热关闭：跳过本轮，线程继续空转等待下轮
            if not self._should_fetch():
                continue
            try:
                self._last_stats = self._fetch_once()
            except Exception:
                logger.warning("[free-proxy-fetch] 周期抓取异常", exc_info=True)

    def _enabled(self) -> bool:
        return bool(self._settings().get("enabled"))

    def _refresh_interval(self) -> int:
        raw = self._settings().get("refresh_interval_min")
        try:
            return max(5, int(raw or 30))
        except (OverflowError, TypeError, ValueError):
            return 30

    def _timeout(self) -> float:
        raw = self._settings().get("timeout_sec")
        try:
            return max(1.0, float(raw or DEFAULT_FETCH_TIMEOUT))
        except (OverflowError, TypeError, ValueError):
            return DEFAULT_FETCH_TIMEOUT

    def _precheck_url(self) -> str:
        return str(self._settings().get("precheck_url") or "https://api.ipify.org").strip()

    def _max_pool_size(self) -> int:
        raw = self._settings().get("max_pool_size")
        try:
            return max(0, int(raw or 0))
        except (OverflowError, TypeError, ValueError):
            return 0

    def _should_fetch(self) -> bool:
        """健康免费代理数 >= min_healthy 时可跳过本轮（省上游请求）。"""
        min_healthy = self._settings().get("min_healthy")
        try:
            threshold = max(0, int(min_healthy or 0))
        except (OverflowError, TypeError, ValueError):
            threshold = 0
        if threshold <= 0:
            return True
        return self._healthy_free_count() < threshold

    def _healthy_free_count(self) -> int:
        pool = self._pool_instance()
        try:
            from services.proxy_pool import ProxyHealthStatus

            with pool._lock:  # noqa: SLF001 - 同模块内访问，避免另开接口
                return sum(
                    1
                    for e in pool._proxies.values()  # noqa: SLF001
                    if e.source == "free" and e.healthy and e.status == ProxyHealthStatus.HEALTHY
                )
        except Exception:
            return 0

    # ---- 抓取 ----

    def _fetch_url(self, url: str, timeout: float) -> str:
        """抓取单个源文本；HTTP 错误/超时抛异常由调用方记录。"""
        session = self._session()
        try:
            response = session.get(str(url), timeout=timeout)
            response.raise_for_status()
            return str(response.text or "")
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _fetch_once(self) -> dict:
        """抓取所有启用源。单源异常不中断，整体不抛。

        返回 {"sources_ok", "fetched", "injected", "precheck_passed"}。
        """
        settings = self._settings()
        raw_sources = settings.get("sources") or []
        if not self._enabled() or not isinstance(raw_sources, list):
            return {"sources_ok": 0, "fetched": 0, "injected": 0, "precheck_passed": 0}
        timeout = self._timeout()
        fetched = 0
        sources_ok = 0
        injected = 0
        for raw in raw_sources:
            if not isinstance(raw, dict):
                continue
            if raw.get("enabled") is False:
                continue
            src = FreeProxySource(
                name=str(raw.get("name") or "?")[:64],
                url=str(raw.get("url") or "").strip(),
                format=str(raw.get("format") or "ipport").strip().lower(),
                protocols=_normalized_protocols(raw.get("protocols")),
                enabled=True,
            )
            if not src.url or src.format not in {"ipport", "json"}:
                continue
            try:
                payload = self._fetch_url(src.url, timeout)
            except Exception as exc:
                logger.warning("[free-proxy] 源 %s 抓取失败: %s", src.name, exc)
                continue
            fetched += 1
            parsed = parse_source(payload, src)
            if not parsed:
                logger.warning("[free-proxy] 源 %s 解析为空", src.name)
                continue
            sources_ok += 1
            result = self._inject(parsed)
            injected += result.get("injected", 0)
            logger.info(
                "[free-proxy] 源 %s 解析 %d 条 → 注入 %d / 丢弃 %d",
                src.name,
                len(parsed),
                result.get("injected", 0),
                result.get("skipped", 0),
            )
        return {"sources_ok": sources_ok, "fetched": fetched, "injected": injected, "precheck_passed": injected}

    # ---- 预检 ----

    def _precheck(self, proxy_url: str, timeout: float) -> bool:
        ok, _ip = self._precheck_and_ip(proxy_url, timeout)
        return ok

    def _precheck_and_ip(self, proxy_url: str, timeout: float) -> tuple[bool, str]:
        """经代理 GET precheck_url，返回 (连通, 出口IP)。失败返回 (False, "")。"""
        url = str(proxy_url or "").strip()
        if not url:
            return False, ""
        session = self._session()
        try:
            response = session.get(self._precheck_url(), proxy=url, timeout=timeout)
            return response.status_code < 500, str(response.text or "").strip()[:64]
        except Exception:
            return False, ""
        finally:
            try:
                session.close()
            except Exception:
                pass

    # ---- 注入 ----

    def _inject(self, parsed_list: list[dict]) -> dict:
        """去重 → 预检 → add_structured(source="free") → 超上限剔除。

        返回 {"injected", "skipped", "pruned"}。
        """
        pool = self._pool_instance()
        timeout = self._timeout()
        max_pool = self._max_pool_size()
        # 限制单轮预检数量：海量免费源全量连通性预检会卡死。
        # 预算 = max(10000, max_pool*10)（免费代理健康率极低，需大量预检才有足够健康 IP）。
        try:
            budget = max(10000, int(max_pool or 200) * 10)
        except (TypeError, ValueError):
            budget = 10000
        candidates = parsed_list[:budget]
        injected = 0
        skipped = 0
        # 并发预检：免费代理健康率极低（约 1/2000），串行预检不可行。
        # 用线程池并行（48 workers），每条超时仍由 _precheck_and_ip 控制。
        from concurrent.futures import ThreadPoolExecutor

        def _precheck_one(parsed: dict):
            url = str(parsed.get("url") or "").strip()
            if not url:
                return None
            ok, ip = self._precheck_and_ip(url, timeout)
            if not ok:
                return None
            out = dict(parsed)
            out["source"] = "free"
            if ip:
                out["label"] = ip
            return out

        try:
            workers = 48
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(_precheck_one, candidates))
        except Exception:
            results = [_precheck_one(c) for c in candidates]
        for parsed in results:
            if parsed is not None and pool.add_structured(parsed, weight=1):
                injected += 1
            else:
                skipped += 1
        pruned = 0
        if max_pool > 0:
            prune = getattr(pool, "prune_free", None)
            if callable(prune):
                try:
                    pruned = prune(max_total=max_pool)
                except Exception:
                    pruned = 0
        return {"injected": injected, "skipped": skipped, "pruned": pruned}


# 全局单例（供 main.py 启动接入；默认 free_proxy.enabled=false 时零副作用）
free_proxy_fetcher = FreeProxyFetcher()
