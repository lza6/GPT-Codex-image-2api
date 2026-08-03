"""图片错误响应 debug 字段透传测试。

覆盖三种错误形态：
- 本地账号池拒选（local_no_quota）→ 429 + accounts_summary
- 上游 HTTP 错误（UpstreamHTTPError）→ 502 + upstream_status_code/body
- 其他异常 → 502 无 debug
"""

from __future__ import annotations

import json

from services.log_service import _image_error_response
from utils.helper import UpstreamHTTPError


def _parse_body(response) -> dict:
    return json.loads(bytes(response.body).decode("utf-8"))


def test_local_no_quota_returns_debug_with_accounts_summary():
    """本地拒选：debug.kind=local_no_quota 且带账号摘要。"""
    exc = RuntimeError("no available image quota (tried 1 tokens)")
    response = _image_error_response(exc)
    assert response.status_code == 429
    body = _parse_body(response)
    error = body.get("error") or {}
    assert error.get("code") == "insufficient_quota"
    debug = error.get("debug") or {}
    assert debug.get("kind") == "local_no_quota"
    # accounts_summary 可能为空列表（无账号时），但字段必须存在
    assert "accounts_summary" in debug
    assert "hint" in debug


def test_upstream_http_error_returns_debug_with_status_and_body():
    """上游错误：debug.kind=upstream_http 且带 status_code/body/retry_after。"""
    upstream_body = {"error": {"message": "rate_limit_exceeded", "type": "tokens"}}
    exc = UpstreamHTTPError(
        "/backend-api/codex/responses",
        429,
        upstream_body,
        retry_after=42,
    )
    response = _image_error_response(exc)
    assert response.status_code == 502
    body = _parse_body(response)
    error = body.get("error") or {}
    assert error.get("code") == "upstream_http_429"
    debug = error.get("debug") or {}
    assert debug.get("kind") == "upstream_http"
    assert debug.get("upstream_status_code") == 429
    assert debug.get("upstream_retry_after") == 42
    assert debug.get("upstream_body") == upstream_body
    assert debug.get("upstream_context") == "/backend-api/codex/responses"


def test_unknown_exception_returns_502_without_debug():
    """其他异常：502 + 无 debug 字段（保持向后兼容）。"""
    exc = RuntimeError("some random failure")
    response = _image_error_response(exc)
    assert response.status_code == 502
    body = _parse_body(response)
    # openai_error_response 可能返回 dict 或 str，看哪种
    if isinstance(body, dict) and "error" in body:
        error = body["error"]
        if isinstance(error, dict):
            assert "debug" not in error
