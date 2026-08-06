"""邮箱验证码登录服务（纯 HTTP 链路 + 微软 Graph 取件(优先)/98faka(兜底) + cf_solver CF 清除）。

`_login_with_password` 走 password/verify，遇 OpenAI 风控要求邮箱 OTP 就返回
`need_verification_code`。本服务改走 email-otp 流程：
  1. （可选）调 cf_solver GET /clearance?url=auth.openai.com 拿 cf_clearance + cookies
     cf_solver 用 Camoufox 过 Cloudflare WAF，返回 cf_clearance/__cf_bm/_cfuvid + UA
  2. PKCE 构造 authorize URL（login_hint=邮箱）
  3. GET authorize → 触发 OpenAI 发 OTP 验证码到邮箱
  4. 取最新 OTP 邮件正文：优先自建微软 Graph 直连（client_id+refresh_token 换 access_token
     读收件箱，国内可直连、凭证不出本机、免第三方限流），token 换不出才回退 98faka 中转
  5. 正则提取 6 位数字
  6. POST /api/accounts/email-otp/validate 提交
  7. 从 continue_url 拿 code → /api/accounts/oauth/token 换 token 三件套

98faka 取件契约（来自参考材料"微软邮箱和卡密以及使用教程.txt"）：
  POST https://app.98faka.top/api/emails
    body={email,password,client_id,refresh_token,folder=inbox}
    → {code:200, data:[{id,subject,body_preview,received_time,from_address}]}
  POST https://app.98faka.top/api/email-body
    body={email,message_id,client_id,refresh_token}
    → {body_html, body_preview}

cf_solver 契约（来自 cf_solver/api_server.py）：
  GET http://127.0.0.1:8001/clearance?url=<URL>&timeout=30
  → 异步，返回 task_id；轮询结果拿 {status:success, cf_clearance, user_agent, cookies}

代理走项目既有 proxy_settings（支持 v2ray 10808）。

设计原则（对照参考项目 revive_import.py，纯 HTTP 化）：
  * 每账号只触发一次 OTP、只取"触发后最新"验证码、只提交一次（防 max_check_attempts 限流）
  * 失败即换下一个，绝不在同一账号上反复重试
  * 返回结构对齐 `_login_with_password`：{ok, access_token, refresh_token, id_token, email, source_type}
"""
from __future__ import annotations

import re
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from curl_cffi import requests

from services.openai_oauth import (
    auth_base,
    common_headers,
    platform_auth0_client,
    platform_base,
    platform_oauth_audience,
    platform_oauth_client_id,
    platform_oauth_redirect_uri,
    sec_ch_ua,
    user_agent,
)
from services.proxy_service import proxy_settings
from utils.pkce import generate_pkce
from utils.sentinel import build_sentinel_token


class OTPLoginError(Exception):
    """OTP 登录流程中的可预期错误。"""


# 98faka 邮箱中转 API（参考材料证实契约，比 91kami 更稳定）
MAIL_API_BASE = "https://app.98faka.top"
# 微软 Graph 直连取件（优先；契约经 scripts/test_outlook_token_mailbox.py 实测验证）
GRAPH_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_MESSAGES_URL = "https://graph.microsoft.com/v1.0/me/messages"
GRAPH_SCOPE = "offline_access https://graph.microsoft.com/Mail.Read"
# cf_solver 本地服务（Camoufox 过 Cloudflare WAF）
CF_SOLVER_BASE = "http://127.0.0.1:8001"
OTP_WAIT_MAX = 90          # 等验证码邮件秒数
OTP_POLL_SEC = 4
OTP_CODE_RE = re.compile(r"\b(\d{6})\b")
OTP_KEYWORD_RE = re.compile(r"(?:code|码|mã|verification)[\s:：\-]{0,4}(\d{6})", re.I)


class OTPLoginService:
    """邮箱验证码登录：cf_solver清CF → authorize → OTP → 取码 → validate → exchange。"""

    def __init__(self, cf_solver_url: str = "") -> None:
        self.cf_solver_url = str(cf_solver_url or CF_SOLVER_BASE).strip().rstrip("/")

    def login(
        self,
        email: str,
        password: str,
        *,
        mail_credential: dict[str, str] | None = None,
        proxy_url: str = "",
        use_cf_solver: bool = True,
    ) -> dict[str, Any]:
        """对单个账号走邮箱验证码登录，返回 token 三件套。

        Args:
            email: 账号邮箱（同时是 OpenAI 登录邮箱 + 收件邮箱）
            password: 账号密码（email-otp 流程不提交密码，保留对齐返回结构）
            mail_credential: 取件凭证，需含 client_id + refresh_token（微软 MSAL）。
                             为空时返回 need_mail_credential。
            proxy_url: 可选代理覆盖（如 v2ray http://127.0.0.1:10808）
            use_cf_solver: 是否调 cf_solver 清除 CF（True 且服务可用时）

        Returns:
            {ok, access_token, refresh_token, id_token, email, source_type} 或
            {ok: False, error, detail}
        """
        email = str(email or "").strip()
        if not email:
            return {"ok": False, "error": "missing_email"}
        if not mail_credential or not mail_credential.get("client_id") or not mail_credential.get("refresh_token"):
            return {"ok": False, "error": "need_mail_credential", "detail": {"email": email}}

        session_kwargs = proxy_settings.build_session_kwargs(impersonate="chrome", verify=False)
        if proxy_url:
            session_kwargs["proxy"] = proxy_url
        session = requests.Session(**session_kwargs)
        device_id = str(uuid.uuid4())

        try:
            # ① 可选：cf_solver 清除 auth.openai.com 的 CF（Camoufox 过 WAF）
            cf_cookies = ""
            if use_cf_solver and self.cf_solver_url:
                cf_cookies = self._get_cf_clearance(f"{auth_base}/")

            # ② PKCE + authorize 触发 OpenAI 发 OTP
            code_verifier, code_challenge = generate_pkce()
            state = f"{secrets.token_hex(16)}.{secrets.token_urlsafe(16)}"
            nonce = secrets.token_urlsafe(32)
            session.cookies.set("oai-did", device_id, domain=".auth.openai.com")
            if cf_cookies:
                # cf_solver 返回的 cookie header 注入 session
                for pair in cf_cookies.split(";"):
                    if "=" in pair:
                        k, v = pair.strip().split("=", 1)
                        session.cookies.set(k.strip(), v.strip(), domain=".openai.com")
            params = {
                "issuer": auth_base,
                "client_id": platform_oauth_client_id,
                "audience": platform_oauth_audience,
                "redirect_uri": platform_oauth_redirect_uri,
                "device_id": device_id,
                "screen_hint": "login_or_signup",
                "max_age": "0",
                "login_hint": email,
                "scope": "openid profile email offline_access",
                "response_type": "code",
                "response_mode": "query",
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "auth0Client": platform_auth0_client,
            }
            authorize_url = f"{auth_base}/api/accounts/authorize?{urlencode(params)}"
            otp_trigger_at = datetime.now(UTC)
            resp = session.get(
                authorize_url,
                headers={
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "user-agent": user_agent,
                    "referer": f"{platform_base}/",
                },
                allow_redirects=True,
                timeout=30,
            )
            final_url = str(resp.url)
            # authorize 失败检测（payload error）
            if "/error" in final_url and "payload=" in final_url:
                return {"ok": False, "error": "authorize_error", "detail": {"url": final_url[:300]}}
            # 直接拿到 code（无需 OTP，罕见但处理）
            if "platform.openai.com/auth/callback" in final_url and "code=" in final_url:
                code = str((parse_qs(urlparse(final_url).query).get("code") or [""])[0]).strip()
                if code:
                    tokens = self._exchange_code(session, code, code_verifier)
                    tokens.update({"ok": True, "email": email, "source_type": "otp"})
                    return tokens

            # ②.5 passwordless 账号 authorize 后停在密码页 → 显式触发发码
            if "/log-in" in final_url:
                if not self._trigger_passwordless_otp(session, device_id):
                    return {"ok": False, "error": "send_otp_failed", "detail": {"email": email}}
                otp_trigger_at = datetime.now(UTC)  # 取件基准重置为发码时刻

            # ③ 取最新 OTP 邮件 → 提取 6 位数字
            code_digits = self._fetch_otp_code(mail_credential, otp_trigger_at, session_kwargs.get("proxy", ""))
            if not code_digits:
                return {"ok": False, "error": "otp_timeout", "detail": {"email": email, "wait_secs": OTP_WAIT_MAX}}

            # ④ sentinel + POST /api/accounts/email-otp/validate
            try:
                sentinel_val, oai_sc_val = build_sentinel_token(session, device_id, "email_otp_verification")
            except Exception as exc:
                return {"ok": False, "error": f"sentinel_failed:{type(exc).__name__}", "detail": {"message": str(exc)}}

            validate_headers = {
                **common_headers,
                "content-type": "application/json",
                "origin": auth_base,
                "referer": f"{auth_base}/email-verification",
                "oai-device-id": device_id,
                "openai-sentinel-token": sentinel_val,
                "user-agent": user_agent,
                "sec-ch-ua": sec_ch_ua,
            }
            if oai_sc_val:
                session.cookies.set("oai-sc", oai_sc_val, domain=".openai.com")

            validate_resp = session.post(
                f"{auth_base}/api/accounts/email-otp/validate",
                headers=validate_headers,
                json={"code": code_digits},
                timeout=30,
            )
            validate_data = {}
            try:
                validate_data = validate_resp.json() if validate_resp.text else {}
            except Exception:
                pass
            if validate_resp.status_code != 200:
                if "max_check_attempts" in str(validate_data).lower():
                    return {"ok": False, "error": "otp_max_attempts", "detail": validate_data}
                return {"ok": False, "error": f"otp_validate_failed_{validate_resp.status_code}", "detail": validate_data}

            continue_url = str(validate_data.get("continue_url") or "").strip()
            auth_code = ""
            if continue_url:
                auth_code = str((parse_qs(urlparse(continue_url).query).get("code") or [""])[0]).strip()
            if not auth_code:
                return {"ok": False, "error": "no_auth_code_after_otp", "detail": validate_data}

            # ⑤ 换 token 三件套
            tokens = self._exchange_code(session, auth_code, code_verifier)
            tokens.update({"ok": True, "email": email, "source_type": "otp"})
            return tokens
        except Exception as exc:
            return {"ok": False, "error": f"otp_login_exception:{type(exc).__name__}", "detail": {"message": str(exc)}}
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _trigger_passwordless_otp(self, session, device_id: str) -> bool:
        """对已设密码的账号（authorize 后停在 log-in/password），POST passwordless/send-otp 触发发码。

        passwordless 注册账号无可用登录密码，authorize 后会停在密码输入页，
        必须显式调此端点让 OpenAI 发邮箱验证码（参考注册项目 revive_protocol.py）。
        空 body 即可（会话 cookie 已标识账号），返回是否成功触发。
        """
        try:
            sentinel, oai_sc = build_sentinel_token(session, device_id, "passwordless_send_otp")
            if oai_sc:
                session.cookies.set("oai-sc", oai_sc, domain=".openai.com")
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "referer": f"{auth_base}/log-in/password",
                "user-agent": user_agent,
                "oai-device-id": device_id,
                "openai-sentinel-token": sentinel,
            }
            resp = session.post(
                f"{auth_base}/api/accounts/passwordless/send-otp",
                json={}, headers=headers, timeout=30,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def _get_cf_clearance(self, url: str, timeout: int = 30) -> str:
        """调 cf_solver GET /clearance 拿 cf_clearance + 全 cookie header。

        cf_solver 契约（来自 cf_solver/api_server.py _solve_clearance）：
          GET /clearance?url=<URL>&timeout=30 → 异步 task_id
          轮询结果：{status:success, cf_clearance, user_agent, cookies(cookie_header str)}

        失败返回空串（不阻塞主流程，让纯 HTTP 自己试）。
        """
        try:
            # cf_solver 的 /clearance 是异步的：先 GET 拿 task_id，再轮询
            r = requests.get(
                f"{self.cf_solver_url}/clearance",
                params={"url": url, "timeout": timeout},
                timeout=timeout + 10,
            )
            data = r.json() if r.text else {}
            # 如果是同步返回结果
            if data.get("status") == "success":
                return str(data.get("cookies") or "")
            # 异步 task_id 轮询
            task_id = data.get("task_id") or data.get("id")
            if not task_id:
                return ""
            deadline = time.time() + timeout + 10
            while time.time() < deadline:
                time.sleep(2)
                pr = requests.get(f"{self.cf_solver_url}/result/{task_id}", timeout=10)
                pdata = pr.json() if pr.text else {}
                if pdata.get("status") == "success":
                    return str(pdata.get("cookies") or "")
                if pdata.get("status") in {"failed", "error"}:
                    return ""
            return ""
        except Exception:
            return ""

    def _fetch_otp_code(
        self,
        mail_credential: dict[str, str],
        after_utc: datetime,
        proxy: str = "",
    ) -> str | None:
        """取 OTP 验证码：优先自建微软 Graph 直连（免第三方 98faka），凭证失效才回退 98faka。

        调度逻辑：Graph token 换出 → 全程用 Graph（不再碰 98faka）；token 换不出（凭证对
        Graph 无效/网络不可达）→ 回退第三方 98faka 兜底。Graph 读到邮箱但没等到码时**不**
        回退双轮询——同一邮箱 98faka 同样取不到，只会徒增 90s 等待。
        """
        client_id = mail_credential.get("client_id", "")
        refresh_token = mail_credential.get("refresh_token", "")
        if client_id and refresh_token:
            access_token = self._graph_access_token(client_id, refresh_token, proxy)
            if access_token:
                return self._poll_graph_otp(access_token, after_utc, proxy)
        return self._fetch_otp_code_98faka(mail_credential, after_utc, proxy)

    # ---------------------------------------------------------------- 微软 Graph 直连取件（优先）
    @staticmethod
    def _graph_access_token(client_id: str, refresh_token: str, proxy: str = "") -> str:
        """用 refresh_token 换 Graph access_token（scope=Mail.Read）。失败返回空串。"""
        proxies = {"http": proxy, "https": proxy} if proxy else {}
        try:
            r = requests.post(
                GRAPH_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": GRAPH_SCOPE,
                },
                headers={"content-type": "application/x-www-form-urlencoded", "user-agent": user_agent},
                proxies=proxies, timeout=30,
            )
            if r.status_code != 200:
                return ""
            body = r.json() if r.text else {}
            return str(body.get("access_token") or "").strip()
        except Exception:
            return ""

    def _graph_list_mails(self, access_token: str, proxy: str = "") -> list[dict]:
        """读收件箱最新邮件，归一化成与 98faka 相同的字段（供 _is_otp_mail/_mail_time 复用）。"""
        proxies = {"http": proxy, "https": proxy} if proxy else {}
        r = requests.get(
            GRAPH_MESSAGES_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "user-agent": user_agent},
            params={"$top": 25, "$orderby": "receivedDateTime desc", "$select": "id,subject,receivedDateTime,from,bodyPreview"},
            proxies=proxies, timeout=30,
        )
        body = r.json() if r.text else {}
        items = body.get("value") if isinstance(body.get("value"), list) else []
        mails: list[dict] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            frm = ""
            fa = it.get("from")
            if isinstance(fa, dict):
                ea = fa.get("emailAddress")
                if isinstance(ea, dict):
                    frm = str(ea.get("address") or ea.get("name") or "")
            mails.append({
                "id": it.get("id"),
                "subject": str(it.get("subject") or ""),
                "received_time": str(it.get("receivedDateTime") or ""),
                "from_address": frm,
                "body_preview": str(it.get("bodyPreview") or ""),
            })
        return mails

    def _graph_code_from_full_body(self, access_token: str, msg_id: str, proxy: str = "") -> str | None:
        """preview 没提到码时，拉单封完整正文再提取（bodyPreview 通常已含码，此为数度兜底）。"""
        if not msg_id:
            return None
        proxies = {"http": proxy, "https": proxy} if proxy else {}
        try:
            r = requests.get(
                f"{GRAPH_MESSAGES_URL}/{msg_id}",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "user-agent": user_agent},
                params={"$select": "body"},
                proxies=proxies, timeout=30,
            )
            body = r.json() if r.text else {}
            b = body.get("body")
            content = str(b.get("content") or "") if isinstance(b, dict) else ""
            return self._extract_otp_code(content)
        except Exception:
            return None

    def _poll_graph_otp(self, access_token: str, after_utc: datetime, proxy: str = "") -> str | None:
        """Graph 轮询取件：取"触发后最新"的 OpenAI 邮件，先 subject+preview 提码，不行拉全文。"""
        deadline = time.time() + OTP_WAIT_MAX
        after_local = after_utc.replace(microsecond=0)
        while time.time() < deadline:
            try:
                mails = self._graph_list_mails(access_token, proxy)
                cands = [m for m in mails if self._is_otp_mail(m) and self._mail_time(m) >= after_local - timedelta(seconds=8)]
                if cands:
                    newest = max(cands, key=self._mail_time)
                    code = self._extract_otp_code(f"{newest.get('subject', '')} {newest.get('body_preview', '')}")
                    if code:
                        return code
                    code = self._graph_code_from_full_body(access_token, str(newest.get("id") or ""), proxy)
                    if code:
                        return code
            except Exception:
                pass
            time.sleep(OTP_POLL_SEC)
        return None

    def _fetch_otp_code_98faka(
        self,
        mail_credential: dict[str, str],
        after_utc: datetime,
        proxy: str = "",
    ) -> str | None:
        """调 98faka 邮箱中转 API 取 OTP 邮件，提取 6 位数字（Graph 失效时的第三方兜底）。

        98faka 契约（来自"微软邮箱和卡密以及使用教程.txt"真实抓包）：
          POST /api/emails body={email,password,client_id,refresh_token,folder=inbox}
          → {code:200, data:[{id,subject,body_preview,received_time,from_address}]}
          POST /api/email-body body={email,message_id,client_id,refresh_token}
          → {body_html, body_preview}

        兜底：若 after 后无新邮件，退回用收件箱最新 15 分钟内的 OTP 邮件。
        """
        proxies = {"http": proxy, "https": proxy} if proxy else {}
        headers = {
            "content-type": "application/json",
            "origin": MAIL_API_BASE,
            "referer": f"{MAIL_API_BASE}/",
            "user-agent": user_agent,
        }
        email = mail_credential.get("email", "")
        client_id = mail_credential.get("client_id", "")
        refresh_token = mail_credential.get("refresh_token", "")
        mail_password = mail_credential.get("password", "")
        deadline = time.time() + OTP_WAIT_MAX
        after_local = after_utc.replace(microsecond=0)

        while time.time() < deadline:
            try:
                r = requests.post(
                    f"{MAIL_API_BASE}/api/emails",
                    json={
                        "email": email, "password": mail_password,
                        "client_id": client_id, "refresh_token": refresh_token,
                        "folder": "inbox",
                    },
                    headers=headers, proxies=proxies, timeout=30,
                )
                body = r.json() if r.text else {}
                data = body.get("data") if isinstance(body.get("data"), list) else []
                cands = [m for m in data if self._is_otp_mail(m) and self._mail_time(m) >= after_local - timedelta(seconds=8)]
                if cands:
                    newest = max(cands, key=self._mail_time)
                    code = self._extract_code_from_mail(newest, mail_credential, proxy)
                    if code:
                        return code
            except Exception:
                pass
            time.sleep(OTP_POLL_SEC)
        return None

    @staticmethod
    def _is_otp_mail(m: dict) -> bool:
        subj = str(m.get("subject") or "")
        frm = str(m.get("from_address") or m.get("from") or "").lower()
        return "openai" in frm or "chatgpt" in subj.lower() or "验证码" in subj

    @staticmethod
    def _mail_time(m: dict) -> datetime:
        raw = str(m.get("received_time") or m.get("date") or "").strip()
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            # 统一为 UTC aware：否则与 after_local(UTC aware) 比较时 naive/aware 冲突
            # 抛 TypeError 被外层 except 静默吞掉，导致永远取不到验证码。
            if d.tzinfo is None:
                d = d.replace(tzinfo=UTC)
            return d.astimezone(UTC)
        except Exception:
            return datetime.fromtimestamp(0, UTC)

    @staticmethod
    def _extract_otp_code(text: str) -> str | None:
        """从邮件文本提取 6 位数字验证码：优先"关键词+数字"，否则取文本中最后一组 6 位数字。"""
        text = re.sub(r"<[^>]+>", " ", text or "")
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None
        m = OTP_KEYWORD_RE.search(text)
        if m:
            return m.group(1)
        nums = OTP_CODE_RE.findall(text)
        return nums[-1] if nums else None

    @staticmethod
    def _extract_code_from_mail(mail: dict, cred: dict[str, str], proxy: str) -> str | None:
        proxies = {"http": proxy, "https": proxy} if proxy else {}
        headers = {
            "content-type": "application/json",
            "origin": MAIL_API_BASE,
            "referer": f"{MAIL_API_BASE}/",
            "user-agent": user_agent,
        }
        try:
            r = requests.post(
                f"{MAIL_API_BASE}/api/email-body",
                json={
                    "email": cred.get("email", ""),
                    "message_id": mail.get("id"),
                    "client_id": cred.get("client_id", ""),
                    "refresh_token": cred.get("refresh_token", ""),
                },
                headers=headers, proxies=proxies, timeout=30,
            )
            body = r.json() if r.text else {}
            html = body.get("body_html") or body.get("body_preview") or ""
            return OTPLoginService._extract_otp_code(html)
        except Exception:
            return None

    @staticmethod
    def _exchange_code(session: requests.Session, code: str, code_verifier: str) -> dict[str, Any]:
        """用 code + verifier 换 token 三件套（复用 oauth_login_service 逻辑）。"""
        resp = session.post(
            f"{auth_base}/api/accounts/oauth/token",
            headers={
                "accept": "*/*",
                "auth0-client": platform_auth0_client,
                "content-type": "application/json",
                "origin": platform_base,
                "referer": f"{platform_base}/",
                "user-agent": user_agent,
                "sec-ch-ua": sec_ch_ua,
            },
            json={
                "client_id": platform_oauth_client_id,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": platform_oauth_redirect_uri,
            },
            timeout=60,
            verify=False,
        )
        data = resp.json() if resp.text else {}
        if resp.status_code != 200 or not data.get("access_token"):
            raise OTPLoginError(f"换token失败 HTTP{resp.status_code}: {str(data)[:300]}")
        return {
            "access_token": str(data.get("access_token") or "").strip(),
            "refresh_token": str(data.get("refresh_token") or "").strip(),
            "id_token": str(data.get("id_token") or "").strip(),
            "expires_at": data.get("expires_in") and int(time.time()) + int(data["expires_in"]),
        }


otp_login_service = OTPLoginService()

