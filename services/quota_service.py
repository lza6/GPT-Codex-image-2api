from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from services.config import config

logger = logging.getLogger(__name__)


def _clean(value: object) -> str:
    return str(value or "").strip()


class QuotaService:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        overage_action: str | None = None,
    ):
        cfg = config.get_quota_management() if enabled is None else {}
        self._enabled = enabled if enabled is not None else bool(cfg.get("enabled", False))
        self._overage_action = overage_action or str(cfg.get("overage_action") or "reject")
        if self._overage_action not in {"reject", "warn"}:
            self._overage_action = "reject"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def check_quota(
        self,
        identity: dict[str, Any],
        api_type: str = "request",
    ) -> tuple[bool, str]:
        """检查配额是否超限。

        Returns:
            (allowed, reason): allowed=True 表示允许通过，reason 为拒绝/告警原因（空串表示无问题）。
        """
        if not self._enabled:
            return True, ""

        role = str(identity.get("role") or "").strip()
        if role == "admin":
            return True, ""

        # 过期检查
        expires_at = _clean(identity.get("expires_at"))
        if expires_at:
            try:
                expires_dt = datetime.fromisoformat(expires_at)
                if expires_dt.tzinfo is None:
                    expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > expires_dt:
                    if self._overage_action == "warn":
                        return True, "超限（仅告警）：密钥已过期"
                    return False, "密钥已过期"
            except Exception:
                pass

        quota = identity.get("quota")
        quota_used = identity.get("quota_used")
        if not isinstance(quota, dict) or not isinstance(quota_used, dict):
            return True, ""

        messages: list[str] = []
        if api_type == "image":
            daily_limit = quota.get("daily_images")
            if daily_limit is not None:
                used = int(quota_used.get("daily_images", 0))
                if used >= int(daily_limit):
                    messages.append(f"每日图片配额已用 {used}/{daily_limit}")
            monthly_limit = quota.get("monthly_images")
            if monthly_limit is not None:
                used = int(quota_used.get("monthly_images", 0))
                if used >= int(monthly_limit):
                    messages.append(f"每月图片配额已用 {used}/{monthly_limit}")
        else:
            daily_limit = quota.get("daily_requests")
            if daily_limit is not None:
                used = int(quota_used.get("daily_requests", 0))
                if used >= int(daily_limit):
                    messages.append(f"每日请求配额已用 {used}/{daily_limit}")
            monthly_limit = quota.get("monthly_requests")
            if monthly_limit is not None:
                used = int(quota_used.get("monthly_requests", 0))
                if used >= int(monthly_limit):
                    messages.append(f"每月请求配额已用 {used}/{monthly_limit}")

        if not messages:
            return True, ""

        if self._overage_action == "warn":
            logger.warning("quota overage (warn only): %s", "; ".join(messages))
            return True, "超限（仅告警）：" + "; ".join(messages)

        return False, "配额超限：" + "; ".join(messages)

    def record_usage(
        self,
        identity: dict[str, Any],
        api_type: str = "request",
        count: int = 1,
    ) -> None:
        if not self._enabled:
            return
        key_id = str(identity.get("id") or "").strip()
        if not key_id:
            return
        try:
            from services.auth_service import auth_service

            auth_service.update_quota_used(key_id, api_type=api_type, count=count)
        except Exception:
            logger.warning("record_usage failed", exc_info=True)


quota_service = QuotaService()