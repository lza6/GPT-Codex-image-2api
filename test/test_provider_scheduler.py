"""ProviderScheduler 单测：档位分布 + provider 统计 + 缓存 + 边界 + 8.2 精细调度。"""
from __future__ import annotations

import time
from unittest.mock import patch

from services.provider_scheduler import ProviderScheduler


def _account(**kw: object) -> dict:
    base = {"access_token": "t", "status": "正常", "quota": 100, "success": 0, "fail": 0, "provider": "chatgpt"}
    base.update(kw)
    return base


class TestProviderScheduler:
    def test_compute_tier_distribution_all(self):
        """不指定 provider 时统计全部账号。"""
        accounts = [
            _account(provider="chatgpt"),
            _account(provider="chatgpt", status="禁用"),
            _account(provider="chatgpt", quota=0),
            _account(provider="grok", status="正常"),
        ]
        tiers = ProviderScheduler().compute_tier_distribution(accounts)
        # 至少有一个 healthy 和一个 risky
        assert tiers["healthy"] >= 1
        assert tiers["risky"] >= 1

    def test_compute_tier_distribution_filtered(self):
        """指定 provider 时只统计该 provider 的账号。"""
        accounts = [
            _account(provider="chatgpt", status="禁用"),
            _account(provider="grok", status="正常"),
        ]
        tiers = ProviderScheduler().compute_tier_distribution(accounts, provider="chatgpt")
        assert tiers["risky"] == 1  # 禁用的 chatgpt
        assert tiers["healthy"] == 0  # grok 被过滤

    def test_compute_tier_distribution_empty(self):
        """空账号列表返回全零档位。"""
        tiers = ProviderScheduler().compute_tier_distribution([])
        assert tiers == {"healthy": 0, "warm": 0, "risky": 0}

    def test_compute_tier_distribution_no_match_provider(self):
        """指定 provider 无匹配账号时返回全零。"""
        accounts = [_account(provider="chatgpt")]
        tiers = ProviderScheduler().compute_tier_distribution(accounts, provider="grok")
        assert tiers == {"healthy": 0, "warm": 0, "risky": 0}

    def test_compute_tier_distribution_risky_statuses(self):
        """状态为"异常"的账号也归入 risky。"""
        accounts = [
            _account(status="异常"),
            _account(status="禁用"),
            _account(status="限流"),
        ]
        tiers = ProviderScheduler().compute_tier_distribution(accounts)
        assert tiers["risky"] == 3
        assert tiers["healthy"] == 0

    def test_compute_tier_distribution_calls_health_tier_for_normal(self):
        """正常状态的账号调用 _account_health_tier 判定档位。"""
        accounts = [
            _account(status="正常", quota=100, success=10, fail=0),
            _account(status="正常", quota=0),
        ]
        tiers = ProviderScheduler().compute_tier_distribution(accounts)
        assert tiers["healthy"] >= 1
        assert tiers["risky"] >= 1  # quota=0 归 risky

    def test_get_provider_stats_empty(self):
        """空账号列表返回空列表。"""
        stats = ProviderScheduler().get_provider_stats([])
        assert stats == []

    def test_get_provider_stats_contains_required_fields(self):
        """统计结果含 name/display_name/enabled/total_accounts/available_accounts/tiers。"""
        accounts = [_account(provider="chatgpt")]
        stats = ProviderScheduler().get_provider_stats(accounts)
        assert len(stats) >= 1
        s = stats[0]
        assert s["name"] == "chatgpt"
        assert s["display_name"] == "ChatGPT"
        assert s["enabled"] is True
        assert s["total_accounts"] == 1
        assert s["available_accounts"] == 1
        assert "tiers" in s

    def test_get_provider_stats_available_excludes_risky(self):
        """available_accounts 应排除 risky 档位。"""
        accounts = [
            _account(provider="chatgpt", status="正常"),
            _account(provider="chatgpt", status="禁用"),
        ]
        stats = ProviderScheduler().get_provider_stats(accounts)
        chatgpt = next(s for s in stats if s["name"] == "chatgpt")
        assert chatgpt["total_accounts"] == 2
        assert chatgpt["available_accounts"] == 1
        assert chatgpt["tiers"]["risky"] == 1

    def test_get_provider_stats_skips_no_accounts(self, monkeypatch):
        """无账号的 provider 不应出现在统计中。"""
        monkeypatch.setattr("services.providers.list_providers", lambda enabled_only=True: [])
        stats = ProviderScheduler().get_provider_stats([])
        assert stats == []

    def test_cache_ttl_used(self):
        """缓存 TTL 属性存在且被使用。"""
        ps = ProviderScheduler()
        assert ps._cache_ttl == 5.0
        now = time.time()
        ps._cache_at = now - 10  # 过期
        assert time.time() - ps._cache_at > ps._cache_ttl

    # ──── 8.2：Provider 级 rate limit ────

    def test_provider_rate_limit_no_limit(self, monkeypatch):
        """rpm=0 时不限流。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_rate_limit_rpm", {})
        ps = ProviderScheduler()
        assert ps._check_provider_rate_limit("chatgpt") is True

    def test_provider_rate_limit_allows_within_limit(self, monkeypatch):
        """rpm=10 时，前 10 次请求应全部允许。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_rate_limit_rpm", {"chatgpt": 10})
        ps = ProviderScheduler()
        for _ in range(10):
            assert ps._check_provider_rate_limit("chatgpt") is True

    def test_provider_rate_limit_blocks_excess(self, monkeypatch):
        """rpm=1 时，第 2 次请求应被拒绝。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_rate_limit_rpm", {"chatgpt": 1})
        ps = ProviderScheduler()
        assert ps._check_provider_rate_limit("chatgpt") is True
        assert ps._check_provider_rate_limit("chatgpt") is False

    def test_provider_rate_remaining(self, monkeypatch):
        """_provider_rate_remaining 返回剩余配额。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_rate_limit_rpm", {"chatgpt": 10})
        ps = ProviderScheduler()
        remaining = ps._provider_rate_remaining("chatgpt")
        assert remaining == 10

    def test_provider_rate_remaining_unlimited(self, monkeypatch):
        """rpm=0 时 _provider_rate_remaining 返回 -1。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_rate_limit_rpm", {})
        ps = ProviderScheduler()
        remaining = ps._provider_rate_remaining("chatgpt")
        assert remaining == -1

    def test_provider_rate_limit_isolated(self, monkeypatch):
        """不同 provider 独立计数，互不影响。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_rate_limit_rpm", {"chatgpt": 1, "grok": 5})
        ps = ProviderScheduler()
        assert ps._check_provider_rate_limit("chatgpt") is True
        assert ps._check_provider_rate_limit("chatgpt") is False  # chatgpt 已超限
        assert ps._check_provider_rate_limit("grok") is True  # grok 还有配额

    # ──── 8.2：Provider 权重调度 ────

    def test_pick_provider_by_weight_no_config(self, monkeypatch):
        """无配置时回退默认 provider。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_weights", {})
        ps = ProviderScheduler()
        result = ps._pick_provider_by_weight()
        assert result == "chatgpt"

    def test_pick_provider_by_weight_single(self, monkeypatch):
        """单 provider 时返回该 provider。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_weights", {"chatgpt": 3})
        ps = ProviderScheduler()
        result = ps._pick_provider_by_weight()
        assert result == "chatgpt"

    def test_pick_provider_by_weight_zero_weight_skipped(self, monkeypatch):
        """权重为 0 时跳过。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_weights", {"chatgpt": 0, "grok": 3})
        # grok 未启用
        ps = ProviderScheduler()
        result = ps._pick_provider_by_weight()
        # grok 未启用，chatgpt 权重为 0，候选为空
        assert result is None

    def test_get_weighted_providers_no_config(self, monkeypatch):
        """无配置时返回默认 provider。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_weights", {})
        ps = ProviderScheduler()
        providers = ps._get_weighted_providers()
        assert providers == ["chatgpt"]

    def test_get_weighted_providers_filters_invalid(self, monkeypatch):
        """只返回已启用且正权重的 provider。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_weights", {"chatgpt": 3, "grok": 1})
        ps = ProviderScheduler()
        providers = ps._get_weighted_providers()
        # grok 未启用，所以只有 chatgpt
        assert providers == ["chatgpt"]

    # ──── 8.2：Provider 熔断器 ────

    def test_provider_breaker_closed_by_default(self):
        """默认熔断器状态为 closed。"""
        ps = ProviderScheduler()
        assert ps._provider_allow_request("chatgpt") is True
        state = ps._provider_breaker_state("chatgpt")
        assert state["state"] == "closed"

    def test_provider_breaker_opens_after_threshold(self):
        """连续失败达到阈值后熔断。"""
        ps = ProviderScheduler()
        ps._PROVIDER_CB_THRESHOLD = 3
        for _ in range(3):
            ps._record_provider_failure("chatgpt")
        assert ps._provider_allow_request("chatgpt") is False

    def test_provider_breaker_success_clears(self):
        """成功记录清零熔断器。"""
        ps = ProviderScheduler()
        ps._PROVIDER_CB_THRESHOLD = 3
        for _ in range(3):
            ps._record_provider_failure("chatgpt")
        ps._record_provider_success("chatgpt")
        assert ps._provider_allow_request("chatgpt") is True

    def test_provider_breaker_recovery_after_timeout(self, monkeypatch):
        """冷却期后自动恢复。"""
        ps = ProviderScheduler()
        ps._PROVIDER_CB_THRESHOLD = 3
        ps._PROVIDER_CB_RECOVERY = 0.05  # 50ms
        for _ in range(3):
            ps._record_provider_failure("chatgpt")
        assert ps._provider_allow_request("chatgpt") is False
        time.sleep(0.06)
        assert ps._provider_allow_request("chatgpt") is True

    def test_provider_breaker_state_open(self):
        """熔断打开时状态正确。"""
        ps = ProviderScheduler()
        ps._PROVIDER_CB_THRESHOLD = 3
        for _ in range(3):
            ps._record_provider_failure("chatgpt")
        state = ps._provider_breaker_state("chatgpt")
        assert state["state"] == "open"
        assert state["recover_in_seconds"] > 0

    def test_provider_breaker_isolated(self):
        """不同 provider 熔断器互不影响。"""
        ps = ProviderScheduler()
        ps._PROVIDER_CB_THRESHOLD = 3
        for _ in range(3):
            ps._record_provider_failure("chatgpt")
        assert ps._provider_allow_request("chatgpt") is False
        assert ps._provider_allow_request("grok") is True

    # ──── 8.2：get_provider_stats 含新字段 ────

    def test_get_provider_stats_contains_new_fields(self, monkeypatch):
        """get_provider_stats 返回 quota_remaining/weight/breaker_state。"""
        from services.config import config

        monkeypatch.setitem(config.data, "provider_weights", {"chatgpt": 3})
        monkeypatch.setitem(config.data, "provider_rate_limit_rpm", {"chatgpt": 10})
        ps = ProviderScheduler()
        accounts = [_account(provider="chatgpt")]
        stats = ps.get_provider_stats(accounts)
        assert len(stats) >= 1
        s = stats[0]
        assert "quota_remaining" in s
        assert "weight" in s
        assert "breaker_state" in s
        assert "breaker_recover_in_seconds" in s
        assert s["quota_remaining"] == 10
        assert s["weight"] == 3
        assert s["breaker_state"] == "closed"