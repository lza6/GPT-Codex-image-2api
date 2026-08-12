"""多参考图编辑验证测试：证明 /v1/images/edits 支持一次多张参考图。

链路：multipart 多个 image 字段 / JSON images 数组 → parse_image_edit_request
→ read_image_sources 多图 → protocol handle 多图 → 上游 ConversationRequest images 数组。

全部 mock 上游（不触网），非 live。
"""
from __future__ import annotations

import base64
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.ai as ai_module

AUTH_HEADERS = {"Authorization": "Bearer chatgpt2api"}
PNG_BYTES = b"\x89PNG\r\n\x1a\n"
DATA_IMAGE_URL = f"data:image/png;base64,{base64.b64encode(PNG_BYTES).decode('ascii')}"


class MultiReferenceApiTests(unittest.TestCase):
    """端到端：TestClient 提交多图 → mock handle 捕获 payload，验证 images 是 N 个。"""

    def setUp(self) -> None:
        self.handle_calls: list[dict] = []

        def fake_handle(payload):
            self.handle_calls.append(payload)
            return {"created": 1, "data": [{"b64_json": base64.b64encode(b"out").decode("ascii")}]}

        self.handler_patcher = mock.patch.object(ai_module.openai_v1_image_edit, "handle", fake_handle)
        self.handler_patcher.start()
        self.addCleanup(self.handler_patcher.stop)
        app = FastAPI()
        app.include_router(ai_module.create_router())
        self.client = TestClient(app)

    def test_multipart_multiple_image_fields(self) -> None:
        """multipart 提交 3 个 image 字段 → payload images 应含 3 个。"""
        files = [
            ("image", ("a.png", PNG_BYTES, "image/png")),
            ("image", ("b.png", PNG_BYTES, "image/png")),
            ("image", ("c.png", PNG_BYTES, "image/png")),
        ]
        response = self.client.post(
            "/v1/images/edits",
            headers=AUTH_HEADERS,
            data={"model": "gpt-image-2", "prompt": "merge all"},
            files=files,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.handle_calls), 1)
        images = self.handle_calls[0].get("images") or []
        self.assertEqual(len(images), 3, f"应解析出 3 张参考图，实际 {len(images)}")
        # 每张都是 (bytes, filename, mime) 元组
        for data, filename, mime in images:
            self.assertTrue(data)
            self.assertTrue(filename.endswith(".png"))
            self.assertEqual(mime, "image/png")

    def test_json_images_array(self) -> None:
        """JSON images 数组（官方格式：images: [{image_url}, {image_url}]）→ 2 张。"""
        response = self.client.post(
            "/v1/images/edits",
            headers=AUTH_HEADERS,
            json={
                "model": "gpt-image-2",
                "prompt": "edit",
                "images": [{"image_url": DATA_IMAGE_URL}, {"image_url": DATA_IMAGE_URL}],
                "n": 1,
                "response_format": "b64_json",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        images = self.handle_calls[0].get("images") or []
        self.assertEqual(len(images), 2, f"JSON images 数组应解析出 2 张，实际 {len(images)}")

    def test_json_image_url_list(self) -> None:
        """JSON image_url 字符串数组（兼容格式）→ 2 张。"""
        response = self.client.post(
            "/v1/images/edits",
            headers=AUTH_HEADERS,
            json={
                "model": "gpt-image-2",
                "prompt": "edit",
                "image_url": [DATA_IMAGE_URL, DATA_IMAGE_URL],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        images = self.handle_calls[0].get("images") or []
        self.assertEqual(len(images), 2)

    def test_single_image_still_works(self) -> None:
        """回归：单图编辑不受影响。"""
        response = self.client.post(
            "/v1/images/edits",
            headers=AUTH_HEADERS,
            data={"model": "gpt-image-2", "prompt": "edit"},
            files=[("image", ("a.png", PNG_BYTES, "image/png"))],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.handle_calls[0]["images"]), 1)


class ProtocolMultiImageTests(unittest.TestCase):
    """协议层：openai_v1_image_edit.handle 把 N 张参考图透传到上游 ConversationRequest.images。"""

    def test_handle_passes_multiple_images_to_conversation(self) -> None:
        import services.protocol.openai_v1_image_edit as edit_mod

        images = [
            (PNG_BYTES, "a.png", "image/png"),
            (PNG_BYTES, "b.png", "image/png"),
        ]
        with mock.patch.object(edit_mod, "ConversationRequest") as fake_cr, mock.patch.object(
            edit_mod, "stream_image_outputs_with_pool", return_value=iter(())
        ), mock.patch.object(edit_mod, "collect_image_outputs", return_value={"data": []}):
            edit_mod.handle({"prompt": "edit", "model": "gpt-image-2", "images": images})
            self.assertEqual(fake_cr.call_count, 1)
            encoded = fake_cr.call_args.kwargs["images"]
            self.assertEqual(len(encoded), 2, f"上游应收到 2 个 image item，实际 {len(encoded)}")

    def test_encode_images_multiple(self) -> None:
        from services.protocol.conversation import encode_images

        images = [
            (PNG_BYTES, "a.png", "image/png"),
            (PNG_BYTES, "b.png", "image/png"),
            (PNG_BYTES, "c.png", "image/png"),
        ]
        encoded = encode_images(images)
        self.assertEqual(len(encoded), 3)
        # 每个 item 是 base64 编码的图片字节（上游组装时包装成 data URI）
        for item in encoded:
            data = base64.b64decode(item)
            self.assertTrue(data.startswith(b"\x89PNG"), "应能解回原始 PNG 字节")


if __name__ == "__main__":
    unittest.main()
