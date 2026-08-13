"""LuckMail 最小客户端（纯 requests，仅购买邮箱 + 取码所需端点）。

移植自 grok-register/luckmail/（完整 SDK 含 HMAC/同步异步双模式/供应商端，本模块只保留
注册机实际使用的部分）。鉴权头 `X-API-Key` 与官方 SDK 一致。

端点契约（来自 luckmail/user.py）：
  POST /api/v1/openapi/email/purchase   body={project_code, quantity, email_type, domain}
  GET  /api/v1/openapi/email/token/{token}/code      → 最新验证码
  GET  /api/v1/openapi/email/token/{token}/mails     → 邮件列表
"""
from __future__ import annotations

from typing import Any, Optional

import requests


class LuckMailError(Exception):
    """LuckMail API 可预期错误。"""


class LuckMailClient:
    def __init__(self, base_url: str, api_key: str, api_secret: str = "", timeout: float = 30.0) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.api_secret = str(api_secret or "").strip()
        self.timeout = float(timeout)
        if not self.base_url:
            raise ValueError("缺少 luckmail base_url")
        if not self.api_key:
            raise ValueError("缺少 luckmail api_key")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            resp = requests.request(method, f"{self.base_url}{path}", headers=headers, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise LuckMailError(f"LuckMail 请求失败: {exc}") from exc
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:300]}
        if resp.status_code >= 400:
            raise LuckMailError(f"LuckMail HTTP {resp.status_code}: {body}")
        return body if isinstance(body, dict) else {"data": body}

    def purchase_emails(
        self,
        project_code: str,
        quantity: int = 1,
        email_type: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"project_code": project_code, "quantity": quantity}
        if email_type:
            body["email_type"] = email_type
        if domain:
            body["domain"] = domain
        data = self._request("POST", "/api/v1/openapi/email/purchase", json=body)
        purchases = data.get("purchases")
        return purchases if isinstance(purchases, list) else []

    def get_token_code(self, token: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/openapi/email/token/{token}/code")

    def get_token_mails(self, token: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/openapi/email/token/{token}/mails")
