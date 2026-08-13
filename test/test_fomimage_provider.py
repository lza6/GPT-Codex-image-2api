"""fomimage provider 协议层单元测试（v2.36.0，不触网，mock 上游）。

覆盖：
- build_fomimage_options：OpenAI size/quality → fomimage options 映射
- generate_fomimage_images：上传→建任务→轮询→下载→产出 ImageOutput
- _generate_single_image 按 account.provider=fomimage 分派到 fomimage 路径
- mark_image_credits_result：按 costCredits 扣 quota，归零自动剔除
"""
from __future__ import annotations

import unittest
from unittest import mock

from services.protocol import conversation
from services.protocol.conversation import ConversationRequest, ImageOutput


class BuildFomimageOptionsTests(unittest.TestCase):
    def _req(self, **kw) -> ConversationRequest:
        return ConversationRequest(model="fomimage-gpt-image-2", **kw)

    def test_i2i_default_ratio(self) -> None:
        req = self._req(size=None, quality=None)
        from services.protocol.fomimage_image import build_fomimage_options

        opts = build_fomimage_options(req, "fomimage-gpt-image-2")
        self.assertEqual(opts["aspectRatio"], "match_input_image")
        self.assertEqual(opts["resolution"], "1K")
        self.assertEqual(opts["quality"], "medium")  # gpt-image-2 默认 medium

    def test_t2i_default_ratio(self) -> None:
        from services.protocol.fomimage_image import build_fomimage_options

        req = ConversationRequest(model="fomimage-wan-2.7-text", size=None, quality=None)
        opts = build_fomimage_options(req, "fomimage-wan-2.7-text")
        self.assertEqual(opts["aspectRatio"], "1:1")

    def test_size_maps_to_ratio(self) -> None:
        from services.protocol.fomimage_image import build_fomimage_options

        req = ConversationRequest(model="fomimage-gpt-image-2-text", size="1024x1536", quality="high")
        opts = build_fomimage_options(req, "fomimage-gpt-image-2-text")
        self.assertEqual(opts["aspectRatio"], "2:3")
        self.assertEqual(opts["quality"], "high")
        self.assertEqual(opts["size"], "1024x1536")

    def test_native_options_passthrough(self) -> None:
        from services.protocol.fomimage_image import build_fomimage_options

        req = ConversationRequest(
            model="fomimage-gpt-image-2",
            options={"aspectRatio": "16:9", "resolution": "4K", "quality": "high"},
        )
        opts = build_fomimage_options(req, "fomimage-gpt-image-2")
        self.assertEqual(opts["aspectRatio"], "16:9")
        self.assertEqual(opts["resolution"], "4K")
        self.assertEqual(opts["quality"], "high")


class GenerateFomimageImagesTests(unittest.TestCase):
    def test_full_flow(self) -> None:
        from services.protocol.fomimage_image import generate_fomimage_images

        backend = mock.Mock()
        backend.proxy = ""
        backend.upload_images.return_value = ["https://images.fromimage.ai/uploads/ref.png"]
        backend.create_task.return_value = {"id": "task1", "status": "pending", "costCredits": 50}
        backend.poll_task.return_value = {"id": "task1", "status": "success", "images": ["https://images.fromimage.ai/uploads/out.png"]}
        backend.download_image.return_value = b"\x89PNG\r\n\x1a\nfake-png-bytes"

        req = ConversationRequest(
            model="fomimage-gpt-image-2",
            prompt="merge",
            images=["aGVsbG8="],
            size=None,
            quality=None,
            response_format="b64_json",
        )
        outputs = list(generate_fomimage_images(backend, req, 1, 1))
        kinds = [o.kind for o in outputs]
        self.assertIn("progress", kinds)
        self.assertIn("result", kinds)
        result = outputs[-1]
        self.assertEqual(result.kind, "result")
        self.assertEqual(len(result.data), 1)
        self.assertIn("b64_json", result.data[0])
        self.assertIn("url", result.data[0])
        # 上传调用带参考图
        backend.upload_images.assert_called_once()

    def test_poll_failure_raises(self) -> None:
        from services.fomimage_backend_api import FomimageTaskError
        from services.protocol.fomimage_image import generate_fomimage_images

        backend = mock.Mock()
        backend.proxy = ""
        backend.upload_images.return_value = []
        backend.create_task.return_value = {"id": "t", "status": "pending", "costCredits": 10}
        backend.poll_task.side_effect = FomimageTaskError("task failed")

        req = ConversationRequest(model="fomimage-wan-2.7-text", prompt="x", images=[], size=None, quality=None)
        with self.assertRaises(FomimageTaskError):
            list(generate_fomimage_images(backend, req, 1, 1))


class GenerateSingleImageDispatchTests(unittest.TestCase):
    def test_fomimage_account_dispatches(self) -> None:
        """account.provider=fomimage 时走 fomimage 路径（不构造 OpenAIBackendAPI）。"""
        req = ConversationRequest(model="fomimage-gpt-image-2", prompt="cat", size=None, quality=None)
        account = {"provider": "fomimage", "email": "a@b.com", "access_token": "tok1", "proxy": "", "quota": 50}
        outputs = [
            ImageOutput(kind="progress", model="fomimage-gpt-image-2", index=1, total=1, text="fomimage 任务已创建（消耗 50 积分）"),
            ImageOutput(kind="result", model="fomimage-gpt-image-2", index=1, total=1,
                        data=[{"b64_json": "AAAA", "url": "http://x", "revised_prompt": "cat"}]),
        ]

        with mock.patch.object(conversation, "account_service") as svc, \
             mock.patch.object(conversation, "circuit_breaker_registry") as breaker, \
             mock.patch("services.fomimage_backend_api.FomimageBackendAPI") as BackendCls, \
             mock.patch("services.protocol.fomimage_image.generate_fomimage_images", return_value=outputs):
            breaker.get.return_value.allow_request.return_value = True
            svc.get_account.return_value = account
            svc.get_available_access_token.return_value = "tok1"
            svc.mark_image_credits_result.return_value = None

            result = conversation._generate_single_image(req, 1, 1)

        self.assertEqual(result, outputs)
        BackendCls.assert_called_once()
        svc.mark_image_credits_result.assert_called()
        breaker.get.return_value.record_success.assert_called_once()

    def test_non_fomimage_uses_openai(self) -> None:
        """account.provider=chatgpt 时仍走 OpenAIBackendAPI 路径。"""
        req = ConversationRequest(model="gpt-image-2", prompt="cat", size=None, quality=None)
        account = {"provider": "chatgpt", "email": "a@b.com", "access_token": "tok1", "quota": -1}
        with mock.patch.object(conversation, "account_service") as svc, \
             mock.patch.object(conversation, "circuit_breaker_registry") as breaker, \
             mock.patch("services.protocol.conversation.OpenAIBackendAPI") as BackendCls, \
             mock.patch("services.protocol.conversation._generate_fomimage_image") as fom_mock:
            breaker.get.return_value.allow_request.return_value = True
            svc.get_account.return_value = account
            svc.get_available_access_token.return_value = "tok1"
            BackendCls.return_value.close = lambda: None
            # 阻止真正调用 OpenAI 流——让 stream_fn 抛错快速返回
            from services.protocol.conversation import ImageGenerationError

            def _stream(backend, request, index, total):
                raise ImageGenerationError("boom")
                yield  # pragma: no cover

            BackendCls.return_value.close = lambda: None
            with mock.patch("services.protocol.conversation.stream_image_outputs", side_effect=_stream):
                try:
                    conversation._generate_single_image(req, 1, 1)
                except ImageGenerationError:
                    pass
        fom_mock.assert_not_called()


class MarkImageCreditsResultTests(unittest.TestCase):
    def test_deduct_quota_and_remove_when_zero(self) -> None:
        import tempfile
        from pathlib import Path

        from services.account_service import AccountService, config
        from services.storage.json_storage import JSONStorageBackend

        svc = AccountService(JSONStorageBackend(Path(tempfile.mkdtemp()) / "a.json"))
        svc._accounts = {}
        svc._token_aliases = {}
        svc._breaker_registry = mock.Mock()
        svc._dirty = False
        svc._accounts["tok1"] = {"access_token": "tok1", "provider": "fomimage", "quota": 1, "status": "正常"}
        old = config.data.get("auto_remove_rate_limited_accounts", False)
        config.data["auto_remove_rate_limited_accounts"] = True
        try:
            with mock.patch.object(svc, "_save_accounts"), \
                 mock.patch("services.account_service.log_service"):
                svc.mark_image_credits_result("tok1", True, credits=1)
        finally:
            config.data["auto_remove_rate_limited_accounts"] = old
        self.assertNotIn("tok1", svc._accounts)  # 用完即弃


class GetAvailableAccessTokenFomimageTests(unittest.TestCase):
    def test_fomimage_skips_openai_remote_validation(self) -> None:
        """fomimage 账号在 get_available_access_token 中跳过 OpenAI get_user_info 远程校验。"""
        import tempfile
        from pathlib import Path

        from services.account_service import AccountService
        from services.storage.json_storage import JSONStorageBackend

        svc = AccountService(JSONStorageBackend(Path(tempfile.mkdtemp()) / "a.json"))
        tok = "fomimage-tok"
        acct = {"access_token": tok, "provider": "fomimage", "quota": 50, "status": "正常", "email": "a@b.com"}
        svc._accounts = {tok: acct}
        svc._token_aliases = {}
        svc._breaker_registry = mock.Mock()

        with mock.patch.object(svc, "_acquire_next_candidate_token", return_value=tok), \
             mock.patch.object(svc, "fetch_remote_info", side_effect=AssertionError("不应走 OpenAI 远程校验")), \
             mock.patch.object(svc, "_is_image_account_available", return_value=True), \
             mock.patch.object(svc, "_account_matches_plan_type", return_value=True), \
             mock.patch.object(svc, "_account_matches_any_plan_type", return_value=True), \
             mock.patch.object(svc, "_account_matches_source_type", return_value=True), \
             mock.patch.object(svc, "_acquire_account_proxy_and_egress"), \
             mock.patch("services.provider_scheduler.provider_scheduler._provider_allow_request", return_value=True), \
             mock.patch("services.provider_scheduler.provider_scheduler._check_provider_rate_limit", return_value=True):
            picked = svc.get_available_access_token(provider="fomimage")
        self.assertEqual(picked, tok)


if __name__ == "__main__":
    unittest.main()
