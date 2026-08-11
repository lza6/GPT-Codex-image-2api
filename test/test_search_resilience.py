"""搜索路径韧性测试（D7）：熔断接入 + backend close 泄漏修复。"""

from __future__ import annotations

from services.circuit_breaker import CircuitBreakerRegistry


def _registry_with_open_breaker(token: str) -> CircuitBreakerRegistry:
    registry = CircuitBreakerRegistry(failure_threshold=5, recovery_timeout=30.0)
    breaker = registry.get(token)
    for _ in range(5):
        breaker.record_failure()
    return registry


def test_search_fails_fast_when_breaker_open(monkeypatch):
    """熔断 OPEN 时 search 快速失败，不请求上游。"""
    from services.protocol import openai_search

    token = "search-token-open"
    registry = _registry_with_open_breaker(token)

    call_count = {"n": 0}

    class _FakeBackend:
        def __init__(self, t):
            call_count["n"] += 1

        def search(self, prompt):
            return {}

        def close(self):
            pass

    monkeypatch.setattr("services.account_service.account_service.get_text_access_token", lambda: token)
    monkeypatch.setattr("services.account_service.account_service.get_account", lambda t: {"email": "a@b.c"})
    monkeypatch.setattr("services.protocol.openai_search.OpenAIBackendAPI", _FakeBackend)
    monkeypatch.setattr("services.account_service.account_service._breaker_registry", registry)

    import pytest

    with pytest.raises(RuntimeError, match="circuit|熔断|unavailable|open"):
        openai_search.handle({"prompt": "test"})
    assert call_count["n"] == 0, "熔断 OPEN 时不应构造/请求 backend"


def test_search_records_failure_on_upstream_5xx(monkeypatch):
    """上游 5xx 时 search 记熔断失败（image_failure should_record_circuit_failure 白名单）。"""
    from services.protocol import openai_search
    from utils.helper import UpstreamHTTPError

    token = "search-token-5xx"
    registry = CircuitBreakerRegistry()

    class _FakeBackend:
        def __init__(self, t):
            pass

        def search(self, prompt):
            raise UpstreamHTTPError("/backend-api/f/conversation", 502, {"error": "bad gateway"})

        def close(self):
            pass

    monkeypatch.setattr("services.account_service.account_service.get_text_access_token", lambda: token)
    monkeypatch.setattr("services.account_service.account_service.get_account", lambda t: {"email": "a@b.c"})
    monkeypatch.setattr("services.protocol.openai_search.OpenAIBackendAPI", _FakeBackend)
    monkeypatch.setattr("services.account_service.account_service._breaker_registry", registry)
    monkeypatch.setattr("services.account_service.account_service.mark_text_used", lambda t: None)

    import pytest

    with pytest.raises(UpstreamHTTPError):
        openai_search.handle({"prompt": "test"})
    # 熔断器应记录 1 次失败（未达阈值仍 closed）
    assert registry.get(token)._failure_count == 1


def test_web_search_tool_closes_backend(monkeypatch):
    """web_search_tool.run_web_search 必须关闭 backend（close 泄漏修复）。"""
    from services.protocol import web_search_tool

    closed = {"flag": False}

    class _FakeBackend:
        def __init__(self, t):
            pass

        def search(self, query):
            return {"answer": "ok", "sources": []}

        def close(self):
            closed["flag"] = True

    monkeypatch.setattr("services.account_service.account_service.get_text_access_token", lambda: "tok")
    monkeypatch.setattr("services.protocol.web_search_tool.OpenAIBackendAPI", _FakeBackend)
    monkeypatch.setattr("services.account_service.account_service.mark_text_used", lambda t: None)

    result = web_search_tool.run_web_search("query")
    assert result["answer"] == "ok"
    assert closed["flag"], "backend.close() 未被调用——连接泄漏"


def test_poll_timeout_retries_bounded():
    """轮询超时重试有上限且不为 5（变异探针锚点：函数局部常量）。"""
    import inspect

    from services.protocol import conversation as conv_mod

    src = inspect.getsource(conv_mod)
    assert "MAX_POLL_TIMEOUT_RETRIES = 4" in src, "轮询超时重试上限应为 4"
