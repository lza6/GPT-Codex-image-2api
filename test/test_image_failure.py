"""统一失败分类（services/image_failure.py）单元测试 —— ADR-015。

重点守护「业务拒绝绝不进熔断」这一历史 bug 根因边界：
熔断 record_failure 仅对上游瞬时抖动（TRANSIENT）返回 True。
"""

from __future__ import annotations

import pytest

from services.image_failure import (
    FailureScope,
    classify_upstream_http_error,
    failure_policy,
    normalize_failure_code,
    should_record_circuit_failure,
    should_switch_account,
    verify_account,
)
from utils.helper import UpstreamHTTPError

pytestmark = pytest.mark.unit


class TestNormalize:
    def test_known_code_passthrough(self):
        assert normalize_failure_code("upstream_error") == "upstream_error"

    def test_alias_collapses(self):
        assert normalize_failure_code("moderation_blocked") == "content_policy_violation"
        assert normalize_failure_code("token_revoked") == "auth_invalid"
        assert normalize_failure_code("insufficient_quota") == "image_quota_exhausted"
        assert normalize_failure_code("rate_limit_exceeded") == "upstream_rate_limited"

    def test_unknown_code_falls_back(self):
        assert normalize_failure_code("some_random_thing") == "upstream_error"
        assert normalize_failure_code("") == "upstream_error"
        assert normalize_failure_code(None) == "upstream_error"

    def test_case_and_whitespace_insensitive(self):
        assert normalize_failure_code("  CONTENT_POLICY_VIOLATION ") == "content_policy_violation"


class TestCircuitBreakerBoundary:
    """核心红线：只有上游瞬时抖动才记熔断。"""

    @pytest.mark.parametrize(
        "code",
        ["upstream_error", "upstream_unavailable", "upstream_connection_failed", "image_poll_timeout"],
    )
    def test_transient_records_failure(self, code):
        assert should_record_circuit_failure(code) is True

    @pytest.mark.parametrize(
        "code",
        [
            "content_policy_violation",  # 审核拒绝
            "invalid_image_input",
            "upstream_text_reply",  # 文本回复（业务结果）
            "unsupported_model",
            "auth_invalid",  # 账号态而非上游抖动
            "image_quota_exhausted",
            "upstream_rate_limited",
        ],
    )
    def test_business_or_account_rejection_never_records(self, code):
        """业务拒绝/账号态被恶意输入触发时，绝不能熔断健康账号。"""
        assert should_record_circuit_failure(code) is False

    def test_alias_business_rejection_never_records(self):
        assert should_record_circuit_failure("moderation_blocked") is False
        assert should_record_circuit_failure("safety_blocked") is False


class TestSwitchAccount:
    @pytest.mark.parametrize("code", ["auth_invalid", "image_quota_exhausted", "upstream_rate_limited", "upstream_error"])
    def test_account_and_transient_switch(self, code):
        assert should_switch_account(code) is True

    @pytest.mark.parametrize("code", ["content_policy_violation", "upstream_text_reply", "invalid_image_input", "unsupported_model"])
    def test_request_rejection_no_switch(self, code):
        assert should_switch_account(code) is False


class TestPolicyMetadata:
    def test_status_codes(self):
        assert failure_policy("auth_invalid").status_code == 401
        assert failure_policy("upstream_rate_limited").status_code == 429
        assert failure_policy("content_policy_violation").status_code == 400

    def test_error_types(self):
        assert failure_policy("auth_invalid").error_type == "authentication_error"
        assert failure_policy("image_quota_exhausted").error_type == "insufficient_quota"
        assert failure_policy("upstream_rate_limited").error_type == "rate_limit_error"

    def test_scope_mapping(self):
        assert failure_policy("upstream_error").scope is FailureScope.TRANSIENT
        assert failure_policy("auth_invalid").scope is FailureScope.ACCOUNT
        assert failure_policy("content_policy_violation").scope is FailureScope.REQUEST

    def test_verify_account_flags(self):
        assert verify_account("auth_invalid") is True
        assert verify_account("content_policy_violation") is False


class TestClassifyUpstreamHTTPError:
    def _err(self, status: int, body=None) -> UpstreamHTTPError:
        return UpstreamHTTPError("/backend-api/conversation", status, body)

    def test_401_auth_invalid(self):
        assert classify_upstream_http_error(self._err(401, {"error": "invalid token"})) == "auth_invalid"

    def test_429_rate_limited(self):
        assert classify_upstream_http_error(self._err(429, "too many")) == "upstream_rate_limited"

    def test_5xx_unavailable(self):
        assert classify_upstream_http_error(self._err(502, "bad gateway")) == "upstream_unavailable"
        assert classify_upstream_http_error(self._err(503)) == "upstream_unavailable"

    def test_504_timeout(self):
        assert classify_upstream_http_error(self._err(504)) == "upstream_connection_timeout"

    def test_400_content_policy(self):
        body = {"error": {"code": "moderation_blocked", "message": "blocked"}}
        assert classify_upstream_http_error(self._err(400, body)) == "content_policy_violation"

    def test_400_invalid_input_default(self):
        assert classify_upstream_http_error(self._err(400, {"error": {"code": "bad"}})) == "invalid_image_input"

    def test_classification_never_marks_400_as_circuit_failure(self):
        """真实 400 业务拒绝经分类后仍不得记熔断（端到端不变量）。"""
        code = classify_upstream_http_error(self._err(400, {"error": {"code": "moderation_blocked"}}))
        assert should_record_circuit_failure(code) is False


# ---------------------------------------------------------------- N6b：classify_image_exception 接入入口
class TestClassifyImageException:
    """N6b 接入点：异常/字符串 → 失败码，且熔断判定与白名单一致。"""

    def test_custom_exception_types(self):
        from services.openai_backend_api import (
            ImageContentPolicyError,
            ImagePollTimeoutError,
            ImageRateLimitError,
            InvalidAccessTokenError,
        )
        from services.image_failure import classify_image_exception

        assert classify_image_exception(ImagePollTimeoutError("t")) == "image_poll_timeout"
        assert classify_image_exception(ImageContentPolicyError("c")) == "content_policy_violation"
        assert classify_image_exception(ImageRateLimitError("r")) == "upstream_rate_limited"
        assert classify_image_exception(InvalidAccessTokenError("i")) == "auth_invalid"

    def test_upstream_http_error_delegates(self):
        from services.image_failure import classify_image_exception
        err = UpstreamHTTPError("/x", 503, "unavailable")
        assert classify_image_exception(err) == "upstream_unavailable"

    def test_business_rejection_never_circuit_failure(self):
        """业务拒绝（审核/配额/文本回复）经 classify 后仍不记熔断（接入点不变量）。"""
        from services.image_failure import classify_image_exception
        for msg in ("moderation_blocked by safety", "insufficient_quota", "unsupported image model"):
            code = classify_image_exception(Exception(msg))
            assert should_record_circuit_failure(code) is False

    def test_transient_marks_circuit_failure(self):
        """上游抖动（5xx/超时/TLS）经 classify 后记熔断。"""
        from services.image_failure import classify_image_exception
        for msg in ("upstream 502 bad gateway", "connection timed out curl: (28)", "ssl: wrong_version_number"):
            code = classify_image_exception(Exception(msg))
            assert should_record_circuit_failure(code) is True

    def test_account_state_switch_not_circuit(self):
        """账号态（限流/配额/token）换号但不记抖动熔断。"""
        from services.image_failure import classify_image_exception
        for msg in ("rate_limit_exceeded 429", "token_invalidated"):
            code = classify_image_exception(Exception(msg))
            assert should_switch_account(code) is True
            assert should_record_circuit_failure(code) is False
