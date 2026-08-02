"""codex 路径池化测试（D6）：经 session_pool 的 curl_cffi Session 发起，不走裸 urllib。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _backend_with_fake_session(monkeypatch):
    from services.openai_backend_api import OpenAIBackendAPI

    monkeypatch.setattr(
        "services.account_service.account_service.get_account",
        lambda token: {"source_type": "codex", "email": "codex@example.com"},
    )
    backend = OpenAIBackendAPI.__new__(OpenAIBackendAPI)
    backend.base_url = "https://chatgpt.com"
    backend.access_token = "codex-token"
    backend.session = MagicMock()
    # 跳过真实 codex source 校验与日志字段依赖
    monkeypatch.setattr(backend, "_ensure_codex_source_account", lambda: None)
    monkeypatch.setattr(backend, "_log_codex_response_failure", lambda *a, **k: None)
    return backend


def test_codex_uses_pooled_session_not_urllib(monkeypatch):
    """iter_codex_image_response_events 必须经 self.session.post（池化），而非 urllib.urlopen。"""
    backend = _backend_with_fake_session(monkeypatch)

    # 池化 session 返回 200 + SSE 空事件流
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"content-type": "text/event-stream"}
    resp.text = "data: [DONE]\n\n"
    resp.read.return_value = b"data: [DONE]\n\n"
    backend.session.post.return_value = resp

    import services.openai_backend_api as mod

    # 若残留 urllib.request 引用则改造未完成
    assert not hasattr(mod, "urllib"), "openai_backend_api 仍 import urllib——池化改造未完成"

    events = list(backend.iter_codex_image_response_events("a cat", images=None))
    assert backend.session.post.called, "codex 未走池化 session.post"
    call_kwargs = backend.session.post.call_args
    assert "/backend-api/codex/responses" in call_kwargs[0][0]
    assert isinstance(events, list)


def test_codex_5xx_raises_upstream_http_error(monkeypatch):
    """codex 上游 5xx → UpstreamHTTPError（供熔断白名单判定）。"""
    from utils.helper import UpstreamHTTPError

    backend = _backend_with_fake_session(monkeypatch)
    resp = MagicMock()
    resp.status_code = 502
    resp.headers = {"content-type": "application/json", "Retry-After": "5"}
    resp.text = '{"error": "bad gateway"}'
    backend.session.post.return_value = resp

    with pytest.raises(UpstreamHTTPError) as exc_info:
        list(backend.iter_codex_image_response_events("a cat", images=None))
    assert exc_info.value.status_code == 502
    assert exc_info.value.retry_after == 5
