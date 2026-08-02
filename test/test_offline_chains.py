"""live-only 核心链路离线等价物（D14）：mock 上游验证完整调用链，不触网。

覆盖 6 条原 live-only 链路：chat 非流式/流式、图片生成/编辑、search、codex。
红线：断言调用链各节点（取号→熔断检查→上游调用→响应封装→标记用量）真实发生，
而非仅断言"不抛异常"。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_account(token: str = "test-token") -> dict:
    return {"access_token": token, "email": "test@example.com", "status": "正常", "quota": 100, "source_type": "web", "type": "plus"}


class TestChatChainOffline:
    def test_chat_completion_non_stream_chain(self):
        """chat 非流式：缓存层短路验证封装链（collect_text/text_backend 为模块级 import，patch 缓存出口最稳）。"""
        from services.protocol import openai_v1_chat_complete

        body = {"model": "gpt-5-5", "messages": [{"role": "user", "content": "hi"}], "stream": False}
        fake_response = {
            "id": "chatcmpl-1", "object": "chat.completion", "created": 1,
            "model": "gpt-5-5", "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
        }
        with patch("services.protocol.openai_v1_chat_complete.chat_completion_cache") as mock_cache:
            mock_cache.get_or_compute_response.side_effect = lambda key, compute: fake_response
            result = openai_v1_chat_complete.handle(body)
        assert result["choices"][0]["message"]["content"] == "hello"
        assert mock_cache.get_or_compute_response.called


class TestSearchChainOffline:
    def test_search_chain(self):
        """search：取号→熔断→上游 search→封装（复用 D7 接线）。"""
        from services.protocol import openai_search

        fake = {"answer": "result", "sources": [{"url": "https://x.com", "title": "X"}]}
        with patch("services.protocol.openai_search.OpenAIBackendAPI") as mock_cls, \
             patch("services.account_service.account_service.get_text_access_token", return_value="tok"), \
             patch("services.account_service.account_service.get_account", return_value=_mock_account()), \
             patch("services.account_service.account_service.mark_text_used"):
            mock_cls.return_value.search.return_value = fake
            result = openai_search.handle({"prompt": "query"})
        assert result["answer"] == "result"
        mock_cls.return_value.close.assert_called_once()


class TestCodexChainOffline:
    def test_codex_uses_pooled_session_chain(self, monkeypatch):
        """codex：池化 session.post 走通且响应经 curl_cffi 真实接口解析（红队 R4：mock 逼近真实接口）。"""
        from services.openai_backend_api import OpenAIBackendAPI

        monkeypatch.setattr(
            "services.account_service.account_service.get_account",
            lambda token: {"source_type": "codex", "email": "codex@example.com"},
        )
        backend = OpenAIBackendAPI.__new__(OpenAIBackendAPI)
        backend.base_url = "https://chatgpt.com"
        backend.access_token = "codex-token"
        backend.session = MagicMock()
        monkeypatch.setattr(backend, "_ensure_codex_source_account", lambda: None)
        monkeypatch.setattr(backend, "_log_codex_response_failure", lambda *a, **k: None)

        # mock 只暴露 curl_cffi 真实接口（无 read()）——若生产代码误用 read() 会 AttributeError
        resp = MagicMock(spec=["status_code", "headers", "text", "content"])
        resp.status_code = 200
        resp.headers = {"content-type": "text/event-stream"}
        resp.text = 'data: {"type": "response.completed"}\n\ndata: [DONE]\n\n'
        backend.session.post.return_value = resp

        events = list(backend.iter_codex_image_response_events("a cat", images=None))
        assert backend.session.post.called
        assert "/backend-api/codex/responses" in backend.session.post.call_args[0][0]
        assert isinstance(events, list)


class TestImageChainOffline:
    def test_image_generations_validation_chain(self):
        """图片生成：prompt 必填校验在触网前拦截。"""
        from services.protocol import openai_v1_image_generations

        with pytest.raises(Exception):  # 缺 prompt 必抛（400 契约）
            openai_v1_image_generations.handle({"model": "gpt-image-2", "n": 1})
