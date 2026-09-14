"""磁盘使用率阈值告警守护（v2.37.0 G1）。

盲区扫描第 3 条：凌晨三点磁盘满。`image_min_free_mb` 只挡图片落盘，
不覆盖全局磁盘——当 data/ 所在分区写满时无任何告警，本模块补上
"磁盘使用率超阈值 → 发布 system.disk_high 事件"的兜底守护。

设计红线：
- 连续超阈值只告警一次（去重），回落到阈值下后再次超才重发
- 检测失败（shutil 异常）只打日志，绝不影响主流程
- 告警事件进事件总线（event_bus），由既有 alerts/SSE 通道消费
- 阈值用模块常量默认（本批不引新配置项，避免 6 步接线负担）
"""

from __future__ import annotations

import logging
import shutil
import threading
from typing import Any

logger = logging.getLogger(__name__)

# 磁盘使用率告警事件名
DISK_ALERT_EVENT = "system.disk_high"

# 默认阈值（%）：磁盘使用率超过该值触发告警
DEFAULT_DISK_ALERT_THRESHOLD_PCT = 90.0

# 守护线程 tick 间隔（秒）
DISK_ALERT_CHECK_INTERVAL_SECONDS = 300.0


def _publish_disk_event(event_type: str, payload: dict[str, Any]) -> None:
    """发布磁盘告警事件到事件总线。失败不阻断主流程。"""
    try:
        from services.event_bus import Event, event_bus

        event_bus.publish(Event(event_type, payload))
    except Exception:  # noqa: BLE001 - 事件发布失败绝不阻断守护
        logger.warning("磁盘告警事件发布失败: %s", event_type)


class DiskAlertGuard:
    """磁盘使用率告警守护。

    状态说明：
    - `_last_alert_above: bool` —— 上次 tick 是否处于"超阈值告警态"。
      仅当从"未告警态"变到"超阈值"时才发布事件；持续超阈值不重复发；
      回落到阈值下后（未告警态）再次超阈值才重发。
    """

    def __init__(self, threshold_pct: float = DEFAULT_DISK_ALERT_THRESHOLD_PCT) -> None:
        self.threshold_pct = max(1.0, min(99.9, float(threshold_pct)))
        self._last_alert_above = False

    def tick(self) -> None:
        """检测一次磁盘使用率，超阈值且状态翻转时发布事件。"""
        try:
            total, used, free = shutil.disk_usage(".")
        except OSError as exc:
            logger.warning("磁盘使用率检测失败: %s", exc)
            return
        used_pct = int(used / total * 100) if total else 0
        free_mb = int(free / (1024 * 1024))
        above = used_pct >= self.threshold_pct
        if above and not self._last_alert_above:
            _publish_disk_event(DISK_ALERT_EVENT, {
                "used_pct": used_pct,
                "threshold_pct": int(self.threshold_pct),
                "free_mb": free_mb,
            })
            self._last_alert_above = True
        elif not above:
            self._last_alert_above = False


def check_alert_unwired(cfg: Any) -> None:
    """启动检查：alert_events 已配置但无任何可用通道时提示接线。不抛异常。"""
    try:
        events = list(cfg.alert_events or [])
        webhook_url = str(getattr(cfg, "alert_webhook_url", "") or "").strip()
        channels = getattr(cfg, "alert_channels", {}) or {}
        any_enabled = any(
            str(ch.get("enabled", "")).strip().lower() in {"1", "true", "yes", "on"}
            for ch in channels.values() if isinstance(ch, dict)
        )
        if events and not webhook_url and not any_enabled:
            logger.warning(
                "告警未接线：alert_events 已配置但无任何可用通道（webhook_url/channels 均未启用），"
                "详见 README 告警章节"
            )
    except Exception as exc:  # noqa: BLE001 - 接线检查失败不阻断启动
        logger.warning("告警接线检查异常: %s", exc)


def start_disk_alert_scheduler(stop_event: threading.Event) -> threading.Thread:
    """启动磁盘告警守护线程（daemon，每 300s tick 一次）。

    由 api/app.py lifespan 调起，stop_event 置位即退出循环；
    daemon 属性提供进程退出兜底。
    """

    def _loop() -> None:
        guard = DiskAlertGuard()
        while not stop_event.wait(DISK_ALERT_CHECK_INTERVAL_SECONDS):
            try:
                guard.tick()
            except Exception:  # noqa: BLE001 - 单次 tick 失败不退出线程
                logger.warning("磁盘告警守护 tick 异常", exc_info=True)

    thread = threading.Thread(
        target=_loop,
        name="disk-alert-guard",
        daemon=True,
    )
    thread.start()
    return thread