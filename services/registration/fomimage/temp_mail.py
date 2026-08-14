"""temp-mail.org 一次性邮箱收件（v2.36.0）。

已实测契约（2026-08-13）：
    POST https://web2.temp-mail.org/mailbox  {} -> {token, mailbox}
    GET  https://web2.temp-mail.org/messages  (Authorization: Bearer <token>) -> {mailbox, messages:[{subject,bodyPreview,...}]}
发送方 no-reply@fromimage.ai，主题形如 "618068 is your FromImage AI email verification code"。

安全：temp-mail 公开收件箱，验证码本身为一次性、短时效；本模块仅在注册时使用，
配合每号独立代理降低关联。与 chatgpt2api 既有 EmailPool/微软 Graph 链路并列，独立实现。
"""
from __future__ import annotations

import re
import time
from typing import Any

from curl_cffi import requests as cffi_requests

TEMP_MAIL_BASE = "https://web2.temp-mail.org"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
DEFAULT_POLL_SEC = 60
POLL_INTERVAL = 4

# fromimage 验证码邮件主题：`(\d{6}) is your FromImage AI email verification code`
FROMIMAGE_CODE_RE = re.compile(r"(\b\d{6}\b).{0,40}(?:FromImage|fromimage|verification)", re.IGNORECASE)


def extract_fromimage_code(text: str) -> str | None:
    """从邮件 subject/正文提取 fromimage 6 位验证码。先剥 HTML。"""
    if not text:
        return None
    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    m = FROMIMAGE_CODE_RE.search(text)
    if m:
        return m.group(1)
    # 兜底：任意 6 位纯数字（验证码邮件主题通常以 6 位开头）
    m = re.search(r"(?<![\d])\b(\d{6})\b(?![\d])", text)
    return m.group(1) if m else None


class TempMailInbox:
    """temp-mail 一次性邮箱：创建 + 轮询收件。每个实例独立会话 + 可选独立指纹。"""

    def __init__(self, proxy: str = "", fingerprint: dict | None = None) -> None:
        self.proxy = proxy
        self.token = ""
        self.mailbox = ""
        fp = fingerprint or {}
        self.fingerprint = fp
        impersonate = str(fp.get("impersonate") or "chrome131")
        self._session = cffi_requests.Session(impersonate=impersonate)
        if proxy:
            self._session.proxies.update({"http": proxy, "https": proxy})
        from services.fomimage_fingerprint import fingerprint_headers

        self._session.headers.update({
            **fingerprint_headers(fp),
            "Origin": "https://temp-mail.org",
        })

    def create(self) -> str:
        """创建一个随机一次性邮箱，返回邮箱地址（形如 xxxx@beiwoh.com）。失败抛 RuntimeError。"""
        response = self._session.post(
            TEMP_MAIL_BASE + "/mailbox",
            json={},
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError(f"temp-mail 创建邮箱失败: {response.status_code} {response.text[:200]}")
        data = response.json()
        token = str(data.get("token") or "")
        mailbox = str(data.get("mailbox") or "")
        if not token or "@" not in mailbox:
            raise RuntimeError(f"temp-mail 创建邮箱返回异常: {response.text[:200]}")
        self.token = token
        self.mailbox = mailbox
        return mailbox

    def fetch_messages(self) -> list[dict[str, Any]]:
        """拉取收件箱消息列表（按时间倒序）。无 token 返回 []。"""
        if not self.token:
            return []
        try:
            response = self._session.get(
                TEMP_MAIL_BASE + "/messages",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=20,
            )
            if response.status_code != 200:
                return []
            data = response.json()
            messages = data.get("messages") if isinstance(data, dict) else None
            return messages if isinstance(messages, list) else []
        except Exception:
            return []

    def poll_code(self, timeout: float = DEFAULT_POLL_SEC) -> str | None:
        """轮询取 fromimage 验证码邮件。超时返回 None。"""
        deadline = time.time() + timeout
        seen: set[str] = set()
        while time.time() < deadline:
            messages = self.fetch_messages()
            for m in messages:
                if not isinstance(m, dict):
                    continue
                mid = str(m.get("_id") or "")
                if mid in seen:
                    continue
                seen.add(mid)
                text = f"{m.get('subject', '')} {m.get('bodyPreview', '')}"
                code = extract_fromimage_code(text)
                if code:
                    return code
            time.sleep(POLL_INTERVAL)
        return None

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
