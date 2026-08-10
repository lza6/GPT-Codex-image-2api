"""日志 API 路由：聚合 / 导出 / 慢查询。

任务 3：新增 /api/logs/aggregate、/api/logs/export、/api/logs/slow-queries 端点。
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Query

from api.support import require_admin
from services.log_service import log_service


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/logs", tags=["logs"])

    @router.get("/aggregate")
    async def aggregate_logs(
        authorization: str | None = Header(default=None),
        group_by: list[str] = Query(default=["type"]),
        start_date: str = "",
        end_date: str = "",
        period: str = "day",
    ):
        require_admin(authorization)
        return log_service.multi_dimension_aggregate(
            {"start_date": start_date, "end_date": end_date},
            group_by=group_by,
            period=period,
        )

    @router.get("/export")
    async def export_logs(
        authorization: str | None = Header(default=None),
        format: str = "csv",
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=1000, ge=1, le=50000),
        fields: str = "",
        type: str = "",
        start_date: str = "",
        end_date: str = "",
    ):
        require_admin(authorization)
        filter_dict = {k: v for k, v in {"type": type, "start_date": start_date, "end_date": end_date}.items() if v}
        field_list = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
        if format == "json":
            return log_service.export_json(filter_dict, page=page, page_size=page_size, fields=field_list)
        return log_service.export_csv_paginated(filter_dict, page=page, page_size=page_size, fields=field_list)

    @router.get("/slow-queries")
    async def slow_queries(
        authorization: str | None = Header(default=None),
        start_date: str = "",
        end_date: str = "",
        threshold_ms: int = Query(default=5000, ge=100),
    ):
        require_admin(authorization)
        return {"items": log_service.list_slow_queries(start_date=start_date, end_date=end_date, threshold_ms=threshold_ms)}

    return router