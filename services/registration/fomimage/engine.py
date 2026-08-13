"""fomimage 自动注册引擎（v2.36.0）。

流程（单号）：
    temp-mail 创建一次性邮箱 → POST sign-up/email（随机不规则密码）
    → 轮询 temp-mail /messages 取 6 位验证码 → POST verify-email → POST sign-in/email 拿 token
    → 校验积分（注册送 50）→ 返回 {email, password, access_token, balance}

风控规避：
- 每号独立出口 IP：`resolve_account_proxy(email)`（免费代理池按邮箱粘性绑定，优先 kookeey）。
- 密码不规则：随机大小写+数字+特殊字符，长度 14-18。
- 注册错峰：批号间 random sleep 1-3s；单号流程内各步骤稳定节拍。
- 失败即弃：任一环节失败释放邮箱，不重试同一邮箱。
"""
from __future__ import annotations

import random
import string
import time
from typing import Any

from services.registration.config import FomimageRegistrationConfig
from services.registration.fomimage.temp_mail import TempMailInbox

FROMIMAGE_BASE = "https://fromimage.ai"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


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


def _proxies(proxy: str = "") -> dict[str, str] | None:
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _extract_fromimage_cookies(inbox: Any) -> dict[str, str]:
    """提取 fromimage 会话 cookie（供生成期 FomimageBackendAPI 恢复认证态）。"""
    try:
        jar = inbox._session.cookies
        raw = getattr(jar, "get_dict", lambda: {})()
        if not isinstance(raw, dict):
            return {}
        return {str(name): str(value) for name, value in raw.items() if name and value}
    except Exception:
        return {}


class FomimageRegisterEngine:
    """fomimage 批量注册引擎。每次 `register()` 自包含一次批量注册。"""

    def __init__(self, cfg: FomimageRegistrationConfig) -> None:
        self.cfg = cfg

    def resolve_email_proxy(self, email: str) -> str:
        """为指定邮箱解析独立出口 IP。proxy_mode=auto 时走 resolve_account_proxy。
        返回代理 URL 或 ""（直连）。
        """
        mode = self.cfg.proxy_mode
        if mode in {"off", "none", "direct"}:
            return ""
        try:
            from services.proxy_service import resolve_account_proxy

            return resolve_account_proxy(email)
        except Exception:
            return ""

    def register_one(self) -> dict[str, Any] | None:
        """注册单个 fomimage 账号。成功返回记录，失败返回 None（邮箱已弃用不重试）。"""
        proxy = ""
        inbox: TempMailInbox | None = None
        try:
            # 1) 先按随机粘性 key 解析独立出口 IP（每个邮箱一个独立代理，用完即弃）
            stub_key = f"fomimage-{random.randint(100000, 999999)}"
            proxy = self.resolve_email_proxy(stub_key)
            inbox = TempMailInbox(proxy=proxy)
            email = inbox.create()

            # 2) fromimage 注册
            password = _generate_random_password()
            name = _generate_random_name()
            headers = {
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Origin": FROMIMAGE_BASE,
                "Referer": FROMIMAGE_BASE + "/",
            }
            signup = inbox._session.post(
                FROMIMAGE_BASE + "/api/auth/sign-up/email",
                json={"name": name, "email": email, "password": password},
                headers=headers,
                timeout=25,
            )
            if signup.status_code != 200:
                logger_warning("fomimage 注册失败", signup.status_code)
                return None

            # 3) 轮询验证码
            code = inbox.poll_code(timeout=float(self.cfg.poll_timeout_sec))
            if not code:
                logger_warning("fomimage 验证码超时", email)
                return None

            # 4) 验证邮箱
            verify = inbox._session.post(
                FROMIMAGE_BASE + "/api/auth/email-otp/verify-email",
                json={"email": email, "otp": code},
                headers=headers,
                timeout=25,
            )
            if verify.status_code != 200:
                logger_warning("fomimage 验证邮箱失败", verify.status_code)
                return None

            # 5) 登录拿会话 token + 会话 cookie（fromimage 认证靠 cookie，token 仅作标识）
            signin = inbox._session.post(
                FROMIMAGE_BASE + "/api/auth/sign-in/email",
                json={"email": email, "password": password},
                headers=headers,
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
            # 提取 fromimage 会话 cookie（业务接口凭 cookie 认证，与账号记录一并入池）
            cookies = _extract_fromimage_cookies(inbox)

            # 6) 查积分（注册送 50，确认可用）
            balance = self._query_balance(inbox, proxy)
            return {
                "email": email,
                "password": password,
                "access_token": token,
                "cookies": cookies,
                "balance": balance,
                "proxy": proxy,
            }
        except Exception as exc:  # noqa: BLE001 - 注册失败记录日志不抛
            logger_warning("fomimage 注册异常", repr(exc)[:200])
            return None
        finally:
            if inbox is not None:
                try:
                    inbox.close()
                except Exception:
                    pass

    @staticmethod
    def _query_balance(inbox: TempMailInbox, proxy: str = "") -> int:
        try:
            data = inbox._session.get(
                FROMIMAGE_BASE + "/api/credits/balance",
                headers={"User-Agent": USER_AGENT, "Origin": FROMIMAGE_BASE, "Referer": FROMIMAGE_BASE + "/"},
                timeout=20,
            ).json()
            inner = data.get("data") if isinstance(data, dict) else None
            return int((inner or {}).get("balance") or 0)
        except Exception:
            return 0

    def register(self, count: int) -> dict[str, Any]:
        """注册 count 个账号，逐个串行（避免同链路并发被风控）。

        返回 {success, failed, items, errors}。
        """
        success = 0
        failed = 0
        items: list[dict[str, Any]] = []
        errors: list[str] = []
        for _ in range(max(1, count)):
            time.sleep(random.uniform(1.0, 3.0))  # 错峰
            result = self.register_one()
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
