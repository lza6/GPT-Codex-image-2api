"""3.1.3：图片生成 seed 透传（单元层）。

- ConversationRequest.seed 默认 None
- stream_codex_image_outputs 透传 request.seed 到 backend.iter_codex_image_response_events
- openai_v1_image_generations.handle 解析 body.seed（数字→int，非法/空→None）
真实上游"seed 相同结果近似"属 live 行为，标 pytest.mark.live 默认排除。
"""

from __future__ import annotations

import pytest

from services.protocol.conversation import ConversationRequest, stream_codex_image_outputs


class _FakeBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def iter_codex_image_response_events(self, **kwargs):  # noqa: ANN002
        self.calls.append(kwargs)
        return iter(())


def _run_stream(backend: _FakeBackend, request: ConversationRequest) -> None:
    """吞掉无图片产出的 ImageGenerationError，只关心 backend 收到的参数。"""
    try:
        list(stream_codex_image_outputs(backend, request))
    except Exception:
        pass


class TestSeedPassthrough:
    def test_seed_default_none(self) -> None:
        assert ConversationRequest(prompt="x").seed is None

    def test_stream_codex_passes_seed_to_backend(self) -> None:
        backend = _FakeBackend()
        _run_stream(backend, ConversationRequest(prompt="cat", model="gpt-image-2", seed=42))
        assert backend.calls
        assert backend.calls[0]["seed"] == 42

    def test_stream_codex_seed_none(self) -> None:
        backend = _FakeBackend()
        _run_stream(backend, ConversationRequest(prompt="cat", model="gpt-image-2", seed=None))
        assert backend.calls
        assert backend.calls[0]["seed"] is None

    def test_handle_parses_numeric_seed(self, monkeypatch) -> None:
        captured: dict = {}

        def _fake_stream(req):  # noqa: ANN001
            captured["req"] = req
            return iter(())

        monkeypatch.setattr(
            "services.protocol.openai_v1_image_generations.stream_image_outputs_with_pool", _fake_stream
        )
        from services.protocol.openai_v1_image_generations import handle

        handle({"prompt": "cat", "seed": "42", "stream": True})
        assert captured["req"].seed == 42

    def test_handle_invalid_or_empty_seed_is_none(self, monkeypatch) -> None:
        captured: dict = {}

        def _fake_stream(req):  # noqa: ANN001
            captured["req"] = req
            return iter(())

        monkeypatch.setattr(
            "services.protocol.openai_v1_image_generations.stream_image_outputs_with_pool", _fake_stream
        )
        from services.protocol.openai_v1_image_generations import handle

        for raw in ("abc", "", None, "-1"):
            captured.clear()
            handle({"prompt": "cat", "seed": raw, "stream": True})
            assert captured["req"].seed is None, f"seed={raw!r} 应解析为 None"


@pytest.mark.live
def test_seed_reproducibility_live() -> None:
    """真实上游：同 seed 两次生成结果近似（需真实服务与配额，CI 默认跳过）。"""
    raise pytest.skip("live 测试需真实上游，手动运行")
