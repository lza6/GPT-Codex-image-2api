"""告警 webhook 测试（D18）：发送/重试/去重/配置关闭。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.alert_service import AlertService


def _service(url: str = "https://hooks.example.com/xyz", events: list[str] | None = None) -> AlertService:
    return AlertService(
        webhook_url=url,
        timeout_seconds=5,
        events=events or ["circuit_breaker_open", "backup_failure", "account_invalid", "quota_exhausted"],
        dedupe_window_seconds=300,
    )


def test_send_success_posts_json():
    svc = _service()
    with patch("services.alert_service.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, ok=True)
        svc.send("backup_failure", {"error": "r2 timeout"})
    assert mock_post.called
    args, kwargs = mock_post.call_args
    assert args[0] == "https://hooks.example.com/xyz"
    assert kwargs["json"]["event"] == "backup_failure"
    assert kwargs["json"]["error"] == "r2 timeout"
    assert "ts" in kwargs["json"]


def test_send_retries_once_on_failure():
    svc = _service()
    with patch("services.alert_service.requests.post") as mock_post, patch("services.alert_service.time.sleep"):
        mock_post.side_effect = [Exception("conn reset"), MagicMock(status_code=200, ok=True)]
        svc.send("circuit_breaker_open", {"token_suffix": "abcd1234"})
    assert mock_post.call_count == 2, "失败应重试 1 次"


def test_send_gives_up_after_retry():
    svc = _service()
    with patch("services.alert_service.requests.post", side_effect=Exception("down")) as mock_post, \
         patch("services.alert_service.time.sleep"):
        # 不抛异常（发送失败不阻塞主流程）
        svc.send("backup_failure", {"error": "x"})
    assert mock_post.call_count == 2


def test_dedupe_same_event_within_window():
    svc = _service()
    with patch("services.alert_service.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, ok=True)
        payload = {"token_suffix": "abcd1234"}
        svc.send("circuit_breaker_open", payload)
        svc.send("circuit_breaker_open", payload)  # 5 分钟内同事件去重
    assert mock_post.call_count == 1


def test_dedupe_allows_different_events():
    svc = _service()
    with patch("services.alert_service.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, ok=True)
        svc.send("circuit_breaker_open", {"token_suffix": "a"})
        svc.send("backup_failure", {"error": "y"})
    assert mock_post.call_count == 2


def test_no_send_when_url_empty():
    svc = _service(url="")
    with patch("services.alert_service.requests.post") as mock_post:
        svc.send("backup_failure", {"error": "x"})
    assert not mock_post.called


def test_no_send_when_event_disabled():
    svc = _service(events=["backup_failure"])
    with patch("services.alert_service.requests.post") as mock_post:
        svc.send("circuit_breaker_open", {"token_suffix": "a"})
    assert not mock_post.called


def test_send_failure_does_not_raise():
    svc = _service()
    with patch("services.alert_service.requests.post", side_effect=Exception("net down")), \
         patch("services.alert_service.time.sleep"):
        svc.send("quota_exhausted", {"account": "x"})  # 不应抛异常


def test_circuit_breaker_trip_triggers_alert(monkeypatch):
    """集成：熔断器 OPEN 时触发 circuit_breaker_open 告警。"""
    import services.alert_service as alert_module

    sent: list[dict] = []
    monkeypatch.setattr(alert_module, "_build_from_config", lambda: AlertService("https://hooks.example.com/x", dedupe_window_seconds=0.01))

    def _fake_post(*args, **kwargs):
        sent.append(kwargs.get("json", {}))

    monkeypatch.setattr(alert_module.requests, "post", _fake_post)

    from services.circuit_breaker import CircuitBreakerRegistry

    unique_token = f"alert-token-{id(sent)}"
    registry = CircuitBreakerRegistry(failure_threshold=5)
    breaker = registry.get(unique_token)
    for _ in range(5):
        breaker.record_failure()
    assert any(e.get("event") == "circuit_breaker_open" for e in sent), "熔断 OPEN 未触发告警"
    assert sent[0].get("token_suffix") == unique_token[-8:]


def test_config_alert_properties():
    from services.config import config

    assert config.alert_webhook_url == ""
    assert config.alert_webhook_timeout == 10
    assert "circuit_breaker_open" in config.alert_events
    data = config.get()
    assert data["alert_webhook_url"] == ""
    assert data["alert_webhook_timeout"] == 10
