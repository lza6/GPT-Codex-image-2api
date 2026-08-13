"""Grok 注册邮箱服务（移植 grok-register/email_service.py 精简 + 集成 email_pool）。

三种邮箱来源（优先级从高到低）：
1. **池模式**（`email_pool` 非空）：使用预置邮箱凭据，取件复用 chatgpt2api 既有
   `otp_login_service` 的微软 Graph 直连链路（client_id+refresh_token → access_token →
   Mail.Read 收件箱），免第三方限流、凭证不出本机。
2. **luckmail 购买**（`email_provider=luckmail` 且池为空）：调 LuckMail 购买接口拿
   新邮箱 + token，token 轮询取验证码。
3. **gptmail 免费**（`email_provider=gptmail`）：GPTMail 免费 API（备用，注册成功率较低）。

对外接口保持与源项目一致：`create_email() -> (token_like, email)`、
`fetch_first_email(token_like) -> str|None`。
"""
from __future__ import annotations

import random
import re
import string as _string
import time
from typing import Any, Optional

import requests

from services.registration.config import GrokRegistrationConfig
from services.registration.email_pool import EmailPool
from services.registration.grok.luckmail import LuckMailClient, LuckMailError

# grok 验证码格式：`SZ0-0SW xAI confirmation code` → 正则 XXX-XXX，去横线返回 6 字符
GROK_CODE_RE = re.compile(r"\b([A-Z0-9]{3})-([A-Z0-9]{3})\b")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
)

# 微软 Graph 取件端点（与 otp_login_service 常量一致）
GRAPH_MESSAGES_URL = "https://graph.microsoft.com/v1.0/me/messages"
WAIT_MAX = 90      # 等验证码邮件总秒数
POLL_SEC = 4


def extract_grok_code(text: str) -> Optional[str]:
    """从邮件文本提取 grok 验证码（`XXX-XXX` → 6 字符）。HTML 先剥标签。"""
    if not text:
        return None
    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    m = GROK_CODE_RE.search(text)
    if m:
        return m.group(1) + m.group(2)
    return None


def _is_grok_mail(m: dict) -> bool:
    """判断是否为 x.ai 的验证码邮件（发件人或主题特征）。"""
    frm = str(m.get("from_address") or m.get("from") or "").lower()
    subj = str(m.get("subject") or "").lower()
    return (
        "x.ai" in frm
        or "xai" in subj
        or "x.ai" in subj
        or ("confirmation" in subj and "code" in subj)
        or ("verification" in subj and "code" in subj)
    )


class GPTMailInboxV2:
    """GPTMail 免费邮箱（备用）。"""

    def __init__(self, proxy: str = "") -> None:
        self.base_url = "https://mail.chatgpt.org.uk"
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.session.headers.update({"User-Agent": UA, "Accept": "application/json"})
        self.email = ""
        self.token = ""
        self._domains: list[str] = []

    def create_email(self) -> str:
        if not self._domains:
            resp = self.session.get(f"{self.base_url}/api/domains/public", timeout=15)
            if resp.status_code != 200:
                raise RuntimeError(f"GPTMail 获取域名失败: {resp.status_code}")
            data = resp.json()
            domains = (data.get("data") or {}).get("domains") or []
            self._domains = [d["domain_name"] for d in domains if d.get("is_active")]
        if not self._domains:
            raise RuntimeError("GPTMail 无活跃域名")
        prefix = "".join(random.choices(_string.ascii_lowercase + _string.digits, k=10))
        domain = random.choice(self._domains)
        self.email = f"{prefix}@{domain}"
        resp = self.session.post(
            f"{self.base_url}/api/inbox-token",
            headers={"Content-Type": "application/json"},
            json={"email": self.email},
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"GPTMail inbox-token 失败: {resp.status_code}")
        data = resp.json()
        self.token = str(((data.get("auth") or {}).get("token") or ""))
        if not self.token:
            raise RuntimeError("GPTMail 未获取到 inbox token")
        return self.email

    def fetch_first_email(self) -> Optional[str]:
        if not self.token or not self.email:
            return None
        try:
            from urllib.parse import quote

            resp = self.session.get(
                f"{self.base_url}/api/emails?email={quote(self.email)}",
                headers={"x-inbox-token": self.token},
                timeout=15,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            emails = (data.get("data") or {}).get("emails") or data.get("data") or []
            if isinstance(emails, dict):
                emails = [emails]
            for msg in emails if isinstance(emails, list) else []:
                if not isinstance(msg, dict):
                    continue
                subject = str(msg.get("subject") or "")
                body = str(msg.get("text") or msg.get("html") or msg.get("body") or "")
                text = subject + " " + body
                code = extract_grok_code(text)
                if code:
                    return text
                if len(text) > 10:
                    return text
        except Exception:
            pass
        return None


class EmailService:
    """统一邮箱服务门面：池模式优先，其次 luckmail/gptmail。"""

    def __init__(self, cfg: GrokRegistrationConfig, email_pool: EmailPool) -> None:
        self.cfg = cfg
        self.pool = email_pool
        self.provider = cfg.email_provider

    # ── 邮箱创建/取用 ──────────────────────────────────────────────

    def create_email(self, proxy: str = "") -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """获取一个可用邮箱。返回 (token_like, email)；失败返回 (None, None)。"""
        # 1) 邮箱池优先
        entry = self.pool.acquire()
        if entry:
            token_like = {"provider": "pool", "email": entry["email"], "mail_credential": entry, "client": self}
            return token_like, entry["email"]
        # 2) luckmail 购买
        if self.provider == "luckmail":
            try:
                client = LuckMailClient(
                    base_url=self.cfg.luckmail_base_url,
                    api_key=self.cfg.luckmail_api_key,
                    api_secret=self.cfg.luckmail_api_secret,
                )
                purchases = client.purchase_emails(
                    project_code=self.cfg.luckmail_project_code,
                    quantity=1,
                    email_type=self.cfg.luckmail_email_type,
                    domain=self.cfg.luckmail_domain,
                )
                if not purchases:
                    return None, None
                purchase = purchases[0] if isinstance(purchases[0], dict) else {}
                email = str(purchase.get("email_address") or "").strip()
                token = str(purchase.get("token") or "").strip()
                if not email or not token:
                    return None, None
                token_like = {"provider": "luckmail", "email": email, "token": token, "client": self}
                return token_like, email
            except (LuckMailError, ValueError):
                return None, None
        # 3) gptmail 免费兜底
        try:
            inbox = GPTMailInboxV2(proxy)
            email = inbox.create_email()
            token_like = {"provider": "gptmail", "email": email, "client": inbox}
            return token_like, email
        except Exception:
            return None, None

    # ── 收件/取验证码 ──────────────────────────────────────────────

    def fetch_first_email(self, token_like: dict[str, Any], proxy: str = "") -> Optional[str]:
        """轮询取最新验证码邮件内容；无内容返回 None（调用方负责多次轮询）。"""
        provider = str(token_like.get("provider") or "")
        if provider == "pool":
            return self._fetch_pool_code(token_like.get("mail_credential") or {}, proxy)
        if provider == "luckmail":
            return self._fetch_luckmail_code(str(token_like.get("token") or ""))
        if provider == "gptmail":
            client = token_like.get("client")
            return client.fetch_first_email() if client else None
        return None

    # 池模式：微软 Graph 直连（复用 otp_login_service 链路）
    def _fetch_pool_code(self, mail_cred: dict[str, str], proxy: str = "") -> Optional[str]:
        client_id = str(mail_cred.get("client_id") or "").strip()
        refresh_token = str(mail_cred.get("refresh_token") or "").strip()
        if not client_id or not refresh_token:
            return None
        try:
            from services.otp_login_service import otp_login_service
        except Exception:
            return None
        access_token = otp_login_service._graph_access_token(client_id, refresh_token, proxy)
        if not access_token:
            return None
        deadline = time.time() + WAIT_MAX
        seen: set[str] = set()
        while time.time() < deadline:
            try:
                mails = otp_login_service._graph_list_mails(access_token, proxy)
                for m in mails:
                    if not _is_grok_mail(m):
                        continue
                    mid = str(m.get("id") or "")
                    if mid in seen:
                        continue
                    seen.add(mid)
                    text = f"{m.get('subject', '')} {m.get('body_preview', '')}"
                    code = extract_grok_code(text)
                    if code:
                        return code
                    code = self._graph_full_body_code(access_token, mid, proxy)
                    if code:
                        return code
            except Exception:
                pass
            time.sleep(POLL_SEC)
        return None

    def _graph_full_body_code(self, access_token: str, msg_id: str, proxy: str = "") -> Optional[str]:
        try:
            proxies = {"http": proxy, "https": proxy} if proxy else None
            resp = requests.get(
                f"{GRAPH_MESSAGES_URL}/{msg_id}",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                params={"$select": "body"},
                proxies=proxies,
                timeout=30,
            )
            body = resp.json() if resp.text else {}
            content = str(((body.get("body") or {}).get("content") or ""))
            return extract_grok_code(content)
        except Exception:
            return None

    # luckmail：token 轮询验证码/邮件
    def _fetch_luckmail_code(self, token: str) -> Optional[str]:
        if not token:
            return None
        try:
            client = LuckMailClient(
                base_url=self.cfg.luckmail_base_url,
                api_key=self.cfg.luckmail_api_key,
                api_secret=self.cfg.luckmail_api_secret,
            )
            # 优先 get_token_code（最新验证码字段）
            try:
                code_data = client.get_token_code(token)
                code = extract_grok_code(
                    f"{code_data.get('verification_code', '')} {code_data.get('message', '')}"
                )
                if code:
                    return code
            except Exception:
                pass
            # 兜底：邮件列表 + 详情
            mails_data = client.get_token_mails(token)
            mails = mails_data.get("mails")
            if isinstance(mails, list) and mails:
                mail = mails[0]
                if isinstance(mail, dict):
                    text = (
                        f"{mail.get('subject', '')} {mail.get('body', '')} "
                        f"{mail.get('html_body', '')} {mail.get('body_preview', '')}"
                    )
                    code = extract_grok_code(text)
                    if code:
                        return code
            return None
        except Exception:
            return None

    # ── 池生命周期透传 ─────────────────────────────────────────────

    def release_email(self, email: str) -> None:
        self.pool.release(email)

    def consume_email(self, email: str) -> None:
        self.pool.consume(email)
