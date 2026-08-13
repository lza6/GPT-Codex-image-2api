"""Grok 注册引擎子包：注册引擎 + 邮箱服务 + Turnstile + Device Flow 铸造。

惰性加载约定：`services/registration/__init__.py` 与 `coordinator.py` 只在本包被
显式导入（且 `registration.grok.enabled=true`）时才拉取 curl_cffi / yescaptcha 等
依赖，默认关闭时 chatgpt2api 完全不加载本包。
"""
from __future__ import annotations

from services.registration.grok.captcha import TurnstileService
from services.registration.grok.device_mint import sso_to_device
from services.registration.grok.email_service import EmailService, extract_grok_code
from services.registration.grok.engine import GrokRegisterEngine, resolve_proxy_for_group

__all__ = [
    "TurnstileService",
    "sso_to_device",
    "EmailService",
    "extract_grok_code",
    "GrokRegisterEngine",
    "resolve_proxy_for_group",
]
