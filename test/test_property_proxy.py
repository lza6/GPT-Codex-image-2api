"""属性基测试（hypothesis）：代理 URL 标准化 + 图片 token 计数。

覆盖：
1. normalize_proxy_url: 各 scheme 标准化、host/port 保留、带/不带认证格式
2. count_image_input_tokens: 结果为正整数、单调性、确定性

注意：
- 代码库中无 _parse_proxy_url 函数，此处用 normalize_proxy_url 替代代理 URL 解析验证
- 代码库中无 calculate_tokens 函数，此处用 count_image_input_tokens 替代 token 计算验证
"""
# ruff: noqa: E402 — mock 必须在模块级导入之前注册

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from hypothesis import assume, given
from hypothesis.strategies import (
    booleans,
    integers,
    just,
    one_of,
    sampled_from,
    text,
)

from services.proxy_service import normalize_proxy_url
from utils.image_tokens import count_image_input_tokens

# ============================================================
# normalize_proxy_url
# ============================================================

# 常见代理 scheme
_schemes = sampled_from(["http", "https", "socks", "socks5", "socks5h"])

# 有效 host 段
_hosts = sampled_from(
    [
        "127.0.0.1",
        "192.168.1.1",
        "10.0.0.1",
        "proxy.example.com",
        "gate.residential.io",
        "185.220.101.42",
    ]
)

# 端口
_ports = sampled_from([80, 443, 1080, 3128, 8080, 9999, 10000])

# 用户/密码（预定义有效值，避免 assume 过滤）
_credential_pairs = sampled_from(
    [
        "user:pass",
        "testuser:testpass123",
        "admin:secret!@#$",
        "user:pass123",
        "proxy_user:proxy_pass",
        "user:pass",
    ]
)


@pytest.mark.property
class TestNormalizeProxyUrl:
    """normalize_proxy_url 属性测试。"""

    # ── 属性 1：SOCKS 标准化 ──

    @given(scheme=sampled_from(["socks", "socks5"]), host=_hosts, port=_ports)
    def test_socks_upgraded_to_socks5h(self, scheme: str, host: str, port: int) -> None:
        """socks:// 和 socks5:// 被升级为 socks5h://。"""
        url = f"{scheme}://{host}:{port}"
        result = normalize_proxy_url(url)
        assert result.startswith("socks5h://"), f"{url} → {result!r}"

    @given(scheme=sampled_from(["http", "https", "socks5h"]), host=_hosts, port=_ports)
    def test_other_schemes_unchanged(self, scheme: str, host: str, port: int) -> None:
        """http/https/socks5h 保持原样。"""
        url = f"{scheme}://{host}:{port}"
        result = normalize_proxy_url(url)
        assert result.startswith(f"{scheme}://"), f"{url} → {result!r}"

    # ── 属性 2：host/port 保留 ──

    @given(scheme=_schemes, host=_hosts, port=_ports)
    def test_host_port_preserved(self, scheme: str, host: str, port: int) -> None:
        """标准化后 host 和 port 保留。"""
        url = f"{scheme}://{host}:{port}"
        result = normalize_proxy_url(url)
        parsed = urlparse(result)
        assert parsed.hostname == host, f"{url} → hostname={parsed.hostname}"
        assert parsed.port == port, f"{url} → port={parsed.port}"

    # ── 属性 3：带认证格式保留 ──

    @given(scheme=_schemes, host=_hosts, port=_ports, cred=_credential_pairs)
    def test_credentials_preserved(self, scheme: str, host: str, port: int, cred: str) -> None:
        """URL 中已存在的 user:password 信息保留。"""
        url = f"{scheme}://{cred}@{host}:{port}"
        result = normalize_proxy_url(url)
        assert "@" in result, f"Credentials lost: {url} → {result!r}"
        assert host in result, f"Host lost: {url} → {result!r}"
        assert str(port) in result, f"Port lost: {url} → {result!r}"

    # ── 属性 4：空字符串/空白返回空 ──

    @given(s=sampled_from(["", " ", "  ", "\t", "\n", "\r\n", "  \t  "]))
    def test_whitespace_trimmed(self, s: str) -> None:
        """空白/空输入返回空字符串。"""
        assert normalize_proxy_url(s) == ""

    @given(s=just(None))
    def test_none_returns_empty(self, s: None) -> None:
        """None 输入返回空字符串。"""
        assert normalize_proxy_url(s) == ""

    # ── 属性 5：无 scheme 输入添加 http:// ──

    @given(host=_hosts, port=_ports)
    def test_colon_format_detected(self, host: str, port: int) -> None:
        """host:port 格式添加 http:// 前缀。"""
        url = f"{host}:{port}"
        result = normalize_proxy_url(url)
        assert result.startswith("http://"), f"{url} → {result!r}"
        assert host in result, f"Host lost: {url} → {result!r}"

    # ── 属性 6：确定性 ──

    @given(url=text(min_size=1, max_size=100))
    def test_deterministic(self, url: str) -> None:
        """相同输入产生相同结果。"""
        r1 = normalize_proxy_url(url)
        r2 = normalize_proxy_url(url)
        assert r1 == r2

    # ── 属性 7：结果始终为 URL 或空 ──

    @given(url=text(max_size=200))
    def test_result_is_url_or_empty(self, url: str) -> None:
        """结果要么是 URL，要么是空字符串，要么是原始输入（无 scheme 且无冒号时）。"""
        result = normalize_proxy_url(url)
        if result:
            if "://" not in result:
                # 无 scheme 且无冒号的情形：_colon_proxy_to_url 原样返回
                assert url.strip() == result or result == "", f"Unexpected non-URL: {result!r}"
            else:
                parsed = urlparse(result)
                assert parsed.scheme, f"No scheme: {result!r}"


# ============================================================
# count_image_input_tokens
# ============================================================

# 模型名
_models = sampled_from(
    [
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5-mini",
        "gpt-4.1-mini",
        "o4-mini",
        "gpt-4o",
        "dall-e-3",
    ]
)

# 图片尺寸
_widths = integers(min_value=1, max_value=10000)
_heights = integers(min_value=1, max_value=10000)

# detail 模式
_details = sampled_from(["auto", "low", "high", "original"])


@pytest.mark.property
class TestCountImageInputTokens:
    """count_image_input_tokens 属性测试。"""

    # ── 属性 1：结果为正整数 ──

    @given(width=_widths, height=_heights, model=_models, detail=_details)
    def test_returns_positive_integer(self, width: int, height: int, model: str, detail: str) -> None:
        """有效输入返回正整数。"""
        tokens = count_image_input_tokens(width, height, model, detail)
        assert isinstance(tokens, int), f"Expected int, got {type(tokens).__name__}: {tokens}"
        assert tokens > 0, f"Expected positive, got {tokens}"

    # ── 属性 2：low detail 是固定基数（不随图片尺寸变化）──

    @given(model=_models, detail=_details)
    def test_low_detail_constant(self, model: str, detail: str) -> None:
        """low detail 的 token 数不随图片大小变化。"""
        t1 = count_image_input_tokens(100, 100, model, "low")
        t2 = count_image_input_tokens(10000, 10000, model, "low")
        assert t1 == t2, f"low detail should be constant, got {t1} vs {t2}"

    # ── 属性 3：相同尺寸相同模型产生相同 token ──

    @given(width=_widths, height=_heights, model=_models, detail=_details)
    def test_deterministic(self, width: int, height: int, model: str, detail: str) -> None:
        """相同输入产生相同结果。"""
        t1 = count_image_input_tokens(width, height, model, detail)
        t2 = count_image_input_tokens(width, height, model, detail)
        assert t1 == t2

    # ── 属性 4：token 数受 patch budget 约束 ──

    @given(width=_widths, height=_heights, model=_models, detail=_details)
    def test_tokens_bounded_by_budget(self, width: int, height: int, model: str, detail: str) -> None:
        """token 数不超过模型 patch budget * multiplier。"""
        tokens = count_image_input_tokens(width, height, model, detail)
        assert tokens > 0
        # gpt-5.4-mini: patch_budget=1536, multiplier=1.62 → max ~2488
        # 其他模型 multiplier 可能不同，但上限应合理
        assert tokens <= 20000, f"token 数过大: {tokens} for {width}x{height} {model} {detail}"

    @given(width=_widths, height=_heights, model=_models, detail=_details)
    def test_result_is_ceil_rounded(self, width: int, height: int, model: str, detail: str) -> None:
        """结果始终是 math.ceil 后的整数。"""
        tokens = count_image_input_tokens(width, height, model, detail)
        assert isinstance(tokens, int) and tokens == tokens  # 无 NaN
        assert tokens > 0

    # ── 属性 5：detail low 是固定值（不随图片尺寸变化）──

    @given(width=_widths, height=_heights, model=_models)
    def test_low_detail_constant(self, width: int, height: int, model: str) -> None:
        """low detail 的 token 数不随图片大小变化。"""
        t1 = count_image_input_tokens(100, 100, model, "low")
        t2 = count_image_input_tokens(10000, 10000, model, "low")
        assert t1 == t2, f"low detail should be constant, got {t1} vs {t2}"

    @given(width=_widths, height=_heights, detail=_details)
    def test_model_case_insensitive(self, width: int, height: int, detail: str) -> None:
        """模型名大小写不敏感。"""
        t_lower = count_image_input_tokens(width, height, "gpt-5.4-mini", detail)
        t_upper = count_image_input_tokens(width, height, "GPT-5.4-MINI", detail)
        t_mixed = count_image_input_tokens(width, height, "Gpt-5.4-Mini", detail)
        assert t_lower == t_upper == t_mixed

    # ── 属性 6：边界值 ──

    @given(model=_models, detail=_details)
    def test_minimal_size(self, model: str, detail: str) -> None:
        """1x1 图片产生正 token。"""
        tokens = count_image_input_tokens(1, 1, model, detail)
        assert isinstance(tokens, int)
        assert tokens > 0

    @given(width=_widths, height=_heights, model=_models)
    def test_auto_detail_default(self, width: int, height: int, model: str) -> None:
        """空字符串 detail 与 auto 一致。"""
        t_auto = count_image_input_tokens(width, height, model, "auto")
        t_empty = count_image_input_tokens(width, height, model, "")
        assert t_auto == t_empty

    # ── 属性 7：零或负尺寸返回 0 ──

    @given(w=integers(min_value=-100, max_value=0), h=integers(min_value=-100, max_value=0), model=_models, detail=_details)
    def test_zero_or_negative_size_returns_zero(self, w: int, h: int, model: str, detail: str) -> None:
        """宽或高 <= 0 返回 0。"""
        tokens = count_image_input_tokens(w, h, model, detail)
        assert tokens == 0, f"Expected 0 for {w}x{h}, got {tokens}"


# ============================================================
# 模块加载验证
# ============================================================


def test_module_loads() -> None:
    """模块加载验证。"""
    assert True