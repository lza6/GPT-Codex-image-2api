"""fomimage 真实上游 live 测试（v2.36.0，`-m live` 手动运行）。

覆盖完整链路：temp-mail 建邮箱 → fromimage 注册 → OTP 收码 → verify → signin → 查余额
→ 上传参考图 → 建图生图任务 → 轮询 → 下载结果图 → 校验余额扣减。

⚠️ 会消耗真实 fomimage 账号（注册送 50 积分，本测试消耗约 10-30 积分），
每个测试一次性邮箱用完即弃。仅手动 `uv run pytest -m live test/test_fomimage_live.py` 运行。
"""
from __future__ import annotations

import io
import unittest

import pytest

from services.fomimage_backend_api import FomimageBackendAPI, BASE_URL
from services.registration.fomimage.engine import _generate_random_name, _generate_random_password
from services.registration.fomimage.temp_mail import TempMailInbox

pytestmark = pytest.mark.live


class FomimageLiveFlowTests(unittest.TestCase):
    def test_full_register_and_edit_flow(self) -> None:
        # 1) 注册
        inbox = TempMailInbox()
        email = inbox.create()
        headers = {"Content-Type": "application/json", "Origin": BASE_URL, "Referer": BASE_URL + "/"}
        pw = _generate_random_password()
        name = _generate_random_name()
        resp = inbox._session.post(
            BASE_URL + "/api/auth/sign-up/email",
            json={"name": name, "email": email, "password": pw},
            headers=headers,
            timeout=25,
        )
        self.assertEqual(resp.status_code, 200)
        code = inbox.poll_code(timeout=60)
        self.assertIsNotNone(code, "验证码邮件超时未收到")
        resp = inbox._session.post(
            BASE_URL + "/api/auth/email-otp/verify-email",
            json={"email": email, "otp": code},
            headers=headers,
            timeout=25,
        )
        self.assertEqual(resp.status_code, 200)
        resp = inbox._session.post(
            BASE_URL + "/api/auth/sign-in/email",
            json={"email": email, "password": pw},
            headers=headers,
            timeout=25,
        )
        token = resp.json().get("token", "")
        self.assertTrue(token, "登录未拿到会话 token")
        balance = inbox._session.get(BASE_URL + "/api/credits/balance", headers=headers, timeout=20).json()
        self.assertEqual((balance.get("data") or {}).get("balance"), 50, "注册应送 50 积分")

        # 2) 图生图（gpt-image-2 low|1K = 10 积分）
        api = FomimageBackendAPI(access_token=token, email=email, proxy="")
        api._session.cookies.update(inbox._session.cookies)
        try:
            buf = io.BytesIO()
            from PIL import Image

            Image.new("RGB", (64, 64), (30, 90, 200)).save(buf, "PNG")
            urls = api.upload_images([(buf.getvalue(), "ref.png", "image/png")])
            self.assertTrue(urls, "参考图上传失败")

            task = api.create_task(
                "fomimage-gpt-image-2",
                "把蓝色物体变成绿色",
                [urls[0]],
                {"aspectRatio": "1:1", "resolution": "1K", "quality": "low"},
            )
            self.assertEqual(task.get("status"), "pending")
            self.assertEqual(task.get("costCredits"), 10)

            final = api.poll_task(task.get("id", ""), timeout=180)
            self.assertEqual(final.get("status"), "success")
            self.assertTrue(final.get("images"), "任务成功但无结果图")

            img_bytes = api.download_image(final["images"][0], proxy="")
            self.assertTrue(img_bytes, "结果图下载为空")
            self.assertEqual(img_bytes[:4], b"\x89PNG", "结果图不是 PNG")

            remaining = api.get_balance()
            self.assertEqual(remaining, 40, "low|1K 应扣 10 积分")
        finally:
            api.close()


if __name__ == "__main__":
    unittest.main()
