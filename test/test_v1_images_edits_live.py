"""v2.9.0：图生图真实 E2E 测试。

验证 /v1/images/edits multipart 上传 → 编辑成功 → download_image_bytes headers 修复有效。
需真实上游 + 活服务(localhost:23456)，CI 默认排除（pytest -m live 本地手动跑）。

跑法：
    uv run pytest -m live test/test_v1_images_edits_live.py::ImageEditsLiveTests -s
"""

from __future__ import annotations

import base64
import glob
import unittest
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.live

AUTH_KEY = "chatgpt2api"
BASE_URL = "http://localhost:23456"


def _find_latest_local_image() -> Path | None:
    """从 data/images 找最新一张已生成的 png 作为图生图输入素材。"""
    candidates = sorted(glob.glob("data/images/2026/*/*/*.png"), reverse=True)
    return Path(candidates[0]) if candidates else None


class ImageEditsLiveTests(unittest.TestCase):
    """图生图真实 E2E —— 验证 v2.8.2 download_image_bytes headers 修复在图生图链路有效。"""

    def test_image_edit_multipart_returns_b64_json(self):
        """multipart 上传 + 编辑 + 返回结果。

        透传开启（默认）：data[].url 为上游直链（非本地 /images/ 或 /api/images/），
        b64_json 为空——省服务器上下行流量。
        透传关闭：b64_json 可解码为合法 PNG（服务端下载重托管）。
        """
        source = _find_latest_local_image()
        if source is None or not source.exists():
            pytest.skip("无本地图片素材（data/images 下无 png），跳过图生图 E2E")

        with open(source, "rb") as f:
            image_bytes = f.read()

        response = requests.post(
            f"{BASE_URL}/v1/images/edits",
            headers={"Authorization": f"Bearer {AUTH_KEY}"},
            data={
                "model": "gpt-image-2",
                "prompt": "把这张图片改成赛博朋克夜景风格，保留主体构图",
                "n": "1",
                "response_format": "b64_json",
            },
            files={"image": (source.name, image_bytes, "image/png")},
            timeout=300,
        )

        # 断言成功（若失败，打印 detail 方便定位是 CF/账号/quota 哪个根因）
        self.assertEqual(response.status_code, 200, f"图生图失败: {response.status_code} {response.text[:300]}")

        payload = response.json()
        data = payload.get("data") or []
        self.assertGreater(len(data), 0, "图生图返回空 data")

        first_item = data[0] or {}
        b64 = str(first_item.get("b64_json") or "")
        url = str(first_item.get("url") or "")

        if b64:
            # 透传关闭：服务端下载重托管，b64_json 可解码为合法 PNG
            decoded = base64.b64decode(b64)
            self.assertGreater(len(decoded), 100, "图生图解码后字节数过小，疑似损坏")
            self.assertEqual(decoded[:8], b"\x89PNG\r\n\x1a\n", "图生图返回非合法 PNG 字节")
        else:
            # 透传开启：应返回上游直链（非本地 /images/、/api/images/），b64_json 空
            self.assertTrue(url, "透传模式图生图 url 为空")
            self.assertNotIn(f"{BASE_URL}/", url, "透传模式 url 不应是本地服务地址")
            self.assertTrue(
                url.startswith("http"),
                f"透传模式 url 应为绝对直链，实际: {url[:120]}",
            )

    def test_image_edit_url_input(self):
        """JSON 图片链接输入方式图生图（验证 URL 路径的 download 也带 headers）。"""
        source = _find_latest_local_image()
        if source is None or not source.exists():
            pytest.skip("无本地图片素材，跳过图生图 URL E2E")

        # 用本地服务的图片 URL（带 auth 才能下载，验证 download_image_bytes 带 Authorization）
        image_url = f"{BASE_URL}/images/2026/08/06/{source.name}"
        # 检查 url 可达
        head_resp = requests.head(image_url, headers={"Authorization": f"Bearer {AUTH_KEY}"}, timeout=30)
        if head_resp.status_code != 200:
            pytest.skip(f"图片 URL 不可达（{head_resp.status_code}），跳过")

        response = requests.post(
            f"{BASE_URL}/v1/images/edits",
            headers={"Authorization": f"Bearer {AUTH_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-image-2",
                "prompt": "将这张图片调整为水彩画风格",
                "n": "1",
                "image": image_url,
            },
            timeout=300,
        )
        self.assertEqual(response.status_code, 200, f"图生图(URL)失败: {response.status_code} {response.text[:300]}")
        payload = response.json()
        data = payload.get("data") or []
        self.assertGreater(len(data), 0, "图生图(URL)返回空 data")
