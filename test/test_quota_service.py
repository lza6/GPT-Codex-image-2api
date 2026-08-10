from __future__ import annotations

import pytest
from services.quota_service import QuotaService


def test_quota_disabled_always_allowed() -> None:
    qs = QuotaService(enabled=False)
    allowed, reason = qs.check_quota({"id": "test"}, api_type="request")
    assert allowed is True
    assert reason == ""


def test_quota_no_quota_field_is_unlimited() -> None:
    qs = QuotaService(enabled=True)
    identity = {"id": "test", "quota": None, "quota_used": None}
    allowed, reason = qs.check_quota(identity, api_type="request")
    assert allowed is True


def test_quota_daily_requests_exceeded() -> None:
    qs = QuotaService(enabled=True)
    identity = {
        "id": "test",
        "quota": {"daily_requests": 10, "daily_images": None, "monthly_requests": None, "monthly_images": None, "reset_cycle": "daily"},
        "quota_used": {"daily_requests": 10, "daily_images": 0, "monthly_requests": 0, "monthly_images": 0},
    }
    allowed, reason = qs.check_quota(identity, api_type="request")
    assert allowed is False
    assert "每日请求" in reason


def test_quota_daily_images_exceeded() -> None:
    qs = QuotaService(enabled=True)
    identity = {
        "id": "test",
        "quota": {"daily_requests": None, "daily_images": 5, "monthly_requests": None, "monthly_images": None, "reset_cycle": "daily"},
        "quota_used": {"daily_requests": 0, "daily_images": 5, "monthly_requests": 0, "monthly_images": 0},
    }
    allowed, reason = qs.check_quota(identity, api_type="image")
    assert allowed is False
    assert "图片" in reason


def test_quota_monthly_requests_exceeded() -> None:
    qs = QuotaService(enabled=True)
    identity = {
        "id": "test",
        "quota": {"daily_requests": None, "daily_images": None, "monthly_requests": 100, "monthly_images": None, "reset_cycle": "monthly"},
        "quota_used": {"daily_requests": 0, "daily_images": 0, "monthly_requests": 100, "monthly_images": 0},
    }
    allowed, reason = qs.check_quota(identity, api_type="request")
    assert allowed is False
    assert "每月请求" in reason


def test_quota_warn_not_reject() -> None:
    qs = QuotaService(enabled=True, overage_action="warn")
    identity = {
        "id": "test",
        "quota": {"daily_requests": 1, "daily_images": None, "monthly_requests": None, "monthly_images": None, "reset_cycle": "daily"},
        "quota_used": {"daily_requests": 1, "daily_images": 0, "monthly_requests": 0, "monthly_images": 0},
    }
    allowed, reason = qs.check_quota(identity, api_type="request")
    assert allowed is True  # warn 模式不拒绝
    assert "超限" in reason


def test_quota_admin_key_unlimited() -> None:
    qs = QuotaService(enabled=True)
    identity = {"id": "admin", "name": "管理员", "role": "admin"}
    allowed, reason = qs.check_quota(identity, api_type="request")
    assert allowed is True


def test_quota_expired_key() -> None:
    from datetime import datetime, timedelta, timezone
    qs = QuotaService(enabled=True)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    identity = {"id": "exp", "role": "user", "expires_at": past}
    allowed, reason = qs.check_quota(identity)
    assert allowed is False
    assert "过期" in reason


def test_quota_future_key_valid() -> None:
    from datetime import datetime, timedelta, timezone
    qs = QuotaService(enabled=True)
    future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    identity = {"id": "val", "role": "user", "expires_at": future, "quota": None, "quota_used": None}
    allowed, reason = qs.check_quota(identity)
    assert allowed is True