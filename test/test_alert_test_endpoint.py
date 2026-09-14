"""告警测试端点单元测试（v2.37.0 G1）。

覆盖场景：
- alert_service.test_alert()：无通道空 results / 单通道成功 / 指定通道不存在 /
  指定通道成功 / webhook_url 也测
- POST /api/system/alerts/test：无鉴权 401 / require_admin / 成功 200 / 无通道 reason=no_channel
- 错误摘要不含 SMTP 密码明文

发送均用 mock 打桩，不真实发网络请求。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# alert_service.test_alert()
# ---------------------------------------------------------------------------


class TestAlertTestFunction:
    def _service_with_channels(self, channels: dict, webhook_url: str = ""):
        from services.alert_service import AlertService

        return AlertService(
            webhook_url=webhook_url,
            timeout_seconds=5,
            events=[],
            dedupe_window_seconds=300,
            channels=channels,
        )

    def test_no_channels_returns_empty_results(self):
        from services.alert_service import test_alert

        with patch("services.alert_service._build_from_config", return_value=self._service_with_channels({})):
            result = test_alert()
        assert result["results"] == []

    def test_single_channel_success(self):
        from services.alert_service import test_alert

        svc = self._service_with_channels({
            "tg": {"type": "telegram", "enabled": True, "bot_token": "123:ABC", "chat_id": "-100"}
        })
        with patch("services.alert_service._build_from_config", return_value=svc), \
             patch.object(svc, "_send_channel", return_value=True) as mock_send:
            result = test_alert()
        assert len(result["results"]) == 1
        assert result["results"][0] == {"channel": "tg", "ok": True, "error": ""}
        mock_send.assert_called_once()

    def test_specified_channel_missing_returns_false(self):
        from services.alert_service import test_alert

        svc = self._service_with_channels({
            "tg": {"type": "telegram", "enabled": True, "bot_token": "123:ABC", "chat_id": "-100"}
        })
        with patch("services.alert_service._build_from_config", return_value=svc):
            result = test_alert(channel="missing")
        assert len(result["results"]) == 1
        assert result["results"][0]["ok"] is False
        assert "不存在" in result["results"][0]["error"]

    def test_specified_channel_success(self):
        from services.alert_service import test_alert

        svc = self._service_with_channels({
            "tg": {"type": "telegram", "enabled": False, "bot_token": "", "chat_id": ""},
            "wecom": {"type": "wecom", "enabled": True, "webhook_url": "https://wecom.example"}
        })
        with patch("services.alert_service._build_from_config", return_value=svc), \
             patch.object(svc, "_send_channel", return_value=True) as mock_send:
            result = test_alert(channel="wecom")
        assert len(result["results"]) == 1
        assert result["results"][0]["channel"] == "wecom"
        assert result["results"][0]["ok"] is True
        mock_send.assert_called_once()

    def test_disabled_specified_channel_returns_false(self):
        from services.alert_service import test_alert

        svc = self._service_with_channels({
            "tg": {"type": "telegram", "enabled": False, "bot_token": "", "chat_id": ""}
        })
        with patch("services.alert_service._build_from_config", return_value=svc):
            result = test_alert(channel="tg")
        assert len(result["results"]) == 1
        assert result["results"][0]["ok"] is False

    def test_error_summary_redacts_password(self):
        """错误摘要不得含 SMTP 密码等敏感配置明文。"""
        from services.alert_service import test_alert

        svc = self._service_with_channels({
            "email": {
                "type": "email",
                "enabled": True,
                "smtp_host": "smtp.example.com",
                "smtp_port": 465,
                "smtp_user": "ops@example.com",
                "smtp_password": "super-secret-pw",
                "use_tls": True,
                "from_addr": "ops@example.com",
                "to_addrs": ["dest@example.com"],
            }
        })
        with patch("services.alert_service._build_from_config", return_value=svc), \
             patch.object(svc, "_send_channel", return_value=False):
            result = test_alert()
        error_text = result["results"][0]["error"]
        # 我方实现失败时不透出异常详情（仅状态字），密码必然不在其中
        assert "super-secret-pw" not in error_text


# ---------------------------------------------------------------------------
# POST /api/system/alerts/test 端点
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """FastAPI TestClient（conftest 已隔离环境变量：auth-key=chatgpt2api、webhook 为空）。"""
    from fastapi.testclient import TestClient

    from api.app import create_app

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


class TestAlertEndpoint:
    def test_requires_auth(self, client):
        resp = client.post("/api/system/alerts/test", json={"message": "hi"})
        assert resp.status_code == 401

    def test_no_channel_returns_ok_false_reason(self, client):
        resp = client.post(
            "/api/system/alerts/test",
            json={"message": "hi"},
            headers={"Authorization": "Bearer chatgpt2api"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # 默认 config 无任何启用通道 → reason=no_channel
        assert data.get("ok") is False
        assert data.get("reason") == "no_channel"
        assert data.get("results") == []

    def test_success_returns_results(self, client):
        from services.alert_service import AlertService

        svc = AlertService(
            webhook_url="https://webhook.example",
            timeout_seconds=5,
            events=[],
            dedupe_window_seconds=300,
            channels={},
        )
        with patch("services.alert_service._build_from_config", return_value=svc), \
             patch.object(svc, "_send_webhook", return_value=True):
            resp = client.post(
                "/api/system/alerts/test",
                json={"message": "ok"},
                headers={"Authorization": "Bearer chatgpt2api"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["results"]) == 1
        assert data["results"][0]["channel"] == "webhook"
        assert data["results"][0]["ok"] is True