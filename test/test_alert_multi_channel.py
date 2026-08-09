"""多通道告警测试：企业微信(WeCom)、钉钉(DingTalk)、通用 webhook 通道、多通道并发。

覆盖场景：
- 各通道正确格式化消息体并发送
- 单通道失败不阻塞其他通道
- 未知通道类型降级到通用 webhook
- 通道配置空 webhook_url 跳过
- 多通道 + 去重协同
- _build_from_config 多通道配置加载
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.alert_service import AlertService


class TestAlertMultiChannel:
    """多通道告警核心行为测试。"""

    def _service(self, channels: dict | None = None, url: str = "https://hooks.example.com/xyz") -> AlertService:
        return AlertService(
            webhook_url=url,
            timeout_seconds=5,
            events=["circuit_breaker_open", "backup_failure", "account_invalid", "quota_exhausted"],
            dedupe_window_seconds=300,
            channels=channels,
        )

    # ---- WeCom 通道 ----

    def test_wecom_channel_formats_markdown(self):
        """WeCom 通道应发送 markdown 格式消息体（msgtype=markdown）。"""
        channels = {"wecom_ops": {"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx", "type": "wecom"}}
        svc = self._service(channels=channels, url="")
        with patch("services.alert_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, ok=True)
            svc.send("backup_failure", {"error": "r2 timeout", "account": "test-acc"})

        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert args[0] == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
        assert kwargs["json"]["msgtype"] == "markdown"
        assert "r2 timeout" in kwargs["json"]["markdown"]["content"]

    def test_wecom_channel_retries_on_failure(self):
        """WeCom 通道发送失败应重试 1 次。"""
        channels = {"wecom_ops": {"webhook_url": "https://qyapi.weixin.qq.com/webhook", "type": "wecom"}}
        svc = self._service(channels=channels, url="")
        with patch("services.alert_service.requests.post", side_effect=Exception("conn reset")) as mock_post, \
             patch("services.alert_service.time.sleep"):
            svc.send("backup_failure", {"error": "x"})
        assert mock_post.call_count == 2

    # ---- 钉钉通道 ----

    def test_dingtalk_channel_formats_markdown(self):
        """钉钉通道应发送 markdown 格式消息体（msgtype=markdown + title）。"""
        channels = {"dingtalk_ops": {"webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=xxx", "type": "dingtalk"}}
        svc = self._service(channels=channels, url="")
        with patch("services.alert_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, ok=True)
            svc.send("quota_exhausted", {"account": "test-acc", "plan_type": "free"})

        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert args[0] == "https://oapi.dingtalk.com/robot/send?access_token=xxx"
        assert kwargs["json"]["msgtype"] == "markdown"
        assert kwargs["json"]["markdown"]["title"] == "quota_exhausted"
        assert "test-acc" in kwargs["json"]["markdown"]["text"]

    def test_dingtalk_channel_retries_on_failure(self):
        """钉钉通道发送失败应重试 1 次。"""
        channels = {"dingtalk_ops": {"webhook_url": "https://oapi.dingtalk.com/robot/send", "type": "dingtalk"}}
        svc = self._service(channels=channels, url="")
        with patch("services.alert_service.requests.post", side_effect=Exception("timeout")) as mock_post, \
             patch("services.alert_service.time.sleep"):
            svc.send("quota_exhausted", {"account": "x"})
        assert mock_post.call_count == 2

    # ---- 多通道并发 ----

    def test_two_channels_both_sent(self):
        """通用 webhook + WeCom 同时配置，两通道均应发出。"""
        channels = {"wecom_ops": {"webhook_url": "https://qyapi.weixin.qq.com/webhook", "type": "wecom"}}
        svc = self._service(channels=channels, url="https://hooks.example.com/generic")
        calls: list[tuple[str, dict]] = []

        def _fake_post(*args, **kwargs):
            calls.append((args[0], kwargs.get("json", {})))

        with patch("services.alert_service.requests.post", side_effect=_fake_post) as mock_post:
            mock_post.return_value = MagicMock(status_code=200, ok=True)
            # 用 side_effect 绕过 mock_post 的 call_args 回调
            mock_post.side_effect = _fake_post
            svc.send("circuit_breaker_open", {"token_suffix": "abcd1234"})

        # 应该有 2 次调用：一次通用 webhook，一次 WeCom
        assert len(calls) == 2, f"应发送 2 个通道，实际: {len(calls)}"
        urls = [c[0] for c in calls]
        assert "https://hooks.example.com/generic" in urls
        assert "https://qyapi.weixin.qq.com/webhook" in urls

    def test_one_channel_fails_other_still_sent(self):
        """通用 webhook 失败时，WeCom 通道仍应正常发出。"""
        channels = {"wecom_ok": {"webhook_url": "https://qyapi.weixin.qq.com/ok", "type": "wecom"}}
        svc = self._service(channels=channels, url="https://hooks.example.com/broken")

        with patch("services.alert_service.requests.post") as mock_post, \
             patch("services.alert_service.time.sleep"):
            def _side_effect(*args, **kwargs):
                url = args[0]
                if "broken" in url:
                    raise Exception("webhook broken")
                return MagicMock(status_code=200, ok=True)
            mock_post.side_effect = _side_effect
            result = svc.send("account_invalid", {"account": "test@x.com", "reason": "401"})

        assert result is True, "任一通道成功应返回 True"
        assert mock_post.call_count == 2

    def test_all_channels_fail_returns_false(self):
        """所有通道均失败时返回 False（不抛异常）。"""
        channels = {"wecom_fail": {"webhook_url": "https://qyapi.weixin.qq.com/fail", "type": "wecom"}}
        svc = self._service(channels=channels, url="https://hooks.example.com/fail")

        with patch("services.alert_service.requests.post", side_effect=Exception("down")) as mock_post, \
             patch("services.alert_service.time.sleep"):
            result = svc.send("backup_failure", {"error": "x"})

        assert result is False, "全失败应返回 False"
        # 通用 webhook 重试 2 次 + WeCom 重试 2 次 = 4
        assert mock_post.call_count == 4

    # ---- 未知通道类型 ----

    def test_unknown_channel_type_falls_back_to_generic(self):
        """未知通道类型（如 slack）应降级到通用 webhook 格式发送。"""
        channels = {"slack_bot": {"webhook_url": "https://hooks.slack.com/services/xxx", "type": "slack"}}
        svc = self._service(channels=channels, url="")
        with patch("services.alert_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, ok=True)
            svc.send("account_invalid", {"account": "test@x.com"})

        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert args[0] == "https://hooks.slack.com/services/xxx"
        assert kwargs["json"]["event"] == "account_invalid"

    def test_channel_type_defaults_to_name(self):
        """通道配置未显式指定 type 时，用 channel_name 作为 type（若未知则降级到通用 webhook）。"""
        channels = {"custom_hook": {"webhook_url": "https://custom.example.com/hook"}}
        svc = self._service(channels=channels, url="")
        with patch("services.alert_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, ok=True)
            svc.send("circuit_breaker_open", {"token_suffix": "xyz"})

        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert args[0] == "https://custom.example.com/hook"
        # custom_hook 非已知类型，走通用 webhook 格式
        assert kwargs["json"]["event"] == "circuit_breaker_open"

    # ---- 通道配置缺失 ----

    def test_channel_without_webhook_url_skipped(self):
        """通道配置缺 webhook_url 应跳过，不阻塞其他通道。"""
        channels = {"no_url": {}, "wecom_ok": {"webhook_url": "https://qyapi.weixin.qq.com/ok", "type": "wecom"}}
        svc = self._service(channels=channels, url="")
        with patch("services.alert_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, ok=True)
            result = svc.send("backup_failure", {"error": "x"})

        assert result is True
        assert mock_post.call_count == 1

    # ---- 多通道 + 去重 ----

    def test_multi_channel_respects_dedupe(self):
        """多通道告警在去重窗口内同指纹应被跳过，不发送任何通道。"""
        channels = {"dingtalk_ops": {"webhook_url": "https://oapi.dingtalk.com/robot/send", "type": "dingtalk"}}
        svc = self._service(channels=channels, url="https://hooks.example.com/gen")
        with patch("services.alert_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, ok=True)
            payload = {"token_suffix": "dedupe-test"}
            svc.send("circuit_breaker_open", payload)
            svc.send("circuit_breaker_open", payload)  # 去重窗口内，应跳过

        # 通用 webhook 2 次 + 钉钉 2 次 = 首次发送；第二次完全跳过
        assert mock_post.call_count == 2, f"去重后应只发 2 次，实际: {mock_post.call_count}"

    # ---- 配置加载 ----

    def test_build_from_config_loads_channels(self, monkeypatch):
        """_build_from_config 应从 config.json 加载多通道配置。"""
        mock_config_data = {
            "alert_webhook_url": "",
            "alert_webhook_timeout": 10,
            "alert_events": ["circuit_breaker_open", "backup_failure"],
            "alert_channels": {
                "wecom_ops": {"webhook_url": "https://qyapi.weixin.qq.com/key=yyy", "type": "wecom"},
                "dingtalk_ops": {"webhook_url": "https://oapi.dingtalk.com/robot/send?token=zzz", "type": "dingtalk"},
            },
        }
        import services.config as cfg
        monkeypatch.setattr(cfg.config, "data", mock_config_data)

        from services.alert_service import _build_from_config
        svc = _build_from_config()

        assert svc.enabled is True
        assert "wecom_ops" in svc.channels
        assert "dingtalk_ops" in svc.channels
        assert svc.channels["wecom_ops"]["webhook_url"] == "https://qyapi.weixin.qq.com/key=yyy"
        assert svc.channels["dingtalk_ops"]["type"] == "dingtalk"

    def test_build_from_config_handles_empty_channels(self, monkeypatch):
        """_build_from_config 在 alert_channels 为空或非 dict 时应返回空 channels。"""
        for empty_val in [None, {}, "not_a_dict", []]:
            mock_data = {"alert_webhook_url": "https://hooks.example.com/x", "alert_channels": empty_val}
            import services.config as cfg
            monkeypatch.setattr(cfg.config, "data", mock_data)

            from services.alert_service import _build_from_config
            svc = _build_from_config()
            assert svc.channels == {}, f"alert_channels={empty_val!r} 应返回空 channels"
            assert svc.enabled is True  # 通用 webhook 仍有值