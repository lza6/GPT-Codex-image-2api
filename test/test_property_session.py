"""属性基测试（hypothesis）：SessionPool key 生成 + 重试预算。

覆盖：
1. SessionPool._make_key: key 包含账号标识(末8位)+指纹
2. retry_budget: 预算在合理范围内（retry_idempotent_get / can_retry_stream）
"""
# ruff: noqa: E402 — mock 必须在模块级导入之前注册

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import assume, given, settings
from hypothesis.strategies import booleans, integers, just, sampled_from, text

from services.retry_budget import (
    PRE_STREAM_SWITCH_MAX_RETRIES,
    can_retry_stream,
    retry_idempotent_get,
)
from services.session_pool import SessionPool, proxy_settings, session_kwargs_cache

# ============================================================
# Strategies
# ============================================================

# token 字母表（access_token 常见字符）
_TOKEN_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"

# 短 token（< 8 字符，应触发 "anon" 兜底）
_short_token = text(min_size=0, max_size=7, alphabet=_TOKEN_CHARS)
# 长 token（>= 8 字符，可提取末 8 位）
_long_token = text(min_size=8, max_size=64, alphabet=_TOKEN_CHARS)
# 任意 token
_any_token = text(min_size=0, max_size=64, alphabet=_TOKEN_CHARS)

# 指纹 key（不含管道符，避免破坏 key 格式）
_fp_key = text(min_size=0, max_size=32, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-")

# 常用 impersonate 值
_impersonate = sampled_from(
    ["chrome110", "chrome120", "safari15_5", "edge99", "firefox110", "safari17_0"]
)


# ============================================================
# Mock：避免 _make_key 真实调用 proxy_settings.get_profile
# ============================================================


@pytest.fixture(autouse=True)
def _mock_session_deps():
    """mock proxy_settings.get_profile 和 session_kwargs_cache，使 _make_key 可控。"""
    with patch.object(proxy_settings, "get_profile") as mock_get_profile:
        with patch.object(session_kwargs_cache, "get", return_value=None):
            with patch.object(session_kwargs_cache, "set"):
                mock_profile = MagicMock()
                mock_profile.proxy_url = "http://test:8080"
                mock_get_profile.return_value = mock_profile
                yield


# ============================================================
# SessionPool._make_key
# ============================================================


@pytest.mark.property
class TestMakeKeyProperties:
    """SessionPool._make_key 属性测试：key 包含账号标识(末8位)+指纹。"""

    def setup_method(self) -> None:
        self.pool = SessionPool()

    # ── 属性 1：key 含账号末 8 位 ──

    @given(token=_long_token, fp=_fp_key, im=_impersonate)
    def test_key_contains_token_suffix(self, token: str, fp: str, im: str) -> None:
        """key 包含 access_token 末 8 位。"""
        account = {"access_token": token}
        key = self.pool._make_key(account, im, True, fp)
        assert token[-8:] in key, f"key={key!r} 不含 token 末 8 位 {token[-8:]}"

    # ── 属性 2：无 token 时 key 含 "anon" ──

    @given(token=_short_token, fp=_fp_key, im=_impersonate)
    def test_no_token_uses_anon(self, token: str, fp: str, im: str) -> None:
        """空 token 时 key 包含 'anon'（代码对非空短 token 用 token[-8:] 即原样）。"""
        account = {"access_token": token} if token else None
        if not token:
            account = None
        key = self.pool._make_key(account, im, True, fp)
        if not token:
            assert "anon" in key, f"key={key!r} 不含 'anon'"
        else:
            assert token in key, f"key={key!r} 应含 token={token!r}"

    # ── 属性 3：key 含指纹标识 ──

    @given(token=_any_token, fp=_fp_key, im=_impersonate)
    def test_key_contains_fingerprint(self, token: str, fp: str, im: str) -> None:
        """key 最后一段为 fp_key（空值时也为空字符串）。"""
        account = {"access_token": token} if token else None
        key = self.pool._make_key(account, im, True, fp)
        parts = key.split("|")
        assert parts[-1] == fp, f"key={key!r} 最后一段应为 {fp!r}，实际为 {parts[-1]!r}"

    # ── 属性 4：不同指纹不同 key ──

    @given(token=_long_token, fp1=_fp_key, fp2=_fp_key)
    def test_different_fp_different_key(self, token: str, fp1: str, fp2: str) -> None:
        """不同指纹产生不同 key（同账号同代理）。"""
        assume(fp1 != fp2)
        account = {"access_token": token}
        key1 = self.pool._make_key(account, "chrome110", True, fp1)
        key2 = self.pool._make_key(account, "chrome110", True, fp2)
        assert key1 != key2, f"不同指纹应产生不同 key: {key1}"

    # ── 属性 5：不同 token 不同 key ──

    @given(token1=_long_token, token2=_long_token)
    def test_different_token_different_key(self, token1: str, token2: str) -> None:
        """不同 token（末 8 位不同）产生不同 key。"""
        assume(token1[-8:] != token2[-8:])
        account1 = {"access_token": token1}
        account2 = {"access_token": token2}
        key1 = self.pool._make_key(account1, "chrome110", True, "")
        key2 = self.pool._make_key(account2, "chrome110", True, "")
        assert key1.split("|")[0] != key2.split("|")[0]

    # ── 属性 6：key 为 5 段管道分隔格式 ──

    @given(token=_any_token, fp=_fp_key, im=_impersonate)
    def test_key_format_five_parts(self, token: str, fp: str, im: str) -> None:
        """key 格式为 acct_id|proxy|impersonate|verify|fp（5 段）。"""
        account = {"access_token": token} if token else None
        key = self.pool._make_key(account, im, True, fp)
        parts = key.split("|")
        assert len(parts) == 5, f"key={key!r} 应为 5 段，实际 {len(parts)} 段"

    # ── 属性 7：verify 布尔值编码为 0/1 ──

    @given(token=_any_token, verify=booleans())
    def test_verify_encoded_as_int(self, token: str, verify: bool) -> None:
        """verify 布尔值正确编码为 '0' 或 '1' 在 key 的第 4 段。"""
        account = {"access_token": token} if token else None
        key = self.pool._make_key(account, "chrome110", verify, "")
        parts = key.split("|")
        assert parts[3] == str(int(verify)), f"verify={verify} → 第 4 段应为 {int(verify)}"

    # ── 属性 8：impersonate 出现在 key 第 3 段 ──

    @given(token=_any_token, im=_impersonate)
    def test_impersonate_in_key(self, token: str, im: str) -> None:
        """impersonate 值出现在 key 第 3 段。"""
        account = {"access_token": token} if token else None
        key = self.pool._make_key(account, im, True, "")
        parts = key.split("|")
        assert parts[2] == im, f"impersonate={im!r} → 第 3 段应为 {im!r}，实际为 {parts[2]!r}"

    # ── 属性 9：空指纹时 key 末尾合法 ──

    @given(token=_any_token, im=_impersonate, verify=booleans())
    def test_empty_fp_ends_with_verify(self, token: str, im: str, verify: bool) -> None:
        """fp_key="" 时 key 第 5 段为空，末尾为 |0 或 |1。"""
        account = {"access_token": token} if token else None
        key = self.pool._make_key(account, im, verify, "")
        assert key.endswith(f"|{int(verify)}|"), f"key={key!r} 空 fp 时末尾应为 |{int(verify)}|"


# ============================================================
# retry_idempotent_get
# ============================================================


class _AlwaysFail:
    """总是抛出 ValueError 的 callable。"""

    def __init__(self) -> None:
        self.attempts = 0

    def __call__(self) -> None:
        self.attempts += 1
        raise ValueError("always fail")


class _SucceedOnAttempt:
    """第 N 次尝试时成功。"""

    def __init__(self, succeed_at: int = 0) -> None:
        self.attempts = 0
        self.succeed_at = succeed_at

    def __call__(self) -> str:
        self.attempts += 1
        if self.attempts > self.succeed_at:
            return "ok"
        raise ValueError(f"attempt {self.attempts}")


@pytest.mark.property
class TestRetryBudgetProperties:
    """retry_idempotent_get 属性测试：预算在合理范围内。"""

    # ── 属性 1：重试次数不超预算 ──

    @given(max_retries=integers(min_value=0, max_value=5))
    @settings(deadline=None)
    def test_retry_count_does_not_exceed_budget(self, max_retries: int) -> None:
        """重试次数不超过 max_retries（总调用 = max_retries+1）。"""
        fn = _AlwaysFail()
        with pytest.raises(ValueError):
            retry_idempotent_get(fn, max_retries=max_retries)
        assert fn.attempts <= max_retries + 1, (
            f"max_retries={max_retries} 时尝试 {fn.attempts} 次，预期 ≤{max_retries + 1}"
        )

    # ── 属性 2：首次成功返回结果 ──

    @given(max_retries=integers(min_value=0, max_value=5))
    def test_first_attempt_success_returns_result(self, max_retries: int) -> None:
        """首次调用成功时直接返回结果，不重试。"""
        fn = _SucceedOnAttempt(succeed_at=0)
        result = retry_idempotent_get(fn, max_retries=max_retries)
        assert result == "ok"
        assert fn.attempts == 1

    # ── 属性 3：max_retries=0 只尝试一次 ──

    def test_zero_retries_attempts_once(self) -> None:
        """max_retries=0 时只尝试一次，失败即抛出。"""
        fn = _AlwaysFail()
        with pytest.raises(ValueError):
            retry_idempotent_get(fn, max_retries=0)
        assert fn.attempts == 1

    # ── 属性 4：最后一次重试成功返回结果 ──

    @given(max_retries=integers(min_value=1, max_value=5))
    @settings(deadline=None)
    def test_last_retry_succeeds(self, max_retries: int) -> None:
        """在最后一次重试成功时返回结果。"""
        fn = _SucceedOnAttempt(succeed_at=max_retries)
        result = retry_idempotent_get(fn, max_retries=max_retries)
        assert result == "ok"
        assert fn.attempts == max_retries + 1

    # ── 属性 5：不可重试异常直接抛出 ──

    @given(max_retries=integers(min_value=1, max_value=3))
    def test_non_retryable_exception_immediate_raise(self, max_retries: int) -> None:
        """retryable 返回 False 的异常不重试、直接抛出。"""
        fn = _AlwaysFail()
        with pytest.raises(ValueError):
            retry_idempotent_get(
                fn, max_retries=max_retries, retryable=lambda exc: isinstance(exc, KeyError)
            )
        assert fn.attempts == 1, "不可重试异常应仅尝试 1 次"


# ============================================================
# can_retry_stream
# ============================================================


@pytest.mark.property
class TestCanRetryStreamProperties:
    """can_retry_stream 属性测试：预算在合理范围内。"""

    # ── 属性 1：emitted=True 永不重试 ──

    def test_emitted_never_retry(self) -> None:
        """已发出任何内容（emitted=True）→ 永不重试。"""
        assert can_retry_stream(True, pre_stream_retries_used=0) is False
        assert can_retry_stream(True, pre_stream_retries_used=1) is False
        assert can_retry_stream(True, pre_stream_retries_used=99) is False

    # ── 属性 2：未发出且预算内 → 可重试 ──

    @given(used=integers(min_value=0, max_value=0))
    def test_not_emitted_within_budget(self, used: int) -> None:
        """未发出且重试次数未达上限（< PRE_STREAM_SWITCH_MAX_RETRIES）→ 可重试。"""
        assert can_retry_stream(False, pre_stream_retries_used=used) is True

    # ── 属性 3：未发出但超预算 → 不可重试 ──

    @given(used=integers(min_value=1, max_value=100))
    def test_not_emitted_exceed_budget(self, used: int) -> None:
        """未发出但已用完重试预算 → 不可重试。"""
        assert can_retry_stream(False, pre_stream_retries_used=used) is False

    # ── 属性 4：emitted 覆盖剩余预算 ──

    @given(used=integers(min_value=0, max_value=100))
    def test_emitted_overrides_remaining_budget(self, used: int) -> None:
        """emitted=True 时无论剩余预算如何都返回 False。"""
        assert can_retry_stream(True, pre_stream_retries_used=used) is False

    # ── 属性 5：返回值始终是布尔值 ──

    @given(emitted=booleans(), used=integers(min_value=0, max_value=5))
    def test_returns_bool(self, emitted: bool, used: int) -> None:
        """返回值始终是 bool 类型。"""
        result = can_retry_stream(emitted, pre_stream_retries_used=used)
        assert isinstance(result, bool)


def test_module_loads() -> None:
    """模块加载验证。"""
    assert True