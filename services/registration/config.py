"""Grok 注册配置读取。

从主 `services.config.config` 的 `data` 热加载（ConfigWatcher 替换 data 即生效），
**不改动** `services/config.py`，仅在启用时读取 `registration.grok` 配置段。

默认全部关闭/留空，保证 `registration` 段缺失或 `enabled=false` 时 chatgpt2api 完全正常。
"""
from __future__ import annotations

from typing import Any


class GrokRegistrationConfig:
    """`registration.grok` 配置段的强类型视图（含默认值）。"""

    def __init__(self, raw: dict[str, Any] | None = None) -> None:
        raw = raw or {}
        self.enabled = bool(raw.get("enabled", False))
        self.yescaptcha_key = str(raw.get("yescaptcha_key") or "").strip()
        self.proxy_group_id = str(raw.get("proxy_group_id") or "").strip()
        self.email_provider = str(raw.get("email_provider") or "luckmail").strip().lower()
        self.min_accounts = self._int(raw.get("min_accounts"), 5, 1)
        self.register_batch = self._int(raw.get("register_batch"), 3, 1)
        self.check_interval_minutes = self._int(raw.get("check_interval_minutes"), 30, 1)
        # 邮箱池：["邮箱----密码----client_id----refresh_token", ...]（也兼容 [{email,password,client_id,refresh_token}]）
        pool = raw.get("email_pool")
        self.email_pool: list[Any] = pool if isinstance(pool, list) else []
        # 邮箱池持久化文件（可选）：与 email_pool 二选一，文件每行一条，同上格式
        self.email_pool_file = str(raw.get("email_pool_file") or "").strip()
        # LuckMail 购买参数（email_provider=luckmail 且邮箱池为空时使用）
        lm = raw.get("luckmail") if isinstance(raw.get("luckmail"), dict) else {}
        self.luckmail_base_url = str(lm.get("base_url") or "https://mails.luckyous.com").strip().rstrip("/")
        self.luckmail_api_key = str(lm.get("api_key") or "").strip()
        self.luckmail_api_secret = str(lm.get("api_secret") or "").strip()
        self.luckmail_use_hmac = str(lm.get("use_hmac") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
        self.luckmail_project_code = str(lm.get("project_code") or "grok").strip()
        self.luckmail_email_type = str(lm.get("email_type") or "ms_imap").strip()
        self.luckmail_domain = str(lm.get("domain") or "outlook.com").strip()
        # 是否尝试 SSO → OAuth Device Flow 铸造（需本机有头 Chrome + patchright，默认关）
        self.device_mint_enabled = bool(raw.get("device_mint_enabled", False))

    @staticmethod
    def _int(value: Any, default: int, minimum: int) -> int:
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default

    def to_dict(self) -> dict[str, Any]:
        """状态接口用（脱敏：密钥只给占位）。"""
        return {
            "enabled": self.enabled,
            "proxy_group_id": self.proxy_group_id,
            "email_provider": self.email_provider,
            "min_accounts": self.min_accounts,
            "register_batch": self.register_batch,
            "check_interval_minutes": self.check_interval_minutes,
            "email_pool_total": len(self.email_pool),
            "email_pool_file": self.email_pool_file,
            "yescaptcha_key_configured": bool(self.yescaptcha_key),
            "luckmail_api_key_configured": bool(self.luckmail_api_key),
            "luckmail_base_url": self.luckmail_base_url,
            "luckmail_project_code": self.luckmail_project_code,
            "device_mint_enabled": self.device_mint_enabled,
        }


def get_registration_config() -> GrokRegistrationConfig:
    """读取当前（热加载后）的 registration.grok 配置。"""
    from services.config import config

    raw = (config.data or {}).get("registration")
    grok_raw = raw.get("grok") if isinstance(raw, dict) else None
    return GrokRegistrationConfig(grok_raw)


class FomimageRegistrationConfig:
    """`registration.fomimage` 配置段的强类型视图（v2.36.0）。

    默认全部关闭，registration 段缺失或 enabled=false 时 chatgpt2api 完全正常。
    """

    def __init__(self, raw: dict[str, Any] | None = None) -> None:
        raw = raw or {}
        self.enabled = bool(raw.get("enabled", False))
        # 每号独立 IP：注册时按邮箱 resolve_account_proxy（免费代理池粘性 / kookeey）。
        # 为空时直连（fromimage 未强制风控时可直连注册）。
        self.proxy_mode = str(raw.get("proxy_mode") or "auto").strip().lower()
        self.min_accounts = self._int(raw.get("min_accounts"), 3, 1)
        self.register_batch = self._int(raw.get("register_batch"), 1, 1)
        self.check_interval_minutes = self._int(raw.get("check_interval_minutes"), 30, 1)
        self.poll_timeout_sec = self._int(raw.get("poll_timeout_sec"), 60, 10)
        self.pool_quota = self._int(raw.get("pool_quota"), 50, 1)

    @staticmethod
    def _int(value: Any, default: int, minimum: int) -> int:
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default

    def to_dict(self) -> dict[str, Any]:
        """状态接口用（脱敏）。"""
        return {
            "enabled": self.enabled,
            "proxy_mode": self.proxy_mode,
            "min_accounts": self.min_accounts,
            "register_batch": self.register_batch,
            "check_interval_minutes": self.check_interval_minutes,
            "poll_timeout_sec": self.poll_timeout_sec,
            "pool_quota": self.pool_quota,
        }


def get_fomimage_registration_config() -> FomimageRegistrationConfig:
    """读取当前（热加载后）的 registration.fomimage 配置。"""
    from services.config import config

    raw = (config.data or {}).get("registration")
    fom_raw = raw.get("fomimage") if isinstance(raw, dict) else None
    return FomimageRegistrationConfig(fom_raw)
