"""生图 protocol 层 provider 透传单测（Phase 4）。

验证 openai_v1_image_generations / openai_v1_image_edit 把请求体 provider
透传给 ConversationRequest，作为生图账号选取的 provider 过滤依据。
纯单元不触网，patch 掉 stream_image_outputs_with_pool 捕获请求对象。
"""
from __future__ import annotations

from unittest import mock

from services.protocol import openai_v1_image_edit, openai_v1_image_generations


def _capture_request(patch_target: str):
    """返回 (patch, captured) —— patch 后捕获传入的 ConversationRequest。"""
    captured: list[object] = []

    def _fake_stream(request):
        captured.append(request)
        return iter([])

    patcher = mock.patch(patch_target, side_effect=_fake_stream)
    return patcher, captured


class TestImageGenerationProviderPassthrough:
    def test_generation_provider_passed_to_request(self) -> None:
        patcher, captured = _capture_request(
            "services.protocol.openai_v1_image_generations.stream_image_outputs_with_pool"
        )
        with patcher:
            openai_v1_image_generations.handle(
                {"prompt": "cat", "model": "grok-3-image", "provider": "grok"}
            )
        assert len(captured) == 1
        req = captured[0]
        assert req.provider == "grok"

    def test_generation_provider_default_none(self) -> None:
        patcher, captured = _capture_request(
            "services.protocol.openai_v1_image_generations.stream_image_outputs_with_pool"
        )
        with patcher:
            openai_v1_image_generations.handle({"prompt": "cat", "model": "gpt-image-2"})
        assert len(captured) == 1
        assert captured[0].provider is None

    def test_generation_provider_normalized_lower(self) -> None:
        patcher, captured = _capture_request(
            "services.protocol.openai_v1_image_generations.stream_image_outputs_with_pool"
        )
        with patcher:
            openai_v1_image_generations.handle(
                {"prompt": "cat", "model": "grok-3-image", "provider": " Grok "}
            )
        assert len(captured) == 1
        assert captured[0].provider == "grok"


class TestImageEditProviderPassthrough:
    def test_edit_provider_passed_to_request(self) -> None:
        patcher, captured = _capture_request(
            "services.protocol.openai_v1_image_edit.stream_image_outputs_with_pool"
        )
        with patcher, mock.patch(
            "services.protocol.openai_v1_image_edit.encode_images",
            return_value=["data:image/png;base64,AAAA"],
        ):
            openai_v1_image_edit.handle(
                {"prompt": "edit", "model": "grok-3-image", "provider": "grok",
                 "images": [(b"one", "one.png", "image/png")]}
            )
        assert len(captured) == 1
        assert captured[0].provider == "grok"

    def test_edit_provider_default_none(self) -> None:
        patcher, captured = _capture_request(
            "services.protocol.openai_v1_image_edit.stream_image_outputs_with_pool"
        )
        with patcher, mock.patch(
            "services.protocol.openai_v1_image_edit.encode_images",
            return_value=["data:image/png;base64,AAAA"],
        ):
            openai_v1_image_edit.handle(
                {"prompt": "edit", "model": "gpt-image-2",
                 "images": [(b"one", "one.png", "image/png")]}
            )
        assert len(captured) == 1
        assert captured[0].provider is None
