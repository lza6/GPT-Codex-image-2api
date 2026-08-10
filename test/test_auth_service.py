"""AuthService 扩展测试：quota/expires_at/permissions 字段。

覆盖：
- _normalize_item 新字段解析（含旧 Key 向后兼容）
- _public_item 暴露新字段
- create_key 支持 expires_at/permissions/quota 参数
- update_key 支持 expires_at/permissions/quota 字段更新
- update_quota_used / get_quota_used 读写方法
- list_keys role=None 返回全部
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.auth_service import AuthService
from services.storage.json_storage import JSONStorageBackend


@pytest.fixture
def auth_service(tmp_path: Path) -> AuthService:
    storage = JSONStorageBackend(
        tmp_path / "accounts.json",
        tmp_path / "auth_keys.json",
    )
    return AuthService(storage)


# =============================================================================
# _normalize_item 新字段
# =============================================================================


def test_normalize_item_with_quota(auth_service: AuthService) -> None:
    raw = {
        "id": "test123",
        "name": "test",
        "role": "user",
        "key_hash": "abc",
        "quota": {"daily_requests": 100, "reset_cycle": "daily"},
        "expires_at": "2027-01-01",
        "permissions": ["image.generate"],
    }
    result = auth_service._normalize_item(raw)
    assert result is not None
    assert result["quota"]["daily_requests"] == 100
    assert result["quota"]["reset_cycle"] == "daily"
    assert result["expires_at"] == "2027-01-01"
    assert result["permissions"] == ["image.generate"]


def test_normalize_item_no_quota_is_none(auth_service: AuthService) -> None:
    """旧 Key 无 quota 字段 -> quota=None（无限）"""
    raw = {"id": "old", "role": "user", "key_hash": "abc"}
    result = auth_service._normalize_item(raw)
    assert result is not None
    assert result["quota"] is None
    assert result["expires_at"] is None
    assert result["permissions"] == ["*"]


def test_normalize_item_quota_none_values(auth_service: AuthService) -> None:
    """quota 中 None 值字段保留为 None"""
    raw = {
        "id": "q2",
        "role": "user",
        "key_hash": "abc",
        "quota": {"daily_requests": None, "reset_cycle": "none"},
    }
    result = auth_service._normalize_item(raw)
    assert result is not None
    assert result["quota"]["daily_requests"] is None
    assert result["quota"]["reset_cycle"] == "none"


def test_normalize_item_quota_invalid_reset_cycle_defaults_none(
    auth_service: AuthService,
) -> None:
    """无效 reset_cycle -> 'none'"""
    raw = {
        "id": "q3",
        "role": "user",
        "key_hash": "abc",
        "quota": {"daily_requests": 10, "reset_cycle": "weekly"},
    }
    result = auth_service._normalize_item(raw)
    assert result is not None
    assert result["quota"]["reset_cycle"] == "none"


def test_normalize_item_quota_used(auth_service: AuthService) -> None:
    """quota_used 完整解析"""
    raw = {
        "id": "q4",
        "role": "user",
        "key_hash": "abc",
        "quota_used": {
            "daily_requests": 5,
            "daily_images": 2,
            "monthly_requests": 50,
            "monthly_images": 10,
            "daily_reset_date": "2026-08-10",
            "monthly_reset_date": "2026-08",
        },
    }
    result = auth_service._normalize_item(raw)
    assert result is not None
    ru = result["quota_used"]
    assert isinstance(ru, dict)
    assert ru["daily_requests"] == 5
    assert ru["daily_images"] == 2
    assert ru["monthly_requests"] == 50
    assert ru["monthly_images"] == 10
    assert ru["daily_reset_date"] == "2026-08-10"
    assert ru["monthly_reset_date"] == "2026-08"


def test_normalize_item_quota_used_none(auth_service: AuthService) -> None:
    """无 quota_used -> None"""
    raw = {"id": "q5", "role": "user", "key_hash": "abc"}
    result = auth_service._normalize_item(raw)
    assert result is not None
    assert result["quota_used"] is None


def test_normalize_item_permissions_empty_defaults_star(
    auth_service: AuthService,
) -> None:
    """permissions 空列表 -> ['*']"""
    raw = {"id": "p1", "role": "user", "key_hash": "abc", "permissions": []}
    result = auth_service._normalize_item(raw)
    assert result is not None
    assert result["permissions"] == ["*"]


def test_normalize_item_permissions_not_list_defaults_star(
    auth_service: AuthService,
) -> None:
    """permissions 非列表 -> ['*']"""
    raw = {"id": "p2", "role": "user", "key_hash": "abc", "permissions": "image.generate"}
    result = auth_service._normalize_item(raw)
    assert result is not None
    assert result["permissions"] == ["*"]


# =============================================================================
# _public_item 暴露新字段
# =============================================================================


def test_public_item_exposes_new_fields(auth_service: AuthService) -> None:
    raw = {
        "id": "pub1",
        "name": "test",
        "role": "user",
        "key_hash": "abc",
        "quota": {"daily_requests": 50, "reset_cycle": "daily"},
        "quota_used": {"daily_requests": 3, "daily_images": 0, "monthly_requests": 0, "monthly_images": 0, "daily_reset_date": None, "monthly_reset_date": None},
        "expires_at": "2027-06-15",
        "permissions": ["*"],
    }
    result = auth_service._public_item(raw)
    assert result["expires_at"] == "2027-06-15"
    assert result["permissions"] == ["*"]
    assert result["quota"]["daily_requests"] == 50
    assert result["quota_used"]["daily_requests"] == 3


# =============================================================================
# create_key 新参数
# =============================================================================


def test_create_key_with_quota(auth_service: AuthService) -> None:
    item, raw_key = auth_service.create_key(
        role="user",
        name="quota-key",
        expires_at="2027-12-31",
        permissions=["image.generate"],
        quota={"daily_requests": 100, "reset_cycle": "daily"},
    )
    assert item["name"] == "quota-key"
    assert item["expires_at"] == "2027-12-31"
    assert item["permissions"] == ["image.generate"]
    assert item["quota"]["daily_requests"] == 100
    assert item["quota"]["reset_cycle"] == "daily"
    # quota_used 应初始化为 0
    assert item["quota_used"]["daily_requests"] == 0
    assert item["quota_used"]["daily_images"] == 0
    assert raw_key.startswith("sk-")


def test_create_key_no_quota(auth_service: AuthService) -> None:
    """不带 quota 参数，向后兼容"""
    item, raw_key = auth_service.create_key(
        role="user",
        name="no-quota",
    )
    assert item["name"] == "no-quota"
    assert item["quota"] is None
    assert item["quota_used"] is None
    assert item["expires_at"] is None
    assert item["permissions"] == ["*"]


def test_create_key_quota_with_images(auth_service: AuthService) -> None:
    item, raw_key = auth_service.create_key(
        role="user",
        name="img-key",
        quota={"daily_images": 10, "monthly_images": 200, "reset_cycle": "daily"},
    )
    assert item["quota"]["daily_images"] == 10
    assert item["quota"]["monthly_images"] == 200


# =============================================================================
# update_key 新字段
# =============================================================================


def test_update_key_expires_at(auth_service: AuthService) -> None:
    item, _ = auth_service.create_key(role="user", name="upd-exp")
    key_id = str(item["id"])

    updated = auth_service.update_key(key_id, {"expires_at": "2028-01-01"})
    assert updated is not None
    assert updated["expires_at"] == "2028-01-01"


def test_update_key_permissions(auth_service: AuthService) -> None:
    item, _ = auth_service.create_key(role="user", name="upd-perm")
    key_id = str(item["id"])

    updated = auth_service.update_key(key_id, {"permissions": ["image.generate", "image.edit"]})
    assert updated is not None
    assert updated["permissions"] == ["image.generate", "image.edit"]


def test_update_key_quota(auth_service: AuthService) -> None:
    item, _ = auth_service.create_key(role="user", name="upd-quota")
    key_id = str(item["id"])

    updated = auth_service.update_key(
        key_id,
        {"quota": {"daily_requests": 200, "reset_cycle": "monthly"}},
    )
    assert updated is not None
    assert updated["quota"]["daily_requests"] == 200
    assert updated["quota"]["reset_cycle"] == "monthly"
    # 改配额后用量应重置
    assert updated["quota_used"]["daily_requests"] == 0


def test_update_key_quota_to_none(auth_service: AuthService) -> None:
    item, _ = auth_service.create_key(
        role="user",
        name="upd-quota-none",
        quota={"daily_requests": 10, "reset_cycle": "daily"},
    )
    key_id = str(item["id"])

    updated = auth_service.update_key(key_id, {"quota": None})
    assert updated is not None
    assert updated["quota"] is None
    assert updated["quota_used"] is None


# =============================================================================
# update_quota_used / get_quota_used
# =============================================================================


def test_update_quota_used_request(auth_service: AuthService) -> None:
    item, _ = auth_service.create_key(
        role="user",
        name="usage-req",
        quota={"daily_requests": 100, "reset_cycle": "daily"},
    )
    key_id = str(item["id"])

    auth_service.update_quota_used(key_id, api_type="request", count=1)
    used = auth_service.get_quota_used(key_id)
    assert used is not None
    assert used["daily_requests"] == 1
    assert used["monthly_requests"] == 1


def test_update_quota_used_image(auth_service: AuthService) -> None:
    item, _ = auth_service.create_key(
        role="user",
        name="usage-img",
        quota={"daily_images": 10, "reset_cycle": "daily"},
    )
    key_id = str(item["id"])

    auth_service.update_quota_used(key_id, api_type="image", count=3)
    used = auth_service.get_quota_used(key_id)
    assert used is not None
    assert used["daily_images"] == 3
    assert used["monthly_images"] == 3


def test_update_quota_used_accumulates(auth_service: AuthService) -> None:
    item, _ = auth_service.create_key(
        role="user",
        name="usage-acc",
        quota={"daily_requests": 100, "reset_cycle": "daily"},
    )
    key_id = str(item["id"])

    auth_service.update_quota_used(key_id, api_type="request", count=1)
    auth_service.update_quota_used(key_id, api_type="request", count=1)
    auth_service.update_quota_used(key_id, api_type="request", count=1)
    used = auth_service.get_quota_used(key_id)
    assert used is not None
    assert used["daily_requests"] == 3


def test_update_quota_used_no_quota_creates_tracking(
    auth_service: AuthService,
) -> None:
    """无 quota 的 Key 也能记录用量（创建默认 tracking dict）"""
    item, _ = auth_service.create_key(role="user", name="usage-noq")
    key_id = str(item["id"])

    auth_service.update_quota_used(key_id, api_type="request", count=5)
    used = auth_service.get_quota_used(key_id)
    assert used is not None
    assert used["daily_requests"] == 5


def test_get_quota_used_nonexistent_key(auth_service: AuthService) -> None:
    """不存在的 key_id -> None"""
    used = auth_service.get_quota_used("nonexistent")
    assert used is None


def test_get_quota_used_empty_key_id(auth_service: AuthService) -> None:
    """空 key_id -> None"""
    used = auth_service.get_quota_used("")
    assert used is None


def test_update_quota_used_empty_key_id_noop(
    auth_service: AuthService,
) -> None:
    """空 key_id 不操作（不抛异常）"""
    auth_service.update_quota_used("", api_type="request", count=1)
    # 没有异常即通过


# =============================================================================
# list_keys 返回全部（role=None）
# =============================================================================


def test_list_keys_role_none_returns_all(auth_service: AuthService) -> None:
    auth_service.create_key(role="user", name="u1")
    auth_service.create_key(role="user", name="u2")
    # 加载时已有 admin 默认 key（如果有）
    all_keys = auth_service.list_keys()
    # 至少包含上面创建的 2 个
    names = [k["name"] for k in all_keys]
    assert "u1" in names
    assert "u2" in names


def test_list_keys_role_user_only(auth_service: AuthService) -> None:
    auth_service.create_key(role="user", name="u1")
    user_keys = auth_service.list_keys(role="user")
    names = [k["name"] for k in user_keys]
    assert "u1" in names


# =============================================================================
# 持久化验证
# =============================================================================


def test_quota_fields_persisted(auth_service: AuthService) -> None:
    """创建后 reload 应保留新字段"""
    item, _ = auth_service.create_key(
        role="user",
        name="persist",
        expires_at="2029-01-01",
        permissions=["image.generate"],
        quota={"daily_requests": 50, "reset_cycle": "daily"},
    )
    key_id = str(item["id"])

    # reload
    auth_service._reload_locked()
    all_keys = auth_service.list_keys()
    found = [k for k in all_keys if k["id"] == key_id]
    assert len(found) == 1
    assert found[0]["expires_at"] == "2029-01-01"
    assert found[0]["permissions"] == ["image.generate"]
    assert found[0]["quota"]["daily_requests"] == 50
    assert found[0]["quota"]["reset_cycle"] == "daily"