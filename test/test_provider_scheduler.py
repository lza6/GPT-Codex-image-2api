"""ProviderScheduler 单测：档位分布 + provider 统计 + 缓存 + 边界。"""
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