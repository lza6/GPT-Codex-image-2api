"""图片透传（上游直链）单元测试。

验证 config.image_passthrough_enabled 开启时：
- build_passthrough_items 组装 url/expires_at，b64_json 为空、不下载
- _passthrough_items_to_data 输出 OpenAI 兼容 data[]（含 expires_at）
- _image_items_from_urls 按开关分流（透传不调用 download_image_bytes）
"""
from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from services.protocol import conversation as conv


class TestBuildPassthroughItems(unittest.TestCase):
    def test_assembles_url_and_expiry(self):
        items = conv.build_passthrough_items(["https://chatgpt.com/backend-api/estuary/content?id=x&sig=1"], "画一只猫")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://chatgpt.com/backend-api/estuary/content?id=x&sig=1")
        self.assertEqual(items[0]["b64_json"], "")
        self.assertEqual(items[0]["revised_prompt"], "画一只猫")
        self.assertIsInstance(items[0]["expires_at"], int)
        self.assertGreater(items[0]["expires_at"], 0)

    def test_skips_empty_url(self):
        items = conv.build_passthrough_items(["", "https://x/y.png"], "p")
        self.assertEqual(len(items), 1)


class TestPassthroughItemsToData(unittest.TestCase):
    def test_outputs_openai_compatible_data(self):
        items = [{"url": "https://a/b.png", "revised_prompt": "猫", "expires_at": 123, "b64_json": ""}]
        data = conv._passthrough_items_to_data(items, "fallback")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["url"], "https://a/b.png")
        self.assertEqual(data[0]["revised_prompt"], "猫")
        self.assertEqual(data[0]["expires_at"], 123)
        self.assertNotIn("b64_json", data[0])

    def test_skips_empty_url(self):
        data = conv._passthrough_items_to_data([{"url": ""}, {"url": "https://a.png"}], "p")
        self.assertEqual(len(data), 1)


class TestImageItemsFromUrls(unittest.TestCase):
    class _FakeBackend:
        def __init__(self):
            self.downloaded = False

        def download_image_bytes(self, urls):
            self.downloaded = True
            return [b"img-bytes"]

    def test_passthrough_does_not_download(self):
        backend = self._FakeBackend()
        with patch.object(type(conv.config), "image_passthrough_enabled", new_callable=lambda: property(lambda self: True)):
            items = conv._image_items_from_urls(backend, ["https://a/b.png"], "p")
        self.assertFalse(backend.downloaded, "透传模式不应调用 download_image_bytes")
        self.assertEqual(items[0]["url"], "https://a/b.png")

    def test_default_downloads_and_encodes_b64(self):
        backend = self._FakeBackend()
        # 透传默认开启；这里显式关闭验证「服务端下载重托管」回退路径不变
        with patch.object(type(conv.config), "image_passthrough_enabled", new_callable=lambda: property(lambda self: False)):
            items = conv._image_items_from_urls(backend, ["https://a/b.png"], "p")
        self.assertTrue(backend.downloaded, "关闭透传时应走服务端下载")
        self.assertEqual(items[0]["b64_json"], base64.b64encode(b"img-bytes").decode("ascii"))


if __name__ == "__main__":
    unittest.main()
