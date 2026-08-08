from __future__ import annotations

from fastapi import APIRouter, Header

from api.support import require_admin
from services.providers import list_providers


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/providers")
    async def get_providers(authorization: str | None = Header(default=None)):
        """返回所有已注册提供商列表（含 enabled 状态），前端用于渲染筛选器与状态展示。"""
        require_admin(authorization)
        providers = list_providers()
        return {
            "providers": [
                {
                    "name": p.name,
                    "display_name": p.display_name,
                    "enabled": p.enabled,
                    "description": p.description,
                }
                for p in providers
            ],
        }

    return router