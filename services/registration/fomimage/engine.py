"""fomimage 自动注册引擎（v2.36.0）。

流程（单号）：
    生成随机指纹（一号一指纹）→ 解析独立出口 IP → 建邮箱（temp-mail/luckmail/gptmail 优先级）
    → POST sign-up/email（随机不规则密码）→ 轮询收 6 位验证码 → POST verify-email
    → POST sign-in/email 拿 token + 会话 cookie → 校验积分（注册送 50）→ 返回记录

风控规避：
- 一号一指纹：`fomimage_fingerprint.random_fingerprint()`（随机 impersonate + UA + 平台）
- 一号一 IP：`resolve_account_proxy(email)`（免费代理池按邮箱粘性绑定，优先 kookeey）
- 密码不规则：随机大小写+数字+符号，长度 14-18
- 注册错峰：批号间 random sleep；并发注册（register_workers>1）时各号独立 IP/指纹
- 失败即弃：任一环节失败释放邮箱，不重试同一邮箱
"""
from __future__ import annotations

import random
import string
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from services.fomimage_fingerprint import fingerprint_headers, random_fingerprint
from services.registration.config import FomimageRegistrationConfig
from services.registration.fomimage.mail_source import MailboxSource, create_mailbox_source

FROMIMAGE_BASE = "https://fromimage.ai"
# fromimage 的 Cloudflare Turnstile sitekey（从首页 HTML turnstile_site_key 提取，2026-08-15）
FROMIMAGE_TURNSTILE_SITEKEY = "0x4AAAAAAEP4Cgtdy3L61Coz"


def _generate_random_name() -> str:
    length = random.randint(5, 8)
    return random.choice(string.ascii_uppercase) + "".join(
        random.choice(string.ascii_lowercase) for _ in range(length - 1)
    )


def _generate_random_password() -> str:
    """不规则密码：大小写+数字+符号混合，长度 14-18（避免常见弱口令）。"""
    length = random.randint(14, 18)
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    pw = list(random.choices(chars, k=length))
    # 保证至少含一个大写、一个小写、一个数字、一个特殊字符
    pw[0] = random.choice(string.ascii_uppercase)
    pw[1] = random.choice(string.ascii_lowercase)
    pw[2] = random.choice(string.digits)
    pw[3] = random.choice("!@#$%^&*")
    random.shuffle(pw)
    return "".join(pw)


def _extract_fromimage_cookies(src: MailboxSource) -> dict[str, str]:
    """提取 fromimage 会话 cookie（供生成期 FomimageBackendAPI 恢复认证态）。"""
    try:
        raw = getattr(src.session.cookies, "get_dict", lambda: {})()
        if not isinstance(raw, dict):
            return {}
        return {str(name): str(value) for name, value in raw.items() if name and value}
    except Exception:
        return {}


def _probe_proxy(proxy_url: str, timeout: float = 4.0) -> bool:
    """探测代理是否可用（能连通 temp-mail 域即可，status<500 视为连通）。

    免费代理死代理多，注册前探测避免把整个注册流程耗在死代理上。
    """
    if not proxy_url:
        return False
    try:
        from curl_cffi import requests as cffi_requests

        session = cffi_requests.Session(impersonate="chrome131")
        try:
            session.proxies.update({"http": proxy_url, "https": proxy_url})
            resp = session.get("https://web2.temp-mail.org/options", timeout=timeout)
            return resp.status_code < 500
        finally:
            try:
                session.close()
            except Exception:
                pass
    except Exception:
        return False


class FomimageRegisterEngine:
    """fomimage 批量注册引擎。每次 `register()` 自包含一次批量注册。"""

    def __init__(self, cfg: FomimageRegistrationConfig) -> None:
        self.cfg = cfg

    def resolve_email_proxy(self, email: str) -> str:
        """为指定邮箱解析独立出口 IP（一号一 IP）。

        proxy_mode=auto 时从免费代理池按邮箱粘性取代理，并对该代理做连通性探测
        （免费代理健康率低，探测命中才用，不可用换下一个，最多 4 次）。
        """
        mode = self.cfg.proxy_mode
        if mode in {"off", "none", "direct"}:
            return ""
        try:
            from services.proxy_service import resolve_account_proxy

            for attempt in range(4):
                proxy = resolve_account_proxy(f"{email}#p{attempt}")
                if not proxy:
                    return ""
                if _probe_proxy(proxy):
                    return proxy
            return ""
        except Exception:
            return ""

    def _solve_turnstile(self, max_attempts: int = 2) -> str | None:
        """用 YesCaptcha 解 fromimage 的 CF Turnstile token（无 yescaptcha_key 返回 None）。"""
        key = self.cfg.yescaptcha_key
        if not key:
            return None
        try:
            from services.registration.grok.captcha import TurnstileService

            service = TurnstileService(key)
            for _ in range(max_attempts):
                try:
                    task_id = service.create_task(FROMIMAGE_BASE + "/sign-in", FROMIMAGE_TURNSTILE_SITEKEY)
                    token = service.get_response(task_id)
                    if token and token != "CAPTCHA_FAIL":
                        return token
                except Exception:
                    continue
        except Exception:
            return None
        return None

    def _signup_with_turnstile(self, session: Any, email: str, password: str, name: str, headers: dict[str, str]) -> Any:
        """注册：先直发；若被 CF Turnstile 拒（数据中心 IP），解 token 带 turnstileToken 重试。"""
        body = {"name": name, "email": email, "password": password}
        resp = session.post(
            FROMIMAGE_BASE + "/api/auth/sign-up/email",
            json=body,
            headers=headers,
            timeout=25,
        )
        if resp.status_code != 403 or "TURNSTILE" not in str(resp.text or ""):
            return resp
        token = self._solve_turnstile()
        if not token:
            logger_warning("fomimage Turnstile 求解失败（无 yescaptcha_key 或打码失败）", email)
            return resp
        logger_warning("fomimage Turnstile 解通过，带 token 重试", email)
        body["turnstileToken"] = token
        return session.post(
            FROMIMAGE_BASE + "/api/auth/sign-up/email",
            json=body,
            headers=headers,
            timeout=25,
        )

    def register_one(self) -> dict[str, Any] | None:
        """注册单个 fomimage 账号。成功返回记录，失败返回 None（邮箱已弃用不重试）。"""
        proxy = ""
        src: MailboxSource | None = None
        try:
            # 1) 一号一指纹 + 一号一 IP：按随机 seed_key 稳定生成（同一号全程不变）
            seed_key = f"fomimage-{random.randint(100000, 9999999)}"
            fingerprint = random_fingerprint(seed_key)
            proxy = self.resolve_email_proxy(seed_key)

            # 2) 建邮箱（temp-mail/luckmail/gptmail 优先级）
            src = create_mailbox_source(self.cfg.email_sources, self.cfg, proxy=proxy, fingerprint=fingerprint)
            email = src.email
            # fromimage 会话头（指纹 + 站点标识）
            base_headers = {
                **fingerprint_headers(fingerprint),
                "Content-Type": "application/json",
                "Origin": FROMIMAGE_BASE,
                "Referer": FROMIMAGE_BASE + "/",
            }

            # 3) fromimage 注册（被 CF Turnstile 拒时自动解 token 重试）
            password = _generate_random_password()
            name = _generate_random_name()
            signup = self._signup_with_turnstile(src.session, email, password, name, base_headers)
            if signup.status_code != 200:
                logger_warning("fomimage 注册失败", signup.status_code)
                return None

            # 4) 轮询验证码
            code = src.poll_code(timeout=float(self.cfg.poll_timeout_sec))
            if not code:
                logger_warning("fomimage 验证码超时", email)
                return None

            # 5) 验证邮箱
            verify = src.session.post(
                FROMIMAGE_BASE + "/api/auth/email-otp/verify-email",
                json={"email": email, "otp": code},
                headers=base_headers,
                timeout=25,
            )
            if verify.status_code != 200:
                logger_warning("fomimage 验证邮箱失败", verify.status_code)
                return None

            # 6) 登录拿会话 token + 会话 cookie
            signin = src.session.post(
                FROMIMAGE_BASE + "/api/auth/sign-in/email",
                json={"email": email, "password": password},
                headers=base_headers,
                timeout=25,
            )
            if signin.status_code != 200:
                logger_warning("fomimage 登录失败", signin.status_code)
                return None
            signin_data = signin.json()
            token = str(signin_data.get("token") or "")
            if not token:
                logger_warning("fomimage 登录无 token", email)
                return None
            cookies = _extract_fromimage_cookies(src)

            # 7) 查积分（注册送 50，确认可用）
            balance = self._query_balance(src, base_headers)
            return {
                "email": email,
                "password": password,
                "access_token": token,
                "cookies": cookies,
                "balance": balance,
                "proxy": proxy,
                "fingerprint": fingerprint,
            }
        except Exception as exc:  # noqa: BLE001 - 注册失败记录日志不抛
            logger_warning("fomimage 注册异常", repr(exc)[:200])
            return None
        finally:
            if src is not None:
                try:
                    src.close()
                except Exception:
                    pass

    @staticmethod
    def _query_balance(src: MailboxSource, headers: dict[str, str]) -> int:
        try:
            data = src.session.get(
                FROMIMAGE_BASE + "/api/credits/balance",
                headers=headers,
                timeout=20,
            ).json()
            inner = data.get("data") if isinstance(data, dict) else None
            return int((inner or {}).get("balance") or 0)
        except Exception:
            return 0

    def register(self, count: int) -> dict[str, Any]:
        """注册 count 个账号。

        register_workers>1 时并发（每号独立 IP/指纹，风控可控）；否则串行错峰。
        返回 {success, failed, items, errors}。
        """
        n = max(1, int(count or 1))
        workers = max(1, self.cfg.register_workers)
        if workers <= 1 or n <= 1:
            return self._register_serial(n)
        return self._register_parallel(n, workers)

    def _register_serial(self, count: int) -> dict[str, Any]:
        success = 0
        failed = 0
        items: list[dict[str, Any]] = []
        errors: list[str] = []
        for _ in range(count):
            time.sleep(random.uniform(1.0, 3.0))  # 错峰
            result = self.register_one()
            if result:
                success += 1
                items.append(result)
            else:
                failed += 1
                errors.append("注册失败（邮箱/验证码/验证/登录任一环节失败）")
        return {"success": success, "failed": failed, "items": items, "errors": errors}

    def _register_parallel(self, count: int, workers: int) -> dict[str, Any]:
        success = 0
        failed = 0
        items: list[dict[str, Any]] = []
        errors: list[str] = []
        # 各 worker 内错峰（不同 worker 独立 IP/指纹，交叉并发）
        def _one(_i: int) -> dict[str, Any] | None:
            time.sleep(random.uniform(0.5, 2.0))
            return self.register_one()

        with ThreadPoolExecutor(max_workers=min(workers, count)) as executor:
            futures = [executor.submit(_one, i) for i in range(count)]
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception:  # noqa: BLE001
                    result = None
                if result:
                    success += 1
                    items.append(result)
                else:
                    failed += 1
                    errors.append("注册失败（邮箱/验证码/验证/登录任一环节失败）")
        return {"success": success, "failed": failed, "items": items, "errors": errors}


def logger_warning(event: str, detail: Any) -> None:
    from utils.log import logger

    logger.warning({"event": event, "detail": str(detail)[:200]})


def resolve_proxy_for_registration(proxy_mode: str, email: str = "") -> str:
    """fomimage 注册代理解析入口（供 coordinator 复用）。"""
    if proxy_mode in {"off", "none", "direct"}:
        return ""
    try:
        from services.proxy_service import resolve_account_proxy

        return resolve_account_proxy(email)
    except Exception:
        return ""
