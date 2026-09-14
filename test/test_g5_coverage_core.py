"""G5 覆盖率攻坚第一批：核心链路补测（v2.37~v2.40）。

目标模块：
- services.retry_budget：指数退避上限 max_delay 封顶、可重试判定、异常链保持
- services.ssrf_guard：_is_private_ip 直测、DNS 失败拒绝、IPv6 段、保留/组播/unspecified
- services.image_failure：400 细分、异常类型分发、文本关键词全分支
- api.rate_limit：Local 滑窗、共享降级、per-ip 限流、prune、XFF 解析
- services.cost_service：三源合并、异常降级、need_config 分支
- services.providers：fomimage 前缀映射、frozen 语义

全部 mock 打桩不触网（conftest 已隔离环境变量）。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.retry_budget import can_retry_stream, retry_idempotent_get
from services.ssrf_guard import _is_private_ip, _resolve_host_ips, validate_image_url

# ---------------------------------------------------------------------------
# A. services.retry_budget（补充既有 11 用例未覆盖分支）
# ---------------------------------------------------------------------------


class TestRetryBudgetExtras:
    def test_backoff_capped_at_max_delay(self):
        """指数退避不能超过 max_delay（max_retries 大时封顶）。"""
        attempts = []

        def always_fail():
            attempts.append(1)
            raise RuntimeError("boom")

        with patch("services.retry_budget.time.sleep") as slp:
            with pytest.raises(RuntimeError):
                retry_idempotent_get(always_fail, max_retries=5, base_delay=1.0, max_delay=2.0)
        delays = [c.args[0] for c in slp.call_args_list]
        assert delays == [1.0, 2.0, 2.0, 2.0, 2.0], "第 2 次起封顶 2.0"

    def test_last_exception_rethrown_after_exhaustion(self):
        """重试耗尽后抛出的是最后一次异常（非首次）。"""
        msgs = ["first", "second", "final"]

        def flaky():
            raise RuntimeError(msgs.pop(0))

        with patch("services.retry_budget.time.sleep"):
            with pytest.raises(RuntimeError) as exc_info:
                retry_idempotent_get(flaky, max_retries=2)
        assert "final" in str(exc_info.value)

    def test_retryable_predicate_filters_exceptions(self):
        """retryable 谓词：仅放行特定异常，其余立即抛。"""
        class Transient(Exception):
            pass

        class Fatal(Exception):
            pass

        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise Transient("t")
            raise Fatal("f")

        with patch("services.retry_budget.time.sleep"):
            with pytest.raises(Fatal):
                retry_idempotent_get(flaky, max_retries=3, retryable=lambda e: isinstance(e, Transient))
        assert len(calls) == 2, "Transient 重试 1 次后遇 Fatal 立即抛"

    def test_can_retry_stream_boundary_usage(self):
        """流式重试边界：emitted 与换号次数组合。"""
        assert not can_retry_stream(emitted=True, pre_stream_retries_used=5)
        assert not can_retry_stream(emitted=False, pre_stream_retries_used=1)
        assert can_retry_stream(emitted=False, pre_stream_retries_used=0)


# ---------------------------------------------------------------------------
# B. services.ssrf_guard（补充既有 20 用例未覆盖分支）
# ---------------------------------------------------------------------------


class TestSsrfGuardExtras:
    def test_private_ip_variants(self):
        assert _is_private_ip("10.0.0.1") is True
        assert _is_private_ip("172.16.0.1") is True
        assert _is_private_ip("192.168.1.1") is True
        assert _is_private_ip("127.0.0.1") is True
        assert _is_private_ip("169.254.169.254") is True  # link-local（云元数据）
        assert _is_private_ip("0.0.0.0") is True  # unspecified
        assert _is_private_ip("224.0.0.1") is True  # multicast
        assert _is_private_ip("::1") is True
        assert _is_private_ip("fe80::1") is True  # IPv6 link-local

    def test_private_ip_public_ipv4(self):
        assert _is_private_ip("93.184.216.34") is False
        assert _is_private_ip("1.1.1.1") is False

    def test_private_ip_invalid_returns_true(self):
        """无法解析的 IP 按危险处理（拒绝）。"""
        assert _is_private_ip("not-an-ip") is True

    def test_resolve_host_ips_failure_returns_empty(self, monkeypatch):
        def _boom(hostname, port=None):
            raise OSError("dns down")

        import services.ssrf_guard as ssrf

        monkeypatch.setattr(ssrf.socket, "getaddrinfo", _boom)
        assert _resolve_host_ips("example.com") == []

    def test_domain_unresolvable_rejected(self, monkeypatch):
        monkeypatch.setattr("services.ssrf_guard._resolve_host_ips", lambda host: [])
        with pytest.raises(ValueError, match="无法解析"):
            validate_image_url("http://does-not-exist.invalid/x.png")

    def test_domain_resolves_to_private_rejected(self, monkeypatch):
        monkeypatch.setattr("services.ssrf_guard._resolve_host_ips", lambda host: ["10.0.0.9"])
        with pytest.raises(ValueError, match="内网"):
            validate_image_url("http://internal.example/x.png")

    def test_ipv6_public_allowed(self):
        validate_image_url("http://[2606:4700:4700::1111]/pic.jpg")

    def test_missing_host_rejected(self):
        with pytest.raises(ValueError, match="host"):
            validate_image_url("http:///no-host")

    def test_allow_private_skips_dns(self, monkeypatch):
        """allow_private_ips=True 时不做 DNS 解析直接放行。"""
        monkeypatch.setattr("services.ssrf_guard._resolve_host_ips", lambda host: (_ for _ in ()).throw(AssertionError("不应调用 DNS")))
        validate_image_url("http://10.0.0.1/x.png", allow_private_ips=True)


# ---------------------------------------------------------------------------
# C. services.image_failure（补充既有 25 用例未覆盖分支）
# ---------------------------------------------------------------------------


def _http_err(status_code=500, body=None):
    from utils.helper import UpstreamHTTPError

    return UpstreamHTTPError(context="test", status_code=status_code, body=body if body is not None else {})


class TestImageFailureExtras:
    def test_classify_400_body_dict_code_field(self):
        from services.image_failure import classify_upstream_http_error

        assert classify_upstream_http_error(_http_err(400, {"code": "MODERATION_BLOCKED"})) == "content_policy_violation"

    def test_classify_400_body_nested_error(self):
        from services.image_failure import classify_upstream_http_error

        assert classify_upstream_http_error(_http_err(400, {"error": {"code": "insufficient_quota"}})) == "image_quota_exhausted"

    def test_classify_400_body_string_quota(self):
        from services.image_failure import classify_upstream_http_error

        assert classify_upstream_http_error(_http_err(400, "insufficient quota for image generation")) == "image_quota_exhausted"

    def test_classify_400_body_unknown_is_invalid_input(self):
        from services.image_failure import classify_upstream_http_error

        assert classify_upstream_http_error(_http_err(400, {"weird": "payload"})) == "invalid_image_input"

    def test_classify_http_non_400_200(self):
        from services.image_failure import classify_upstream_http_error

        assert classify_upstream_http_error(_http_err(200)) == "upstream_error"
        assert classify_upstream_http_error(_http_err(301)) == "upstream_error"
        assert classify_upstream_http_error(_http_err(403)) == "upstream_unavailable"
        assert classify_upstream_http_error(_http_err(423)) == "upstream_unavailable"
        assert classify_upstream_http_error(_http_err(408)) == "upstream_connection_timeout"
        assert classify_upstream_http_error(_http_err(504)) == "upstream_connection_timeout"
        assert classify_upstream_http_error(_http_err(502)) == "upstream_unavailable"
        assert classify_upstream_http_error(_http_err(401)) == "auth_invalid"
        assert classify_upstream_http_error(_http_err(429)) == "upstream_rate_limited"

    def test_classify_exception_by_type_name(self):
        """按类型名分发的自定义异常（延迟 import 不触发循环）。"""
        from services.image_failure import classify_image_exception

        class ImagePollTimeoutError(Exception):
            pass

        class ImageContentPolicyError(Exception):
            pass

        class ImageRateLimitError(Exception):
            pass

        class InvalidAccessTokenError(Exception):
            pass

        assert classify_image_exception(ImagePollTimeoutError("t")) == "image_poll_timeout"
        assert classify_image_exception(ImageContentPolicyError("c")) == "content_policy_violation"
        assert classify_image_exception(ImageRateLimitError("r")) == "upstream_rate_limited"
        assert classify_image_exception(InvalidAccessTokenError("a")) == "auth_invalid"

    def test_classify_exception_unknown_type(self):
        from services.image_failure import classify_image_exception

        assert classify_image_exception(RuntimeError("unknown boom")) == "upstream_error"

    def test_classify_message_empty_returns_upstream_error(self):
        from services.image_failure import classify_image_exception

        assert classify_image_exception("") == "upstream_error"

    def test_text_keywords_full_branches(self):
        from services.image_failure import classify_image_exception

        assert classify_image_exception("moderation blocked: sexual content") == "content_policy_violation"
        assert classify_image_exception("unsupported image model: gpt-x") == "unsupported_model"
        assert classify_image_exception("upstream returned text reply instead of image") == "upstream_text_reply"
        assert classify_image_exception("token_invalidated: please login again") == "auth_invalid"
        assert classify_image_exception("quota_exhausted") == "image_quota_exhausted"
        assert classify_image_exception("rate limit exceeded") == "upstream_rate_limited"
        assert classify_image_exception("生图超时") == "image_poll_timeout"
        assert classify_image_exception("curl: (35) SSL connect error") == "upstream_connection_failed"
        assert classify_image_exception("read timed out") == "upstream_connection_timeout"
        assert classify_image_exception("502 bad gateway") == "upstream_unavailable"
        assert classify_image_exception("upstream error occurred") == "upstream_unavailable"

    def test_verify_account_policy(self):
        from services.image_failure import verify_account

        assert verify_account("upstream_error") is True
        assert verify_account("content_policy_violation") is False

    def test_is_token_invalid_error_variants(self):
        from services.image_failure import is_connection_timeout_error, is_tls_connection_error, is_token_invalid_error

        assert is_token_invalid_error("token_revoked") is True
        assert is_token_invalid_error("invalidated oauth token") is True
        assert is_token_invalid_error("normal message") is False
        assert is_tls_connection_error("curl: (35)") is True
        assert is_tls_connection_error("certificate_verify_failed") is False  # 非精确清单（同模块语义）
        assert is_connection_timeout_error("operation timed out") is True

    def test_image_stream_error_message_mapping(self):
        from services.image_failure import image_stream_error_message

        assert image_stream_error_message("token_invalidated") == "image generation failed"
        assert image_stream_error_message("curl: (35)") == "upstream image connection failed, please retry later"
        assert image_stream_error_message("read timed out") == "upstream connection timed out, please retry later"
        assert image_stream_error_message("") == "image generation failed"
        assert image_stream_error_message("custom error") == "custom error"


# ---------------------------------------------------------------------------
# D. api.rate_limit（补充既有缺失分支——中间件 dispatch 全覆盖）
# ---------------------------------------------------------------------------


class TestRateLimitExtras:
    def _limiter(self, max_requests=0):
        from api.rate_limit import SlidingWindowLimiter

        return SlidingWindowLimiter(window_seconds=60.0, max_requests=max_requests)

    def test_max_requests_zero_always_allows(self):
        limiter = self._limiter(max_requests=0)
        assert limiter.check("any") is True

    def test_local_sliding_window_rejects_over_limit(self):
        limiter = self._limiter(max_requests=2)
        assert limiter.check("k") is True
        assert limiter.check("k") is True
        assert limiter.check("k") is False  # 第 3 次拒绝

    def test_local_window_expires_after_cutoff(self):
        limiter = self._limiter(max_requests=2)
        with patch("api.rate_limit.time.monotonic", side_effect=[100.0, 100.0, 161.0, 161.0]):
            assert limiter.check("k") is True
            assert limiter.check("k") is True
            assert limiter.check("k") is True  # 窗口过期后放行
            assert limiter.check("k") is True

    def test_local_window_cutoff_prunes_old_records(self):
        limiter = self._limiter(max_requests=5)
        with patch("api.rate_limit.time.monotonic", side_effect=[0.0, 10.0, 20.0, 100.0, 100.0, 100.0]):
            limiter.check("k")  # 0s
            limiter.check("k")  # 10s
            limiter.check("k")  # 20s
            limiter.check("k")  # 100s（清 0s 记录）
            assert limiter.check("k") is True  # 仍有 3 条 < 5 上限

    def test_shared_uses_redis_backend(self, monkeypatch):
        from api.rate_limit import SlidingWindowLimiter

        backend = MagicMock()
        backend.incr.return_value = 1
        import api.rate_limit as rl

        monkeypatch.setattr(rl.SlidingWindowLimiter, "_check_shared", lambda self, key: True)
        # 直接验证 _use_shared 分支被走（config.redis_url 有值时）
        monkeypatch.setattr(rl.SlidingWindowLimiter, "_check_local", lambda self, key: (_ for _ in ()).throw(AssertionError("不应走 local")))
        limiter = SlidingWindowLimiter(max_requests=5)
        # 让 redis_url 非空：conftest 已钉死为空，用 monkeypatch 该 property
        from services.config import config as cfg

        monkeypatch.setattr(cfg, "data", {**cfg.data, "redis_url": "redis://127.0.0.1:6379/0"})
        assert limiter.check("g") is True

    def test_shared_rejects_when_count_over(self, monkeypatch):
        import api.rate_limit as rl
        from api.rate_limit import SlidingWindowLimiter

        monkeypatch.setattr(rl.SlidingWindowLimiter, "_check_shared", lambda self, key: False)
        limiter = SlidingWindowLimiter(max_requests=5)
        from services.config import config as cfg

        monkeypatch.setattr(cfg, "data", {**cfg.data, "redis_url": "redis://127.0.0.1:6379/0"})
        assert limiter.check("g") is False

    def test_shared_redis_failure_degrades_local(self, monkeypatch):

        # Redis 后端断连时：incr 抛异常 → 内部捕获 → 走 _check_local 降级，不 500。
        # 打补丁 get_shared_state 抛异常（模拟 RedisBackend 初始化失败/断连），走真实 _check_shared except 分支。
        import services.shared_state as ss
        from api.rate_limit import SlidingWindowLimiter

        def _boom_state():
            raise RuntimeError("redis down")

        monkeypatch.setattr(ss, "get_shared_state", _boom_state)
        from services.config import config as cfg

        monkeypatch.setattr(cfg, "data", {**cfg.data, "redis_url": "redis://127.0.0.1:6379/0"})
        limiter = SlidingWindowLimiter(max_requests=100)
        assert limiter.check("g") is True  # 降级本地，不炸

    def test_clear_removes_key(self):
        limiter = self._limiter(max_requests=2)
        limiter.check("k")
        limiter.check("k")
        assert limiter.check("k") is False
        limiter.clear("k")
        assert limiter.check("k") is True

    def test_resolve_client_ip_trusted_proxy(self):
        from api.rate_limit import resolve_client_ip

        assert resolve_client_ip("127.0.0.1", {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}, ["127.0.0.1"]) == "1.2.3.4"

    def test_resolve_client_ip_untrusted_ignores_xff(self):
        from api.rate_limit import resolve_client_ip

        assert resolve_client_ip("9.9.9.9", {"x-forwarded-for": "1.2.3.4"}, ["127.0.0.1"]) == "9.9.9.9"

    def test_resolve_client_ip_empty_xff(self):
        from api.rate_limit import resolve_client_ip

        assert resolve_client_ip("127.0.0.1", {}, ["127.0.0.1"]) == "127.0.0.1"

    def test_resolve_client_ip_unknown_fallback(self):
        from api.rate_limit import resolve_client_ip

        assert resolve_client_ip("", {"x-forwarded-for": "1.2.3.4"}, ["127.0.0.1"]) == "unknown"

    def test_middleware_dispatch_global_429(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.rate_limit import RateLimitMiddleware

        app = FastAPI()

        @app.get("/api/test")
        async def ok():
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware, global_rpm=1, per_ip_rpm=0)
        client = TestClient(app)
        assert client.get("/api/test").status_code == 200
        assert client.get("/api/test").status_code == 429
        assert client.get("/api/test").headers.get("retry-after") == "1"

    def test_middleware_dispatch_per_ip_429(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.rate_limit import RateLimitMiddleware

        app = FastAPI()

        @app.get("/api/test")
        async def ok():
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware, global_rpm=0, per_ip_rpm=1)
        client = TestClient(app)
        assert client.get("/api/test").status_code == 200
        assert client.get("/api/test").status_code == 429

    def test_middleware_skips_static_path(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.rate_limit import RateLimitMiddleware

        app = FastAPI()

        @app.get("/index.html")
        async def idx():
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware, global_rpm=1, per_ip_rpm=0)
        client = TestClient(app)
        assert client.get("/index.html").status_code == 200
        assert client.get("/index.html").status_code == 200  # 静态不限流


# ---------------------------------------------------------------------------
# E. services.cost_service（补充既有 4 用例未覆盖分支）
# ---------------------------------------------------------------------------


def _fake_usage_agg(totals_value=None, daily_series=None, totals_side_effect=None):
    """构造 usage_agg 模块 mock：cost_service 用 `from services.usage_agg import usage_agg`，
    因此 mock 模块须自带 `.usage_agg` 属性指回自身/同名对象。
    """
    fake = MagicMock()
    if totals_side_effect is not None:
        fake.totals.side_effect = totals_side_effect
    else:
        fake.totals.return_value = totals_value or {"total_requests": 0, "total_success": 0, "total_fail": 0, "by_type": {}}
    fake.daily_success_series.return_value = daily_series or []
    fake.usage_agg = fake  # from module import usage_agg 取到自身
    return fake


class TestCostServiceExtras:
    def test_usage_agg_failure_degrades(self):
        from services.cost_service import CostService

        svc = CostService()
        fake = _fake_usage_agg(totals_side_effect=RuntimeError("agg down"))
        with patch.dict("sys.modules", {"services.usage_agg": fake}), \
             patch("services.cost_service.account_service.list_accounts", return_value=[]):
            result = svc.get_cost_overview()
        assert result["total_requests"] == 0

    def test_provider_stats_success(self):
        from services.cost_service import CostService

        svc = CostService()
        fake_ps = MagicMock()
        fake_ps.get_provider_stats.return_value = [
            {"name": "chatgpt", "display_name": "ChatGPT", "total_accounts": 10, "available_accounts": 8, "quota_remaining": 5}
        ]
        fake_agg = _fake_usage_agg({"total_requests": 10, "total_success": 8, "total_fail": 2, "by_type": {}})
        with patch.dict("sys.modules", {"services.usage_agg": fake_agg}), \
             patch("services.cost_service.account_service.list_accounts", return_value=[{}]), \
             patch.dict("sys.modules", {"services.provider_scheduler": MagicMock(provider_scheduler=fake_ps)}):
            result = svc.get_cost_overview()
        assert result["total_requests"] == 10
        assert result["provider_distribution"][0]["name"] == "chatgpt"

    def test_kookeey_need_config(self):
        from services.cost_service import CostService

        svc = CostService()
        fake_kk = MagicMock()
        fake_kk.get_traffic_overview.return_value = {"need_config": True}
        fake_agg = _fake_usage_agg({"total_requests": 0, "total_success": 0, "total_fail": 0, "by_type": {}})
        with patch.dict("sys.modules", {"services.usage_agg": fake_agg}), \
             patch.dict("sys.modules", {"services.provider_scheduler": MagicMock()}):
            with patch("services.cost_service.account_service.list_accounts", return_value=[]), \
                 patch.dict("sys.modules", {"services.kookeey_service": MagicMock(kookeey_service=fake_kk)}):
                result = svc.get_cost_overview()
        assert result["kookeey_traffic"] == {"need_config": True}

    def test_kookeey_error_result(self):
        from services.cost_service import CostService

        svc = CostService()
        fake_kk = MagicMock()
        fake_kk.get_traffic_overview.return_value = {"ok": False, "error": "timeout"}
        fake_agg = _fake_usage_agg({"total_requests": 0, "total_success": 0, "total_fail": 0, "by_type": {}})
        with patch.dict("sys.modules", {"services.usage_agg": fake_agg}), \
             patch.dict("sys.modules", {"services.provider_scheduler": MagicMock()}):
            with patch("services.cost_service.account_service.list_accounts", return_value=[]), \
                 patch.dict("sys.modules", {"services.kookeey_service": MagicMock(kookeey_service=fake_kk)}):
                result = svc.get_cost_overview()
        assert result["kookeey_traffic"] == {"error": "timeout"}

    def test_kookeey_success(self):
        from services.cost_service import CostService

        svc = CostService()
        fake_kk = MagicMock()
        fake_kk.get_traffic_overview.return_value = {"ok": True, "balance_mb": 100, "today_use_mb": 2, "month_use_mb": 50, "package": "P1"}
        fake_agg = _fake_usage_agg({"total_requests": 0, "total_success": 0, "total_fail": 0, "by_type": {}})
        with patch.dict("sys.modules", {"services.usage_agg": fake_agg}), \
             patch.dict("sys.modules", {"services.provider_scheduler": MagicMock()}):
            with patch("services.cost_service.account_service.list_accounts", return_value=[]), \
                 patch.dict("sys.modules", {"services.kookeey_service": MagicMock(kookeey_service=fake_kk)}):
                result = svc.get_cost_overview()
        assert result["kookeey_traffic"]["balance_mb"] == 100


# ---------------------------------------------------------------------------
# F. services.providers（补充既有用例未覆盖分支）
# ---------------------------------------------------------------------------


class TestProvidersExtras:
    def test_fomimage_model_helpers(self):
        from services.providers.registry import (
            fomimage_models,
            fomimage_upstream_model,
            is_fomimage_model,
        )

        assert is_fomimage_model("fomimage-gpt-image-2") is True
        assert is_fomimage_model("gpt-image-2") is False
        assert fomimage_upstream_model("fomimage-nano-banana-2-text") == "nano-banana-2-text"
        assert fomimage_upstream_model("gpt-image-2") == "gpt-image-2"  # 非 fomimage 原样返回
        assert len(fomimage_models()) == 12

    def test_provider_meta_frozen(self):
        from services.providers.base import ProviderMeta

        meta = ProviderMeta(name="x", display_name="X")
        with pytest.raises(Exception):
            meta.name = "y"  # frozen dataclass 不可变

    def test_normalize_provider_fallback(self):
        from services.providers.registry import normalize_provider

        assert normalize_provider("chatgpt") == "chatgpt"
        assert normalize_provider("FOMIMAGE") == "fomimage"  # 大小写归一
        assert normalize_provider("nope") == "chatgpt"
        assert normalize_provider(None) == "chatgpt"

    def test_get_provider_unknown(self):
        from services.providers.registry import get_provider

        assert get_provider("nope") is None
        assert get_provider(None) is None