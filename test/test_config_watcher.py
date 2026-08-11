"""配置热加载测试：文件变更检测/事件通知/缓存刷新"""

from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_config_file(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"auth-key": "test-key-1234567890"}), encoding="utf-8")
    return cfg


def test_config_watcher_detects_file_change(temp_config_file: Path) -> None:
    from services.config_watcher import ConfigWatcher

    reload_count = 0
    reload_lock = threading.Lock()

    def _track_reload() -> None:
        nonlocal reload_count
        with reload_lock:
            reload_count += 1

    config_store = MagicMock()
    config_store.path = temp_config_file

    stop_event = threading.Event()
    watcher = ConfigWatcher(config_store, poll_interval=0.05, reload_callback=_track_reload)
    watcher.start(stop_event)

    # 等初始轮询完成
    time.sleep(0.2)
    with reload_lock:
        assert reload_count >= 1, f"初始轮询应触发 reload，实际 {reload_count}"

    # 修改文件
    temp_config_file.write_text(json.dumps({"auth-key": "new-key-1234567890"}), encoding="utf-8")
    time.sleep(0.3)

    with reload_lock:
        assert reload_count >= 2, f"文件变更后应触发 reload，实际 {reload_count}"

    stop_event.set()
    watcher.stop()


def test_config_watcher_publishes_event(temp_config_file: Path) -> None:
    from services.config_watcher import ConfigWatcher
    from services.event_bus import event_bus, CONFIG_CHANGED, Event

    received_events: list[Event] = []
    event_bus.subscribe(CONFIG_CHANGED, sync_handler=lambda e: received_events.append(e))

    config_store = MagicMock()
    config_store.path = temp_config_file

    stop_event = threading.Event()
    watcher = ConfigWatcher(config_store, poll_interval=0.05)
    watcher.start(stop_event)

    time.sleep(0.2)

    temp_config_file.write_text(json.dumps({"auth-key": "another-key-1234567890"}), encoding="utf-8")
    time.sleep(0.3)

    stop_event.set()
    watcher.stop()

    # 清理订阅
    for handler in list(event_bus._sync_handlers.get(CONFIG_CHANGED, [])):
        event_bus.unsubscribe(CONFIG_CHANGED, handler)

    assert any(e.type == CONFIG_CHANGED for e in received_events), (
        f"期望收到 CONFIG_CHANGED 事件，实际: {[e.type for e in received_events]}"
    )


def test_config_watcher_poll_interval(temp_config_file: Path) -> None:
    from services.config_watcher import ConfigWatcher

    config_store = MagicMock()
    config_store.path = temp_config_file

    watcher = ConfigWatcher(config_store, poll_interval=0.5)
    assert watcher.poll_interval == 0.5

    stop_event = threading.Event()
    watcher.start(stop_event)
    assert watcher.is_running
    stop_event.set()
    watcher.stop()


def test_config_watcher_stop(temp_config_file: Path) -> None:
    from services.config_watcher import ConfigWatcher

    config_store = MagicMock()
    config_store.path = temp_config_file

    stop_event = threading.Event()
    watcher = ConfigWatcher(config_store, poll_interval=0.05)
    watcher.start(stop_event)
    assert watcher.is_running

    stop_event.set()
    watcher.stop()
    assert not watcher.is_running


def test_config_watcher_idempotent_start(temp_config_file: Path) -> None:
    from services.config_watcher import ConfigWatcher

    config_store = MagicMock()
    config_store.path = temp_config_file

    stop_event = threading.Event()
    watcher = ConfigWatcher(config_store, poll_interval=0.05)
    watcher.start(stop_event)
    thread_id = id(watcher._thread)
    watcher.start(stop_event)  # 第二次 start
    assert id(watcher._thread) == thread_id, "多次 start 不应创建新线程"
    stop_event.set()
    watcher.stop()


def test_config_watcher_handles_bad_path() -> None:
    from services.config_watcher import ConfigWatcher

    config_store = MagicMock()
    config_store.path = Path("/nonexistent/config.json")

    stop_event = threading.Event()
    watcher = ConfigWatcher(config_store, poll_interval=0.05)
    watcher.start(stop_event)
    time.sleep(0.15)

    stop_event.set()
    watcher.stop()
    assert not watcher.is_running


def test_config_watcher_reload_on_consecutive_changes(temp_config_file: Path) -> None:
    from services.config_watcher import ConfigWatcher

    reload_count = 0
    reload_lock = threading.Lock()

    def _track_reload() -> None:
        nonlocal reload_count
        with reload_lock:
            reload_count += 1

    config_store = MagicMock()
    config_store.path = temp_config_file

    stop_event = threading.Event()
    watcher = ConfigWatcher(config_store, poll_interval=0.02, reload_callback=_track_reload)
    watcher.start(stop_event)

    time.sleep(0.15)
    with reload_lock:
        assert reload_count >= 1, f"初始轮询应触发 reload，实际 {reload_count}"

    # 第一次修改
    temp_config_file.write_text(json.dumps({"auth-key": "key-1"}), encoding="utf-8")
    time.sleep(0.15)

    # 第二次修改
    temp_config_file.write_text(json.dumps({"auth-key": "key-2"}), encoding="utf-8")
    time.sleep(0.15)

    with reload_lock:
        assert reload_count >= 3, f"期望至少 3 次，实际 {reload_count}"

    stop_event.set()
    watcher.stop()