"""配置热加载器：文件监听 + 增量更新 + 事件通知。

监听 config.json 文件 mtime 变化，触发 ConfigStore 热加载并发布 CONFIG_CHANGED 事件。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from services.event_bus import CONFIG_CHANGED, Event, event_bus

if TYPE_CHECKING:
    from services.config import ConfigStore

logger = logging.getLogger(__name__)


class ConfigWatcher:
    """配置文件热加载器。

    轮询检测 config.json 的 mtime 变化，调用 ConfigStore 的 _try_reload 后发布 CONFIG_CHANGED 事件。
    线程安全，支持启动/停止，幂等多次 start。
    """

    def __init__(
        self,
        config_store: ConfigStore,
        poll_interval: float = 5.0,
        *,
        reload_callback: Callable[[], None] | None = None,
    ) -> None:
        self._config_store = config_store
        self._poll_interval = max(0.01, float(poll_interval))
        self._reload_callback: Callable[[], None] = reload_callback or self._default_reload
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_mtime: float = 0.0
        self._lock = threading.Lock()

    @property
    def poll_interval(self) -> float:
        return self._poll_interval

    @property
    def is_running(self) -> bool:
        return self._running

    def _default_reload(self) -> None:
        self._config_store._try_reload()

    def start(self, stop_event: threading.Event | None = None) -> None:
        """启动轮询线程。幂等——多次 start 不创建新线程。"""
        with self._lock:
            if self._running:
                return
            self._running = True
            # 初始化为 0，确保第一次轮询时触发 reload
            self._last_mtime = 0.0
            self._thread = threading.Thread(
                target=self._poll_loop,
                args=(stop_event or threading.Event(),),
                daemon=True,
                name="config-watcher",
            )
            self._thread.start()
            logger.info(
                "ConfigWatcher 已启动（轮询间隔 %.1fs）",
                self._poll_interval,
            )

    def stop(self) -> None:
        """停止轮询线程。"""
        with self._lock:
            self._running = False
            self._thread = None

    def _get_file_mtime(self) -> float:
        try:
            return self._config_store.path.stat().st_mtime
        except OSError:
            return 0.0

    def _poll_loop(self, stop_event: threading.Event) -> None:
        """轮询循环：检测 mtime 变更 → 调用 reload → 发布事件。"""
        while self._running and not stop_event.is_set():
            try:
                current_mtime = self._get_file_mtime()

                if current_mtime > self._last_mtime and current_mtime > 0:
                    logger.debug(
                        "config.json mtime 变更: %.6f → %.6f",
                        self._last_mtime,
                        current_mtime,
                    )
                    self._reload_callback()
                    self._last_mtime = current_mtime
                    # 发布 CONFIG_CHANGED 事件
                    try:
                        event_bus.publish(Event(CONFIG_CHANGED, {
                            "reloaded_at": time.time(),
                            "mtime": current_mtime,
                        }))
                    except Exception:
                        logger.warning("CONFIG_CHANGED 事件发布失败", exc_info=True)
            except Exception as exc:
                logger.warning("ConfigWatcher 轮询异常: %s", exc)

            stop_event.wait(self._poll_interval)

        self._running = False