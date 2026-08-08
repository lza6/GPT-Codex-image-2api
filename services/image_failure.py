"""统一图片失败分类（对标上游 v3.0 `image_failure.py` 的主项目裁剪版）。

设计目标（ADR-015）：把「这次失败要不要换号 / 要不要记熔断 / 对用户显示什么」
收敛为一组可测的纯函数，替代散落在各调用点的字符串匹配。

与主项目现有判定的关系（不改动现有函数，仅新增本模块）：
- `conversation.is_upstream_instability_error` 仍是熔断 record_failure 的正向白名单。
  本模块的 `should_record_circuit_failure` 复用同一语义（上游抖动才记），保持单一事实来源。
- `conversation.is_token_invalid_error` / `is_tls_connection_error` /
  `is_connection_timeout_error` 仍负责文本级识别，本模块在其上做「分类」。

边界（诚实）：
- 本模块只做「分类 + 公共文案 + 决策谓词」，不改变任何现有调用方行为；
  接入由后续节点逐个进行，接入点须保持熔断白名单语义不回退。
- 术语遵循 docs/domain-context.md：业务拒绝（content_policy/quota/text_reply）
  不是上游抖动，绝不计熔断。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from utils.helper import UpstreamHTTPError


class FailureScope(StrEnum):
    """失败归因域：换号/熔断策略按域区分。"""

    TRANSIENT = "transient"  # 上游瞬时抖动（5xx/超时/TLS/连接）→ 记熔断、可换号
    ACCOUNT = "account"  # 账号态问题（配额/限流/token 失效）→ 换号，不记「抖动」熔断
    REQUEST = "request"  # 请求/业务拒绝（审核/违规/文本回复）→ 不换号不记熔断，直接对用户
    INTERNAL = "internal"  # 本地/未知错误 → 默认上游异常，保守记熔断由白名单裁决


@dataclass(frozen=True)
class FailurePolicy:
    """单个失败码的处置策略（不可变）。"""

    scope: FailureScope
    status_code: int
    error_type: str
    public_message: str
    verify_account: bool = False  # 是否触发账号核验/处置（换号依据之一）


# 失败码注册表：唯一的「失败语义」事实来源。
# public_message 仅作占位兜底；对外公共文案统一经 public_image_error_message 裁决。
FAILURE_POLICIES: dict[str, FailurePolicy] = {
    # —— 上游瞬时抖动（记熔断、可换号）——
    "upstream_error": FailurePolicy(FailureScope.TRANSIENT, 502, "server_error", "upstream error", verify_account=True),
    "upstream_unavailable": FailurePolicy(FailureScope.TRANSIENT, 502, "server_error", "upstream unavailable", verify_account=True),
    "upstream_connection_failed": FailurePolicy(FailureScope.TRANSIENT, 502, "server_error", "upstream connection failed", verify_account=True),
    "upstream_connection_timeout": FailurePolicy(FailureScope.TRANSIENT, 504, "server_error", "upstream connection timeout", verify_account=True),
    "image_poll_timeout": FailurePolicy(FailureScope.TRANSIENT, 502, "server_error", "image poll timeout", verify_account=True),
    # —— 账号态（换号，不计「抖动」熔断）——
    "upstream_rate_limited": FailurePolicy(FailureScope.ACCOUNT, 429, "rate_limit_error", "rate limited", verify_account=True),
    "image_quota_exhausted": FailurePolicy(FailureScope.ACCOUNT, 429, "insufficient_quota", "quota exhausted", verify_account=True),
    "auth_invalid": FailurePolicy(FailureScope.ACCOUNT, 401, "authentication_error", "invalid access token", verify_account=True),
    # —— 业务/请求拒绝（不换号不记熔断）——
    "content_policy_violation": FailurePolicy(FailureScope.REQUEST, 400, "invalid_request_error", "content policy violation"),
    "invalid_image_input": FailurePolicy(FailureScope.REQUEST, 400, "invalid_request_error", "invalid image input"),
    "upstream_text_reply": FailurePolicy(FailureScope.REQUEST, 400, "invalid_request_error", "upstream text reply"),
    "unsupported_model": FailurePolicy(FailureScope.REQUEST, 400, "invalid_request_error", "unsupported model"),
    # —— 本地/未知 ——
    "internal_error": FailurePolicy(FailureScope.INTERNAL, 500, "server_error", "internal error"),
}

# 别名归一：把上游/历史多写法收敛到注册表主码。
FAILURE_CODE_ALIASES: dict[str, str] = {
    "connection_failed": "upstream_connection_failed",
    "connection_timeout": "upstream_connection_timeout",
    "upstream_timeout": "upstream_connection_timeout",
    "invalid_access_token": "auth_invalid",
    "token_invalid": "auth_invalid",
    "token_invalidated": "auth_invalid",
    "token_revoked": "auth_invalid",
    "moderation_blocked": "content_policy_violation",
    "safety_blocked": "content_policy_violation",
    "quota_exhausted": "image_quota_exhausted",
    "insufficient_quota": "image_quota_exhausted",
    "rate_limit_exceeded": "upstream_rate_limited",
    "rate_limited": "upstream_rate_limited",
    "unsupported_image_model": "unsupported_model",
}


def normalize_failure_code(code: Any) -> str:
    """把任意失败码归一到注册表主码；未知码回退 upstream_error。"""
    normalized = str(code or "upstream_error").strip().lower()
    normalized = FAILURE_CODE_ALIASES.get(normalized, normalized)
    return normalized if normalized in FAILURE_POLICIES else "upstream_error"


def failure_policy(code: Any) -> FailurePolicy:
    """取失败码对应策略（未知码归一后取 upstream_error 策略）。"""
    return FAILURE_POLICIES[normalize_failure_code(code)]


# 决策谓词（供调用方/熔断器使用，语义与 conversation 白名单一致）——

def should_switch_account(code: Any) -> bool:
    """是否应换号：账号态或上游抖动可换号重试；业务拒绝不换号。"""
    return failure_policy(code).scope in {FailureScope.ACCOUNT, FailureScope.TRANSIENT}


def should_record_circuit_failure(code: Any) -> bool:
    """是否应记熔断 record_failure：仅上游瞬时抖动（TRANSIENT）记。

    与 `conversation.is_upstream_instability_error` 同语义——业务拒绝（REQUEST）
    与账号态（ACCOUNT，如限流/配额）不记，防恶意输入熔断健康账号。
    """
    return failure_policy(code).scope is FailureScope.TRANSIENT


def verify_account(code: Any) -> bool:
    """是否触发账号核验/处置（换号依据）：策略显式标记的才核验。"""
    return failure_policy(code).verify_account


def classify_upstream_http_error(exc: UpstreamHTTPError) -> str:
    """把 UpstreamHTTPError（携带 status_code/body）分类为失败码。

    规则（真实 HTTP 状态优先，避免字符串误配）：
    - 401 → auth_invalid
    - 429 → upstream_rate_limited
    - 408/504 → upstream_connection_timeout
    - 5xx / 403 / 423 → upstream_unavailable
    - 400 → 依 body 细分为 content_policy/invalid_image_input
    - 其他 → upstream_error
    """
    status = int(getattr(exc, "status_code", 0) or 0)
    body = getattr(exc, "body", None)
    if status == 401:
        return "auth_invalid"
    if status == 429:
        return "upstream_rate_limited"
    if status in {408, 504}:
        return "upstream_connection_timeout"
    if status >= 500 or status in {403, 423}:
        return "upstream_unavailable"
    if status == 400:
        return _classify_400_body(body)
    return "upstream_error"


def _classify_400_body(body: Any) -> str:
    """对 400 业务拒绝做细分：审核/配额/输入。body 可能为 dict/str。"""
    text = ""
    if isinstance(body, dict):
        for key in ("code", "error_code", "type"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip().lower()
                break
        if not text:
            error = body.get("error")
            if isinstance(error, dict):
                text = str(error.get("code") or error.get("type") or "").strip().lower()
    elif isinstance(body, str):
        text = body.strip().lower()
    if any(token in text for token in ("moderation", "content_policy", "safety", "blocked")):
        return "content_policy_violation"
    if any(token in text for token in ("quota", "insufficient")):
        return "image_quota_exhausted"
    return "invalid_image_input"


def classify_image_exception(exc: BaseException | str) -> str:
    """把生图链路的自定义异常/字符串错误分类为失败码（N6b 接入入口）。

    对齐上游用法：把 conversation 的 last_error 字符串 / 自定义异常映射到注册表主码，
    供熔断判定（should_record_circuit_failure）与对外错误码统一。
    兼容 str 入参——文本链路 error_message 直接走 _classify_message_text，不再
    散落 is_upstream_instability_error 白名单。

    规则（异常类型优先，其次字符串关键词，最后兜底）：
    - UpstreamHTTPError → classify_upstream_http_error（真实状态码优先）
    - ImagePollTimeoutError → image_poll_timeout（TRANSIENT，记熔断）
    - ImageContentPolicyError → content_policy_violation（REQUEST，不记熔断）
    - ImageRateLimitError → upstream_rate_limited（ACCOUNT，换号不记抖动熔断）
    - InvalidAccessTokenError → auth_invalid（ACCOUNT）
    - 其他异常/字符串 → 走 _classify_message_text 关键词识别
    """
    # str 入参直接走文本分类（文本链路统一入口）
    if isinstance(exc, str):
        return _classify_message_text(exc)
    # 延迟 import 避免循环依赖（openai_backend_api 也 import 本模块）
    from utils.helper import UpstreamHTTPError as _UpstreamHTTPError

    if isinstance(exc, _UpstreamHTTPError):
        return classify_upstream_http_error(exc)

    name = type(exc).__name__
    if name == "ImagePollTimeoutError":
        return "image_poll_timeout"
    if name == "ImageContentPolicyError":
        return "content_policy_violation"
    if name == "ImageRateLimitError":
        return "upstream_rate_limited"
    if name == "InvalidAccessTokenError":
        return "auth_invalid"

    return _classify_message_text(str(exc))


def _classify_message_text(message: str) -> str:
    """按错误文本关键词分类（与 conversation 白名单判定同语义，但产出失败码）。

    优先级：业务拒绝 > 账号态 > 上游抖动 > 兜底。与 conversation.is_upstream_instability_error
    的正向白名单保持互斥一致——凡是「上游抖动」关键词才落 TRANSIENT 码。
    """
    text = str(message or "").lower()
    if not text:
        return "upstream_error"

    # 业务/请求拒绝（REQUEST，不记熔断）——先于抖动判定，防 "moderation... 500" 误判
    if any(tok in text for tok in ("moderation", "content_policy", "content policy", "safety", "blocked by", "policy violation")):
        return "content_policy_violation"
    if "unsupported image model" in text or "unsupported model" in text:
        return "unsupported_model"
    if "text reply" in text or ("upstream" in text and "text" in text and "reply" in text):
        return "upstream_text_reply"

    # 账号态（ACCOUNT，换号不记抖动熔断）
    if any(tok in text for tok in ("token_invalidated", "token_revoked", "invalid access token", "authentication token has been invalidated", "401")):
        return "auth_invalid"
    if any(tok in text for tok in ("insufficient_quota", "quota_exhausted", "quota exhausted", "rate_limit_exceeded", "rate limit", "429", "too many requests")):
        # 配额/限流属账号态
        if "quota" in text or "insufficient" in text:
            return "image_quota_exhausted"
        return "upstream_rate_limited"

    # 上游瞬时抖动（TRANSIENT，记熔断）——与 conversation.is_upstream_instability_error 同语义。
    # 关键词须与白名单同样精确，避免宽松匹配导致「该记的不记/不该记的记」漂移。
    if "poll_timeout" in text or "生图超时" in text:
        return "image_poll_timeout"
    # TLS/连接错误（精确对齐 is_tls_connection_error）
    if any(tok in text for tok in ("curl: (35)", "tls connect error", "openssl_internal",
                                    "wrong_version_number", "certificate_verify_failed",
                                    "connection aborted", "remote disconnected",
                                    "connection reset by peer", "connection refused")):
        return "upstream_connection_failed"
    # 连接/读取超时（精确对齐 is_connection_timeout_error）
    if any(tok in text for tok in ("curl: (28)", "operation timed out", "connection timed out",
                                    "read timed out", "connect timeout", "gateway timeout")):
        return "upstream_connection_timeout"
    # 5xx / 网关（对齐 is_upstream_instability_error 的 5xx 段）
    if any(tok in text for tok in ("500", "502", "503", "504", "520", "521", "522", "523", "524",
                                    "service unavailable", "bad gateway")):
        return "upstream_unavailable"
    if "upstream" in text and ("timeout" in text or "unavailable" in text or "error" in text):
        return "upstream_unavailable"

    return "upstream_error"
