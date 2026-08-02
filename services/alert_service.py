"""主动告警 webhook（D18）：熔断/备份失败/账号失效/配额耗尽事件推送到运维通道。

设计红线：
- 发送失败绝不阻塞主流程（异步调用方自行决定；本模块同步发送但吞掉所有异常）
- 失败重试 1 次（固定 1s 退避），最多 2 次尝试
- 防告警风暴：同事件指纹在去重窗口内只发一次（内存去重，惰性淘汰）
- 配置为空（未启用）时所有 send 为 no-op
"""

from __future__ import annotations

import logging
import threading
import time

from curl_cffi import requests

logger = logging.getLogger(__name__)

DEFAULT_EVENTS = ["circuit_breaker_open", "backup_failure", "account_invalid", "quota_exhausted"]


class AlertService:
    def __init__(
        self,
        webhook_url: str = "",
        timeout_seconds: int = 10,
        events: list[str] | None = None,
        dedupe_window_seconds: float = 300.0,
    ) -> None:
        self.webhook_url = str(webhook_url or "").strip()
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.events = set(events or DEFAULT_EVENTS)
        self.dedupe_window = max(1.0, float(dedupe_window_seconds))
        self._sent_at: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def _fingerprint(self, event: str, payload: dict) -> str:
        # 同事件 + 关键字段一致视为重复（如熔断同一账号、备份同一错误）
        key_parts = [event]
        for field in ("token_suffix", "account", "error", "model"):
            value = payload.get(field)
            if value:
                key_parts.append(str(value)[:64])
        return "|".join(key_parts)

    def _should_skip_dedupe(self, fingerprint: str) -> bool:
        now = time.monotonic()
        with self._lock:
            # 惰性淘汰过期指纹（防 _sent_at 无界增长）
            cutoff = now - self.dedupe_window
            self._sent_at = {fp: ts for fp, ts in self._sent_at.items() if ts >= cutoff}
            if fingerprint in self._sent_at:
                return True
            self._sent_at[fingerprint] = now
            return False

    def send(self, event: str, payload: dict) -> bool:
        """发送告警。返回是否实际发出（去重/禁用/失败均返回 False，绝不抛异常）。"""
        if not self.enabled or event not in self.events:
            return False
        fingerprint = self._fingerprint(event, payload)
        if self._should_skip_dedupe(fingerprint):
            logger.debug("告警去重跳过: %s", fingerprint)
            return False
        body = {"event": event, "ts": int(time.time()), **payload}
        for attempt in range(2):  # 首次 + 重试 1 次
            try:
                requests.post(self.webhook_url, json=body, timeout=self.timeout_seconds)
                logger.info("告警已发送: %s", event)
                return True
            except Exception as exc:  # noqa: BLE001 - 发送失败绝不阻塞主流程
                logger.warning("告警发送失败（第 %d 次）: %s", attempt + 1, exc)
                if attempt == 0:
                    time.sleep(1.0)
        logger.error("告警发送最终失败: %s", event)
        return False


def _build_from_config() -> AlertService:
    from services.config import config

    return AlertService(
        webhook_url=config.alert_webhook_url,
        timeout_seconds=config.alert_webhook_timeout,
        events=config.alert_events,
    )


def send_alert(event: str, payload: dict) -> bool:
    """全局入口：从 config 动态构建（配置热更新生效）。"""
    try:
        return _build_from_config().send(event, payload)
    except Exception as exc:  # noqa: BLE001 - 双保险，告警路径绝不抛异常
        logger.warning("告警构建/发送异常: %s", exc)
        return False
