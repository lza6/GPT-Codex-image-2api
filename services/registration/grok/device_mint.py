"""SSO → OAuth Device Flow 铸造（移植 grok-register/device_mint.py）。

原理：x.ai OAuth Device Authorization Grant——scope 必须为 7 个（不能加
conversations/workspaces，否则该 client 未授权 Access denied）；授权依赖有头
Chrome + patchright 注入 SSO cookie 并自动点击"继续/允许"按钮，然后轮询 token。

**依赖按需加载**：patchright（异步 Playwright fork）+ 有头 Chrome 仅在本模块被
调用时导入；缺失时 `sso_to_device` 返回 None（不影响注册入库——号池以 SSO 作为
access_token 即可用，铸造只是附带产出 OAuth AT/RT 供上游使用）。
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = "openid profile email offline_access grok-cli:access api:access"
DEVICE_CODE_URL = "https://auth.x.ai/oauth2/device/code"
TOKEN_URL = "https://auth.x.ai/oauth2/token"


def _http_json(url: str, method: str = "GET", form: dict[str, Any] | None = None, timeout: int = 40, proxy: str = ""):
    """带代理的同步 HTTP 请求，返回 (status, json|str)。"""
    handlers: list[Any] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    opener = urllib.request.build_opener(*handlers)
    data = urllib.parse.urlencode(form).encode() if form else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "grok-register-cpa/1.0")
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body


async def _browser_authorize(vuc: str, sso_jwt: str, proxy: str = "") -> bool:
    """有头 Chrome + 代理，注入 SSO cookie，自动点授权按钮。patchright 缺失返回 False。"""
    try:
        from patchright.async_api import async_playwright
    except Exception:
        return False
    async with async_playwright() as p:
        launch_kwargs: dict[str, Any] = {
            "headless": False,
            "channel": "chrome",
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
        browser = await p.chromium.launch(**launch_kwargs)
        ctx = await browser.new_context(viewport={"width": 1000, "height": 700})
        await ctx.add_cookies([{"name": "sso", "value": sso_jwt, "domain": ".x.ai", "path": "/"}])
        page = await ctx.new_page()
        try:
            await page.goto(vuc, timeout=40000, wait_until="domcontentloaded")
            for _ in range(20):
                await asyncio.sleep(2)
                if "/device/done" in page.url:
                    return True
                for sel in [
                    "button:has-text('继续')",
                    "button:has-text('Allow')",
                    "button:has-text('允许')",
                    "button:has-text('Continue')",
                    "button[type=submit]",
                ]:
                    try:
                        btn = await page.query_selector(sel)
                        if btn and await btn.is_visible():
                            await btn.click()
                            break
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            await browser.close()
    return False


def sso_to_device(sso_token: str, email: str = "", proxy: str = "") -> Optional[dict[str, Any]]:
    """Device Flow 铸造：SSO cookie → OAuth AT/RT。

    返回 {access_token, refresh_token, expires_in, token_type} 或 None。
    依赖缺失（patchright/Chrome）或流程失败均返回 None，不抛异常。
    """
    try:
        status, payload = _http_json(
            DEVICE_CODE_URL, "POST",
            {"client_id": CLIENT_ID, "scope": SCOPE},
            proxy=proxy,
        )
        if status != 200 or not isinstance(payload, dict) or "device_code" not in payload:
            return None
        device_code = payload["device_code"]
        vuc = payload.get("verification_uri_complete")
        if vuc:
            # 协调器在后台线程调用本函数，无运行中事件循环，直接 asyncio.run 即可。
            try:
                asyncio.run(_browser_authorize(vuc, sso_token, proxy))
            except Exception:
                # 浏览器授权失败不阻断：继续轮询 token（源实现同样允许授权未确认后轮询）
                pass
        deadline = time.time() + 90
        interval = max(int(payload.get("interval", 5)), 1)
        while time.time() < deadline:
            time.sleep(interval)
            status, token_data = _http_json(
                TOKEN_URL, "POST",
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": CLIENT_ID,
                },
                proxy=proxy,
            )
            if status == 200 and isinstance(token_data, dict) and token_data.get("access_token"):
                return {
                    "access_token": token_data["access_token"],
                    "refresh_token": token_data.get("refresh_token", ""),
                    "expires_in": int(token_data.get("expires_in") or 21600),
                    "token_type": token_data.get("token_type", "Bearer"),
                }
            err = token_data.get("error") if isinstance(token_data, dict) else None
            if err in ("access_denied", "expired_token"):
                return None
            if err == "slow_down":
                interval += 5
        return None
    except Exception:
        return None
