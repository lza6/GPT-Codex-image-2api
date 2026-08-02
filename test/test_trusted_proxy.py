"""XFF 伪造防护测试（D3）：trusted_proxies 白名单。"""

from __future__ import annotations

from services.config import ConfigStore


def _ip_for(client_host: str, xff: str, trusted: list[str]) -> str:
    from api.rate_limit import resolve_client_ip

    return resolve_client_ip(client_host, {"x-forwarded-for": xff}, trusted)


def test_xff_ignored_when_client_not_trusted():
    # 连接 IP 不在白名单 → 忽略 XFF，用连接 IP
    assert _ip_for("203.0.113.5", "1.2.3.4", ["127.0.0.1"]) == "203.0.113.5"


def test_xff_honored_when_client_trusted():
    # 连接 IP 在白名单（反向代理）→ 信任 XFF 首跳
    assert _ip_for("127.0.0.1", "1.2.3.4, 10.0.0.1", ["127.0.0.1"]) == "1.2.3.4"


def test_xff_honored_for_ipv6_loopback():
    assert _ip_for("::1", "5.6.7.8", ["127.0.0.1", "::1"]) == "5.6.7.8"


def test_no_xff_falls_back_to_client():
    assert _ip_for("198.51.100.9", "", ["127.0.0.1"]) == "198.51.100.9"


def test_empty_trusted_list_never_trusts_xff():
    assert _ip_for("10.0.0.2", "9.9.9.9", []) == "10.0.0.2"


def test_config_trusted_proxies_default():
    from services.config import config

    assert config.trusted_proxies == ["127.0.0.1", "::1"]


def test_config_trusted_proxies_env_override(monkeypatch):
    from services.config import config

    monkeypatch.setenv("CHATGPT2API_TRUSTED_PROXIES", "10.0.0.1, 10.0.0.2")
    assert config.trusted_proxies == ["10.0.0.1", "10.0.0.2"]


def test_config_trusted_proxies_schema_validation():
    import pytest

    with pytest.raises(ValueError, match="trusted_proxies"):
        ConfigStore._validate_schema({"trusted_proxies": 123})
    # 合法类型不抛错
    ConfigStore._validate_schema({"trusted_proxies": ["10.0.0.1"]})
    ConfigStore._validate_schema({"trusted_proxies": "10.0.0.1,10.0.0.2"})
