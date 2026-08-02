"""请求体大小限制中间件：按路径分级限制，超限返回 413，防大 body 攻击拖垮服务。

配置项（config.json 或环境变量）：
- max_request_body_mb_chat: chat/responses 类上限（MB，默认 10）
- max_request_body_mb_image: 图片编辑类上限（MB，默认 50，base64 图占体积）

分级规则：
- /v1/images/* 走 image 上限（图片编辑含 base64，体积大）
- 其余 API 默认走 chat 上限

chunked 防御：无 Content-Length（Transfer-Encoding: chunked）的 API 写请求无法预知
大小，会被超限绕过（实测 11MB chunked 返回 422 而非 413，上限形同虚设）。OpenAI 官方
SDK 与 curl 客户端的 API 写请求总是带 Content-Length，故对 /v1、/api 的写请求直接
要求必须带 Content-Length（411 Length Required），既堵住绕过又不影响正常客户端。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from services.config import config

_IMAGE_PREFIXES = ("/v1/images",)


def _limit_for_path(path: str) -> int:
    """按路径返回请求体上限（字节）。精确匹配前缀，避免 /v1/images2 误判。"""
    if any(path == p or path.startswith(p + "/") for p in _IMAGE_PREFIXES):
        return config.max_request_body_mb_image * 1024 * 1024
    return config.max_request_body_mb_chat * 1024 * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """读 Content-Length，超限直接 413，不读 body 不进路由。"""

    async def dispatch(self, request: Request, call_next):
        # 仅限制有请求体的方法，且仅对 API 路径（静态资源/前端不受影响）
        if request.method in ("POST", "PUT", "PATCH"):
            path = request.url.path
            is_api = path.startswith("/v1") or path.startswith("/api")
            content_length = request.headers.get("content-length")
            if is_api and content_length is None:
                # chunked 传输无法预知大小，会被用来绕过限制；API 写请求必须带 Content-Length
                transfer_encoding = (request.headers.get("transfer-encoding") or "").lower()
                if "chunked" in transfer_encoding:
                    return JSONResponse(
                        status_code=411,
                        content={
                            "error": {
                                "message": "Content-Length header required for API write requests",
                                "type": "invalid_request_error",
                                "param": None,
                                "code": "length_required",
                            }
                        },
                    )
            if content_length is not None:
                try:
                    size = int(content_length)
                except ValueError:
                    size = 0
                limit = _limit_for_path(path)
                if size > limit:
                    limit_mb = limit // (1024 * 1024)
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "message": f"request body too large (limit {limit_mb} MB)",
                                "type": "invalid_request_error",
                                "param": None,
                                "code": "request_too_large",
                            }
                        },
                    )
        return await call_next(request)
