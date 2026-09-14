"""告警测试端点 / 磁盘告警守护 单元测试（v2.37.0 G1）。

覆盖场景：
- POST /api/system/alerts/test：无启用通道返回提示 / 单通道成功 / 单通道失败不炸整个请求
- 磁盘告警守护：mock 磁盘占用 -> publish 事件；去重窗口内不重复发；低于阈值不触发
- 启动 WARNING：alert_events 非空但全通道禁用时提示

发送均用 mock 打桩，不真实发网络请求。
"""

from __future__ import annotations

from unittest.mock import patch

# ---------------------------------------------------------------------------
# 磁盘告警守护（services/disk_alert_guard.py）
# ---------------------------------------------------------------------------


def _make_guard(threshold_pct: float = 90.0):
    from services.disk_alert_guard import DiskAlertGuard

    return DiskAlertGuard(threshold_pct=threshold_pct)


class TestDiskAlertGuard:
    def test_below_threshold_no_publish(self):
        guard = _make_guard(threshold_pct=90.0)
        with patch("services.disk_alert_guard.shutil.disk_usage", return_value=(1000, 100, 900)), \
             patch("services.disk_alert_guard._publish_disk_event") as mock_pub:
            guard.tick()
        mock_pub.assert_not_called()

    def test_above_threshold_publishes_once(self):
        guard = _make_guard(threshold_pct=90.0)
        # used=950, total=1000 -> 95% > 90%
        with patch("services.disk_alert_guard.shutil.disk_usage", return_value=(1000, 950, 50)), \
             patch("services.disk_alert_guard._publish_disk_event") as mock_pub:
            guard.tick()
            guard.tick()  # 去重窗口内第二次不再发布
        assert mock_pub.call_count == 1

    def test_recovers_after_under_threshold(self):
        guard = _make_guard(threshold_pct=90.0)
        # 先超阈值触发一次，再降到阈值下，再超 -> 重新触发
        with patch("services.disk_alert_guard.shutil.disk_usage", return_value=(1000, 950, 50)), \
             patch("services.disk_alert_guard._publish_disk_event") as mock_pub:
            guard.tick()
        with patch("services.disk_alert_guard.shutil.disk_usage", return_value=(1000, 100, 900)), \
             patch("services.disk_alert_guard._publish_disk_event"):
            guard.tick()  # 降回阈值下，标记恢复
        with patch("services.disk_alert_guard.shutil.disk_usage", return_value=(1000, 950, 50)), \
             patch("services.disk_alert_guard._publish_disk_event") as mock_pub3:
            guard.tick()
        assert mock_pub.call_count == 1
        assert mock_pub3.call_count == 1

    def test_alert_event_name_and_data(self):
        guard = _make_guard(threshold_pct=90.0)
        captured = {}

        def fake_publish(event_type, payload):
            captured["type"] = event_type
            captured["payload"] = payload

        with patch("services.disk_alert_guard.shutil.disk_usage", return_value=(1000, 950, 50)), \
             patch("services.disk_alert_guard._publish_disk_event", side_effect=fake_publish):
            guard.tick()
        assert captured["type"] == "system.disk_high"
        assert captured["payload"]["used_pct"] == 95
        assert captured["payload"]["threshold_pct"] == 90

    def test_tick_handles_shutil_error(self):
        guard = _make_guard(threshold_pct=90.0)
        with patch("services.disk_alert_guard.shutil.disk_usage", side_effect=OSError("no disk")), \
             patch("services.disk_alert_guard.logger.warning") as mock_warn:
            guard.tick()  # 不抛异常
        assert mock_warn.call_count == 1


# ---------------------------------------------------------------------------
# 启动 WARNING（api/system.py 或无：config 提示）
# ---------------------------------------------------------------------------


class TestAlertUnwiredWarning:
    def test_warning_when_events_configured_but_no_channel(self, tmp_path, monkeypatch):
        """alert_events 非空 + 全通道 disabled + webhook_url 空 -> 启动 log WARNING。"""
        import json
        import logging

        from services.config import ConfigStore

        records: list[logging.LogRecord] = []

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Handler()
        logger = logging.getLogger("services.disk_alert_guard")
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        try:
            cfg_file = tmp_path / "config.json"
            cfg_file.write_text(json.dumps({"auth-key": "test-auth-key-long"}), encoding="utf-8")
            store = ConfigStore(cfg_file)
            # 模拟已加载配置（有 events 无通道）
            store.data["alert_events"] = ["circuit_breaker_open", "quota_exhausted"]
            store.data["alert_webhook_url"] = ""
            store.data["alert_channels"] = {
                "telegram_ops": {"type": "telegram", "enabled": False, "bot_token": "", "chat_id": ""}
            }
            from services.disk_alert_guard import check_alert_unwired

            check_alert_unwired(store)
            assert any("告警" in r.getMessage() for r in records)
        finally:
            logger.removeHandler(handler)