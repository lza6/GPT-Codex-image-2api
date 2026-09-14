"""G6-S2/S3/S5 测试：图片下载内容白名单、SMTP 弱口令、配置保存审计。

- S2：ImagePipeline._assert_allowed_content_type（image/* 通过 / text/html 拒绝 / 无头警告）
      API 层 _response_mime_type（text/html -> 400，octet-stream + .png 后缀 -> 放行）
- S3：_validate_weak_channel_credentials（development warning / production 拒绝）
- S5：POST /api/settings 审计埋点（成功/失败都 record_admin_access）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

_AUTH = {"Authorization": "Bearer chatgpt2api"}


def _client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# S2 - ImagePipeline 内容类型白名单
# ---------------------------------------------------------------------------


def _assert_allowed(header_type: str) -> None:
    from services.image_pipeline import ImagePipeline

    ImagePipeline._assert_allowed_content_type(header_type, None, "http://example.test/img.png")


def test_whitelist_accepts_image_types() -> None:
    for header_type in ("image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "image/svg+xml"):
        _assert_allowed(header_type)


def test_whitelist_accepts_octet_stream() -> None:
    _assert_allowed("application/octet-stream")


def test_whitelist_rejects_html_and_text() -> None:
    from services.image_failure import ImageDownloadError

    for header_type in ("text/html", "text/plain", "application/json", "application/x-msdownload"):
        with pytest.raises(ImageDownloadError):
            _assert_allowed(header_type)


def test_whitelist_missing_header_warns_but_allows() -> None:

    with patch("services.image_pipeline.logger.warning") as mock_warn:
        # 无 Content-Type 头 -> 保守允许 + 警告
        _assert_allowed("")
    assert mock_warn.call_count == 1


def test_image_download_uses_whitelist_in_pipeline(monkeypatch) -> None:
    """真实 _download 路径：响应带 content-type 头时按白名单校验。"""
    import asyncio

    from services.image_pipeline import ImagePipeline

    class FakeResponse:
        headers = {"content-type": "text/html"}
        content = b"<html>not an image</html>"

        def raise_for_status(self) -> None:
            pass

    async def _run():
        p = ImagePipeline()
        # monkeypatch requests.get 返回 text/html 响应（curl_cffi requests 模块级 patch 目标不对，改 patch requests.get）
        import unittest.mock as um

        import requests as real_requests

        with um.patch.object(real_requests, "get", return_value=FakeResponse()) as mock_get:
            with pytest.raises(Exception) as exc_info:
                await p._download("http://example.test/img.png")
            mock_get.assert_called_once()
        assert "Content-Type 非图片" in str(exc_info.value)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# S2 - API 层 _response_mime_type
# ---------------------------------------------------------------------------


def _fake_response(headers: dict[str, str]) -> MagicMock:
    resp = MagicMock()
    resp.headers = headers
    return resp


def test_api_mime_rejects_text_html() -> None:
    from fastapi import HTTPException

    from api.image_inputs import _response_mime_type

    with pytest.raises(HTTPException) as exc_info:
        _response_mime_type(_fake_response({"content-type": "text/html"}), "/img.png")
    assert exc_info.value.status_code == 400
    assert "image" in str(exc_info.value.detail)


def test_api_mime_accepts_image_and_octet_stream() -> None:
    from api.image_inputs import _response_mime_type

    assert _response_mime_type(_fake_response({"content-type": "image/jpeg"}), "/img") == "image/jpeg"
    # octet-stream + .png 后缀 -> 按后缀 image/png
    assert _response_mime_type(_fake_response({"content-type": "application/octet-stream"}), "/img.png") == "image/png"
    # 无 content-type + .png -> image/png
    assert _response_mime_type(_fake_response({}), "/img.png") == "image/png"


# ---------------------------------------------------------------------------
# S3 - SMTP 弱口令检测
# ---------------------------------------------------------------------------


def _channel(email_cfg: dict) -> dict:
    return {"email_ops": {"type": "email", **email_cfg}}


def test_weak_smtp_password_warns_in_development(capsys) -> None:
    from services.config import _validate_weak_channel_credentials

    _validate_weak_channel_credentials(_channel({"enabled": True, "smtp_password": "admin"}), "development")
    assert "WARNING" in capsys.readouterr().err


def test_weak_smtp_password_rejected_in_production(capsys) -> None:
    from services.config import _validate_weak_channel_credentials

    with pytest.raises(ValueError, match="SMTP"):
        _validate_weak_channel_credentials(_channel({"enabled": True, "smtp_password": "secret"}), "production")
    # production 无 warning（直接拒绝）
    assert "WARNING" not in capsys.readouterr().err


def test_strong_smtp_password_no_warning(capsys) -> None:
    from services.config import _validate_weak_channel_credentials

    _validate_weak_channel_credentials(
        _channel({"enabled": True, "smtp_password": "xK9p#mQ2!vLz7"}), "production"
    )
    assert "WARNING" not in capsys.readouterr().err


def test_disabled_email_channel_not_checked(capsys) -> None:
    from services.config import _validate_weak_channel_credentials

    _validate_weak_channel_credentials(_channel({"enabled": False, "smtp_password": "admin"}), "production")
    assert "WARNING" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# S5 - 配置保存审计埋点
# ---------------------------------------------------------------------------


def test_save_settings_records_audit_success() -> None:
    from services.audit_service import record_admin_access

    with patch("services.audit_service.record_admin_access", wraps=record_admin_access) as mock_audit, \
         patch("services.config.config.update", return_value={"ok": True}):
        client = _client()
        r = client.post("/api/settings", json={"base_url": "http://example.test"}, headers=_AUTH)
        assert r.status_code == 200
        # 至少有一次 /api/settings 的成功审计（record_admin_access 关键字入参，无 operator 参数）
        assert any(
            call.kwargs.get("result") == "success" and call.kwargs.get("action") == "/api/settings"
            for call in mock_audit.call_args_list
        )


def test_save_settings_records_audit_error() -> None:
    from services.audit_service import record_admin_access

    with patch("services.audit_service.record_admin_access", wraps=record_admin_access) as mock_audit, \
         patch("services.config.config.update", side_effect=ValueError("bad config")):
        client = _client()
        r = client.post("/api/settings", json={"base_url": "x"}, headers=_AUTH)
        assert r.status_code == 400
        assert any(
            call.kwargs.get("result") == "error" and call.kwargs.get("action") == "/api/settings"
            for call in mock_audit.call_args_list
        )