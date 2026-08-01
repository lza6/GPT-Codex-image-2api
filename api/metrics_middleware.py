"""请求指标中间件：记录请求计数、延迟、追踪 ID。

在每个请求上：
- 注入 X-Request-ID 追踪头
- 记录延迟与状态到 metrics_service
- 追踪 inflight 并发数
"""

from __future__ import annotations

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from services.metrics_service import metrics_service


class MetricsMiddleware(BaseHTTPMiddleware):
    """记录请求指标与追踪 ID。"""

    async def dispatch(self, request: Request, call_next):
        request_id = metrics_service.new_request_id()
        method = request.method
        path = request.url.path

        # 排除静态资源，减少噪音
        is_api = path.startswith(("/v1/", "/api/", "/auth/"))
        start = time.perf_counter()

        if is_api:
            metrics_service.record_inflight(method, path, +1)

        status = 500
        response = None
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            if is_api:
                metrics_service.record_inflight(method, path, -1)
                duration_ms = (time.perf_counter() - start) * 1000
                metrics_service.record_request(method, path, status, duration_ms)
            # 注入追踪 ID 头（仅在 response 存在时；异常路径由异常处理器接管）
            if response is not None:
                response.headers["X-Request-ID"] = request_id
                duration_ms = (time.perf_counter() - start) * 1000
                response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
