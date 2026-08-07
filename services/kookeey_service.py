"""kookeey 代理服务集成（v2.9.0）。

支持两种模式：
1. 提取链接模式：用户在设置页填 kookeey 提取链接（含 sign + accessid 的完整 URL），
   后端调链接拉 IP 列表入池。最省事，用户已有现成链接。
2. API 签名模式（预留）：用户填 developer_token + access_id，后端用 HMAC-SHA1 签名调 kookeey API。

流量统计：kookeey API 不提供单 IP 流量，按请求次数 × 估算大小统计（或调 /ol 订单列表接口拿总量）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from curl_cffi.requests import Session

from services.log_service import LOG_TYPE_ACCOUNT, log_service
from services.proxy_pool import proxy_pool


@dataclass
class KookeeyConfig:
    enabled: bool = False
    extract_url: str = ""  # 提取链接模式：完整 URL（含 sign + accessid）
    developer_token: str = ""  # API 签名模式：开发者 token（base64）
    access_id: str = ""  # API 签名模式：accessid
    default_country: str = "US"
    default_count: int = 10


@dataclass
class KookeeyStats:
    """kookeey 用量统计（累计，重启不丢）。"""
    total_extracted: int = 0  # 累计拉取 IP 数
    total_requests: int = 0  # 累计调 kookeey 次数
    total_errors: int = 0
    last_extract_at: str = ""
    last_extract_count: int = 0
    last_error: str = ""
    # 按国家统计
    by_country: dict[str, int] = field(default_factory=dict)


class KookeeyService:
    """kookeey 代理集成服务。"""

    def __init__(self) -> None:
        self._config = KookeeyConfig()
        self._stats = KookeeyStats()
        self._lock = Lock()

    def update_config(self, cfg: dict) -> None:
        with self._lock:
            self._config.enabled = bool(cfg.get("enabled", False))
            self._config.extract_url = str(cfg.get("extract_url") or "").strip()
            self._config.developer_token = str(cfg.get("developer_token") or "").strip()
            self._config.access_id = str(cfg.get("access_id") or "").strip()
            self._config.default_country = str(cfg.get("default_country") or "US").strip() or "US"
            try:
                self._config.default_count = max(1, min(100, int(cfg.get("default_count") or 10)))
            except (TypeError, ValueError):
                self._config.default_count = 10

    def get_config(self) -> dict:
        with self._lock:
            return {
                "enabled": self._config.enabled,
                "extract_url": self._config.extract_url,
                "developer_token": self._config.developer_token,
                "access_id": self._config.access_id,
                "default_country": self._config.default_country,
                "default_count": self._config.default_count,
            }

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "total_extracted": self._stats.total_extracted,
                "total_requests": self._stats.total_requests,
                "total_errors": self._stats.total_errors,
                "last_extract_at": self._stats.last_extract_at,
                "last_extract_count": self._stats.last_extract_count,
                "last_error": self._stats.last_error,
                "by_country": dict(self._stats.by_country),
            }

    def test_connection(self) -> dict:
        """测试 kookeey 连接：用提取链接拉 1 个 IP 验证可用。"""
        with self._lock:
            url = self._config.extract_url
            enabled = self._config.enabled
        if not enabled or not url:
            return {"ok": False, "error": "kookeey 未启用或提取链接为空"}
        try:
            # 调链接拉 IP（n=1 测试）
            test_url = self._build_extract_url(count=1)
            ips = self._fetch_ips(test_url)
            return {"ok": True, "extracted": len(ips), "sample": ips[0] if ips else ""}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def extract_to_pool(self, country: str = "", count: int = 0) -> dict:
        """从 kookeey 拉 IP 入池。返回 {extracted, imported, deduped, skipped}。"""
        with self._lock:
            if not self._config.enabled:
                return {"ok": False, "error": "kookeey 未启用"}
            url = self._config.extract_url
            if not url:
                return {"ok": False, "error": "提取链接为空"}
            country = country or self._config.default_country
            count = max(1, min(100, count or self._config.default_count))

        try:
            extract_url = self._build_extract_url(country=country, count=count)
            self._record_request()
            ips = self._fetch_ips(extract_url)
            # 解析每行 IP 入池
            imported = 0
            deduped = 0
            skipped = 0
            for line in ips:
                parsed = _parse_kookeey_ip_line(line, country=country)
                if parsed is None:
                    skipped += 1
                    continue
                if proxy_pool.add_structured(parsed, weight=1):
                    imported += 1
                else:
                    deduped += 1
            self._record_extract_success(len(ips), imported, country)
            log_service.add(
                LOG_TYPE_ACCOUNT,
                "kookeey 提取 IP 入池",
                {"country": country, "count": count, "extracted": len(ips),
                 "imported": imported, "deduped": deduped, "skipped": skipped},
            )
            return {
                "ok": True,
                "extracted": len(ips),
                "imported": imported,
                "deduped": deduped,
                "skipped": skipped,
                "country": country,
            }
        except Exception as exc:
            self._record_error(str(exc))
            log_service.add(LOG_TYPE_ACCOUNT, "kookeey 提取失败", {"error": str(exc)[:200]})
            return {"ok": False, "error": str(exc)}

    def _build_extract_url(self, country: str = "", count: int = 10) -> str:
        """构建提取链接：基于用户配置的 extract_url，替换 n 和 g 参数。"""
        with self._lock:
            base = self._config.extract_url
        # 简单替换 n 和 g 参数
        url = re.sub(r"([?&])n=\d+", rf"\1n={count}", base)
        if country:
            if re.search(r"[?&]g=", url):
                url = re.sub(r"([?&]g=)[^&]*", rf"\1{country}", url)
            else:
                url += f"&g={country}"
        return url

    def _fetch_ips(self, url: str) -> list[str]:
        """调 kookeey 提取链接，返回 IP 行列表。"""
        with Session(impersonate="chrome110", verify=True) as session:
            resp = session.get(url, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f"kookeey extract http_{resp.status_code}: {resp.text[:200]}")
            text = resp.text or ""
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return lines

    def _record_request(self) -> None:
        with self._lock:
            self._stats.total_requests += 1

    def _record_extract_success(self, extracted: int, imported: int, country: str) -> None:
        with self._lock:
            self._stats.total_extracted += extracted
            self._stats.last_extract_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self._stats.last_extract_count = extracted
            self._stats.by_country[country] = self._stats.by_country.get(country, 0) + imported

    def _record_error(self, error: str) -> None:
        with self._lock:
            self._stats.total_errors += 1
            self._stats.last_error = error[:200]


def _parse_kookeey_ip_line(line: str, country: str = "") -> dict | None:
    """解析 kookeey 提取返回的单行 IP。

    kookeey 提取链接返回格式可能是：
    - gate.kookeey.info:1000:1023701-4a2c845a:12843fee-US  （带国家后缀）
    - 1.2.3.4:7135  （纯 IP:port，白名单模式）
    - ip:user:pass@host:port
    """
    from services.proxy_pool import parse_proxy_line
    parsed = parse_proxy_line(line)
    if parsed is None:
        return None
    parsed["source"] = "kookeey"
    if country and not parsed.get("country"):
        parsed["country"] = country
    return parsed


# 全局单例
kookeey_service = KookeeyService()
