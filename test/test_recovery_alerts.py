"""5.3：告警降级与恢复事件——熔断恢复（circuit_breaker_closed）+ 账号恢复（account_recovered）。

验证点：
- 熔断 HALF_OPEN 连续成功恢复 CLOSED → 触发 circuit_breaker_closed（含 token_suffix）。
- 账号从失效态刷新成功清零 → 触发 account_recovered（含 account 后缀）。
- 复用既有去重机制（同指纹 5 分钟窗口内不重复）。
"""

from __future__ import annotations

import services.alert_service as alert_module
from services.account_service import AccountService
from services.alert_service import AlertService
from services.circuit_breaker import CircuitBreakerRegistry
from services.event_bus_init import register_subscribers
from services.storage.json_storage import JSONStorageBackend


def _fake_alert_factory(sent: list[dict]):
    def _factory():
        return AlertService("https://hooks.example.com/x", dedupe_window_seconds=0.01)
    return _factory


class TestRecoveryAlerts:
    def test_circuit_closed_triggers_recovery_alert(self, monkeypatch):
        """熔断半开连续成功恢复 CLOSED → 触发 circuit_breaker_closed 恢复事件。"""
        sent: list[dict] = []
        monkeypatch.setattr(alert_module, "_build_from_config", _fake_alert_factory(sent))

        def _fake_post(*args, **kwargs):
            sent.append(kwargs.get("json", {}))

        monkeypatch.setattr(alert_module.requests, "post", _fake_post)

        # 注册事件总线订阅
        register_subscribers()

        unique_token = f"alert-closed-{id(sent)}"
        registry = CircuitBreakerRegistry(failure_threshold=2, recovery_timeout=0.01, half_open_max_calls=2)
        breaker = registry.get(unique_token)
        # 熔断 → 冷却期过 → 半开 → 连续成功恢复
        breaker.record_failure()
        breaker.record_failure()  # 达到阈值 → OPEN
        assert breaker.state.value == "open"
        import time
        time.sleep(0.02)  # 越过冷却期；访问 state 触发 OPEN→HALF_OPEN（与真实调用经 allow_request 一致）
        assert breaker.state.value == "half_open"
        breaker.record_success()
        breaker.record_success()  # 半开连续成功 → CLOSED
        assert breaker.state.value == "closed"

        events = [e.get("event") for e in sent]
        assert "circuit_breaker_closed" in events, f"恢复事件未触发: {events}"
        closed = next(e for e in sent if e.get("event") == "circuit_breaker_closed")
        assert closed.get("token_suffix") == unique_token[-8:]

    def test_account_recovered_triggers_after_invalid_cleared(self, monkeypatch, tmp_path):
        """账号从失效态刷新成功（invalid_count/last_invalid_at 清零）→ 触发 account_recovered。"""
        sent: list[dict] = []
        monkeypatch.setattr(alert_module, "_build_from_config", _fake_alert_factory(sent))

        def _fake_post(*args, **kwargs):
            sent.append(kwargs.get("json", {}))

        monkeypatch.setattr(alert_module.requests, "post", _fake_post)

        # 注册事件总线订阅
        register_subscribers()

        storage = JSONStorageBackend(tmp_path / "accounts.json")
        svc = AccountService(storage)
        token = f"recover-token-{id(sent)}"
        svc._accounts[token] = {
            "access_token": token,
            "status": "正常",
            "quota": 100,
            "success": 5,
            "fail": 3,
            "invalid_count": 2,
            "last_invalid_at": "2026-08-05 00:00:00",
            "last_refresh_error_at": "2026-08-05 00:00:00",
        }
        # 刷新成功应清零失效态
        svc._record_refresh_success(token)
        events = [e.get("event") for e in sent]
        assert "account_recovered" in events, f"账号恢复事件未触发: {events}"

    def test_recovery_dedupe_window(self, monkeypatch, tmp_path):
        """同指纹恢复事件在去重窗口内不重复（复用既有机制）。"""
        sent: list[dict] = []
        monkeypatch.setattr(alert_module, "_build_from_config", lambda: AlertService(
            "https://hooks.example.com/x", dedupe_window_seconds=300.0))

        def _fake_post(*args, **kwargs):
            sent.append(kwargs.get("json", {}))

        monkeypatch.setattr(alert_module.requests, "post", _fake_post)

        # 注册事件总线订阅
        register_subscribers()

        storage = JSONStorageBackend(tmp_path / "accounts.json")
        svc = AccountService(storage)
        token = f"recover-dedupe-{id(sent)}"
        svc._accounts[token] = {
            "access_token": token, "status": "正常", "quota": 100,
            "success": 5, "fail": 3, "invalid_count": 1,
            "last_invalid_at": "2026-08-05 00:00:00",
        }
        svc._record_refresh_success(token)
        svc._record_refresh_success(token)  # 第二次 refresh 同样触发，但应被去重
        count = sum(1 for e in sent if e.get("event") == "account_recovered")
        assert count <= 1, f"恢复事件应去重: {count}"
