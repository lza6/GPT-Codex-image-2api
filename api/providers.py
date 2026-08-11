from __future__ import annotations

from fastapi import APIRouter, Header, Response

from api.response_cache import response_cache, apply_cache_headers
from api.support import require_admin
from services.providers import list_providers


def create_router() -> APIRouter:
    router = APIRouter(tags=["Providers"])

    @router.get("/api/providers")
    async def get_providers(
        authorization: str | None = Header(default=None),
        refresh: bool = False,
        response: Response = None,
    ):
        """返回所有已注册提供商列表（含 enabled 状态），前端用于渲染筛选器与状态展示。"""
        require_admin(authorization)
        if not refresh:
            cached = response_cache.get("/api/providers")
            if cached is not None:
                if response is not None:
                    apply_cache_headers("/api/providers", response)
                return cached
        providers = list_providers()
        result = {
            "providers": [
                {
                    "name": p.name,
                    "display_name": p.display_name,
                    "enabled": p.enabled,
                    "description": p.description,
                    "models": list(p.models),
                    "capabilities": list(p.capabilities),
                }
                for p in providers
            ],
        }
        response_cache.set("/api/providers", result)
        if response is not None:
            apply_cache_headers("/api/providers", response)
        return result

    return router