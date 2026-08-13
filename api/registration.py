"""Grok 注册管理 API（挂到主应用，不新开端口）。

端点：
- POST /api/registration/grok/register  手动触发注册 N 个（管理员鉴权）
- GET  /api/registration/status         注册状态/号池健康（管理员鉴权）
"""
from __future__ import annotations

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from api.support import require_admin
from services.registration.coordinator import registration_coordinator


class GrokRegisterRequest(BaseModel):
    count: int | None = Field(default=None, ge=1, le=20, description="注册数量（默认取配置 register_batch，上限 20）")


class FomimageRegisterRequest(BaseModel):
    count: int | None = Field(default=None, ge=1, le=10, description="fomimage 注册数量（默认取配置 register_batch，上限 10）")


def create_router() -> APIRouter:
    router = APIRouter(tags=["Registration"])

    @router.post("/api/registration/grok/register")
    def grok_register(
        body: GrokRegisterRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        """手动触发 grok 号注册 N 个（同步执行，内部入池；FastAPI 自动跑在线程池，不阻塞事件循环）。"""
        require_admin(authorization)
        return registration_coordinator.register(body.count)

    @router.post("/api/registration/fomimage/register")
    def fomimage_register(
        body: FomimageRegisterRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        """手动触发 fomimage 号注册 N 个（temp-mail 收件 + 每号独立 IP + 入池）。"""
        require_admin(authorization)
        from services.registration.fomimage.coordinator import fomimage_registration_coordinator

        return fomimage_registration_coordinator.register(body.count)

    @router.get("/api/registration/fomimage/status")
    def fomimage_registration_status(
        authorization: str | None = Header(default=None),
    ) -> dict:
        """fomimage 注册状态：配置、号池可用数、最近一次执行统计。"""
        require_admin(authorization)
        from services.registration.fomimage.coordinator import fomimage_registration_coordinator

        return fomimage_registration_coordinator.status()

    @router.get("/api/registration/status")
    def registration_status(
        authorization: str | None = Header(default=None),
    ) -> dict:
        """返回 grok 注册状态：配置、号池可用数、邮箱池、最近一次执行统计。"""
        require_admin(authorization)
        return registration_coordinator.status()

    return router
