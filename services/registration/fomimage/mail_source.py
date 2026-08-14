"""fomimage 邮箱源（v2.36.0）：temp-mail / luckmail / gptmail 三种收件方式统一。

每个邮箱源提供：
- `session`：curl_cffi Session（带指纹+代理，用于 fromimage 注册/登录/查余额）
- `email`：邮箱地址
- `poll_code(timeout) -> str|None`：轮询收 fromimage 6 位验证码
- `close()`：释放

engine 按 `email_sources` 配置优先级逐个尝试，首个可建成功者使用。
"""
from __future__ import annotations

import re
import time
from typing import Any, Protocol

from curl_cffi import requests as cffi_requests

FROMIMAGE_BASE = "https://fromimage.ai"

# fromimage 验证码：`618068 is your FromImage AI email verification code`
CODE_RE = re.compile(r"(\b\d{6}\b).{0,40}(?:FromImage|fromimage|verification)", re.IGNORECASE)


def extract_fromimage_code(text: str) -> str | None:
    if not text:
        return None
    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    m = CODE_RE.search(text)
    if m:
        return m.group(1)
    m = re.search(r"(?<![\d])\b(\d{6})\b(?![\d])", text)
    return m.group(1) if m else None


class MailboxSource(Protocol):
    session: Any
    email: str
    source_name: str

    def poll_code(self, timeout: float = 60.0) -> str | None: ...
    def close(self) -> None: ...


class TempMailSource:
    """temp-mail.org 一次性邮箱（免费，本机家庭 IP 实测可用；数据中心 IP 可能被 CF 403）。"""

    source_name = "temp-mail"
    TEMP_MAIL_BASE = "https://web2.temp-mail.org"

    def __init__(self, proxy: str = "", fingerprint: dict | None = None) -> None:
        self.proxy = proxy
        self.email = ""
        self.token = ""
        fp = fingerprint or {}
        from services.fomimage_fingerprint import fingerprint_headers

        self.session = cffi_requests.Session(impersonate=str(fp.get("impersonate") or "chrome131"))
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.session.headers.update({**fingerprint_headers(fp), "Origin": "https://temp-mail.org"})

    def create(self) -> str:
        resp = self.session.post(
            self.TEMP_MAIL_BASE + "/mailbox",
            json={},
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"temp-mail 创建邮箱失败: {resp.status_code}")
        data = resp.json()
        self.token = str(data.get("token") or "")
        self.email = str(data.get("mailbox") or "")
        if not self.token or "@" not in self.email:
            raise RuntimeError(f"temp-mail 返回异常: {resp.text[:200]}")
        return self.email

    def poll_code(self, timeout: float = 60.0) -> str | None:
        if not self.token:
            return None
        deadline = time.time() + timeout
        seen: set[str] = set()
        while time.time() < deadline:
            try:
                resp = self.session.get(
                    self.TEMP_MAIL_BASE + "/messages",
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=20,
                )
                if resp.status_code == 200:
                    messages = resp.json().get("messages") or []
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
            except Exception:
                pass
            time.sleep(4)
        return None

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass


class LuckMailSource:
    """luckmail 付费购买邮箱（服务器可达，唯一能规模化供给的邮箱源）。"""

    source_name = "luckmail"

    def __init__(
        self,
        cfg: Any,
        proxy: str = "",
        fingerprint: dict | None = None,
    ) -> None:
        self.proxy = proxy
        self.email = ""
        self._token = ""
        self._cfg = cfg
        from services.registration.grok.luckmail import LuckMailClient, LuckMailError

        self._client = LuckMailClient(
            base_url=cfg.luckmail_base_url,
            api_key=cfg.luckmail_api_key,
            api_secret=cfg.luckmail_api_secret,
        )
        self._LuckMailError = LuckMailError
        fp = fingerprint or {}
        from services.fomimage_fingerprint import fingerprint_headers

        self.session = cffi_requests.Session(impersonate=str(fp.get("impersonate") or "chrome131"))
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.session.headers.update({**fingerprint_headers(fp), "Origin": FROMIMAGE_BASE})

    def create(self) -> str:
        purchases = self._client.purchase_emails(
            project_code=self._cfg.luckmail_project_code,
            quantity=1,
            email_type=self._cfg.luckmail_email_type or None,
            domain=self._cfg.luckmail_domain or None,
        )
        if not purchases:
            raise RuntimeError("luckmail 购买邮箱返回空")
        purchase = purchases[0] if isinstance(purchases[0], dict) else {}
        self.email = str(purchase.get("email_address") or "").strip()
        self._token = str(purchase.get("token") or "").strip()
        if not self.email or not self._token:
            raise RuntimeError(f"luckmail 购买返回异常: {purchase}")
        return self.email

    def poll_code(self, timeout: float = 60.0) -> str | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data = self._client.get_token_code(self._token)
                code = extract_fromimage_code(
                    f"{data.get('verification_code', '')} {data.get('message', '')}"
                )
                if code:
                    return code
                mails = self._client.get_token_mails(self._token)
                for mail in mails.get("mails") or []:
                    if isinstance(mail, dict):
                        text = f"{mail.get('subject', '')} {mail.get('body', '')} {mail.get('body_preview', '')}"
                        code = extract_fromimage_code(text)
                        if code:
                            return code
            except Exception:
                pass
            time.sleep(4)
        return None

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass


class GPTMailSource:
    """gptmail 免费邮箱（备用；服务器实测 428，本机可建）。"""

    source_name = "gptmail"
    BASE = "https://mail.chatgpt.org.uk"

    def __init__(self, proxy: str = "", fingerprint: dict | None = None) -> None:
        self.proxy = proxy
        self.email = ""
        self._token = ""
        fp = fingerprint or {}
        from services.fomimage_fingerprint import fingerprint_headers

        self.session = cffi_requests.Session(impersonate=str(fp.get("impersonate") or "chrome131"))
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.session.headers.update({**fingerprint_headers(fp), "Accept": "application/json"})

    def create(self) -> str:
        resp = self.session.get(self.BASE + "/api/domains/public", timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"gptmail 获取域名失败: {resp.status_code}")
        data = resp.json()
        domains = (data.get("data") or {}).get("domains") or []
        active = [d for d in domains if isinstance(d, dict) and d.get("is_active")]
        if not active:
            raise RuntimeError("gptmail 无活跃域名")
        import random
        import string as _string

        domain = active[random.randrange(len(active))]["domain_name"]
        prefix = "".join(random.choices(_string.ascii_lowercase + _string.digits, k=10))
        self.email = f"{prefix}@{domain}"
        resp = self.session.post(
            self.BASE + "/api/inbox-token",
            json={"email": self.email},
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"gptmail inbox-token 失败: {resp.status_code}")
        self._token = str(((resp.json() or {}).get("auth") or {}).get("token") or "")
        if not self._token:
            raise RuntimeError("gptmail 未获取 inbox token")
        return self.email

    def poll_code(self, timeout: float = 60.0) -> str | None:
        from urllib.parse import quote

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = self.session.get(
                    self.BASE + f"/api/emails?email={quote(self.email)}",
                    headers={"x-inbox-token": self._token},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    emails = (data.get("data") or {}).get("emails") or data.get("data") or []
                    if isinstance(emails, dict):
                        emails = [emails]
                    for m in emails if isinstance(emails, list) else []:
                        if not isinstance(m, dict):
                            continue
                        text = f"{m.get('subject', '')} {m.get('text', '')} {m.get('html', '')} {m.get('body', '')}"
                        code = extract_fromimage_code(text)
                        if code:
                            return code
            except Exception:
                pass
            time.sleep(4)
        return None

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass


def create_mailbox_source(
    sources: list[str],
    cfg: Any,
    proxy: str = "",
    fingerprint: dict | None = None,
) -> MailboxSource:
    """按优先级创建第一个可用的邮箱源。全部失败抛 RuntimeError。"""
    order = [s.strip().lower() for s in (sources or ["temp-mail"]) if s.strip()]
    last_err = ""
    for name in order:
        try:
            if name == "temp-mail":
                src: MailboxSource = TempMailSource(proxy=proxy, fingerprint=fingerprint)
            elif name == "luckmail":
                if not (cfg.luckmail_api_key):
                    continue
                src = LuckMailSource(cfg, proxy=proxy, fingerprint=fingerprint)
            elif name == "gptmail":
                src = GPTMailSource(proxy=proxy, fingerprint=fingerprint)
            else:
                continue
            src.create()
            return src
        except Exception as exc:  # noqa: BLE001 - 该源失败换下一个
            last_err = f"{type(exc).__name__}: {str(exc)[:160]}"
            try:
                src.close()  # type: ignore[name-defined]
            except Exception:
                pass
    raise RuntimeError(f"所有邮箱源均不可用: {last_err}")
