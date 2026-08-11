"""告警多通道扩展测试（P2/III-07）：Telegram Bot + SMTP 邮件 + 多通道并存。

覆盖场景：
- Telegram 通道：正确 URL/body、缺参数跳过、失败重试、disabled 跳过
- SMTP 邮件通道：SSL 直连与 STARTTLS、缺参数跳过、失败重试
- 多通道并存：telegram/email/wecom/dingtalk/通用 webhook 一次 send 全发
- 恢复事件（circuit_breaker_closed / account_recovered）跨通道一致分发
- 去重窗口跨通道一致：同指纹所有通道只发一次
- 配置归一化与校验：_normalize_alert_channels / update() fail-fast
- 环境变量覆盖约定：CHATGPT2API_ALERT_TELEGRAM_* / CHATGPT2API_ALERT_EMAIL_*

发送均用 mock 打桩，不真实发网络请求。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from services.alert_service import AlertService

EMAIL_CFG = {
    "type": "email",
    "enabled": True,
    "smtp_host": "smtp.example.com",
    "smtp_port": 465,
    "smtp_user": "alert@example.com",
    "smtp_password": "secret",
    "use_tls": True,
    "from_addr": "alert@example.com",
    "to_addrs": ["ops@example.com"],
}

ALL_EVENTS = [
    "circuit_breaker_open", "circuit_breaker_closed", "backup_failure",
    "account_invalid", "account_recovered", "quota_exhausted",
    "quota_forecast_depletion",
]


class TestTelegramChannel:
    def setup_method(self) -> None:
        from services.alert_service import _GLOBAL_SENT_AT
        _GLOBAL_SENT_AT.clear()

    def _service(self, channels: dict | None = None, url: str = "") -> AlertService:
        return AlertService(
            webhook_url=url,
            timeout_seconds=5,
            events=ALL_EVENTS,
            dedupe_window_seconds=300,
            channels=channels,
        )

    def test_telegram_sends_message_with_url_and_body(self):
        channels = {"tg": {"type": "telegram", "enabled": True, "bot_token": "123:ABC", "chat_id": "-100123"}}
        svc = self._service(channels=channels)
        with patch("services.alert_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, ok=True)
            svc.send("quota_exhausted", {"account": "test-acc"})

        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.telegram.org/bot123:ABC/sendMessage"
        assert kwargs["json"]["chat_id"] == "-100123"
        assert "test-acc" in kwargs["json"]["text"]

    def test_telegram_missing_token_or_chat_skipped(self):
        for cfg in [
            {"type": "telegram", "enabled": True, "bot_token": "", "chat_id": "1"},
            {"type": "telegram", "enabled": True, "bot_token": "123:ABC", "chat_id": ""},
        ]:
            svc = self._service(channels={"tg": cfg})
            with patch("services.alert_service.requests.post") as mock_post:
                mock_post.return_value = MagicMock(status_code=200, ok=True)
                svc.send("backup_failure", {"error": "x"})
            assert not mock_post.called, f"缺参数应跳过: {cfg}"

    def test_telegram_retries_on_failure(self):
        channels = {"tg": {"type": "telegram", "enabled": True, "bot_token": "123:ABC", "chat_id": "1"}}
        svc = self._service(channels=channels)
        with patch("services.alert_service.requests.post", side_effect=Exception("timeout")) as mock_post, \
             patch("services.alert_service.time.sleep"):
            svc.send("backup_failure", {"error": "x"})
        assert mock_post.call_count == 2

    def test_disabled_channel_skipped(self):
        channels = {"tg": {"type": "telegram", "enabled": False, "bot_token": "123:ABC", "chat_id": "1"}}
        svc = self._service(channels=channels)
        with patch("services.alert_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, ok=True)
            svc.send("backup_failure", {"error": "x"})
        assert not mock_post.called


class TestEmailChannel:
    def setup_method(self) -> None:
        from services.alert_service import _GLOBAL_SENT_AT
        _GLOBAL_SENT_AT.clear()

    def _service(self, channels: dict | None = None, url: str = "") -> AlertService:
        return AlertService(
            webhook_url=url,
            timeout_seconds=5,
            events=ALL_EVENTS,
            dedupe_window_seconds=300,
            channels=channels,
        )

    def test_email_sends_via_smtp_ssl(self):
        svc = self._service(channels={"email_ops": dict(EMAIL_CFG)})
        with patch("services.alert_service.smtplib.SMTP_SSL") as mock_ssl, \
             patch("services.alert_service.time.sleep"):
            mock_server = MagicMock()
            mock_server.__enter__.return_value = mock_server
            mock_ssl.return_value = mock_server
            result = svc.send("backup_failure", {"error": "r2 timeout"})

        assert result is True
        assert mock_ssl.called
        args, kwargs = mock_ssl.call_args
        assert args[0] == "smtp.example.com"
        assert args[1] == 465
        mock_server.login.assert_called_once_with("alert@example.com", "secret")
        mock_server.send_message.assert_called_once()
        msg = mock_server.send_message.call_args[0][0]
        assert msg["Subject"] == "[ChatGPT2API 告警] backup_failure"
        assert msg["From"] == "alert@example.com"
        assert msg["To"] == "ops@example.com"
        assert "r2 timeout" in msg.get_content()

    def test_email_sends_via_starttls(self):
        cfg = {**EMAIL_CFG, "use_tls": False}
        svc = self._service(channels={"email_ops": cfg})
        with patch("services.alert_service.smtplib.SMTP") as mock_smtp, \
             patch("services.alert_service.time.sleep"):
            mock_server = MagicMock()
            mock_server.__enter__.return_value = mock_server
            mock_smtp.return_value = mock_server
            result = svc.send("backup_failure", {"error": "x"})

        assert result is True
        assert mock_smtp.called
        mock_server.starttls.assert_called_once()
        mock_server.send_message.assert_called_once()

    def test_email_missing_host_or_recipients_skipped(self):
        cases = [
            {**EMAIL_CFG, "smtp_host": ""},
            {**EMAIL_CFG, "smtp_user": "", "from_addr": ""},
            {**EMAIL_CFG, "to_addrs": []},
        ]
        for cfg in cases:
            svc = self._service(channels={"email_ops": cfg})
            with patch("services.alert_service.smtplib.SMTP_SSL") as mock_ssl, \
                 patch("services.alert_service.time.sleep"):
                mock_ssl.return_value = MagicMock()
                result = svc.send("backup_failure", {"error": "x"})
            assert result is False
            assert not mock_ssl.called, f"缺参数应跳过 SMTP: {cfg}"

    def test_email_retries_on_failure(self):
        svc = self._service(channels={"email_ops": dict(EMAIL_CFG)})
        with patch("services.alert_service.smtplib.SMTP_SSL", side_effect=Exception("conn refused")) as mock_ssl, \
             patch("services.alert_service.time.sleep"):
            mock_ssl.return_value = MagicMock()
            svc.send("backup_failure", {"error": "x"})
        assert mock_ssl.call_count == 2


class TestMultiChannelCrossConsistency:
    def setup_method(self) -> None:
        from services.alert_service import _GLOBAL_SENT_AT
        _GLOBAL_SENT_AT.clear()

    def _service(self, channels: dict | None = None, url: str = "") -> AlertService:
        return AlertService(
            webhook_url=url,
            timeout_seconds=5,
            events=ALL_EVENTS,
            dedupe_window_seconds=300,
            channels=channels,
        )

    def test_recovery_event_dispatched_to_all_channels(self):
        channels = {
            "tg": {"type": "telegram", "enabled": True, "bot_token": "123:ABC", "chat_id": "1"},
            "email_ops": dict(EMAIL_CFG),
            "wecom": {"type": "wecom", "enabled": True, "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=w"},
            "dingtalk": {"type": "dingtalk", "enabled": True, "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=d"},
        }
        svc = self._service(channels=channels, url="https://hooks.example.com/gen")
        posts: list[tuple[str, dict]] = []

        def _fake_post(*args, **kwargs):
            posts.append((args[0], kwargs.get("json", {})))
            return MagicMock(status_code=200, ok=True)

        with patch("services.alert_service.requests.post", side_effect=_fake_post) as mock_post, \
             patch("services.alert_service.smtplib.SMTP_SSL") as mock_ssl, \
             patch("services.alert_service.time.sleep"):
            mock_server = MagicMock()
            mock_ssl.return_value = mock_server
            result = svc.send("circuit_breaker_closed", {"token_suffix": "recover-cross"})

        assert result is True
        # 通用 webhook + telegram + wecom + dingtalk = 4 次 requests.post；email 走 smtplib
        assert mock_post.call_count == 4, f"预期 4 次 http 发送，实际 {mock_post.call_count}"
        urls = [c[0] for c in posts]
        assert any("api.telegram.org" in u for u in urls)
        assert any("qyapi.weixin.qq.com" in u for u in urls)
        assert any("oapi.dingtalk.com" in u for u in urls)
        assert any("hooks.example.com" in u for u in urls)
        mock_ssl.assert_called_once()

    def test_account_recovered_cross_channel(self):
        channels = {
            "tg": {"type": "telegram", "enabled": True, "bot_token": "123:ABC", "chat_id": "1"},
            "email_ops": dict(EMAIL_CFG),
        }
        svc = self._service(channels=channels)
        with patch("services.alert_service.requests.post") as mock_post, \
             patch("services.alert_service.smtplib.SMTP_SSL") as mock_ssl, \
             patch("services.alert_service.time.sleep"):
            mock_ssl.return_value = MagicMock()
            result = svc.send("account_recovered", {"account": "recover@x.com", "reason": "refresh_ok"})

        assert result is True
        mock_post.assert_called_once()
        mock_ssl.assert_called_once()

    def test_dedupe_applies_across_all_channels(self):
        channels = {
            "tg": {"type": "telegram", "enabled": True, "bot_token": "123:ABC", "chat_id": "1"},
            "email_ops": dict(EMAIL_CFG),
        }
        svc = self._service(channels=channels)
        with patch("services.alert_service.requests.post") as mock_post, \
             patch("services.alert_service.smtplib.SMTP_SSL") as mock_ssl, \
             patch("services.alert_service.time.sleep"):
            mock_ssl.return_value = MagicMock()
            payload = {"token_suffix": "dedupe-cross-channel"}
            svc.send("account_invalid", payload)
            svc.send("account_invalid", payload)  # 去重窗口内，所有通道都应跳过

        assert mock_post.call_count == 1, f"telegram 应只发 1 次，实际 {mock_post.call_count}"
        assert mock_ssl.call_count == 1, "email 应只发 1 次"

    def test_one_channel_fails_others_still_sent(self):
        channels = {
            "tg_broken": {"type": "telegram", "enabled": True, "bot_token": "", "chat_id": ""},
            "wecom_ok": {"type": "wecom", "enabled": True, "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=ok"},
        }
        svc = self._service(channels=channels)
        with patch("services.alert_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, ok=True)
            result = svc.send("account_invalid", {"account": "x@x.com", "reason": "401"})

        assert result is True
        # 只有 wecom 成功发 1 次；tg 缺参数被跳过
        assert mock_post.call_count == 1


class TestAlertChannelConfig:
    def test_normalize_alert_channels(self):
        from services.config import _normalize_alert_channels

        raw = {
            "tg": {"type": "telegram", "bot_token": " 123:ABC ", "chat_id": "1"},  # 无 enabled → 默认启用
            "wecom": {"type": "wecom", "webhook_url": " https://qyapi.weixin.qq.com/x "},
            "email": {"type": "email", "smtp_host": "smtp.x.com", "smtp_user": "u@x.com", "to_addrs": "a@x.com, b@x.com"},
            "slack": {"type": "slack", "webhook_url": "https://hooks.slack.com/zzz"},
        }
        result = _normalize_alert_channels(raw)
        assert result["tg"]["enabled"] is True
        assert result["tg"]["bot_token"] == "123:ABC"
        assert result["wecom"]["webhook_url"] == "https://qyapi.weixin.qq.com/x"
        # 无 from_addr 时回落 smtp_user；to_addrs 支持逗号分隔字符串
        assert result["email"]["from_addr"] == "u@x.com"
        assert result["email"]["to_addrs"] == ["a@x.com", "b@x.com"]
        # 自定义通道保留
        assert result["slack"]["webhook_url"] == "https://hooks.slack.com/zzz"
        assert result["slack"]["type"] == "slack"

    def test_normalize_alert_channels_handles_invalid(self):
        from services.config import _normalize_alert_channels

        for bad in [None, "not_dict", [], 42]:
            assert _normalize_alert_channels(bad) == {}, f"非法输入应返回空: {bad!r}"
        # 非 dict 的通道配置被丢弃
        result = _normalize_alert_channels({"tg": "not-a-dict"})
        assert result == {}

    def test_config_alert_channels_exposed_in_get(self):
        from services.config import config

        data = config.get()
        assert "alert_channels" in data
        assert isinstance(data["alert_channels"], dict)

    def test_config_alert_channels_env_override(self, monkeypatch):
        from services.config import config

        monkeypatch.setenv("CHATGPT2API_ALERT_TELEGRAM_BOT_TOKEN", "env-token:XYZ")
        monkeypatch.setenv("CHATGPT2API_ALERT_TELEGRAM_CHAT_ID", "-100env")
        channels = config.alert_channels
        tg = channels["telegram_ops"]
        assert tg["type"] == "telegram"
        assert tg["enabled"] is True
        assert tg["bot_token"] == "env-token:XYZ"
        assert tg["chat_id"] == "-100env"

    def test_config_alert_channels_email_env_override(self, monkeypatch):
        from services.config import config

        monkeypatch.setenv("CHATGPT2API_ALERT_EMAIL_SMTP_HOST", "smtp.env.com")
        monkeypatch.setenv("CHATGPT2API_ALERT_EMAIL_TO", "ops@x.com,admin@x.com")
        monkeypatch.setenv("CHATGPT2API_ALERT_EMAIL_USE_TLS", "false")
        channels = config.alert_channels
        email = channels["email_ops"]
        assert email["type"] == "email"
        assert email["enabled"] is True
        assert email["smtp_host"] == "smtp.env.com"
        assert email["to_addrs"] == ["ops@x.com", "admin@x.com"]
        assert email["use_tls"] is False

    def test_update_validates_alert_channels(self, tmp_path):
        from services.config import ConfigStore

        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "auth-key": "test-key-1234567890abcdef",
            "alert_channels": {"tg": {"type": "telegram", "enabled": True, "bot_token": "abc", "chat_id": "123"}},
        }), encoding="utf-8")
        store = ConfigStore(cfg_file)

        # 合法：完整 telegram 配置可保存
        ok = store.update({"alert_channels": {
            "tg": {"type": "telegram", "enabled": True, "bot_token": "abc", "chat_id": "123"},
        }})
        assert ok["alert_channels"]["tg"]["bot_token"] == "abc"

        # 非法：启用 telegram 缺 bot_token → fail-fast
        with pytest.raises(ValueError, match="bot_token"):
            store.update({"alert_channels": {
                "tg": {"type": "telegram", "enabled": True, "bot_token": "", "chat_id": "123"},
            }})

        # 非法：启用 email 缺收件人 → fail-fast
        with pytest.raises(ValueError, match="to_addrs"):
            store.update({"alert_channels": {
                "email": {"type": "email", "enabled": True, "smtp_host": "smtp.x.com", "from_addr": "a@x.com", "to_addrs": []},
            }})

        # 关闭的通道不校验参数
        ok_disabled = store.update({"alert_channels": {
            "tg": {"type": "telegram", "enabled": False, "bot_token": "", "chat_id": ""},
        }})
        assert ok_disabled["alert_channels"]["tg"]["enabled"] is False
