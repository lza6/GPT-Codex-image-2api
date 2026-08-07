"""kookeey 代理集成 API（v2.9.0）。"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from api.support import require_admin
from services.kookeey_service import kookeey_service


class KookeeyConfigRequest(BaseModel):
    enabled: bool = False
    extract_url: str = ""
    developer_token: str = ""
    access_id: str = ""
    default_country: str = "US"
    default_count: int = 10


class KookeeyExtractRequest(BaseModel):
    country: str = ""
    count: int = 0


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/kookeey/config")
    async def get_kookeey_config(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return kookeey_service.get_config()

    @router.post("/api/kookeey/config")
    async def update_kookeey_config(body: KookeeyConfigRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        kookeey_service.update_config(body.model_dump())
        # 持久化到 config.json 的 kookeey 块
        try:
            from services.config import config
            config.data["kookeey"] = kookeey_service.get_config()
            config._save()  # noqa: SLF001
        except Exception:
            pass
        return {"ok": True, "config": kookeey_service.get_config()}

    @router.get("/api/kookeey/stats")
    async def get_kookeey_stats(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return kookeey_service.get_stats()

    @router.post("/api/kookeey/test")
    async def test_kookeey(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return kookeey_service.test_connection()

    @router.post("/api/kookeey/extract")
    async def extract_kookeey(body: KookeeyExtractRequest, authorization: str | None = Header(default=None)):
        """从 kookeey 拉取 IP 入池。"""
        require_admin(authorization)
        return kookeey_service.extract_to_pool(country=body.country, count=body.count)

    return router
