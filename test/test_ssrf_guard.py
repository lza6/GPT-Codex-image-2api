"""SSRF 防护测试（D2）：协议白名单 + 内网 IP 段校验 + 重定向防护。"""

from __future__ import annotations

import pytest

from services.ssrf_guard import validate_image_url


def test_allows_public_https_url():
    validate_image_url("https://example.com/image.png")  # 不抛异常即通过


def test_allows_public_ip_literal():
    # 公网 IP 字面量不经 DNS，离线可测
    validate_image_url("http://93.184.216.34/pic.jpg")
    validate_image_url("https://1.1.1.1/image.png")


def test_allows_public_domain(monkeypatch):
    # 域名走 mock，避免依赖外部 DNS（CI 离线可跑）
    monkeypatch.setattr(
        "services.ssrf_guard._resolve_host_ips",
        lambda host: ["93.184.216.34"],
    )
    validate_image_url("http://cdn.example.org/pic.jpg")


def test_rejects_file_scheme():
    with pytest.raises(ValueError, match="http"):
        validate_image_url("file:///etc/passwd")


def test_rejects_ftp_scheme():
    with pytest.raises(ValueError):
        validate_image_url("ftp://example.com/x.png")


def test_rejects_gopher_scheme():
    with pytest.raises(ValueError):
        validate_image_url("gopher://127.0.0.1:6379/_INFO")


def test_rejects_loopback_ipv4():
    with pytest.raises(ValueError, match="内网|private|loopback|拒绝"):
        validate_image_url("http://127.0.0.1/internal")


def test_rejects_loopback_ipv6():
    with pytest.raises(ValueError):
        validate_image_url("http://[::1]/admin")


def test_rejects_private_10():
    with pytest.raises(ValueError):
        validate_image_url("http://10.0.0.5/secret")


def test_rejects_private_172():
    with pytest.raises(ValueError):
        validate_image_url("http://172.16.0.1/router")


def test_rejects_private_192168():
    with pytest.raises(ValueError):
        validate_image_url("http://192.168.1.1/config")


def test_rejects_link_local():
    with pytest.raises(ValueError):
        validate_image_url("http://169.254.169.254/latest/meta-data")


def test_rejects_zero_address():
    with pytest.raises(ValueError):
        validate_image_url("http://0.0.0.0/")


def test_allow_private_ips_config_bypass():
    # 用户 legit 抓内网图床的回退开关
    validate_image_url("http://192.168.1.100/photo.png", allow_private_ips=True)


def test_rejects_empty_or_malformed():
    with pytest.raises(ValueError):
        validate_image_url("")
    with pytest.raises(ValueError):
        validate_image_url("http://")
    with pytest.raises(ValueError):
        validate_image_url("not-a-url")


# ---------------------------------------------------------------------------
# 端到端：_download_image_url 经 SSRF 防护拦截
# ---------------------------------------------------------------------------


def test_download_image_url_rejects_loopback():
    from fastapi import HTTPException

    from api.image_inputs import _download_image_url

    with pytest.raises(HTTPException) as exc_info:
        _download_image_url("http://127.0.0.1:9999/internal")
    assert exc_info.value.status_code == 400
    assert "SSRF" in str(exc_info.value.detail) or "内网" in str(exc_info.value.detail) or "拒绝" in str(exc_info.value.detail)


def test_download_image_url_rejects_file_scheme():
    from fastapi import HTTPException

    from api.image_inputs import _download_image_url

    with pytest.raises(HTTPException) as exc_info:
        _download_image_url("file:///etc/passwd")
    assert exc_info.value.status_code == 400


def test_download_image_url_rejects_redirect_to_private(monkeypatch):
    """重定向到内网 IP 必须被拦截（DNS rebinding / 内网跳转防护）。"""
    from fastapi import HTTPException

    from api import image_inputs

    class _Resp:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data"}

    monkeypatch.setattr(image_inputs.requests, "get", lambda *a, **k: _Resp())
    with pytest.raises(HTTPException) as exc_info:
        image_inputs._download_image_url("http://93.184.216.34/redirect")
    assert exc_info.value.status_code == 400
