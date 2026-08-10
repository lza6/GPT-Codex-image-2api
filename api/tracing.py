"""追踪数据 API 端点。"""
from __future__ import annotations
from fastapi import APIRouter
from services.tracing import tracer

def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/tracing", tags=["tracing"])

    @router.get("/traces")
    async def get_traces(limit: int = 50, slow_only: bool = False):
        if slow_only:
            spans = tracer.get_slow_traces(limit=limit)
        else:
            spans = tracer.get_all_traces(limit=limit)
        return {"spans": [{"name": s.name, "start_time": s.start_time, "duration_ms": round(s.duration_ms, 1), "status": s.status, "error": s.error, "metadata": s.metadata} for s in spans]}

    @router.get("/stats")
    async def get_tracing_stats():
        return tracer.get_stats()

    return router
