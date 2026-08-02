"""安全响应头中间件：为所有响应注入安全头，防 MIME 嗅探/点击劫持/引用泄漏。

设置的头：
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Referrer-Policy: strict-origin-when-cross-origin

说明：API 路由（/v1、/api）无 HTML，不设置 CSP；CSP 仅适用于 web_dist 静态页。
作为纯 ASGI 中间件实现，确保 4xx/5xx/异常响应也带头。
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
]


class SecurityHeadersMiddleware:
    """纯 ASGI 中间件：在 http.response.start 时追加安全头。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}
                for name, value in _SECURITY_HEADERS:
                    if name not in existing:
                        headers.append((name, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
