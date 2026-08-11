"""主动告警（D18）：熔断/备份失败/账号失效/配额耗尽事件推送到运维通道。

设计红线：
- 发送失败绝不阻塞主流程（异步调用方自行决定；本模块同步发送但吞掉所有异常）
- 失败重试 1 次（固定 1s 退避），最多 2 次尝试
- 防告警风暴：同事件指纹在去重窗口内只发一次（内存去重，惰性淘汰）
- 配置为空（未启用）时所有 send 为 no-op
- 多通道支持：通用 webhook 兼容 + 企业微信(WeCom) + 钉钉(DingTalk) +
  Telegram Bot API + SMTP 邮件，任一通道失败不阻塞其他通道
"""

from __future__ import annotations

import logging
import smtplib
import threading
import time
from email.message import EmailMessage
from typing import Any

from curl_cffi import requests

logger = logging.getLogger(__name__)

DEFAULT_EVENTS = [
    "circuit_breaker_open", "circuit_breaker_closed", "backup_failure", "backup_checksum_mismatch",
    "account_invalid", "account_recovered", "quota_exhausted", "quota_forecast_depletion",
]

# S-R6：模块级去重状态（跨实例共享）。_build_from_config 每次重建 AlertService，
# 若去重表是实例字段则每重建一次清空一次 → 告警风暴。这里提升到模块级。
_GLOBAL_SENT_AT: dict[str, float] = {}
_GLOBAL_LOCK = threading.Lock()


def _bool_value(value: object, default: bool = True) -> bool:
    """通道配置布尔归一化（兼容字符串 "true"/"false"）。缺省按 default（向后兼容旧配置无 enabled 字段）。"""
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    if value is None:
        return default
    return bool(value)


class AlertService:
    def __init__(
        self,
        webhook_url: str = "",
        timeout_seconds: int = 10,
        events: list[str] | None = None,
        dedupe_window_seconds: float = 300.0,
        channels: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.webhook_url = str(webhook_url or "").strip()
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.events = set(events or DEFAULT_EVENTS)
        self.dedupe_window = max(1.0, float(dedupe_window_seconds))
        # S-R6：去重表升级为模块级共享——原实现是每实例内存态，而 send_alert 每次
        # _build_from_config 重建实例 → 去重表被清空，熔断高频触发时同账号告警刷屏
        self._sent_at = _GLOBAL_SENT_AT
        self._lock = _GLOBAL_LOCK
        # 多通道配置：{通道名: {webhook_url, type, ...}}
        self.channels: dict[str, dict[str, Any]] = dict(channels or {})

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url) or bool(self.channels)

    def _fingerprint(self, event: str, payload: dict) -> str:
        # 同事件 + 语义字段一致视为重复（如熔断同一账号、备份同一错误、账号同一失效原因）。
        # 字段不全会导致不同语义的告警互相误抑制（红队 R2：account_invalid 的 reason 必须入指纹）。
        key_parts = [event]
        for field in ("token_suffix", "account", "error", "model", "reason", "trigger", "plan_type", "source_type"):
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
        """发送告警。返回是否至少有一个通道实际发出（去重/禁用/全失败均返回 False，绝不抛异常）。"""
        if not self.enabled or event not in self.events:
            return False
        fingerprint = self._fingerprint(event, payload)
        if self._should_skip_dedupe(fingerprint):
            logger.debug("告警去重跳过: %s", fingerprint)
            return False
        body = {"event": event, "ts": int(time.time()), **payload}

        any_sent = False

        # 通用 webhook 通道（保持向后兼容）
        if self.webhook_url:
            if self._send_webhook(body):
                any_sent = True

        # 多通道分发：任一通道失败不阻塞其他通道
        for channel_name, channel_cfg in self.channels.items():
            if self._send_channel(channel_name, channel_cfg, body):
                any_sent = True

        if not any_sent:
            logger.error("告警发送最终失败: %s", event)
        return any_sent

    # ------------------------------------------------------------------
    # 通道发送
    # ------------------------------------------------------------------

    def _send_webhook(self, body: dict) -> bool:
        """通用 webhook 发送（含重试）。"""
        for attempt in range(2):  # 首次 + 重试 1 次
            try:
                requests.post(self.webhook_url, json=body, timeout=self.timeout_seconds)
                logger.info("告警已发送(webhook): %s", body.get("event", ""))
                return True
            except Exception as exc:  # noqa: BLE001 - 发送失败绝不阻塞主流程
                logger.warning("告警发送失败(webhook)（第 %d 次）: %s", attempt + 1, exc)
                if attempt == 0:
                    time.sleep(1.0)
        return False

    def _send_channel(self, channel_name: str, channel_cfg: dict[str, Any], body: dict) -> bool:
        """按通道类型分发告警。任一通道失败/未配置不阻塞其他通道。

        支持类型：telegram / wecom / dingtalk / email / 自定义（按通用 webhook 发送）。
        enabled=False 的通道直接跳过；参数不完整（如缺 bot_token、缺 webhook_url）也跳过。
        """
        if not _bool_value(channel_cfg.get("enabled"), True):
            logger.debug("告警通道 %s 已禁用，跳过", channel_name)
            return False
        channel_type = str(channel_cfg.get("type", channel_name)).strip().lower()
        if channel_type == "telegram":
            return self._send_telegram(channel_cfg, body)
        elif channel_type == "email":
            return self._send_email(channel_cfg, body)
        elif channel_type == "wecom":
            webhook_url = str(channel_cfg.get("webhook_url", "")).strip()
            if not webhook_url:
                logger.warning("告警通道 %s 缺少 webhook_url，跳过", channel_name)
                return False
            return self._send_wecom(webhook_url, body)
        elif channel_type == "dingtalk":
            webhook_url = str(channel_cfg.get("webhook_url", "")).strip()
            if not webhook_url:
                logger.warning("告警通道 %s 缺少 webhook_url，跳过", channel_name)
                return False
            return self._send_dingtalk(webhook_url, body)
        else:
            # 未知通道类型，尝试通用 webhook 格式
            webhook_url = str(channel_cfg.get("webhook_url", "")).strip()
            if not webhook_url:
                logger.warning("告警通道 %s 缺少 webhook_url，跳过", channel_name)
                return False
            logger.debug("告警通道 %s 类型 %s 未知，按通用 webhook 发送", channel_name, channel_type)
            return self._send_webhook_generic(webhook_url, body)

    def _send_telegram(self, channel_cfg: dict[str, Any], body: dict) -> bool:
        """Telegram Bot API 发送（sendMessage，纯文本避免 Markdown 转义 400）。"""
        bot_token = str(channel_cfg.get("bot_token") or "").strip()
        chat_id = str(channel_cfg.get("chat_id") or "").strip()
        if not bot_token or not chat_id:
            logger.warning("告警通道 telegram 缺少 bot_token 或 chat_id，跳过")
            return False
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        text = self._format_markdown(body)
        for attempt in range(2):
            try:
                requests.post(
                    url,
                    json={"chat_id": chat_id, "text": text},
                    timeout=self.timeout_seconds,
                )
                logger.info("告警已发送(telegram): %s", body.get("event", ""))
                return True
            except Exception as exc:  # noqa: BLE001 - 发送失败绝不阻塞主流程
                logger.warning("告警发送失败(telegram)（第 %d 次）: %s", attempt + 1, exc)
                if attempt == 0:
                    time.sleep(1.0)
        return False

    def _send_email(self, channel_cfg: dict[str, Any], body: dict) -> bool:
        """SMTP 邮件发送（支持 SSL 直连或 STARTTLS）。"""
        smtp_host = str(channel_cfg.get("smtp_host") or "").strip()
        try:
            smtp_port = max(1, int(channel_cfg.get("smtp_port") or 465))
        except (TypeError, ValueError):
            smtp_port = 465
        smtp_user = str(channel_cfg.get("smtp_user") or "").strip()
        smtp_password = str(channel_cfg.get("smtp_password") or "").strip()
        use_tls = _bool_value(channel_cfg.get("use_tls"), True)
        from_addr = str(channel_cfg.get("from_addr") or "").strip() or smtp_user
        raw_to = channel_cfg.get("to_addrs") or []
        if isinstance(raw_to, str):
            to_addrs = [addr.strip() for addr in raw_to.split(",") if addr.strip()]
        else:
            to_addrs = [str(addr).strip() for addr in raw_to if str(addr).strip()]
        if not smtp_host or not from_addr or not to_addrs:
            logger.warning("告警通道 email 配置不完整（smtp_host/from_addr/to_addrs），跳过")
            return False

        msg = EmailMessage()
        msg["Subject"] = f"[ChatGPT2API 告警] {body.get('event', '告警')}"
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)
        msg.set_content(self._format_markdown(body))

        for attempt in range(2):
            try:
                if use_tls:
                    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=self.timeout_seconds) as server:
                        if smtp_user:
                            server.login(smtp_user, smtp_password)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(smtp_host, smtp_port, timeout=self.timeout_seconds) as server:
                        server.starttls()
                        if smtp_user:
                            server.login(smtp_user, smtp_password)
                        server.send_message(msg)
                logger.info("告警已发送(email): %s", body.get("event", ""))
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("告警发送失败(email)（第 %d 次）: %s", attempt + 1, exc)
                if attempt == 0:
                    time.sleep(1.0)
        return False

    def _send_webhook_generic(self, webhook_url: str, body: dict) -> bool:
        """通用 webhook 发送（指定 URL，含重试）。"""
        for attempt in range(2):
            try:
                requests.post(webhook_url, json=body, timeout=self.timeout_seconds)
                logger.info("告警已发送(channel): %s", body.get("event", ""))
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("告警通道发送失败（第 %d 次）: %s", attempt + 1, exc)
                if attempt == 0:
                    time.sleep(1.0)
        return False

    def _send_wecom(self, webhook_url: str, body: dict) -> bool:
        """企业微信机器人消息。"""
        markdown_content = self._format_markdown(body)
        for attempt in range(2):
            try:
                requests.post(
                    webhook_url,
                    json={"msgtype": "markdown", "markdown": {"content": markdown_content}},
                    timeout=self.timeout_seconds,
                )
                logger.info("告警已发送(wecom): %s", body.get("event", ""))
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("告警发送失败(wecom)（第 %d 次）: %s", attempt + 1, exc)
                if attempt == 0:
                    time.sleep(1.0)
        return False

    def _send_dingtalk(self, webhook_url: str, body: dict) -> bool:
        """钉钉机器人消息。"""
        markdown_text = self._format_markdown(body)
        for attempt in range(2):
            try:
                requests.post(
                    webhook_url,
                    json={
                        "msgtype": "markdown",
                        "markdown": {
                            "title": body.get("event", "告警"),
                            "text": markdown_text,
                        },
                    },
                    timeout=self.timeout_seconds,
                )
                logger.info("告警已发送(dingtalk): %s", body.get("event", ""))
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("告警发送失败(dingtalk)（第 %d 次）: %s", attempt + 1, exc)
                if attempt == 0:
                    time.sleep(1.0)
        return False

    @staticmethod
    def _format_markdown(body: dict) -> str:
        """格式化告警载荷为 Markdown 文本。"""
        lines = [f"## {body.get('event', '告警')}"]
        for key, value in body.items():
            if key != "event":
                lines.append(f"**{key}**: {value}")
        return "\n\n".join(lines)


def _build_from_config() -> AlertService:
    from services.config import config

    # 多通道配置经 config.alert_channels 归一化（normalize + 环境变量覆盖）后注入
    return AlertService(
        webhook_url=config.alert_webhook_url,
        timeout_seconds=config.alert_webhook_timeout,
        events=config.alert_events,
        channels=config.alert_channels,
    )


def send_alert(event: str, payload: dict) -> bool:
    """全局入口：从 config 动态构建（配置热更新生效）。"""
    try:
        return _build_from_config().send(event, payload)
    except Exception as exc:  # noqa: BLE001 - 双保险，告警路径绝不抛异常
        logger.warning("告警构建/发送异常: %s", exc)
        return False