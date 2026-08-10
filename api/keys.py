"""API Key 管理端点（/api/auth/keys）。

包括 CRUD、撤销、用量查询。
旧 /api/auth/users 端点保留在 accounts.py 中用于向后兼容。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from api.support import require_admin
from services.auth_service import auth_service


class KeyCreateRequest(BaseModel):
    name: str = ""
    role: str = "user"
    expires_at: str | None = None
    permissions: list[str] | None = None
    quota: dict[str, Any] | None = None


class KeyUpdateRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    expires_at: str | None = None
    permissions: list[str] | None = None
    quota: dict[str, Any] | None = None


def _build_admin_virtual_item() -> dict[str, Any]:
    return {
        "id": "admin",
        "name": "管理员",
        "role": "admin",
        "enabled": True,
        "created_at": "2024-01-01T00:00:00",
        "last_used_at": None,
        "usage_count": 0,
        "expires_at": None,
        "permissions": ["*"],
        "quota": None,
        "quota_used": None,
    }


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/auth/keys")
    async def list_keys(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        user_keys = auth_service.list_keys(role="user")
        return {"items": [_build_admin_virtual_item(), *user_keys]}

    @router.post("/api/auth/keys")
    async def create_key(body: KeyCreateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item, raw_key = auth_service.create_key(
                role=body.role,  # type: ignore[arg-type]
                name=body.name,
                expires_at=body.expires_at,
                permissions=body.permissions,
                quota=body.quota,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "key": raw_key, "items": auth_service.list_keys()}

    @router.post("/api/auth/keys/{key_id}")
    async def update_key(key_id: str, body: KeyUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        updates: dict[str, Any] = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.enabled is not None:
            updates["enabled"] = body.enabled
        if body.expires_at is not None:
            updates["expires_at"] = body.expires_at
        if body.permissions is not None:
            updates["permissions"] = body.permissions
        if body.quota is not None:
            updates["quota"] = body.quota
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "还没有检测到改动，请修改后再保存"})
        try:
            item = auth_service.update_key(key_id, updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "密钥不存在"})
        return {"item": item, "items": auth_service.list_keys()}

    @router.delete("/api/auth/keys/{key_id}")
    async def delete_key(key_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not auth_service.delete_key(key_id):
            raise HTTPException(status_code=404, detail={"error": "密钥不存在"})
        return {"items": auth_service.list_keys()}

    @router.post("/api/auth/keys/{key_id}/revoke")
    async def revoke_key(key_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        item = auth_service.update_key(key_id, {"enabled": False})
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "密钥不存在"})
        return {"item": item, "items": auth_service.list_keys()}

    @router.get("/api/auth/keys/usage")
    async def get_key_usage(key_id: str, authorization: str | None = Header(default=None)):
        """获取指定 Key 的用量统计"""
        require_admin(authorization)
        used = auth_service.get_quota_used(key_id)
        return {"usage": used or {}}

    return router