from __future__ import annotations

import random
import time
from threading import Lock
from typing import Any


class ProviderScheduler:
    """各 Provider 独立调度池（Phase 2：调度分池）。

    每个 provider 独立维护：
    - 健康档位分布（healthy/warm/risky）
    - 调度分排序列表
    - 熔断器状态
    - 配额隔离（独立 rate limit）
    - 权重调度（配置化比率）

    与 AccountService 桥接：AccountService 的 _ranked_candidate_tokens 等
    方法通过 provider 参数过滤后，由本模块包装为 provider 级调度。
    """

    _HEALTHY = "healthy"
    _WARM = "warm"
    _RISKY = "risky"
    _TIER_ORDER = (_HEALTHY, _WARM, _RISKY)

    # Provider 级熔断器参数
    _PROVIDER_CB_THRESHOLD = 3  # 连续 N 次无可用账号后熔断该 provider
    _PROVIDER_CB_RECOVERY = 60.0  # 冷却期（秒）

    # Provider 级 rate limit 滑动窗口（秒）
    _PROVIDER_RATE_WINDOW = 60.0

    def __init__(self):
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_at: float = 0.0
        self._cache_ttl: float = 5.0

        # Provider 级熔断器
        self._provider_breakers: dict[str, dict[str, Any]] = {}
        self._provider_lock = Lock()

        # Provider 级 rate limiter
        self._provider_rate_limiters: dict[str, list[float]] = {}
        self._provider_rate_lock = Lock()

    # ──── Provider 级 rate limit ────

    def _check_provider_rate_limit(self, provider: str) -> bool:
        """检查该 provider 是否还有配额。返回 True 表示允许请求。"""
        from services.config import config

        rpm = config.provider_rate_limit_rpm.get(provider, 0)
        if rpm <= 0:
            return True  # 0=不限
        now = time.monotonic()
        with self._provider_rate_lock:
            timestamps = self._provider_rate_limiters.get(provider, [])
            cutoff = now - self._PROVIDER_RATE_WINDOW
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= rpm:
                self._provider_rate_limiters[provider] = timestamps
                return False
            timestamps.append(now)
            self._provider_rate_limiters[provider] = timestamps
            return True

    def _provider_rate_remaining(self, provider: str) -> int:
        """返回该 provider 剩余配额（窗口内）。-1 表示不限。"""
        from services.config import config

        rpm = config.provider_rate_limit_rpm.get(provider, 0)
        if rpm <= 0:
            return -1
        now = time.monotonic()
        with self._provider_rate_lock:
            timestamps = [
                t
                for t in self._provider_rate_limiters.get(provider, [])
                if t > now - self._PROVIDER_RATE_WINDOW
            ]
            return max(0, rpm - len(timestamps))

    # ──── Provider 级熔断器 ────

    def _record_provider_failure(self, provider: str) -> None:
        """记录 provider 级连续失败，达到阈值熔断该 provider。"""
        prev_state = "closed"
        with self._provider_lock:
            cb = self._provider_breakers.get(provider)
            if cb is None:
                cb = {"count": 0, "state": "closed", "opened_at": 0.0}
            prev_state = cb["state"]
            cb["count"] = cb.get("count", 0) + 1
            if cb["count"] >= self._PROVIDER_CB_THRESHOLD:
                cb["state"] = "open"
                cb["opened_at"] = time.monotonic()
            self._provider_breakers[provider] = cb
        # 状态变化时发布事件
        if prev_state != cb["state"]:
            try:
                from services.event_bus import PROVIDER_HEALTH_CHANGED, Event, event_bus
                event_bus.publish(Event(PROVIDER_HEALTH_CHANGED, {
                    "provider": provider,
                    "from_state": prev_state,
                    "to_state": cb["state"],
                    "reason": "circuit_breaker_open" if cb["state"] == "open" else "failure_count_increase",
                }))
            except Exception:
                pass

    def _record_provider_success(self, provider: str) -> None:
        """成功清零 provider 熔断器。"""
        prev_state = "unknown"
        with self._provider_lock:
            cb = self._provider_breakers.get(provider)
            if cb:
                prev_state = cb["state"]
            self._provider_breakers.pop(provider, None)
        # 从熔断状态恢复时发布事件
        if prev_state in ("open", "half_open"):
            try:
                from services.event_bus import PROVIDER_HEALTH_CHANGED, Event, event_bus
                event_bus.publish(Event(PROVIDER_HEALTH_CHANGED, {
                    "provider": provider,
                    "from_state": prev_state,
                    "to_state": "closed",
                    "reason": "success_recovery",
                }))
            except Exception:
                pass

    def _provider_allow_request(self, provider: str) -> bool:
        """检查该 provider 是否允许请求（未熔断）。"""
        with self._provider_lock:
            cb = self._provider_breakers.get(provider)
            if cb is None:
                return True
            if cb["state"] == "open":
                if time.monotonic() - cb["opened_at"] >= self._PROVIDER_CB_RECOVERY:
                    self._provider_breakers.pop(provider, None)
                    return True
                return False
            return True

    def _provider_breaker_state(self, provider: str) -> dict[str, Any]:
        """返回该 provider 熔断器状态。"""
        with self._provider_lock:
            cb = self._provider_breakers.get(provider)
            if cb is None:
                return {"state": "closed", "recover_in_seconds": 0}
            if cb["state"] == "open":
                remaining = max(
                    0.0,
                    self._PROVIDER_CB_RECOVERY - (time.monotonic() - cb["opened_at"]),
                )
                return {
                    "state": "open",
                    "recover_in_seconds": round(remaining, 1),
                }
            return {"state": "closed", "recover_in_seconds": 0}

    # ──── Provider 权重调度 ────

    def _pick_provider_by_weight(
        self, enabled_providers: list[str] | None = None
    ) -> str | None:
        """按配置权重随机选取一个 provider。返回 None 表示无可用 provider。"""
        from services.config import config
        from services.providers import DEFAULT_PROVIDER, is_valid_provider

        weights = config.provider_weights
        if not weights:
            return DEFAULT_PROVIDER
        candidates = {
            p: w
            for p, w in weights.items()
            if w > 0
            and is_valid_provider(p)
            and (enabled_providers is None or p in enabled_providers)
        }
        if not candidates:
            return None
        if len(candidates) == 1:
            return next(iter(candidates))
        providers = list(candidates.keys())
        weights_list = [candidates[p] for p in providers]
        return random.choices(providers, weights=weights_list, k=1)[0]

    def _get_weighted_providers(self) -> list[str]:
        """返回配置了正权重的 provider 列表。"""
        from services.config import config
        from services.providers import is_valid_provider

        weights = config.provider_weights
        if not weights:
            from services.providers import DEFAULT_PROVIDER

            return [DEFAULT_PROVIDER]
        return [
            p
            for p, w in weights.items()
            if w > 0 and is_valid_provider(p)
        ]

    # ──── 档位分布统计 ────

    def compute_tier_distribution(
        self, accounts: list[dict], provider: str | None = None
    ) -> dict[str, int]:
        """计算某 provider（或全部）的档位分布。"""
        from services.account_service import AccountService

        tiers = {"healthy": 0, "warm": 0, "risky": 0}
        for account in accounts:
            if provider and account.get("provider") != provider:
                continue
            status = str(account.get("status") or "")
            if status in {"禁用", "异常"}:
                tiers["risky"] += 1
            else:
                tier = AccountService._account_health_tier(account)
                tiers[tier] = tiers.get(tier, 0) + 1
        return tiers

    def get_provider_stats(self, accounts: list[dict]) -> list[dict[str, Any]]:
        """返回各 provider 统计摘要，供前端看板使用。"""
        from services.config import config
        from services.providers import list_providers

        providers = list_providers(enabled_only=True)
        weights = config.provider_weights
        result = []
        for prov in providers:
            prov_accounts = [a for a in accounts if a.get("provider") == prov.name]
            if not prov_accounts:
                continue
            tiers = self.compute_tier_distribution(prov_accounts, prov.name)
            total = sum(tiers.values())
            available = sum(v for k, v in tiers.items() if k != "risky")
            quota_remaining = self._provider_rate_remaining(prov.name)
            weight = weights.get(prov.name, 0) if weights else 0
            breaker = self._provider_breaker_state(prov.name)
            result.append(
                {
                    "name": prov.name,
                    "display_name": prov.display_name,
                    "enabled": prov.enabled,
                    "total_accounts": total,
                    "available_accounts": available,
                    "tiers": tiers,
                    "quota_remaining": quota_remaining,
                    "weight": weight,
                    "breaker_state": breaker["state"],
                    "breaker_recover_in_seconds": breaker["recover_in_seconds"],
                }
            )
        return result


provider_scheduler = ProviderScheduler()