"""Grok 注册引擎（移植 grok-register/grok.py 精简）。

关键差异 vs 源项目：
- 配置驱动：代理 / YesCaptcha key / 邮箱均来自 `registration` 配置段，不读硬编码
  常量与环境变量；代理组复用 chatgpt2api 的 `proxy_groups`。
- 无全局可变状态 / 无键盘输入：每次 `register()` 是自包含的一次批量注册。
- 结构化返回：不写 keys/grok.txt，由 coordinator 直接写入 chatgpt2api 号池。
- 依赖：curl_cffi（主项目已依赖）。yescaptcha 仅启用时实例化。

流程（单号）：创建邮箱 → gRPC 发送验证码 → 轮询收件取码 → YesCaptcha 解 Turnstile →
提交 /sign-up → 提取 SSO。失败即换号，单个失败不阻断整批。
"""
from __future__ import annotations

import random
import re
import string
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional
from urllib.parse import urljoin

import requests as std_requests
from curl_cffi import requests as cffi_requests

from services.registration.config import GrokRegistrationConfig
from services.registration.grok.captcha import TurnstileService
from services.registration.grok.email_service import EmailService, extract_grok_code

SITE_URL = "https://accounts.x.ai"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
)
DEFAULT_SITE_KEY = "0x4AAAAAAAhr9JGVDZbrZOo0"
DEFAULT_STATE_TREE = (
    "%5B%22%22%2C%7B%22children%22%3A%5B%22(app)%22%2C%7B%22children%22%3A%5B%22(auth)%22%2C%7B%22children%22%3A%5B%22sign-up%22%2C"
    "%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2Fsign-up%22%2C%22refresh%22%5D%7D%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%2Ctrue%5D"
)


def _generate_random_name() -> str:
    length = random.randint(4, 6)
    return random.choice(string.ascii_uppercase) + "".join(
        random.choice(string.ascii_lowercase) for _ in range(length - 1)
    )


def _generate_random_string(length: int = 15) -> str:
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))


# ── gRPC-web 协议编码（与源实现一致）───────────────────────────────

def _encode_grpc_message(field_id: int, string_value: str) -> bytes:
    key = (field_id << 3) | 2
    value_bytes = string_value.encode("utf-8")
    payload = struct.pack("B", key) + struct.pack("B", len(value_bytes)) + value_bytes
    return b"\x00" + struct.pack(">I", len(payload)) + payload


def _encode_grpc_message_verify(email: str, code: str) -> bytes:
    p1 = struct.pack("B", (1 << 3) | 2) + struct.pack("B", len(email)) + email.encode("utf-8")
    p2 = struct.pack("B", (2 << 3) | 2) + struct.pack("B", len(code)) + code.encode("utf-8")
    payload = p1 + p2
    return b"\x00" + struct.pack(">I", len(payload)) + payload


def _grpc_headers() -> dict[str, str]:
    return {
        "content-type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "x-user-agent": "connect-es/2.1.1",
        "origin": SITE_URL,
        "referer": f"{SITE_URL}/sign-up?redirect=grok-com",
    }


class GrokRegisterEngine:
    """批量注册引擎。每次 `register()` 自包含：discover（或缓存）→ 逐号注册。"""

    def __init__(self, cfg: GrokRegistrationConfig) -> None:
        self.cfg = cfg
        self._discovered: dict[str, Any] | None = None
        self._turnstile: TurnstileService | None = None

    # ── 动态参数发现 ───────────────────────────────────────────────

    def discover(self, proxy: str = "", force: bool = False) -> dict[str, Any]:
        """抓取 /sign-up 页面 + JS 扫描，返回 {site_key, state_tree, action_id}。
        失败时回退默认 site_key/state_tree（action_id 为 None 则后续注册会失败）。"""
        if self._discovered is not None and not force:
            return self._discovered
        cfg: dict[str, Any] = {"site_key": DEFAULT_SITE_KEY, "state_tree": DEFAULT_STATE_TREE, "action_id": None}
        try:
            with cffi_requests.Session(impersonate="chrome120", proxies=_proxies(proxy)) as session:
                html = session.get(f"{SITE_URL}/sign-up", timeout=15).text
            key_match = re.search(r'sitekey":"(0x4[a-zA-Z0-9_-]+)"', html)
            if key_match:
                cfg["site_key"] = key_match.group(1)
            tree_match = re.search(r'next-router-state-tree":"([^"]+)"', html)
            if tree_match:
                cfg["state_tree"] = tree_match.group(1)
            js_urls = list(
                dict.fromkeys(
                    urljoin(f"{SITE_URL}/sign-up", m.group(0))
                    for m in re.finditer(r"/_next/static/chunks/[^\"'\s>]+\.js", html)
                )
            )
            cfg["action_id"] = self._scan_action_id(js_urls, proxy)
        except Exception:
            pass
        self._discovered = cfg
        return cfg

    @staticmethod
    def _scan_action_id(js_urls: list[str], proxy: str = "") -> Optional[str]:
        """并发扫描 JS 文件，找 `7f` 开头的 41 位 hex Action ID。"""
        if not js_urls:
            return None
        proxies = _proxies(proxy)

        def _fetch(url: str) -> Optional[str]:
            try:
                js = std_requests.get(url, proxies=proxies, timeout=10).text
                m = re.search(r"7f[a-fA-F0-9]{40}", js)
                if m:
                    return m.group(0)
            except Exception:
                pass
            return None

        try:
            with ThreadPoolExecutor(max_workers=10) as pool:
                for result in pool.map(_fetch, js_urls):
                    if result:
                        pool.shutdown(wait=False, cancel_futures=True)
                        return result
        except Exception:
            pass
        return None

    # ── Turnstile ──────────────────────────────────────────────────

    def _solve_turnstile(self, site_key: str, max_attempts: int = 3) -> Optional[str]:
        if self._turnstile is None:
            self._turnstile = TurnstileService(self.cfg.yescaptcha_key)
        for _ in range(max_attempts):
            try:
                task_id = self._turnstile.create_task(SITE_URL, site_key)
                token = self._turnstile.get_response(task_id)
                if token and token != "CAPTCHA_FAIL":
                    return token
            except Exception:
                pass
            time.sleep(2)
        return None

    # ── 单号注册 ───────────────────────────────────────────────────

    def _send_email_code(self, session, email: str) -> bool:
        try:
            url = f"{SITE_URL}/auth_mgmt.AuthManagement/CreateEmailValidationCode"
            resp = session.post(
                url,
                data=_encode_grpc_message(1, email),
                headers=_grpc_headers(),
                timeout=15,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def register_one(self, email_service: EmailService, proxy: str = "") -> Optional[dict[str, Any]]:
        """注册单个账号。成功返回 {email, password, sso}，失败返回 None（邮箱已归还/消耗）。"""
        token_like, email = email_service.create_email(proxy)
        if not email:
            return None
        password = _generate_random_string()
        discovered = self.discover(proxy)
        action_id = discovered.get("action_id")
        try:
            # 预热连接
            with cffi_requests.Session(impersonate="chrome120", proxies=_proxies(proxy)) as session:
                try:
                    session.get(SITE_URL, timeout=10)
                except Exception:
                    pass

                # Step 1: 发送验证码
                if not self._send_email_code(session, email):
                    email_service.release_email(email)
                    return None

                # Step 2: 轮询收件取码（12 次 × 5s）
                verify_code: Optional[str] = None
                for _ in range(12):
                    time.sleep(5)
                    content = email_service.fetch_first_email(token_like, proxy)
                    code = extract_grok_code(content)
                    if code:
                        verify_code = code
                        break
                if not verify_code:
                    email_service.release_email(email)
                    return None

                # Step 3: 先解 Turnstile（最耗时），避免验证码过期
                ts_token = self._solve_turnstile(discovered.get("site_key", DEFAULT_SITE_KEY))
                if not ts_token:
                    email_service.release_email(email)
                    return None

                # Step 4: 提交注册
                headers = {
                    "user-agent": USER_AGENT,
                    "accept": "text/x-component",
                    "content-type": "text/plain;charset=UTF-8",
                    "origin": SITE_URL,
                    "referer": f"{SITE_URL}/sign-up",
                    "cookie": f"__cf_bm={session.cookies.get('__cf_bm', '')}",
                    "next-router-state-tree": discovered.get("state_tree", DEFAULT_STATE_TREE),
                }
                if action_id:
                    headers["next-action"] = action_id
                payload = [
                    {
                        "emailValidationCode": verify_code,
                        "createUserAndSessionRequest": {
                            "email": email,
                            "givenName": _generate_random_name(),
                            "familyName": _generate_random_name(),
                            "clearTextPassword": password,
                            "tosAcceptedVersion": "$undefined",
                        },
                        "turnstileToken": ts_token,
                        "promptOnDuplicateEmail": True,
                    }
                ]
                resp = session.post(f"{SITE_URL}/sign-up", json=payload, headers=headers, timeout=30)
                if resp.status_code != 200:
                    email_service.release_email(email)
                    return None

                sso = self._extract_sso(session, resp)
                if not sso:
                    email_service.release_email(email)
                    return None

                email_service.consume_email(email)
                return {"email": email, "password": password, "sso": sso}
        except Exception:
            email_service.release_email(email)
            return None

    @staticmethod
    def _extract_sso(session, resp) -> Optional[str]:
        """从响应/会话 cookie 提取 SSO JWT（多方式兜底，与源实现一致）。"""
        sso = None
        # 方式1: set-cookie?q= URL（老格式），GET 后从 cookie 取
        for pat in [
            r"(https://[^\"\s]+set-cookie\?q=[^:\"\s]+)",
            r"(https://[^\"\s]+set-cookie[^\"\s]+)",
        ]:
            m = re.search(pat, resp.text)
            if m:
                sso_url = m.group(0).rstrip("1:").rstrip("2:").rstrip("3:")
                try:
                    session.get(sso_url, allow_redirects=True, timeout=15)
                except Exception:
                    pass
                sso = session.cookies.get("sso")
                if sso:
                    break
        # 方式2: 直接从 response cookies
        if not sso:
            sso = session.cookies.get("sso")
        # 方式3: Set-Cookie header
        if not sso:
            set_cookie = resp.headers.get("set-cookie", "")
            for c in set_cookie.split(","):
                if "sso=" in c:
                    sso_val = c.split("sso=")[1].split(";")[0]
                    if sso_val:
                        sso = sso_val
                        break
        return sso if sso else None

    # ── 批量注册 ───────────────────────────────────────────────────

    def register(self, email_service: EmailService, count: int, proxy: str = "") -> dict[str, Any]:
        """注册 count 个账号，逐个串行（避免同 IP 批量并发被风控）。

        成功账号直接写入号池（provider=grok）；返回 {success, failed, items, errors}。
        """
        # 先做一次 discover（成功则缓存；失败也不阻断，register_one 会再取缓存/默认）
        self.discover(proxy, force=False)
        success = 0
        failed = 0
        items: list[dict[str, Any]] = []
        errors: list[str] = []
        for _ in range(max(1, count)):
            time.sleep(random.uniform(0.5, 2.0))  # 错峰
            result = self.register_one(email_service, proxy)
            if result:
                success += 1
                items.append(result)
            else:
                failed += 1
                errors.append("注册失败（邮箱/验证码/Turnstile/提交任一环节失败）")
        return {"success": success, "failed": failed, "items": items, "errors": errors}


def _proxies(proxy: str = "") -> dict[str, str] | None:
    """把代理 URL 转成 curl_cffi/requests 的 proxies 字典。空代理返回 None（直连）。"""
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def resolve_proxy_for_group(proxy_group_id: str) -> str:
    """复用 chatgpt2api `proxy_groups`：按 id 取组内第一个 enabled 节点的 url。

    留空/未命中返回 ""（直连）。多个节点时可手动扩展为轮换（当前取第一个）。
    """
    if not proxy_group_id:
        return ""
    try:
        from services.config import config

        groups = config.data.get("proxy_groups") or []
        for group in groups:
            if not isinstance(group, dict) or str(group.get("id") or "") != proxy_group_id:
                continue
            nodes = group.get("nodes") or []
            for node in nodes:
                if isinstance(node, dict) and node.get("enabled", True):
                    url = str(node.get("url") or "").strip()
                    if url:
                        return url
    except Exception:
        pass
    return ""
