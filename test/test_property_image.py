"""属性基测试（hypothesis）：classify_image_exception + should_record_circuit_failure。

覆盖：
- classify_image_exception: 异常类型/状态码/错误文本的组合映射
- should_record_circuit_failure: 各失败码是否应记熔断

注意：utils.helper 有模块级循环依赖（utils.helper → services.proxy_service
→ services.config → services.storage → services.config），因此本文件
在导入 services.image_failure 之前 mock 了 utils.helper，避免
classify_image_exception 函数体内的延迟导入触发循环依赖崩溃。
"""
# ruff: noqa: E402 — mock 必须在模块级导入之前注册

from __future__ import annotations

import sys
import types  # fmt: skip
from typing import Any


# ── 在 services.image_failure 导入前，mock utils.helper ──
# 原 utils.helper 有循环依赖导致模块级 import 失败。classify_image_exception
# 函数体内有 `from utils.helper import UpstreamHTTPError as _UpstreamHTTPError`，
# 仅用于 isinstance 检查。我们提供一个轻量 mock 让该导入成功。
# 注意：运行此文件后，同进程内其他测试若真正需要 utils.helper 其他功能，
# 不应与此文件同进程运行，或需在 conftest 中处理。
class _MockUpstreamHTTPError(RuntimeError):
    """替代 utils.helper.UpstreamHTTPError 的轻量 mock，仅含 classify_image_exception
    需要的字段（status_code, body）。"""

    def __init__(
        self, context: str = "", status_code: int = 0, body: Any = None, retry_after: int | None = None
    ) -> None:
        self.context = context
        self.status_code = status_code
        self.body = body
        self.retry_after = retry_after
        super().__init__()


_mock_helper = types.ModuleType("utils.helper")
_mock_helper.UpstreamHTTPError = _MockUpstreamHTTPError
sys.modules["utils.helper"] = _mock_helper


# ── 正常导入 ──
import pytest  # noqa: E402
from hypothesis import assume, given  # noqa: E402, I001
from hypothesis.strategies import (  # noqa: E402, I001
    integers,
    sampled_from,
    text,
)

from services.image_failure import (  # noqa: E402, I001
    FAILURE_CODE_ALIASES,
    FAILURE_POLICIES,
    FailureScope,
    classify_image_exception,
    should_record_circuit_failure,
)  # fmt: skip

# ============================================================
# 模拟异常类（classify_image_exception 用 type(...).__name__ 匹配）
# 注意：这些类名必须与 production 代码匹配，因为 classify_image_exception
# 检查 type(exc).__name__，而非 isinstance。
# ============================================================


class ImagePollTimeoutError(RuntimeError):
    pass


class ImageContentPolicyError(RuntimeError):
    pass


class ImageRateLimitError(RuntimeError):
    pass


class InvalidAccessTokenError(RuntimeError):
    pass


# ============================================================
# 常量
# ============================================================

_transient_codes = [k for k, v in FAILURE_POLICIES.items() if v.scope is FailureScope.TRANSIENT]
_non_transient_codes = [k for k, v in FAILURE_POLICIES.items() if v.scope is not FailureScope.TRANSIENT]
_all_failure_keys = list(FAILURE_POLICIES.keys())
_all_input_codes = _all_failure_keys + list(FAILURE_CODE_ALIASES.keys())


def _upstream(status_code: int, body: Any = None) -> Any:
    """创建 mock UpstreamHTTPError 实例（无需导入 utils.helper）。"""
    return _MockUpstreamHTTPError("test", status_code, body)


# ============================================================
# classify_image_exception
# ============================================================


@pytest.mark.property
class TestClassifyImageException:
    """classify_image_exception 属性测试。"""

    # ── 属性 1：输出始终是合法失败码 ──

    @given(exc=text(max_size=200))
    def test_string_returns_valid_code(self, exc: str) -> None:
        """字符串输入始终返回 FAILURE_POLICIES 中的合法码。"""
        code = classify_image_exception(exc)
        assert code in FAILURE_POLICIES, f"Unexpected code {code!r} from {exc!r}"

    @given(status=integers(min_value=100, max_value=599))
    def test_upstream_http_returns_valid_code(self, status: int) -> None:
        """UpstreamHTTPError 始终返回合法码。"""
        code = classify_image_exception(_upstream(status))
        assert code in FAILURE_POLICIES, f"Unexpected code {code!r} from status {status}"

    # ── 属性 2：UpstreamHTTPError 状态码映射正确 ──

    @given(status=integers(min_value=500, max_value=599))
    def test_5xx_returns_transient(self, status: int) -> None:
        """5xx 状态码返回 TRANSIENT 域失败码。"""
        code = classify_image_exception(_upstream(status))
        assert FAILURE_POLICIES[code].scope is FailureScope.TRANSIENT

    @given(status=sampled_from([403, 423]))
    def test_403_423_returns_upstream_unavailable(self, status: int) -> None:
        """403/423 → upstream_unavailable。"""
        assert classify_image_exception(_upstream(status)) == "upstream_unavailable"

    @given(status=sampled_from([408, 504]))
    def test_408_504_returns_connection_timeout(self, status: int) -> None:
        """408/504 → upstream_connection_timeout。"""
        assert classify_image_exception(_upstream(status)) == "upstream_connection_timeout"

    def test_401_returns_auth_invalid(self) -> None:
        """401 → auth_invalid。"""
        assert classify_image_exception(_upstream(401)) == "auth_invalid"

    def test_429_returns_rate_limited(self) -> None:
        """429 → upstream_rate_limited。"""
        assert classify_image_exception(_upstream(429)) == "upstream_rate_limited"

    def test_400_moderation_body(self) -> None:
        """400 + moderation body → content_policy_violation。"""
        assert (
            classify_image_exception(_upstream(400, {"code": "moderation"}))
            == "content_policy_violation"
        )
        assert (
            classify_image_exception(
                _upstream(400, {"error": {"code": "content_policy_violation"}})
            )
            == "content_policy_violation"
        )

    def test_400_quota_body(self) -> None:
        """400 + quota body → image_quota_exhausted。"""
        assert (
            classify_image_exception(_upstream(400, {"code": "insufficient_quota"}))
            == "image_quota_exhausted"
        )

    def test_400_unknown_body(self) -> None:
        """400 + 未知 body → invalid_image_input。"""
        assert classify_image_exception(_upstream(400, "some random error")) == "invalid_image_input"

    # ── 属性 3：自定义异常类型名称匹配正确 ──

    def test_poll_timeout_exception(self) -> None:
        """ImagePollTimeoutError → image_poll_timeout。"""
        assert classify_image_exception(ImagePollTimeoutError()) == "image_poll_timeout"

    def test_content_policy_exception(self) -> None:
        """ImageContentPolicyError → content_policy_violation。"""
        assert classify_image_exception(ImageContentPolicyError()) == "content_policy_violation"

    def test_rate_limit_exception(self) -> None:
        """ImageRateLimitError → upstream_rate_limited。"""
        assert classify_image_exception(ImageRateLimitError()) == "upstream_rate_limited"

    def test_invalid_token_exception(self) -> None:
        """InvalidAccessTokenError → auth_invalid。"""
        assert classify_image_exception(InvalidAccessTokenError()) == "auth_invalid"

    def test_unknown_exception_falls_back(self) -> None:
        """未知异常类型 → 走 str(exc) 文本分类。"""
        assert classify_image_exception(RuntimeError("random")) == "upstream_error"

    # ── 属性 4：字符串关键词映射正确 ──

    @given(
        msg=sampled_from(
            [
                "moderation",
                "content_policy",
                "safety block",
                "blocked by policy",
            ]
        )
    )
    def test_moderation_keywords(self, msg: str) -> None:
        """含 moderation/safety 关键词 → content_policy_violation。"""
        assert classify_image_exception(msg) == "content_policy_violation", f"Failed for {msg!r}"

    @given(msg=sampled_from(["insufficient_quota", "quota_exhausted", "quota exhausted"]))
    def test_quota_keywords(self, msg: str) -> None:
        """含 quota 关键词 → image_quota_exhausted。"""
        assert classify_image_exception(msg) == "image_quota_exhausted", f"Failed for {msg!r}"

    @given(msg=sampled_from(["rate_limit_exceeded", "rate limit", "too many requests", "429"]))
    def test_rate_limit_keywords(self, msg: str) -> None:
        """含限流关键词 → upstream_rate_limited。"""
        assert classify_image_exception(msg) == "upstream_rate_limited", f"Failed for {msg!r}"

    @given(
        msg=sampled_from(
            ["token_invalidated", "token_revoked", "invalid access token", "401"]
        )
    )
    def test_auth_invalid_keywords(self, msg: str) -> None:
        """含 token 失效关键词 → auth_invalid。"""
        assert classify_image_exception(msg) == "auth_invalid", f"Failed for {msg!r}"

    @given(msg=sampled_from(["poll_timeout", "生图超时"]))
    def test_poll_timeout_keywords(self, msg: str) -> None:
        """含轮询超时关键词 → image_poll_timeout。"""
        assert classify_image_exception(msg) == "image_poll_timeout", f"Failed for {msg!r}"

    @given(
        msg=sampled_from(
            [
                "curl: (35)",
                "tls connect error",
                "openssl_internal",
                "connection reset by peer",
                "connection refused",
            ]
        )
    )
    def test_tls_connection_keywords(self, msg: str) -> None:
        """含 TLS/连接错误关键词 → upstream_connection_failed。"""
        assert classify_image_exception(msg) == "upstream_connection_failed", f"Failed for {msg!r}"

    @given(
        msg=sampled_from(
            [
                "curl: (28)",
                "operation timed out",
                "connection timed out",
                "read timed out",
            ]
        )
    )
    def test_timeout_keywords(self, msg: str) -> None:
        """含超时关键词 → upstream_connection_timeout。"""
        assert classify_image_exception(msg) == "upstream_connection_timeout", f"Failed for {msg!r}"

    @given(
        msg=sampled_from(
            [
                "500",
                "502",
                "503",
                "504",
                "520",
                "service unavailable",
                "bad gateway",
            ]
        )
    )
    def test_server_error_keywords(self, msg: str) -> None:
        """含 5xx/网关错误关键词 → upstream_unavailable。"""
        assert classify_image_exception(msg) == "upstream_unavailable", f"Failed for {msg!r}"

    @given(msg=sampled_from(["unsupported image model", "unsupported model"]))
    def test_unsupported_model_keywords(self, msg: str) -> None:
        """含不支持的模型关键词 → unsupported_model。"""
        assert classify_image_exception(msg) == "unsupported_model", f"Failed for {msg!r}"

    def test_text_reply_keyword(self) -> None:
        """text reply → upstream_text_reply。"""
        assert classify_image_exception("text reply") == "upstream_text_reply"

    def test_upstream_text_reply_keyword(self) -> None:
        """upstream + text + reply → upstream_text_reply。"""
        assert classify_image_exception("upstream text reply") == "upstream_text_reply"

    # ── 属性 5：边界值 ──

    def test_empty_string(self) -> None:
        """空字符串 → upstream_error。"""
        assert classify_image_exception("") == "upstream_error"

    def test_lowercase_normalization(self) -> None:
        """大小写不敏感。"""
        assert classify_image_exception("MODERATION") == "content_policy_violation"
        assert classify_image_exception("Content_Policy") == "content_policy_violation"

    # ── 属性 6：确定性 ──

    @given(exc=text(max_size=50))
    def test_deterministic(self, exc: str) -> None:
        """相同输入产生相同结果。"""
        assert classify_image_exception(exc) == classify_image_exception(exc)


# ============================================================
# should_record_circuit_failure
# ============================================================


@pytest.mark.property
class TestShouldRecordCircuitFailure:
    """should_record_circuit_failure 属性测试。"""

    # ── 属性 1：类型稳定 ──

    @given(code=sampled_from(_all_input_codes))
    def test_returns_bool(self, code: str) -> None:
        """始终返回 bool。"""
        assert isinstance(should_record_circuit_failure(code), bool)

    @given(code=text(min_size=1, max_size=50))
    def test_unknown_code_returns_bool(self, code: str) -> None:
        """未知码始终返回 bool（不抛异常）。"""
        result = should_record_circuit_failure(code)
        assert isinstance(result, bool)

    # ── 属性 2：TRANSIENT → True ──

    @given(code=sampled_from(_transient_codes))
    def test_transient_returns_true(self, code: str) -> None:
        """TRANSIENT 域失败码 → True。"""
        assert should_record_circuit_failure(code) is True

    # ── 属性 3：非 TRANSIENT → False ──

    @given(code=sampled_from(_non_transient_codes))
    def test_non_transient_returns_false(self, code: str) -> None:
        """非 TRANSIENT 域（ACCOUNT/REQUEST/INTERNAL）→ False。"""
        assert should_record_circuit_failure(code) is False

    # ── 属性 4：未知码 → True（归一至 upstream_error → TRANSIENT）──

    @given(code=text(min_size=1, max_size=30))
    def test_unknown_code_returns_true(self, code: str) -> None:
        """未知失败码归一为 upstream_error（TRANSIENT）→ True。"""
        assume(code not in FAILURE_POLICIES and code not in FAILURE_CODE_ALIASES)
        assert should_record_circuit_failure(code) is True

    # ── 属性 5：None → True ──

    def test_none_returns_true(self) -> None:
        """None → normalize 为 upstream_error（TRANSIENT）→ True。"""
        assert should_record_circuit_failure(None) is True

    # ── 属性 6：确定性 ──

    @given(code=sampled_from(_all_input_codes))
    def test_deterministic(self, code: str) -> None:
        """相同输入产生相同结果。"""
        assert should_record_circuit_failure(code) == should_record_circuit_failure(code)


# ============================================================
# 模块加载验证
# ============================================================


def test_module_loads() -> None:
    """模块加载验证。"""
    assert True