from __future__ import annotations

import base64
import json
import logging
import random
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Condition, Lock, RLock, Thread
from typing import Any
from urllib.parse import urlencode

from services.circuit_breaker import circuit_breaker_registry
from services.config import config
from services.log_service import (
    LOG_TYPE_ACCOUNT,
    log_service,
)
from services.router_service import router_service
from services.storage.base import StorageBackend
from utils.helper import anonymize_token

logger = logging.getLogger(__name__)


class AccountService:
    """账号池服务，使用 token -> account 的 dict 保存账号。"""

    _NEW_ACCOUNT_INVALID_GRACE_SECONDS = 10 * 60
    _INVALID_CONFIRM_SECONDS = 30
    _ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 24 * 60 * 60
    _REFRESH_TOKEN_KEEPALIVE_SECONDS = 3 * 24 * 60 * 60
    _REFRESH_TOKEN_KEEPALIVE_ERROR_BACKOFF_SECONDS = 6 * 60 * 60
    _REFRESH_TOKEN_KEEPALIVE_BATCH_SIZE = 3
    _TOKEN_REFRESH_ERROR_BACKOFF_SECONDS = 5 * 60
    _OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
    _OAUTH_CLIENT_ID = "app_2SKx67EdpoN0G6j64rFvigXD"
    # 邮箱+密码导入时登录失败账号的占位 access_token 前缀（不污染真实 token 空间，
    # 调度/刷新遍历一律跳过；凭据保留，可用 re_login_accounts 重试）。
    _PENDING_PREFIX = "pending:"
    _OAUTH_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    )
    _ACCOUNT_LIST_CACHE_TTL: float = 5.0
    # 3.1.4：脏标记节流——_save_accounts 最多每秒写一次，避免高频 mutation 重复全量写
    _SAVE_DEBOUNCE_SECONDS: float = 1.0

    def __init__(self, storage_backend: StorageBackend, progress_ttl_seconds: float = 3600.0):
        self.storage = storage_backend
        # 进度记录 TTL（秒）：防止进度字典随运行时间无界增长（D5 收口）。
        # 允许亚秒级取值以支持测试与极端运维场景；非正数回退默认 3600。
        try:
            ttl = float(progress_ttl_seconds)
        except (TypeError, ValueError):
            ttl = 3600.0
        self.progress_ttl_seconds = ttl if ttl > 0 else 3600.0
        # 进度追踪为实例属性（曾用类属性，多实例共享 + 各自 TTL 清理会跨实例误删——独立审查 Critical 1）
        self._refresh_progress: dict[str, dict] = {}
        self._refresh_progress_lock = Lock()
        self._relogin_progress: dict[str, dict] = {}
        self._relogin_progress_lock = Lock()
        self._consecutive_429_count = 0
        # 熔断器注册表引用（默认全局单例；测试可注入独立注册表验证生命周期清理 D4）
        self._breaker_registry = circuit_breaker_registry
        # prune 节流：距上次清理 <60s 跳过（防 SSE 高频轮询 get 路径 O(n) 全扫退化，红队 R5）
        self._last_prune_at: dict[int, float] = {}
        self._lock = RLock()
        self._token_refresh_lock = Lock()
        self._image_slot_condition = Condition(self._lock)
        self._index = 0
        with self._lock:
            self._accounts = self._load_accounts()
        # 3.1.4：脏标记 + 节流——避免连续 mutation 重复全量写存储
        self._dirty = False
        self._last_save_at = 0.0
        self._image_inflight: dict[str, int] = {}
        self._token_aliases: dict[str, str] = {}
        self._cumulative_total = self._load_cumulative_total()
        self._account_list_cache: dict[str, object] = {}
        self._account_list_cache_at: float = 0.0
        # 智能调度增强：Affinity 亲和路由
        self._affinity_map: dict[str, str] = {}  # model -> last_token
        self._affinity_at: dict[str, float] = {}  # model -> last_used_timestamp
        # 智能调度增强：Predictive EWMA 消耗速率（token -> rate）
        self._usage_rate: dict[str, float] = {}  # token -> EWMA rate (calls/hour)
        # III-02：调度模式 A/B 可观测——per-mode 聚合（命中数/成功/失败/延迟累计）
        self._scheduler_mode_stats: dict[str, dict[str, float | int]] = {}
        # token -> 本次 pick 时的生效调度模式（mark_image_result 回填结果）
        self._last_pick_mode: dict[str, str] = {}
        # token -> 本次 pick 的单调时钟起点（结果回填时算端到端耗时）
        self._pick_started_at: dict[str, float] = {}

    def set_circuit_breaker_registry(self, registry) -> None:
        """注入熔断器注册表（生产为全局单例，测试注入独立实例验证清理）。"""
        self._breaker_registry = registry

    def _get_cumulative_file(self) -> Path:
        from services.config import DATA_DIR
        return DATA_DIR / ".cumulative_total"

    def _load_cumulative_total(self) -> int:
        try:
            f = self._get_cumulative_file()
            if f.exists():
                return int(f.read_text().strip())
        except Exception:
            pass
        return len(self._accounts)

    def _save_cumulative_total(self) -> None:
        try:
            self._get_cumulative_file().write_text(str(self._cumulative_total))
        except Exception:
            pass

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _decode_jwt_payload(token: str) -> dict:
        try:
            payload = str(token or "").split(".")[1]
            payload += "=" * ((4 - len(payload) % 4) % 4)
            import base64
            import json
            data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            try:
                parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _timestamp_to_iso(value: object) -> str:
        """D12/D17：导出时间戳统一为 UTC ISO8601（原 UTC+8 硬编码，跨时区部署不一致）。"""
        try:
            ts = int(value)
        except (TypeError, ValueError):
            return ""
        return datetime.fromtimestamp(ts, tz=UTC).isoformat()

    def _load_accounts(self) -> dict[str, dict]:
        accounts = self.storage.load_accounts()
        return {
            normalized["access_token"]: normalized
            for item in accounts
            if (normalized := self._normalize_account(item)) is not None
        }

    def _save_accounts(self) -> None:
        if not self._dirty:
            return
        self.storage.save_accounts(list(self._accounts.values()))
        self._invalidate_account_list_cache()
        self._dirty = False
        self._last_save_at = time.time()

    @staticmethod
    def _is_image_account_available(account: dict) -> bool:
        if not isinstance(account, dict):
            return False
        if account.get("status") in {"禁用", "限流", "异常"}:
            return False
        quota = int(account.get("quota") or 0)
        # quota != 0 即可用：> 0 是常规剩余配额，-1 是 OpenAI 无限配额
        # （free plan 无硬上限场景，实测真实账号返回 remaining=-1）。
        # quota=0/None 才拒选。
        return quota != 0

    # ---- 健康档位 + 调度分（移植自 codex2api fast_scheduler） ----
    # 档位：healthy > warm > risky，档位越高优先调度；
    # 调度分：同档位内按分数竞争，分数 = 配额比例 + 成功加成 - 失败惩罚 - 冷却惩罚
    _HEALTHY = "healthy"
    _WARM = "warm"
    _RISKY = "risky"
    _TIER_ORDER = (_HEALTHY, _WARM, _RISKY)
    _TIER_BASE_SCORE = {_HEALTHY: 100.0, _WARM: 60.0, _RISKY: 20.0}

    @classmethod
    def _recent_error_seconds(cls, account: dict, field: str) -> float | None:
        value = account.get(field)
        if not value:
            return None
        try:
            ts = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, time.time() - ts)

    @classmethod
    def _account_health_tier(cls, account: dict) -> str:
        """按状态 + 最近错误 + 配额比例计算健康档位（5.1 起含寿命预测降档）。"""
        tier = cls._account_health_tier_base(account)
        return cls._lifetime_downgrade(tier, account)

    @classmethod
    def _account_health_tier_base(cls, account: dict) -> str:
        """基础档位（不含寿命预测降档）——供调度分与测试复用。"""
        if not isinstance(account, dict):
            return cls._RISKY
        status = account.get("status")
        if status in {"禁用", "异常"}:
            return cls._RISKY
        if status == "限流":
            return cls._RISKY
        quota = max(0, int(account.get("quota") or 0))
        # 最近刷新错误惩罚
        refresh_err = cls._recent_error_seconds(account, "last_refresh_error_at")
        token_err = cls._recent_error_seconds(account, "last_token_refresh_error_at")
        if (refresh_err is not None and refresh_err < 600) or (token_err is not None and token_err < 300):
            return cls._WARM
        fail = max(0, int(account.get("fail") or 0))
        success = max(0, int(account.get("success") or 0))
        total = fail + success
        if total >= 3 and fail / total > 0.5:
            return cls._RISKY
        if quota <= 0:
            return cls._RISKY
        if quota < 5 or (total >= 3 and fail / total > 0.2):
            return cls._WARM
        return cls._HEALTHY

    @classmethod
    def _lifetime_downgrade(cls, tier: str, account: dict) -> str:
        """5.1：账号寿命预测降档——濒危→risky、高→warm，低/中不降。

        只降不升（健康账号不会因预测被抬升）；最小观测窗口守卫在
        account_lifetime 内部完成，避免「瞬间封禁/复活抖动」。

        III-03：配额预警第三信号——按配额消耗速率估算剩余天数，
        剩余 <=1 天 → risky、<=3 天且当前 healthy → warm（同样只降不升）。
        """
        try:
            from services.account_lifetime import (
                LEVEL_CRITICAL,
                LEVEL_HIGH,
                QUOTA_CRITICAL_DAYS,
                QUOTA_WARN_DAYS,
                compute_lifetime_risk,
            )
        except Exception:  # pragma: no cover - 模块缺失时降级为原档位
            return tier
        risk = compute_lifetime_risk(account)
        level = risk.get("level")
        quota_days = (risk.get("signals") or {}).get("quota_remaining_days")
        if level == LEVEL_CRITICAL:
            return cls._RISKY
        # III-03：配额濒危（剩余 <=1 天）优先降 risky——避免耗尽瞬间才熔断
        if quota_days is not None and quota_days <= QUOTA_CRITICAL_DAYS:
            if tier != cls._RISKY:
                return cls._RISKY
        if level == LEVEL_HIGH and tier == cls._HEALTHY:
            return cls._WARM
        # III-03：配额预警档位（只降不升）
        if quota_days is not None and quota_days <= QUOTA_WARN_DAYS and tier == cls._HEALTHY:
            return cls._WARM
        return tier

    @classmethod
    def _account_dispatch_score(cls, account: dict, tier: str | None = None) -> float:
        """同档位内竞争分数：配额占比 + 成功加成 - 失败惩罚 - 冷却惩罚。"""
        if not isinstance(account, dict):
            return -100.0
        tier = tier or cls._account_health_tier(account)
        score = cls._TIER_BASE_SCORE.get(tier, 20.0)
        quota = max(0, int(account.get("quota") or 0))
        # 配额占比（0-10 分）：quota 越高分越高
        score += min(10.0, quota / 10.0)
        success = max(0, int(account.get("success") or 0))
        fail = max(0, int(account.get("fail") or 0))
        total = success + fail
        if total > 0:
            # 成功加成最多 +5，失败惩罚最多 -10
            score += 5.0 * (success / total)
            score -= 10.0 * (fail / total)
        # 最近错误时间惩罚：1 分钟前错误 -10，越近越重
        for field in ("last_refresh_error_at", "last_token_refresh_error_at"):
            err_seconds = cls._recent_error_seconds(account, field)
            if err_seconds is not None and err_seconds < 1800:
                score -= 10.0 * (1.0 - err_seconds / 1800)
        return round(score, 2)

    def _priority_for_token(self, token: str) -> int:
        """账号级调度优先级（config.scheduler_priority 按 email/token 前缀配置）。"""
        priorities = config.scheduler_priority
        if not priorities:
            return 0
        if token in priorities:
            return int(priorities[token])
        account = self._accounts.get(token) if isinstance(self._accounts, dict) else None
        email = str((account or {}).get("email") or "")
        if email in priorities:
            return int(priorities[email])
        return 0

    def _effective_scheduler_mode(self) -> str:
        """当前生效调度模式：自适应开启时用 adaptive_scheduler.current_mode，否则 config.scheduler_mode。

        adaptive 切换只改 AdaptiveScheduler 内部状态（不写回 config），
        故实际选号分支仍按 config.scheduler_mode 走，但 A/B 观测用生效模式
        标记每次 pick，使自适应切换前后标签口径一致。
        """
        try:
            if config.scheduler_adaptive_enabled:
                from services.adaptive_scheduler import adaptive_scheduler

                mode = adaptive_scheduler.current_mode
                if mode:
                    return mode
        except Exception:  # noqa: BLE001 - 观测不影响选号主流程
            pass
        return config.scheduler_mode or "round_robin"

    def _record_scheduler_pick_stat(self, access_token: str, mode: str) -> None:
        """记录一次调度选取到 per-mode 统计（供看板 A/B 对比）。"""
        if not mode:
            mode = "round_robin"
        stat = self._scheduler_mode_stats.setdefault(
            mode, {"picks": 0, "success": 0, "fail": 0, "latency_sum_ms": 0.0}
        )
        stat["picks"] = int(stat.get("picks") or 0) + 1
        self._last_pick_mode[access_token] = mode
        self._pick_started_at[access_token] = time.monotonic()

    def _record_scheduler_result_stat(self, access_token: str, success: bool) -> None:
        """把一次调度结果（成功/失败 + 端到端耗时）回填到对应模式的统计。"""
        mode = self._last_pick_mode.pop(access_token, None)
        start = self._pick_started_at.pop(access_token, None)
        if mode is None or mode not in self._scheduler_mode_stats:
            return
        stat = self._scheduler_mode_stats[mode]
        if success:
            stat["success"] = int(stat.get("success") or 0) + 1
        else:
            stat["fail"] = int(stat.get("fail") or 0) + 1
        if start is not None:
            stat["latency_sum_ms"] = float(stat.get("latency_sum_ms") or 0.0) + (time.monotonic() - start) * 1000.0

    def get_scheduler_mode_stats(self, limit: int = 20) -> list[dict[str, object]]:
        """按调度模式返回聚合统计（命中数/成功率/平均延迟），供看板 A/B 对比。

        延迟口径：从调度 pick 到 mark_image_result（端到端出图耗时），
        可对比不同调度模式的出图快慢。
        """
        with self._lock:
            items = [dict(item) for item in self._scheduler_mode_stats.values()]
            keys = list(self._scheduler_mode_stats.keys())
        stats = []
        for mode, stat in zip(keys, items):
            picks = int(stat.get("picks") or 0)
            success = int(stat.get("success") or 0)
            fail = int(stat.get("fail") or 0)
            done = success + fail
            latency_sum = float(stat.get("latency_sum_ms") or 0.0)
            stats.append({
                "mode": mode,
                "picks": picks,
                "success": success,
                "fail": fail,
                "fail_rate": round(fail / done, 4) if done else 0.0,
                "avg_latency_ms": round(latency_sum / done, 1) if done else 0.0,
            })
        stats.sort(key=lambda item: -int(item["picks"]))
        return stats[:limit]

    @classmethod
    def _account_matches_plan_type(cls, account: dict, plan_type: str | None = None) -> bool:
        if not plan_type:
            return True
        normalized_plan = cls._normalize_account_type(plan_type)
        normalized_account = cls._normalize_account_type(account.get("type"))
        if not normalized_plan or not normalized_account:
            return False
        return normalized_plan.lower() == normalized_account.lower()

    @classmethod
    def _account_matches_source_type(cls, account: dict, source_type: str | None = None) -> bool:
        if not source_type:
            return True
        return cls._normalize_source_type(account.get("source_type")) == cls._normalize_source_type(source_type)

    @classmethod
    def _account_matches_provider(cls, account: dict, provider: str | None = None) -> bool:
        """provider 为空或不传时不过滤（兼容全量返回场景）。"""
        if not provider:
            return True
        from services.providers import normalize_provider
        return normalize_provider(account.get("provider")) == normalize_provider(provider)

    @classmethod
    def _account_matches_any_plan_type(cls, account: dict, plan_types: set[str] | tuple[str, ...] | None = None) -> bool:
        if not plan_types:
            return True
        normalized_account = cls._normalize_account_type(account.get("type"))
        normalized_plans = {
            normalized
            for plan_type in plan_types
            if (normalized := cls._normalize_account_type(plan_type))
        }
        return bool(normalized_account and normalized_account in normalized_plans)

    @staticmethod
    def _normalize_source_type(value: object) -> str:
        return str(value or "web").strip().lower() or "web"

    @staticmethod
    def _normalize_account_type(value: object) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        key = raw.lower().replace("-", "_").replace(" ", "_")
        compact = key.replace("_", "")
        aliases = {
            "free": "free",
            "plus": "Plus",
            "pro": "Pro",
            "prolite": "ProLite",
            "team": "Team",
            "business": "Team",
            "enterprise": "Enterprise",
        }
        return aliases.get(compact) or aliases.get(key) or raw

    def _search_account_type(self, payload: object) -> str | None:
        if isinstance(payload, dict):
            for key in ("plan_type", "account_plan", "account_type", "subscription_type", "type"):
                plan = self._normalize_account_type(payload.get(key))
                if plan:
                    return plan
            for value in payload.values():
                plan = self._search_account_type(value)
                if plan:
                    return plan
        elif isinstance(payload, list):
            for value in payload:
                plan = self._search_account_type(value)
                if plan:
                    return plan
        return None

    def _normalize_account(self, item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        access_token = item.get("access_token") or item.get("accessToken") or ""
        if not access_token:
            return None
        normalized = dict(item)
        normalized.pop("accessToken", None)
        normalized["access_token"] = access_token
        if str(normalized.get("type") or "").strip().lower() == "codex":
            normalized["export_type"] = "codex"
            normalized.pop("type", None)
        normalized["type"] = normalized.get("type") or "free"
        normalized["status"] = normalized.get("status") or "正常"
        normalized["quota"] = normalized.get("quota")
        if normalized["quota"] is not None:
            try:
                quota_val = int(normalized["quota"])
                # 负数表示无限配额（OpenAI 语义，free plan 常见），保留原值
                normalized["quota"] = quota_val if quota_val < 0 else max(0, quota_val)
            except (TypeError, ValueError):
                normalized["quota"] = 0
        else:
            normalized["quota"] = 0
        normalized["email"] = normalized.get("email") or None
        normalized["user_id"] = normalized.get("user_id") or None
        normalized["proxy"] = str(normalized.get("proxy") or "").strip()
        source_type = normalized.get("source_type")
        if not source_type and str(normalized.get("export_type") or "").strip().lower() == "codex":
            source_type = "codex"
        normalized["source_type"] = self._normalize_source_type(source_type)
        limits_progress = normalized.get("limits_progress")
        normalized["limits_progress"] = limits_progress if isinstance(limits_progress, list) else []
        normalized["default_model_slug"] = normalized.get("default_model_slug") or None
        normalized["restore_at"] = normalized.get("restore_at") or None
        normalized["success"] = int(normalized.get("success") or 0)
        normalized["fail"] = int(normalized.get("fail") or 0)
        normalized["invalid_count"] = int(normalized.get("invalid_count") or 0)
        normalized["last_used_at"] = normalized.get("last_used_at")
        normalized["last_invalid_at"] = normalized.get("last_invalid_at") or None
        normalized["last_refresh_error"] = normalized.get("last_refresh_error") or None
        normalized["last_refresh_error_at"] = normalized.get("last_refresh_error_at") or None
        normalized["last_refresh_error_detail"] = normalized.get("last_refresh_error_detail") or None
        normalized["last_token_refresh_at"] = normalized.get("last_token_refresh_at") or None
        normalized["last_token_refresh_error"] = normalized.get("last_token_refresh_error") or None
        normalized["last_token_refresh_error_at"] = normalized.get("last_token_refresh_error_at") or None
        # 多提供商地基：账号归属提供商，默认 chatgpt（自由 schema，无需改库）
        from services.providers import normalize_provider
        normalized["provider"] = normalize_provider(normalized.get("provider"))
        normalized["created_at"] = normalized.get("created_at") or AccountService._now()
        normalized["health_score"] = float(normalized.get("health_score") or 0.0)
        normalized["health_score_below_20_since"] = normalized.get("health_score_below_20_since") or None
        normalized["self_heal_retry_attempts"] = int(normalized.get("self_heal_retry_attempts") or 0)
        normalized["self_heal_next_retry_at"] = normalized.get("self_heal_next_retry_at") or None
        normalized["replaced_by"] = normalized.get("replaced_by") or None
        return normalized

    @staticmethod
    def _jwt_exp(access_token: str) -> int:
        try:
            return int(AccountService._decode_jwt_payload(access_token).get("exp") or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _token_expires_in(cls, access_token: str) -> int | None:
        exp = cls._jwt_exp(access_token)
        if exp <= 0:
            return None
        return exp - int(time.time())

    @classmethod
    def _token_needs_refresh(cls, access_token: str, *, force: bool = False) -> bool:
        if force:
            return True
        remaining = cls._token_expires_in(access_token)
        return remaining is not None and remaining <= cls._ACCESS_TOKEN_REFRESH_SKEW_SECONDS

    @classmethod
    def _token_issued_at(cls, access_token: str) -> datetime | None:
        try:
            iat = int(cls._decode_jwt_payload(access_token).get("iat") or 0)
        except (TypeError, ValueError):
            return None
        if iat <= 0:
            return None
        return datetime.fromtimestamp(iat, tz=UTC)

    @staticmethod
    def _safe_response_text(response: object, limit: int = 300) -> str:
        try:
            return str(getattr(response, "text", "") or "")[:limit]
        except Exception:
            return ""

    def _resolve_access_token_locked(self, access_token: str) -> str:
        token = str(access_token or "").strip()
        seen: set[str] = set()
        while token and token not in self._accounts and token in self._token_aliases and token not in seen:
            seen.add(token)
            token = self._token_aliases.get(token, token)
        return token

    def resolve_access_token(self, access_token: str) -> str:
        if not access_token:
            return ""
        with self._lock:
            return self._resolve_access_token_locked(access_token)

    def _get_account_for_token(self, access_token: str) -> tuple[str, dict | None]:
        with self._lock:
            resolved = self._resolve_access_token_locked(access_token)
            account = self._accounts.get(resolved)
            return resolved, dict(account) if account else None

    def _record_token_refresh_error(self, access_token: str, event: str, error: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            resolved = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(resolved)
            if current is None:
                return
            next_item = dict(current)
            next_item["last_token_refresh_error"] = str(error or "refresh token failed")
            next_item["last_token_refresh_error_at"] = now
            account = self._normalize_account(next_item)
            if account is not None:
                self._accounts[resolved] = account
                self._dirty = True
                self._save_accounts()
        log_service.add(
            LOG_TYPE_ACCOUNT,
            "refresh_token 刷新 access_token 失败",
            {"source": event, "token": anonymize_token(access_token), "error": str(error or "")},
        )

    def _recent_token_refresh_error(self, account: dict) -> bool:
        last_error_at = self._parse_time(account.get("last_token_refresh_error_at"))
        if last_error_at is None:
            return False
        return (datetime.now(UTC) - last_error_at).total_seconds() < self._TOKEN_REFRESH_ERROR_BACKOFF_SECONDS

    def _recent_refresh_token_keepalive_error(self, account: dict, now: datetime) -> bool:
        last_error_at = self._parse_time(account.get("last_token_refresh_error_at"))
        if last_error_at is None:
            return False
        return (now - last_error_at).total_seconds() < self._REFRESH_TOKEN_KEEPALIVE_ERROR_BACKOFF_SECONDS

    def _refresh_token_keepalive_anchor(self, account: dict) -> datetime | None:
        return (
            self._parse_time(account.get("last_token_refresh_at"))
            or self._token_issued_at(str(account.get("access_token") or ""))
            or self._parse_time(account.get("created_at"))
        )

    def _refresh_token_keepalive_due_at(self, account: dict, now: datetime) -> datetime | None:
        if not str(account.get("refresh_token") or "").strip():
            return None
        if account.get("status") == "禁用":
            return None
        if self._recent_refresh_token_keepalive_error(account, now):
            return None
        anchor = self._refresh_token_keepalive_anchor(account)
        if anchor is None:
            return now
        due_at = anchor + timedelta(seconds=self._REFRESH_TOKEN_KEEPALIVE_SECONDS)
        return due_at if due_at <= now else None

    def _request_access_token_refresh(self, refresh_token: str, account: dict | None = None) -> dict[str, str]:
        from services.session_pool import session_pool

        # 复用连接池中的 Session，避免每次 TLS 握手
        session = session_pool.get(account=account, impersonate="chrome110", verify=True)
        try:
            response = session.post(
                self._OAUTH_TOKEN_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": self._OAUTH_USER_AGENT,
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self._OAUTH_CLIENT_ID,
                },
                timeout=60,
            )
            data = response.json() if response.text else {}
            if response.status_code != 200 or not isinstance(data, dict) or not data.get("access_token"):
                detail = ""
                if isinstance(data, dict):
                    detail = str(data.get("error_description") or data.get("error") or data.get("message") or "")
                detail = detail or self._safe_response_text(response)
                raise RuntimeError(f"oauth_refresh_http_{response.status_code}{': ' + detail if detail else ''}")
            return {
                "access_token": str(data.get("access_token") or "").strip(),
                "refresh_token": str(data.get("refresh_token") or refresh_token).strip(),
                "id_token": str(data.get("id_token") or "").strip(),
            }
        finally:
            # 池化 Session：归还到池复用，不真正 close（否则每次刷新都拆掉池化连接，池形同虚设）
            if getattr(session, "_chatgpt2api_pooled", False):
                session_pool.release(session)
            else:
                session.close()

    def _apply_refreshed_tokens(self, old_access_token: str, token_data: dict, event: str) -> str:
        now = datetime.now(UTC).isoformat()
        with self._image_slot_condition:
            old_token = self._resolve_access_token_locked(old_access_token)
            current = self._accounts.get(old_token)
            if current is None:
                return old_token
            new_token = str(token_data.get("access_token") or old_token).strip()
            if not new_token:
                return old_token

            next_item = dict(current)
            next_item["access_token"] = new_token
            if token_data.get("refresh_token"):
                next_item["refresh_token"] = str(token_data.get("refresh_token") or "").strip()
            if token_data.get("id_token"):
                next_item["id_token"] = str(token_data.get("id_token") or "").strip()
            next_item["last_token_refresh_at"] = now
            next_item["last_token_refresh_error"] = None
            next_item["last_token_refresh_error_at"] = None
            next_item["invalid_count"] = 0
            next_item["last_invalid_at"] = None
            next_item["last_refresh_error"] = None
            next_item["last_refresh_error_at"] = None
            next_item["last_refresh_error_detail"] = None

            account = self._normalize_account(next_item)
            if account is None:
                return old_token

            rotated = new_token != old_token
            if rotated:
                self._accounts.pop(old_token, None)
                self._token_aliases[old_token] = new_token
                # D4：token 轮换后清理旧 token 的熔断器（防注册表孤儿化）
                self._breaker_registry.remove(old_token)
                old_inflight = int(self._image_inflight.pop(old_token, 0))
                if old_inflight:
                    self._image_inflight[new_token] = int(self._image_inflight.get(new_token, 0)) + old_inflight
            self._accounts[new_token] = account
            self._dirty = True
            self._save_accounts()
            self._image_slot_condition.notify_all()

        log_service.add(
            LOG_TYPE_ACCOUNT,
            "refresh_token 已刷新 access_token",
            {"source": event, "token": anonymize_token(new_token), "rotated": rotated},
        )
        return new_token

    def refresh_access_token(self, access_token: str, *, force: bool = False, event: str = "refresh_access_token") -> str:
        if not access_token:
            return ""
        with self._token_refresh_lock:
            resolved_token, account = self._get_account_for_token(access_token)
            if not account:
                return access_token
            active_token = str(account.get("access_token") or resolved_token or access_token)
            if not self._token_needs_refresh(active_token, force=force):
                return active_token
            refresh_token = str(account.get("refresh_token") or "").strip()
            if not refresh_token:
                return active_token
            if not force and self._recent_token_refresh_error(account):
                return active_token
            try:
                token_data = self._request_access_token_refresh(refresh_token, account)
            except Exception as exc:
                error_str = str(exc or "")
                self._record_token_refresh_error(active_token, event, error_str)
                # 如果是 app_session_terminated 错误，尝试密码重新登录
                if "app_session_terminated" in error_str.lower():
                    # 获取账号信息（email, password）
                    email = str(account.get("email") or "").strip()
                    password = str(account.get("password") or "").strip()
                    if email and password:
                        # 创建新线程执行密码重新登录
                        t = Thread(
                            target=self._password_re_login_thread,
                            args=(active_token, email, password, event),
                            daemon=True,
                        )
                        t.start()
                return active_token
            return self._apply_refreshed_tokens(active_token, token_data, event)

    # 触发 OTP 降级的密码登录错误集合（OpenAI 风控要验证码 / passwordless 账号无可用密码 401/400）
    _OTP_FALLBACK_ERRORS = frozenset({"need_verification_code", "password_verify_failed_401", "password_verify_failed_400"})

    def _otp_fallback_login(self, email: str, password: str, mail_cred: dict | None, proxy_url: str = "") -> dict | None:
        """密码登录失败后的邮箱验证码降级登录（watcher 重登与导入共用）。

        有取件凭证(client_id+refresh_token)时走 OTP 取件登录，返回结果 dict；无凭证返回
        None（调用方保留原错误落 pending）。**不**把 GPT 登录密码塞进 mail_credential——
        微软 Graph 取件用 refresh_token 不需要它，避免 98faka 兜底时把 GPT 密码发给第三方。
        """
        if not (mail_cred and mail_cred.get("client_id") and mail_cred.get("refresh_token")):
            return None
        try:
            from services.otp_login_service import otp_login_service

            otp_result = otp_login_service.login(
                email,
                password,
                mail_credential={**mail_cred, "email": email},
                proxy_url=proxy_url,
            )
            if otp_result.get("ok"):
                otp_result["source_type"] = "otp"
            return otp_result
        except Exception as exc:
            return {"ok": False, "error": f"otp_login_exception:{type(exc).__name__}", "detail": {"message": str(exc)}}

    def _password_re_login_thread(self, access_token: str, email: str, password: str, event: str, progress_id: str | None = None) -> None:
        """密码重新登录线程入口（走 kookeey 住宅代理 + 取件凭证 + OTP 降级）"""
        try:
            from services.proxy_service import kookeey_proxy_for

            # 读取账号已存的取件凭证（client_id + refresh_token），供 OTP 降级用
            acct = self.get_account(access_token) or {}
            mail_cred = acct.get("mail_credential") if isinstance(acct.get("mail_credential"), dict) else None
            # 每号固定住宅 IP（粘性 session），避免同 IP 批量登录被风控
            proxy_url = kookeey_proxy_for(email)
            result = self._login_with_password(email, password, proxy_url=proxy_url)
            # 遇 OpenAI 风控要求邮箱 OTP、或 passwordless 账号无密码(401/400) 且有取件凭证 → 降级走 OTP 取件登录
            if (not result.get("ok")) and str(result.get("error") or "") in self._OTP_FALLBACK_ERRORS:
                otp_result = self._otp_fallback_login(email, password, mail_cred, proxy_url)
                if otp_result is not None:
                    result = otp_result
            if result.get("ok"):
                # 登录成功，更新账号
                new_access_token = result.get("access_token", "")
                new_refresh_token = result.get("refresh_token", "")
                new_id_token = result.get("id_token", "")
                # 注意：expires_at 取出后未写入 token_data（存量 bug，账号过期时间未入库），登记后续修复

                # 构建 token_data 供 _apply_refreshed_tokens 使用
                token_data = {
                    "access_token": new_access_token,
                    "refresh_token": new_refresh_token,
                    "id_token": new_id_token,
                }

                # 使用 _apply_refreshed_tokens 更新账号（处理 token 别名）
                new_token = self._apply_refreshed_tokens(access_token, token_data, f"{event}:password_relogin")

                # 额外更新 source_type 和 status（静默，避免重复日志）
                self.update_account(new_token, {
                    "source_type": result.get("source_type", "password"),
                    "status": "正常",
                }, quiet=True)

                log_service.add(
                    LOG_TYPE_ACCOUNT,
                    "更新账号",
                    {
                        "source": event,
                        "old_token": anonymize_token(access_token),
                        "new_token": anonymize_token(new_access_token),
                        "email": email,
                        "status": "成功",
                    },
                )
                if progress_id:
                    self.update_relogin_progress(progress_id, access_token, "成功")
            else:
                # 登录失败
                error_type = result.get("error", "")
                if error_type == "password_verify_failed_403" and isinstance(result.get("detail"), dict):
                    log_service.add(
                        LOG_TYPE_ACCOUNT,
                        "更新账号",
                        {
                            "source": event,
                            "token": anonymize_token(access_token),
                            "email": email,
                            "status": "失败",
                            "error": error_type,
                            "detail": result.get("detail", {}),
                        },
                    )
                    detail_error = result["detail"].get("error", {})
                    if isinstance(detail_error, dict) and detail_error.get("code") == "account_deactivated":
                        # 账号已删除/停用 → 标记为禁用，并记入回收站（含上游返回原因）
                        self.update_account(access_token, {"status": "禁用", "quota": 0}, quiet=True)
                        log_service.add(
                            LOG_TYPE_ACCOUNT,
                            "账号已停用-标记禁用",
                            {
                                "source": event,
                                "token": anonymize_token(access_token),
                                "email": email,
                                "detail": result.get("detail", {}),
                            },
                        )
                        try:
                            from services.trash_service import trash_service
                            acct = self.get_account(access_token) or {}
                            reason = str(detail_error.get("message") or "account_deactivated")[:200]
                            trash_service.add(
                                email=str(acct.get("email") or email),
                                access_token=str(acct.get("access_token") or access_token),
                                status="禁用",
                                reason=reason,
                                source=f"{event}:account_deactivated",
                                detail={"upstream_error": detail_error},
                            )
                        except Exception:
                            pass  # 回收站记录失败不阻断
                        if progress_id:
                            self.update_relogin_progress(progress_id, access_token, "禁用")
                    else:
                        # 永久故障：将账号标记为异常（或自动移除）
                        self.remove_invalid_token(access_token, f"{event}:password_relogin_failed", quiet=True)
                        if progress_id:
                            self.update_relogin_progress(progress_id, access_token, "异常", error_type)
                else:
                    log_service.add(
                        LOG_TYPE_ACCOUNT,
                        "更新账号",
                        {
                            "source": event,
                            "token": anonymize_token(access_token),
                            "email": email,
                            "status": "失败",
                            "error": error_type,
                            "detail": result.get("detail", {}),
                        },
                    )
                    # 永久故障：将账号标记为异常（或自动移除）
                    self.remove_invalid_token(access_token, f"{event}:password_relogin_failed", quiet=True)
                    if progress_id:
                        self.update_relogin_progress(progress_id, access_token, "异常", error_type)
        except Exception as exc:
            log_service.add(
                LOG_TYPE_ACCOUNT,
                "更新账号",
                {
                    "source": event,
                    "token": anonymize_token(access_token),
                    "email": email,
                    "status": "异常",
                    "error": str(exc),
                },
            )
            # 将账号标记为异常（或自动移除）
            self.remove_invalid_token(access_token, f"{event}:password_relogin_exception", quiet=True)
            if progress_id:
                self.update_relogin_progress(progress_id, access_token, "异常", str(exc))

    def _login_with_password(self, email: str, password: str, proxy_url: str = "") -> dict:
        """通过邮箱+密码登录，返回 {access_token, refresh_token, id_token, ...}

        proxy_url：可选的每号独立出口（kookeey 住宅代理）。为空时回退到全局
        `config.get_proxy_settings()`。传独立的住宅 IP 可降低同 IP 批量登录被风控的概率。
        """
        from curl_cffi import requests
        
        # 常量
        auth_base = "https://auth.openai.com"
        platform_oauth_audience = "https://api.openai.com/v1"
        platform_auth0_client = "eyJuYW1lIjoiYXV0aDAtc3BhLWpzIiwidmVyc2lvbiI6IjEuMjEuMCJ9"
        platform_oauth_client_id = self._OAUTH_CLIENT_ID
        platform_oauth_redirect_uri = "https://platform.openai.com/auth/callback"
        user_agent = self._OAUTH_USER_AGENT
        
        # 创建 session
        session_kwargs = {"impersonate": "chrome110", "verify": False}
        proxy = str(proxy_url or "").strip() or config.get_proxy_settings()
        if proxy:
            session_kwargs["proxy"] = proxy
        session = requests.Session(**session_kwargs)
        
        try:
            device_id = str(uuid.uuid4())
            
            # ─── 方式2: OAuth authorize 流程 ──────────────────────────
            # 使用 Platform Client + PKCE
            
            from utils.pkce import generate_pkce
            code_verifier, code_challenge = generate_pkce()
            
            # ② 发起 OAuth authorize 请求 (使用 Platform Client + PKCE)
            session.cookies.set("oai-did", device_id, domain=".auth.openai.com")
            session.cookies.set("oai-did", device_id, domain="auth.openai.com")
            params = {
                "issuer": auth_base,
                "client_id": platform_oauth_client_id,
                "audience": platform_oauth_audience,
                "redirect_uri": platform_oauth_redirect_uri,
                "device_id": device_id,
                "screen_hint": "login_or_signup",
                "max_age": "0",
                "login_hint": email,
                "scope": "openid profile email offline_access",
                "response_type": "code",
                "response_mode": "query",
                "state": secrets.token_urlsafe(32),
                "nonce": secrets.token_urlsafe(32),
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "auth0Client": platform_auth0_client,
            }
            authorize_url = f"{auth_base}/api/accounts/authorize?{urlencode(params)}"
            resp = session.get(
                authorize_url,
                headers={
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "user-agent": user_agent,
                    "sec-ch-ua": '"Chromium";v="145", "Google Chrome";v="145", "Not/A)Brand";v="99"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "document",
                    "sec-fetch-mode": "navigate",
                    "sec-fetch-site": "cross-site",
                    "sec-fetch-user": "?1",
                    "upgrade-insecure-requests": "1",
                    "referer": "https://platform.openai.com/",
                },
                allow_redirects=True,
                timeout=30,
            )
            
            if resp.status_code not in (200, 302):
                return {"ok": False, "error": f"authorize_failed_{resp.status_code}", "detail": {"url": resp.url, "text": resp.text[:500]}}
            
            # 检测最终 URL 是否指向错误页面
            final_url = str(resp.url)
            if "/error" in final_url and "payload=" in final_url:
                from urllib.parse import parse_qs, urlparse
                try:
                    parsed_query = parse_qs(urlparse(final_url).query)
                    error_payload_b64 = parsed_query.get("payload", [""])[0]
                    error_payload_b64 += "=" * ((4 - len(error_payload_b64) % 4) % 4)
                    error_payload = json.loads(base64.b64decode(error_payload_b64))
                    error_code = error_payload.get("errorCode", "")
                    if error_code == "rate_limit_exceeded":
                        return {"ok": False, "error": "rate_limit_exceeded", "detail": error_payload}
                    else:
                        return {"ok": False, "error": f"authorize_error_{error_code}", "detail": error_payload}
                except Exception as e:
                    return {"ok": False, "error": "authorize_redirect_error", "detail": {"url": final_url, "parse_error": str(e)}}
            
            # ③ 提交密码验证
            login_headers = {
                "accept": "application/json",
                "accept-language": "zh-CN,zh;q=0.9",
                "content-type": "application/json",
                "origin": auth_base,
                "priority": "u=1, i",
                "user-agent": user_agent,
                "sec-ch-ua": '"Chromium";v="145", "Google Chrome";v="145", "Not/A)Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "referer": f"{auth_base}/email-verification",
                "oai-device-id": device_id,
            }
            
            # 添加 sentinel token
            try:
                from utils.sentinel import build_sentinel_token
                sentinel_val, oai_sc_val = build_sentinel_token(session, device_id, "password_verify")
                login_headers["openai-sentinel-token"] = sentinel_val
                if oai_sc_val:
                    session.cookies.set("oai-sc", oai_sc_val, domain=".openai.com")
            except Exception:
                pass
            
            login_resp = session.post(
                f"{auth_base}/api/accounts/password/verify",
                headers=login_headers,
                json={"password": password},
                timeout=30,
            )
            
            login_data = {}
            try:
                login_data = login_resp.json() if login_resp.text else {}
            except Exception:
                pass
            
            if login_resp.status_code != 200:
                error_code = login_data.get("error", {}).get("code", "")
                error_msg = login_data.get("error", {}).get("message", "")
                if error_code == "unsupported_country_region_territory":
                    return {"ok": False, "error": "unsupported_country_region_territory", "detail": login_data}
                elif error_code == "invalid_state":
                    return {"ok": False, "error": "invalid_state", "detail": login_data}
                elif "Invalid credentials" in error_msg or "wrong password" in error_msg.lower():
                    return {"ok": False, "error": "invalid_password", "detail": login_data}
                return {"ok": False, "error": f"password_verify_failed_{login_resp.status_code}", "detail": login_data}
            
            # 获取 authorization code
            continue_url = str(login_data.get("continue_url") or "").strip()
            auth_code = ""
            if continue_url:
                from urllib.parse import parse_qs, urlparse
                parsed_params = parse_qs(urlparse(continue_url).query)
                auth_code = str((parsed_params.get("code") or [""])[0]).strip()
            
            # ─── 处理邮箱 OTP 验证 ──────────────────────────
            if not auth_code:
                page_type = ""
                page_info = login_data.get("page")
                if isinstance(page_info, dict):
                    page_type = str(page_info.get("type") or "")
                
                if page_type == "email_otp_verification":
                    # 需要验证码才能登录，直接标记为账号异常
                    return {"ok": False, "error": "need_verification_code", "detail": login_data}
                else:
                    return {"ok": False, "error": "no_auth_code", "detail": login_data}
            
            # ④ 用 code 换 token (使用 Platform Client + code_verifier)
            platform_base = "https://platform.openai.com"
            token_resp = session.post(
                f"{auth_base}/api/accounts/oauth/token",
                headers={
                    "accept": "*/*",
                    "accept-language": "zh-CN,zh;q=0.9",
                    "auth0-client": platform_auth0_client,
                    "cache-control": "no-cache",
                    "content-type": "application/json",
                    "origin": platform_base,
                    "pragma": "no-cache",
                    "priority": "u=1, i",
                    "referer": f"{platform_base}/",
                    "sec-ch-ua": '"Chromium";v="145", "Google Chrome";v="145", "Not/A)Brand";v="99"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-site",
                    "user-agent": user_agent,
                },
                json={
                    "client_id": platform_oauth_client_id,
                    "code_verifier": code_verifier,
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "redirect_uri": platform_oauth_redirect_uri,
                },
                verify=False,
                timeout=60,
            )
            
            token_data = {}
            try:
                token_data = token_resp.json() if token_resp.text else {}
            except Exception:
                pass
            
            if token_resp.status_code != 200 or not token_data.get("access_token"):
                return {"ok": False, "error": "token_exchange_failed", "detail": token_data}
            
            access_token = str(token_data.get("access_token") or "").strip()
            refresh_token = str(token_data.get("refresh_token") or "").strip()
            id_token = str(token_data.get("id_token") or "").strip()
            
            # ⑤ 用 access_token 获取用户信息
            user_info = {}
            try:
                me_resp = session.get(
                    "https://chatgpt.com/backend-api/me",
                    headers={
                        "accept": "application/json",
                        "authorization": f"Bearer {access_token}",
                        "user-agent": user_agent,
                    },
                    timeout=30,
                )
                if me_resp.status_code == 200:
                    user_info = me_resp.json() if me_resp.text else {}
            except Exception:
                pass
            
            # 解析 JWT payload
            jwt_payload = self._decode_jwt_payload(access_token)
            
            email_from_jwt = str(jwt_payload.get("https://api.openai.com/profile", {}).get("email") or "").strip()
            account_id_from_jwt = str(
                jwt_payload.get("https://api.openai.com/auth", {}).get("chatgpt_account_id") or ""
            ).strip()
            
            account_info = user_info.get("account") if isinstance(user_info.get("account"), dict) else {}
            result = {
                "ok": True,
                "email": email_from_jwt or email,
                "account_id": account_id_from_jwt or account_info.get("account_id", ""),
                "access_token": access_token,
                "refresh_token": refresh_token,
                "id_token": id_token,
                "expires_at": jwt_payload.get("exp"),
                "source_type": "password",
            }
            
            return result
        
        finally:
            session.close()

    def list_expiring_access_tokens(self) -> list[str]:
        with self._lock:
            return [
                token
                for account in self._accounts.values()
                if str(account.get("refresh_token") or "").strip()
                and (token := str(account.get("access_token") or "").strip())
                and self._token_needs_refresh(token)
            ]

    def list_refresh_token_keepalive_tokens(self) -> list[str]:
        now = datetime.now(UTC)
        due_items: list[tuple[datetime, str]] = []
        with self._lock:
            for account in self._accounts.values():
                due_at = self._refresh_token_keepalive_due_at(account, now)
                token = str(account.get("access_token") or "").strip()
                if due_at is not None and token:
                    due_items.append((due_at, token))
        due_items.sort(key=lambda item: item[0])
        return [token for _, token in due_items[: self._REFRESH_TOKEN_KEEPALIVE_BATCH_SIZE]]

    def keepalive_refresh_tokens(self, access_tokens: list[str]) -> dict[str, Any]:
        access_tokens = list(dict.fromkeys(token for token in access_tokens if token))
        if not access_tokens:
            return {"refreshed": 0, "errors": [], "items": self.list_accounts()}

        refreshed = 0
        errors = []
        for access_token in access_tokens:
            before = self.resolve_access_token(access_token)
            after = self.refresh_access_token(before, force=True, event="refresh_token_keepalive")
            account = self.get_account(after)
            if account and str(account.get("last_token_refresh_error") or "").strip():
                errors.append({
                    "token": anonymize_token(before),
                    "error": str(account.get("last_token_refresh_error") or "refresh token failed"),
                })
                continue
            if account:
                refreshed += 1

        return {
            "refreshed": refreshed,
            "errors": errors,
            "items": self.list_accounts(),
            "relogined": 0,
        }

    def list_tokens(self) -> list[str]:
        with self._lock:
            return [
                token
                for token in self._accounts
                if token and not token.startswith(self._PENDING_PREFIX)
            ]

    def _list_ready_candidate_tokens(
            self,
            excluded_tokens: set[str] | None = None,
            plan_type: str | None = None,
            source_type: str | None = None,
            plan_types: set[str] | tuple[str, ...] | None = None,
            provider: str | None = None,
    ) -> list[str]:
        excluded = set(excluded_tokens or set())
        return [
            token
            for item in self._accounts.values()
            if self._is_image_account_available(item)
               and self._account_matches_plan_type(item, plan_type)
               and self._account_matches_any_plan_type(item, plan_types)
               and self._account_matches_source_type(item, source_type)
               and self._account_matches_provider(item, provider)
               and (token := item.get("access_token") or "")
               and token not in excluded
        ]

    def _ranked_candidate_tokens(
            self,
            excluded_tokens: set[str] | None = None,
            plan_type: str | None = None,
            source_type: str | None = None,
            plan_types: set[str] | tuple[str, ...] | None = None,
            provider: str | None = None,
    ) -> list[str]:
        """按 优先级 > 健康档位 > 调度分 排序的候选 token 列表。

        移植自 codex2api fast_scheduler 的三级排序：
        1. 账号级调度优先级（config.scheduler_priority）高者优先
        2. 同优先级内按健康档位（healthy > warm > risky）
        3. 同档位内按调度分（配额/成功率/最近错误）竞争
        """
        candidates = self._list_ready_candidate_tokens(excluded_tokens, plan_type, source_type, plan_types, provider)
        ranked = sorted(
            candidates,
            key=lambda token: (
                -self._priority_for_token(token),                      # 优先级高者在前
                self._TIER_ORDER.index(self._account_health_tier(self._accounts.get(token) or {})),
                -self._account_dispatch_score(self._accounts.get(token) or {}),
            ),
        )
        if config.scheduler_mode == "remaining_quota":
            # remaining_quota 模式：同优先级内按剩余配额降序（quota 高者先调度）
            ranked.sort(
                key=lambda token: (
                    -self._priority_for_token(token),
                    -max(0, int((self._accounts.get(token) or {}).get("quota") or 0)),
                ),
            )
        return ranked

    def _list_available_candidate_tokens(
            self,
            excluded_tokens: set[str] | None = None,
            plan_type: str | None = None,
            source_type: str | None = None,
            plan_types: set[str] | tuple[str, ...] | None = None,
            provider: str | None = None,
    ) -> list[str]:
        max_concurrency = max(1, int(config.image_account_concurrency or 1))
        return [
            token
            for token in self._ranked_candidate_tokens(excluded_tokens, plan_type, source_type, plan_types, provider)
            if int(self._image_inflight.get(token, 0)) < max_concurrency
        ]

    def _acquire_next_candidate_token(
            self,
            excluded_tokens: set[str] | None = None,
            plan_type: str | None = None,
            source_type: str | None = None,
            plan_types: set[str] | tuple[str, ...] | None = None,
            provider: str | None = None,
            model: str = "",
    ) -> str:
        with self._image_slot_condition:
            while True:
                if not self._list_ready_candidate_tokens(excluded_tokens, plan_type, source_type, plan_types, provider):
                    raise RuntimeError(
                        f"no available {plan_type or source_type or ''} image quota".replace("  ", " ").strip()
                        if plan_type or source_type else "no available image quota"
                    )
                tokens = self._list_available_candidate_tokens(excluded_tokens, plan_type, source_type, plan_types, provider)
                if tokens:
                    if config.scheduler_mode == "remaining_quota":
                        # remaining_quota：直接取排序后第一个（已按 quota 降序）
                        access_token = tokens[0]
                    elif config.scheduler_mode == "weighted_random":
                        # F3/B5：档位内按调度分加权随机——同档账号按分数比例分配流量，
                        # 摊平单账号磨损（纯 round_robin 均匀但无视健康差异，排序首选手
                        # 又造成单账号热点）。权重取 max(score,0)+1 保底，避免零权。
                        access_token = self._weighted_pick(tokens)
                    elif config.scheduler_mode == "least_load":
                        # Least-Load：选择当前负载最低的账号（image_inflight 最小者）
                        access_token = self._pick_least_load(tokens)
                    elif config.scheduler_mode == "predictive":
                        # Predictive：基于历史用量预测选择配额最充足的账号
                        access_token = self._pick_predictive(tokens)
                    elif config.scheduler_mode == "least_used":
                        # 雨露均沾：选最近最少使用的账号（last_used_at 最久远者优先），
                        # 避免集中突刺单号、让免费号更像真人分布。同未见使用记录者
                        # 视为最久未用，优先调度。
                        access_token = self._pick_least_used(tokens)
                    elif config.scheduler_mode == "affinity":
                        # Affinity：同一模型路由到同一账号（5 分钟无请求超时释放）
                        access_token = self._pick_affinity(tokens, model=model)
                    else:
                        access_token = tokens[self._index % len(tokens)]
                        self._index += 1
                    self._image_inflight[access_token] = int(self._image_inflight.get(access_token, 0)) + 1
                    # v2.10.0：调度选取指标（tier 分布）
                    # III-02：带 mode 标签（A/B 对比各调度模式命中分布）
                    mode = self._effective_scheduler_mode()
                    try:
                        from services.prometheus_metrics import record_scheduler_pick
                        record_scheduler_pick(self._account_health_tier(self._accounts.get(access_token) or {}), mode)
                    except Exception:
                        pass
                    self._record_scheduler_pick_stat(access_token, mode)
                    return access_token
                self._image_slot_condition.wait(timeout=1.0)

    def _weighted_pick(self, tokens: list[str]) -> str:
        """档位内按调度分加权随机选取（F3/B5）。

        tokens 已按 优先级>档位>调度分 排序，同档账号分数相近。以
        max(score,0)+1 为权重随机，分数越高被选概率越大，但低分账号也有机会，
        避免排序首选模式造成的单账号热点、摊平磨损。
        """
        weights = [max(0.0, self._account_dispatch_score(self._accounts.get(t) or {})) + 1.0 for t in tokens]
        return random.choices(tokens, weights=weights, k=1)[0]

    # ---- 智能调度增强：Least-Load / Least-Used / Predictive / Affinity ----

    def _pick_least_used(self, tokens: list[str]) -> str:
        """Least-Used：雨露均沾——选最近最少使用的账号（last_used_at 最久远者优先）。

        避免集中突刺单号：同一批免费号被轮流使用、间隔拉开，更接近真人使用分布，
        降低上游风控"单号高频调用"批量打死的概率。tokens 已按 优先级>档位>调度分
        排序，同档内选最久未用者；无 last_used_at 记录的账号视为最久未用优先调度。
        """
        if not tokens:
            raise RuntimeError("no available tokens for least_used pick")

        def _last_used_ts(token: str) -> float:
            account = self._accounts.get(token) or {}
            raw = str(account.get("last_used_at") or "").strip()
            if not raw:
                # 从未使用 → 视为最久未用（-inf 排最前）
                return float("-inf")
            parsed = self._parse_time(raw)
            return parsed.timestamp() if parsed else float("-inf")

        return min(tokens, key=_last_used_ts)

    def _pick_least_load(self, tokens: list[str]) -> str:
        """Least-Load：选择当前负载最低的账号（image_inflight 最小者）。

        适用于突发流量场景，避免单账号过载。
        """
        if not tokens:
            raise RuntimeError("no available tokens for least_load pick")
        # 按 image_inflight 升序取首（同负载取第一个）
        return min(tokens, key=lambda t: int(self._image_inflight.get(t, 0)))

    def _pick_predictive(self, tokens: list[str]) -> str:
        """Predictive：基于历史用量预测，选择配额最充足的账号。

        使用账号的 success/fail 计数和 last_used_at 计算近似消耗速率，
        结合剩余配额预测可用时间，选最长者。无历史数据时回退 round_robin。
        """
        if not tokens:
            raise RuntimeError("no available tokens for predictive pick")
        now = time.time()

        def _predicted_remaining_seconds(token: str) -> float:
            account = self._accounts.get(token) or {}
            quota = max(0, int(account.get("quota") or 0))
            success = max(0, int(account.get("success") or 0))
            fail = max(0, int(account.get("fail") or 0))
            total_used = success + fail
            if total_used == 0:
                # 无历史数据：视为高可用，返回大值
                return float(quota * 3600) if quota > 0 else -1.0
            last_used_raw = account.get("last_used_at")
            if last_used_raw:
                try:
                    last_used = datetime.fromisoformat(str(last_used_raw).replace("Z", "+00:00")).timestamp()
                except Exception:
                    last_used = now
            else:
                last_used = now
            hours_since_first_use = max(0.001, (now - min(last_used, now)) / 3600)
            # EWMA 消耗速率（次/小时），以总用量 / 存在时间 近似
            rate = total_used / hours_since_first_use
            if rate <= 0:
                return float(quota * 3600) if quota > 0 else -1.0
            return quota / rate * 3600 if quota > 0 else -1.0

        # 按预测剩余时间降序取首
        return max(tokens, key=_predicted_remaining_seconds)

    def _pick_affinity(self, tokens: list[str], model: str = "") -> str:
        """Affinity：同一模型（model）的请求尽量路由到同一账号。

        维护 _affinity_map（model -> last_token）字典，优先选上一次同一模型
        用的账号（若可用）。超时机制：_affinity_ttl 秒无该模型请求则释放。
        """
        if not tokens:
            raise RuntimeError("no available tokens for affinity pick")
        if not model:
            # 无模型信息时回退 round_robin
            return tokens[self._index % len(tokens)]

        now = time.time()
        # 清理过期亲和性
        stale_models = [
            m for m, at in self._affinity_at.items()
            if now - at > config.scheduler_affinity_ttl_seconds
        ]
        for m in stale_models:
            self._affinity_map.pop(m, None)
            self._affinity_at.pop(m, None)

        # 尝试亲和命中
        last_token = self._affinity_map.get(model)
        if last_token and last_token in tokens:
            self._affinity_at[model] = now
            return last_token

        # 亲和未命中或超时，选一个 token 并记录亲和
        chosen = tokens[self._index % len(tokens)]
        self._index += 1
        self._affinity_map[model] = chosen
        self._affinity_at[model] = now
        return chosen

    @staticmethod
    def get_account_health_score(account: dict) -> float:
        """账号健康评分 (0-100)。"""
        if not isinstance(account, dict):
            return 0.0
        status = str(account.get("status") or "")
        if status in ("禁用",):
            return 0.0
        if status in ("异常",):
            return 10.0
        if status in ("限流",):
            return 25.0
        fail = max(0, int(account.get("fail") or 0))
        success = max(0, int(account.get("success") or 0))
        total = fail + success
        fail_ratio = fail / max(1, total)
        quota = max(0, int(account.get("quota") or 0))
        quota_ratio = min(1.0, quota / 20.0)
        base = 70.0 * (1 - fail_ratio) * quota_ratio
        last_invalid = account.get("last_invalid_at")
        if last_invalid:
            try:
                elapsed = (datetime.now(UTC) - datetime.fromisoformat(str(last_invalid).replace("Z", "+00:00"))).total_seconds()
                recency = max(0.5, 1.0 - elapsed / 3600)
                base *= recency
            except Exception:
                pass
        return round(base, 1)

    def release_image_slot(self, access_token: str) -> None:
        if not access_token:
            return
        with self._image_slot_condition:
            access_token = self._resolve_access_token_locked(access_token)
            current_inflight = int(self._image_inflight.get(access_token, 0))
            if current_inflight <= 1:
                self._image_inflight.pop(access_token, None)
            else:
                self._image_inflight[access_token] = current_inflight - 1
            self._image_slot_condition.notify_all()

    def get_available_access_token(
            self,
            plan_type: str | None = None,
            source_type: str | None = None,
            plan_types: set[str] | tuple[str, ...] | None = None,
            provider: str | None = None,
            model: str = "",
    ) -> str:
        """从候选池中获取一个可用的图片生图 token。

        8.2：当 provider 未指定时，按权重选取 provider。
        基于本地缓存做初筛，然后通过 fetch_remote_info 做远程验证（token 有效性、配额等）。
        限制最大尝试次数防止 token rotation 导致无限循环。

        model 参数用于 affinity/predictive 调度模式（可选，默认空字符串）。
        """
        # 8.2：权重调度：当 provider 未指定时，按权重选取
        from services.provider_scheduler import provider_scheduler

        if provider is None:
            chosen = provider_scheduler._pick_provider_by_weight()
            if chosen:
                provider = chosen

        # 8.2：配额 + 熔断检查
        if provider is not None:
            if not provider_scheduler._provider_allow_request(provider):
                raise RuntimeError(f"provider {provider} is circuit-broken")
            if not provider_scheduler._check_provider_rate_limit(provider):
                raise RuntimeError(f"provider {provider} rate limit exceeded")

        max_attempts = 20  # 防止无限循环
        attempted_tokens: set[str] = set()
        for _attempt in range(max_attempts):
            access_token = self._acquire_next_candidate_token(
                excluded_tokens=attempted_tokens,
                plan_type=plan_type,
                source_type=source_type,
                plan_types=plan_types,
                provider=provider,
                model=model,
            )
            attempted_tokens.add(access_token)
            # 熔断器：熔断中的账号直接跳过，避免上游抖动雪崩
            breaker = circuit_breaker_registry.get(access_token)
            if not breaker.allow_request():
                continue
            try:
                account = self.fetch_remote_info(access_token, "get_available_access_token")
            except Exception:
                breaker.record_failure()
                self.release_image_slot(access_token)
                continue
            # fetch_remote_info 内部可能因 token rotation 导致 access_token 变化，
            # 把新 token 也加入排除列表，防止重复尝试
            resolved = str((account or {}).get("access_token") or "")
            if resolved and resolved != access_token:
                attempted_tokens.add(resolved)
            if (
                    self._is_image_account_available(account or {})
                    and self._account_matches_plan_type(account or {}, plan_type)
                    and self._account_matches_any_plan_type(account or {}, plan_types)
                    and self._account_matches_source_type(account or {}, source_type)
            ):
                # 仅当账号真正可用时才记录熔断成功
                breaker.record_success()
                return str((account or {}).get("access_token") or access_token)
            # 返回成功但账号不可用（限流/无配额），记为失败
            breaker.record_failure()
            self.release_image_slot(access_token)
        # 通过事件总线发布配额耗尽事件
        try:
            from services.event_bus import ACCOUNT_QUOTA_EXHAUSTED, Event, event_bus

            event_bus.publish(Event(ACCOUNT_QUOTA_EXHAUSTED, {
                "tried_tokens": len(attempted_tokens),
                "plan_type": plan_type or "",
                "source_type": source_type or "",
            }))
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(
            f"no available {plan_type or source_type or ''} image quota (tried {len(attempted_tokens)} tokens)".replace("  ", " ").strip()
            if plan_type or source_type else f"no available image quota (tried {len(attempted_tokens)} tokens)"
        )

    def get_text_access_token(
            self,
            excluded_tokens: set[str] | None = None,
            model: str = "auto",
            provider: str | None = None,
    ) -> str:
        excluded = set(excluded_tokens or set())
        requested_model = str(model or "auto").strip() or "auto"

        # 8.2：权重调度 + 配额检查 + 熔断检查
        # 当未指定 provider 且 model=auto 时，按权重选取 provider
        # 权重调度仅在 provider_weights 配置非空时生效
        from services.provider_scheduler import provider_scheduler

        if provider is None and requested_model == "auto":
            chosen = provider_scheduler._pick_provider_by_weight()
            if chosen:
                provider = chosen

        # Phase 3：provider 为空时按模型自动路由
        if provider is None and requested_model != "auto":
            provider = router_service.route_for_model(requested_model)

        # 8.2：配额耗尽 + 熔断时 fallback 到其他 provider
        if provider is not None:
            attempted_providers: set[str] = set()
            max_provider_attempts = len(config.provider_weights) or 1
            for _ in range(max_provider_attempts + 1):
                if provider in attempted_providers:
                    raise RuntimeError("no available provider")
                if not provider_scheduler._provider_allow_request(provider):
                    attempted_providers.add(provider)
                    provider = provider_scheduler._pick_provider_by_weight(
                        [p for p in (provider_scheduler._get_weighted_providers() or []) if p not in attempted_providers]
                    ) or "chatgpt"
                    continue
                if not provider_scheduler._check_provider_rate_limit(provider):
                    attempted_providers.add(provider)
                    provider = provider_scheduler._pick_provider_by_weight(
                        [p for p in (provider_scheduler._get_weighted_providers() or []) if p not in attempted_providers]
                    ) or "chatgpt"
                    continue
                break

        route = None
        if requested_model != "auto":
            from services.model_service import model_catalog_service

            route = model_catalog_service.route_for_model(requested_model)
        with self._lock:
            candidates = [
                token
                for account in self._accounts.values()
                if account.get("status") not in {"禁用", "异常"}
                   and self._account_matches_provider(account, provider)
                   and (
                       route is None
                       or self._normalize_account_type(account.get("type")) in route.account_types
                   )
                   and (token := account.get("access_token") or "")
                   and token not in excluded
            ]
            if not candidates:
                if route is None or route.allow_anonymous:
                    return ""
                from services.model_service import ModelUnavailableError

                raise ModelUnavailableError(
                    f"model {requested_model!r} is not available to any active account"
                )
            access_token = candidates[self._index % len(candidates)]
            self._index += 1
        return self.refresh_access_token(access_token, event="get_text_access_token") or access_token

    def mark_text_used(self, access_token: str) -> None:
        if not access_token:
            return
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return
            next_item = dict(current)
            next_item["last_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            account = self._normalize_account(next_item)
            if account is None:
                return
            self._accounts[access_token] = account
            self._dirty = True
            self._save_accounts()

    def remove_invalid_token(self, access_token: str, event: str, quiet: bool = False) -> bool:
        # token 失效时强制重建对应 Session，避免用过期会话继续请求
        try:
            from services.session_pool import session_pool
            session_pool.invalidate(account=self.get_account(access_token))
        except Exception:
            pass
        if not config.auto_remove_invalid_accounts:
            # 读取当前 invalid_count 递增，确保 list_abnormal_tokens_for_recover 能发现
            cur = self.get_account(access_token) or {}
            cur_invalid_count = int(cur.get("invalid_count") or 0)
            cur_detail = cur.get("last_refresh_error_detail") or None
            self.update_account(access_token, {
                "status": "异常", "quota": 0,
                "invalid_count": cur_invalid_count + 1,
                "last_invalid_at": datetime.now(UTC).isoformat(),
                "last_refresh_error": str(event or "invalid access token"),
                "last_refresh_error_at": datetime.now(UTC).isoformat(),
                "last_refresh_error_detail": cur_detail,
            }, quiet=quiet)
            # 通过事件总线发布账号失效事件
            try:
                from services.event_bus import ACCOUNT_INVALID, Event, event_bus

                event_bus.publish(Event(ACCOUNT_INVALID, {
                    "token_suffix": anonymize_token(access_token),
                    "reason": event,
                }))
            except Exception:  # noqa: BLE001
                pass
            return False
        removed = bool(self.delete_accounts([access_token])["removed"])
        if removed:
            log_service.add(LOG_TYPE_ACCOUNT, "自动移除异常账号",
                            {"source": event, "token": anonymize_token(access_token)})
        elif access_token:
            self.update_account(access_token, {"status": "异常", "quota": 0}, quiet=quiet)
        return removed

    def get_account(self, access_token: str) -> dict | None:
        if not access_token:
            return None
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            account = self._accounts.get(access_token)
            return dict(account) if account else None

    def get_account_by_email(self, email: str) -> dict | None:
        """按 email 找回账号（含最新 access_token）。

        用于 resume_poll 等"知道原账号、需重连"场景：token 可能已轮换，
        但 email 稳定，经此找回当前有效 token。
        """
        target = str(email or "").strip().lower()
        if not target:
            return None
        with self._lock:
            for account in self._accounts.values():
                if str((account or {}).get("email") or "").strip().lower() == target:
                    return dict(account)
        return None

    def _invalidate_account_list_cache(self) -> None:
        self._account_list_cache = {}
        self._account_list_cache_at = 0.0

    def get_accounts_cached(self) -> list[dict]:
        now = time.time()
        if now - self._account_list_cache_at < self._ACCOUNT_LIST_CACHE_TTL:
            cached = self._account_list_cache.get("account_list")
            if cached is not None:
                return cached  # type: ignore[return-value]
        result = self.list_accounts()
        self._account_list_cache = {"account_list": result}
        self._account_list_cache_at = now
        return result

    def list_accounts(self) -> list[dict]:
        """返回所有账号的副本，并为每个账号附加当前图片在途数 image_inflight。

        image_inflight 为内存态并发计数(账号正在生成、尚未结束的图片数)。号池空闲时
        若某账号该值持续 > 0，说明其并发槽位泄漏、已被静默排除出调度，可借此在 UI 上诊断。
        """
        with self._lock:
            result = []
            for item in self._accounts.values():
                account = dict(item)
                token = account.get("access_token") or ""
                account["image_inflight"] = int(self._image_inflight.get(token, 0))
                # 附加健康档位与调度分，供前端筛选排序
                tier = self._account_health_tier(account)
                account["tier"] = tier
                account["score"] = self._account_dispatch_score(account, tier)
                # 确保健康评分存在
                if "health_score" not in account or account.get("health_score") is None:
                    account["health_score"] = self._compute_health_score(account)
                result.append(account)
                # 注入 Prometheus 账号数量指标
                try:
                    from services.prometheus_metrics import record_accounts_count
                    record_accounts_count(account.get("provider", "chatgpt"), account.get("status", "正常"))
                except Exception:
                    pass
            return result

    def list_groups(self) -> list[dict[str, Any]]:
        """返回所有账号标签的唯一值及其计数。"""
        from collections import Counter
        labels: Counter[str] = Counter()
        for account in self.list_accounts():
            label = str(account.get("label") or "").strip()
            if label:
                labels[label] += 1
        return [{"label": label, "count": count} for label, count in sorted(labels.items())]

    def rename_label(self, old_label: str, new_label: str) -> int:
        """重命名标签（合并两个标签）。返回更新的账号数。"""
        old = str(old_label or "").strip()
        new = str(new_label or "").strip()
        if not old or not new:
            raise ValueError("old_label and new_label are required")
        updated = 0
        for account in self.list_accounts():
            if str(account.get("label") or "").strip() == old:
                token = account.get("access_token", "")
                if token and self.update_account(token, {"label": new}, quiet=True):
                    updated += 1
        return updated

    def list_limited_tokens(self) -> list[str]:
        with self._lock:
            return [
                token
                for item in self._accounts.values()
                if item.get("status") == "限流"
                   and (token := item.get("access_token") or "")
            ]

    def list_normal_tokens(self) -> list[str]:
        with self._lock:
            return [
                token
                for item in self._accounts.values()
                if item.get("status") == "正常"
                   and (token := item.get("access_token") or "")
            ]

    def list_abnormal_tokens_for_recover(self) -> list[str]:
        """v2.9.0：列出可尝试自动恢复的异常账号 token。

        条件：status=异常 且 invalid_count >= 2（避免新账号误判）。
        排除：额度真实耗尽的账号（last_refresh_error 含 quota_exhausted/rate_limit_exhausted 等
        关键字，说明上游明确告知额度用完，反复刷新只会浪费请求额度，不可恢复）。
        纯 token 账号（有 refresh_token）走 refresh_token 换 token 路径；
        带 email+password 的账号走密码重登兜底。两者 fetch_remote_info 都会覆盖。

        v3.0.0：排除已放弃恢复的账号（self_heal_retry_attempts >= max_attempts 且
        self_heal_next_retry_at 为空）。这些账号经指数退避达到重试上限，被判定为不可恢复，
        再拉取只会反复失败并无限累加 invalid_count（实测达 800+），应停止自动重试。
        """
        # v2.9.0：额度真实耗尽错误关键字（这些说明上游明确告知额度用完，不可恢复）
        QUOTA_EXHAUSTED_MARKERS = (
            "quota_exhausted", "rate_limit_exhausted", "usage_limit_reached",
            "plan_limit_reached", "no available image quota",
        )

        def _is_quota_exhausted(item: dict) -> bool:
            err = str(item.get("last_refresh_error") or "").lower()
            return any(marker in err for marker in QUOTA_EXHAUSTED_MARKERS)

        def _recovery_given_up(item: dict) -> bool:
            """指数退避达到重试上限（self_heal_retry_attempts >= max 且无下次重试时间）。"""
            attempts = int(item.get("self_heal_retry_attempts") or 0)
            if attempts < config.self_heal_retry_max_attempts:
                return False
            next_retry = str(item.get("self_heal_next_retry_at") or "").strip()
            return not next_retry

        with self._lock:
            return [
                token
                for item in self._accounts.values()
                if item.get("status") == "异常"
                   and int(item.get("invalid_count") or 0) >= 2
                   and not _is_quota_exhausted(item)
                   and not _recovery_given_up(item)
                   and (token := item.get("access_token") or "")
            ]

    def list_all_access_tokens(self) -> list[str]:
        """全部持有 access_token 的账号（F4 主动探活用，不限状态）。"""
        with self._lock:
            return [
                token
                for item in self._accounts.values()
                if (token := item.get("access_token") or "")
            ]

    @staticmethod
    def _account_payload_token(item: dict) -> str:
        return str(item.get("access_token") or item.get("accessToken") or "").strip()

    @staticmethod
    def _prepare_account_payload(item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        access_token = AccountService._account_payload_token(item)
        if not access_token:
            return None
        payload = dict(item)
        payload.pop("accessToken", None)
        payload["access_token"] = access_token
        # CPA/Codex 导出文件里的 `type=codex` 是导出格式，不是号池套餐类型。
        if str(payload.get("type") or "").strip().lower() == "codex":
            payload["export_type"] = "codex"
            payload["source_type"] = "codex"
            payload.pop("type", None)
        if str(payload.get("export_type") or "").strip().lower() == "codex":
            payload["source_type"] = "codex"
        if payload.get("plan_type") and not payload.get("type"):
            payload["type"] = str(payload.get("plan_type") or "").strip()
        return payload

    def add_account_items(self, items: list[dict]) -> dict:
        payloads = [
            payload
            for item in items
            if (payload := self._prepare_account_payload(item)) is not None
        ]
        return self._add_account_payloads(payloads)

    def add_accounts(self, tokens: list[str], source_type: str = "web") -> dict:
        tokens = list(dict.fromkeys(token for token in tokens if token))
        if not tokens:
            return {"added": 0, "skipped": 0, "items": self.list_accounts()}
        return self._add_account_payloads([
            {"access_token": token, "source_type": self._normalize_source_type(source_type)}
            for token in tokens
        ])

    def add_password_accounts(self, credentials: list[dict]) -> dict:
        """邮箱+密码凭据批量导入：逐条自动登录抓 token 入库，失败保留待登录凭据。

        - 登录成功：以 access_token 为 key 正常入库（source_type=password，保留 email/password 供 re-login）。
        - 登录失败（OTP/风控/网络等）：以 `pending:{email}` 占位入库（status=待登录，quota=0，
          保留 email/password 与 login_error），后续可用 re_login_accounts 重试。
        不强制要求能抓到 token——凭据本身即入库，失败账号保留待登录。

        返回 {added, skipped, pending, failed, errors, items}。errors 每条含 email/error/detail。
        """
        from services.proxy_service import kookeey_proxy_for

        deduped: dict[str, dict] = {}
        for item in credentials:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email") or "").strip()
            password = str(item.get("password") or "").strip()
            if not email or not password:
                continue
            key = email.lower()
            if key not in deduped:
                deduped[key] = {"email": email, "password": password, **item}

        added = 0
        skipped = 0
        pending = 0
        errors: list[dict] = []
        for cred in deduped.values():
            email = str(cred.get("email") or "").strip()
            password = str(cred.get("password") or "").strip()
            # 取件凭证（client_id + refresh_token），登录成功/待登录都入库，供重登 OTP 用
            mail_cred = cred.get("mail_credential") if isinstance(cred.get("mail_credential"), dict) else None
            if self._find_account_by_email(email):
                skipped += 1
                continue
            # 每号固定住宅 IP（粘性 session），批量导入也分摊出口，避免同 IP 批量登录被风控
            proxy_url = kookeey_proxy_for(email)
            try:
                result = self._login_with_password(email, password, proxy_url=proxy_url)
            except Exception as exc:
                result = {"ok": False, "error": f"login_exception:{type(exc).__name__}", "detail": {"message": str(exc)}}

            # 密码登录要求邮箱 OTP、或 passwordless 账号无密码(401/400) → 降级走 OTP 流程（需 cred 带 mail_credential）
            if not result.get("ok") and str(result.get("error") or "") in self._OTP_FALLBACK_ERRORS:
                otp_result = self._otp_fallback_login(email, password, mail_cred, proxy_url)
                if otp_result is not None:
                    result = otp_result
                # 无取件凭证时 _otp_fallback_login 返回 None：保留原错误落 pending 待补凭证
            if result.get("ok"):
                payload = {
                    "access_token": str(result.get("access_token") or "").strip(),
                    "refresh_token": str(result.get("refresh_token") or "").strip(),
                    "id_token": str(result.get("id_token") or "").strip(),
                    "email": str(result.get("email") or email).strip(),
                    "password": password,
                    "source_type": str(result.get("source_type") or "password"),
                    "type": "free",
                    "status": "正常",
                }
                if mail_cred:
                    payload["mail_credential"] = {
                        "client_id": str(mail_cred.get("client_id") or "").strip(),
                        "refresh_token": str(mail_cred.get("refresh_token") or "").strip(),
                    }
                if result.get("expires_at"):
                    payload["expires_at"] = result["expires_at"]
                acc = self._add_account_payloads([payload])
                if int(acc.get("added") or 0) > 0:
                    added += 1
                else:
                    skipped += 1
            else:
                error_type = str(result.get("error") or "unknown")
                pending += 1
                pending_payload = {
                    "access_token": f"{self._PENDING_PREFIX}{email}",
                    "email": email,
                    "password": password,
                    "source_type": "password",
                    "type": "free",
                    "status": "待登录",
                    "quota": 0,
                    "login_error": error_type,
                    "login_error_at": self._now(),
                }
                if mail_cred:
                    pending_payload["mail_credential"] = {
                        "client_id": str(mail_cred.get("client_id") or "").strip(),
                        "refresh_token": str(mail_cred.get("refresh_token") or "").strip(),
                    }
                self._add_account_payloads([pending_payload])
                errors.append({
                    "email": email,
                    "error": error_type,
                    "detail": result.get("detail") if isinstance(result.get("detail"), dict) else None,
                })
        items = self.list_accounts()
        log_service.add(
            LOG_TYPE_ACCOUNT,
            f"密码导入：新增 {added}，待登录 {pending}，跳过 {skipped}",
            {"added": added, "pending": pending, "skipped": skipped},
        )
        return {
            "added": added,
            "skipped": skipped,
            "pending": pending,
            "failed": pending,
            "errors": errors,
            "items": items,
        }

    def _find_account_by_email(self, email: str) -> dict | None:
        """按 email 查找已入库账号（含 pending 占位账号），用于导入去重。"""
        low = str(email or "").strip().lower()
        if not low:
            return None
        with self._lock:
            for acc in self._accounts.values():
                if str(acc.get("email") or "").strip().lower() == low:
                    return acc
        return None

    def _add_account_payloads(self, payloads: list[dict]) -> dict:
        deduped: dict[str, dict] = {}
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            access_token = self._account_payload_token(payload)
            if not access_token:
                continue
            current = deduped.get(access_token, {})
            deduped[access_token] = {**current, **payload, "access_token": access_token}

        if not deduped:
            return {"added": 0, "skipped": 0, "items": self.list_accounts()}

        with self._lock:
            added = 0
            skipped = 0
            for access_token, payload in deduped.items():
                current = self._accounts.get(access_token)
                if current is None:
                    added += 1
                    self._cumulative_total += 1
                    self._save_cumulative_total()
                    current = {"created_at": self._now()}
                else:
                    skipped += 1
                incoming = dict(payload)
                if not incoming.get("created_at"):
                    incoming.pop("created_at", None)
                account = self._normalize_account(
                    {
                        **current,
                        **incoming,
                        "access_token": access_token,
                        "type": str(incoming.get("type") or current.get("type") or "free"),
                    }
                )
                if account is not None:
                    self._accounts[access_token] = account
                    self._dirty = True
            self._save_accounts()
            items = [dict(item) for item in self._accounts.values()]
            log_service.add(LOG_TYPE_ACCOUNT, f"新增 {added} 个账号，跳过 {skipped} 个",
                            {"added": added, "skipped": skipped})
        return {"added": added, "skipped": skipped, "items": items}

    def delete_accounts(self, tokens: list[str]) -> dict:
        target_set = set(token for token in tokens if token)
        if not target_set:
            return {"removed": 0, "items": self.list_accounts()}
        with self._lock:
            target_set = {self._resolve_access_token_locked(token) for token in target_set if token}
            # 记录回收站（删除前快照，保留 email/token/状态/上游原因）
            removed_accounts = [
                dict(self._accounts[token]) for token in target_set if token in self._accounts
            ]
            removed = sum(self._accounts.pop(token, None) is not None for token in target_set)
            for token in target_set:
                self._image_inflight.pop(token, None)
                # D4：账号删除时清理熔断器（防注册表孤儿化）
                self._breaker_registry.remove(token)
            self._token_aliases = {
                old: new
                for old, new in self._token_aliases.items()
                if old not in target_set and new not in target_set
            }
            if removed:
                self._dirty = True
                if self._accounts:
                    self._index %= len(self._accounts)
                else:
                    self._index = 0
                self._save_accounts()
                log_service.add(LOG_TYPE_ACCOUNT, f"删除 {removed} 个账号", {"removed": removed})
                # 回收站记录
                try:
                    from services.trash_service import trash_service
                    for acct in removed_accounts:
                        trash_service.add_from_account(
                            acct,
                            reason=str(acct.get("last_refresh_error") or "manual_delete"),
                            source="manual_delete",
                        )
                except Exception:
                    pass  # 回收站记录失败不阻断删除
            items = [dict(item) for item in self._accounts.values()]
        return {"removed": removed, "items": items}

    def update_account(self, access_token: str, updates: dict, quiet: bool = False) -> dict | None:
        if not access_token:
            return None
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return None
            account = self._normalize_account({**current, **updates, "access_token": access_token})
            if account is None:
                return None
            if account.get("status") == "限流" and config.auto_remove_rate_limited_accounts:
                self._accounts.pop(access_token, None)
                # D4：自动移除账号时清理熔断器（防注册表孤儿化）
                self._breaker_registry.remove(access_token)
                self._dirty = True
                self._save_accounts()
                log_service.add(LOG_TYPE_ACCOUNT, "自动移除限流账号", {"token": anonymize_token(access_token)})
                return None
            self._accounts[access_token] = account
            self._dirty = True
            self._save_accounts()
            if not quiet:
                log_service.add(LOG_TYPE_ACCOUNT, "更新账号",
                                {"token": anonymize_token(access_token), "status": account.get("status")})
            return dict(account)
        return None

    def _record_refresh_success(self, access_token: str) -> None:
        was_invalid = False
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return
            # 5.3：仅在确实从失效态恢复时触发恢复事件（防每次刷新都发告警）
            was_invalid = (
                int(current.get("invalid_count") or 0) > 0
                or bool(current.get("last_invalid_at"))
                or bool(current.get("last_refresh_error_at"))
            )
            next_item = dict(current)
            next_item["invalid_count"] = 0
            next_item["last_invalid_at"] = None
            next_item["last_refresh_error"] = None
            next_item["last_refresh_error_at"] = None
            next_item["last_refresh_error_detail"] = None
            account = self._normalize_account(next_item)
            if account is not None:
                self._accounts[access_token] = account
        if was_invalid:
            try:
                from services.event_bus import ACCOUNT_RECOVERED, Event, event_bus

                event_bus.publish(Event(ACCOUNT_RECOVERED, {
                    "token_suffix": str(access_token)[-8:],
                    "account": str((current or {}).get("email") or str(access_token)[-8:]),
                }))
            except Exception:  # noqa: BLE001 - 事件绝不阻塞账号刷新主流程
                pass

    def _should_defer_invalid_token(self, account: dict | None, now: datetime) -> bool:
        if not isinstance(account, dict):
            return False
        created_at = self._parse_time(account.get("created_at"))
        if created_at is not None and (now - created_at).total_seconds() < self._NEW_ACCOUNT_INVALID_GRACE_SECONDS:
            return True
        last_invalid_at = self._parse_time(account.get("last_invalid_at"))
        invalid_count = int(account.get("invalid_count") or 0)
        if invalid_count <= 1:
            return True
        if last_invalid_at is not None and (now - last_invalid_at).total_seconds() < self._INVALID_CONFIRM_SECONDS:
            return True
        return False

    # ---- 自愈功能：健康评分 + 指数退避 + 自动替换 ----

    @classmethod
    def _compute_health_score(cls, account: dict) -> float:
        """计算账号健康评分 (0-100)。

        公式：score = 100 * (1 - fail_ratio) * quota_ratio * recency_factor
        - fail_ratio = fail / max(1, success + fail)
        - quota_ratio = min(1.0, quota / 20)
        - recency_factor = max(0.5, 1.0 - last_error_minutes / 60)
        """
        if not isinstance(account, dict):
            return 0.0
        status = str(account.get("status") or "")
        if status == "禁用":
            return 0.0
        if status == "异常":
            return 10.0
        if status == "限流":
            return 25.0
        fail = max(0, int(account.get("fail") or 0))
        success = max(0, int(account.get("success") or 0))
        total = fail + success
        fail_ratio = fail / max(1, total)
        quota = max(0, int(account.get("quota") or 0))
        quota_ratio = min(1.0, quota / 20.0)
        recency_factor = 1.0
        last_invalid = account.get("last_invalid_at")
        if last_invalid:
            try:
                elapsed = (datetime.now(UTC) - datetime.fromisoformat(str(last_invalid).replace("Z", "+00:00"))).total_seconds()
                recency_factor = max(0.5, 1.0 - elapsed / 3600)
            except Exception:
                pass
        score = 100.0 * (1.0 - fail_ratio) * quota_ratio * recency_factor
        return round(score, 1)

    def _update_health_score(self, access_token: str) -> None:
        """计算并更新账号健康评分，同时跟踪低分持续时间。"""
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return
            score = self._compute_health_score(current)
            next_item = dict(current)
            next_item["health_score"] = score
            if score < 20 and current.get("health_score_below_20_since") is None:
                next_item["health_score_below_20_since"] = datetime.now(UTC).isoformat()
            elif score >= 20:
                next_item["health_score_below_20_since"] = None
            account = self._normalize_account(next_item)
            if account is not None:
                self._accounts[access_token] = account
                self._dirty = True
                self._save_accounts()

    def _exponential_backoff_delay(self, account: dict) -> float | None:
        """计算指数退避延迟：若未到退避时间返回 None（跳过），否则返回 0 表示可立即重试。

        退避公式：min(initial_delay * 2^attempt, max_delay)
        """
        attempts = int(account.get("self_heal_retry_attempts") or 0)
        if attempts >= config.self_heal_retry_max_attempts:
            return None
        initial = config.self_heal_retry_initial_secs
        max_delay = config.self_heal_retry_max_secs
        next_retry_raw = account.get("self_heal_next_retry_at")
        if next_retry_raw:
            try:
                next_retry_at = datetime.fromisoformat(str(next_retry_raw).replace("Z", "+00:00"))
                if next_retry_at > datetime.now(UTC):
                    return None  # 未到退避时间，跳过
            except Exception:
                pass
        delay = min(initial * (2 ** attempts), max_delay)
        return delay

    def _record_invalid_token_seen(
        self,
        access_token: str,
        event: str,
        error: str,
        defer_invalid_removal: bool = True,
    ) -> bool:
        now = datetime.now(UTC)
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return True
            # 指数退避检查：只有在退避时间已过时才继续标记为需恢复
            backoff_delay = self._exponential_backoff_delay(current)
            if backoff_delay is not None:
                # 已到达退避时间，重置尝试计数并更新
                next_item = dict(current)
                next_item["self_heal_retry_attempts"] = int(next_item.get("self_heal_retry_attempts") or 0) + 1
                next_attempts = int(next_item["self_heal_retry_attempts"])
                if next_attempts < config.self_heal_retry_max_attempts:
                    # 计算下一次重试时间
                    next_delay = min(config.self_heal_retry_initial_secs * (2 ** next_attempts), config.self_heal_retry_max_secs)
                    next_item["self_heal_next_retry_at"] = (now + timedelta(seconds=next_delay)).isoformat()
                else:
                    next_item["self_heal_next_retry_at"] = None
            else:
                # 未到退避时间或已达到最大尝试次数，跳过恢复标记
                next_item = dict(current)
                pass  # 仍然记录 invalid_count，但不标记为可恢复

            should_defer = defer_invalid_removal and self._should_defer_invalid_token(current, now)
            next_item["invalid_count"] = int(next_item.get("invalid_count") or 0) + 1
            next_item["last_invalid_at"] = now.isoformat()
            next_item["last_refresh_error"] = str(error or "invalid access token")
            next_item["last_refresh_error_at"] = now.isoformat()
            next_item["last_refresh_error_detail"] = str(error or "invalid access token")
            # 更新健康评分
            account = self._normalize_account(next_item)
            if account is not None:
                self._accounts[access_token] = account
                self._dirty = True
                self._save_accounts()
            # 重新计算健康评分（基于已更新的 fail/last_invalid_at 等字段）
            self._update_health_score(access_token)
            if should_defer:
                log_service.add(
                    LOG_TYPE_ACCOUNT,
                    "暂缓标记异常账号",
                    {"source": event, "token": anonymize_token(access_token), "error": str(error or "")},
                )
                return False
        return True

    def mark_image_result(self, access_token: str, success: bool, bytes: int | None = None) -> dict | None:
        if not access_token:
            return None
        self.release_image_slot(access_token)
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return None
            next_item = dict(current)
            next_item["last_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if success:
                next_item["success"] = int(next_item.get("success") or 0) + 1
                # quota < 0 表示无限配额（OpenAI 语义），不应扣减
                if int(next_item.get("quota") or 0) >= 0:
                    next_item["quota"] = max(0, int(next_item.get("quota") or 0) - 1)
                if next_item["quota"] == 0:
                    next_item["status"] = "限流"
                    next_item["restore_at"] = next_item.get("restore_at") or None
                elif 0 < next_item["quota"] < 5:
                    # 配额低预警（配额 > 0 且 < 5）
                    try:
                        from services.event_bus import ACCOUNT_QUOTA_LOW, Event, event_bus
                        event_bus.publish(Event(ACCOUNT_QUOTA_LOW, {
                            "token_suffix": str(access_token)[-8:],
                            "remaining_quota": next_item["quota"],
                            "threshold": 5,
                        }))
                    except Exception:
                        pass
                    if next_item.get("status") == "限流":
                        next_item["status"] = "正常"
                elif next_item.get("status") == "限流":
                    next_item["status"] = "正常"
            else:
                next_item["fail"] = int(next_item.get("fail") or 0) + 1
            account = self._normalize_account(next_item)
            if account is None:
                return None
            # III-02：按调度模式回填结果（命中数/失败率/平均延迟）
            self._record_scheduler_result_stat(access_token, success)
            # 更新健康评分
            self._update_health_score(access_token)
            if account.get("status") == "限流" and config.auto_remove_rate_limited_accounts:
                self._accounts.pop(access_token, None)
                # D4：自动移除账号时清理熔断器（防注册表孤儿化）
                self._breaker_registry.remove(access_token)
                self._dirty = True
                self._save_accounts()
                log_service.add(LOG_TYPE_ACCOUNT, "自动移除限流账号", {"token": anonymize_token(access_token)})
                return None
            self._accounts[access_token] = account
            self._dirty = True
            self._save_accounts()
            # v2.9.0：挂钩 kookeey 单 IP 使用画像（按账号粘性 session 记请求数）
            try:
                from services.kookeey_service import kookeey_service
                _email = str(account.get("email") or "").strip()
                if _email:
                    kookeey_service.record_ip_usage(_email, success, bytes=bytes)
            except Exception:  # noqa: BLE001 - 画像记录失败不影响主流程
                pass
            return dict(account)
        return None

    def fetch_remote_info(
        self,
        access_token: str,
        event: str = "fetch_remote_info",
        defer_invalid_removal: bool = True,
    ) -> dict[str, Any] | None:
        if not access_token:
            raise ValueError("access_token is required")

        active_token = self.refresh_access_token(access_token, event=f"{event}:preflight") or access_token
        try:
            from services.openai_backend_api import InvalidAccessTokenError, OpenAIBackendAPI
            backend = OpenAIBackendAPI(active_token)
            try:
                result = backend.get_user_info()
            finally:
                backend.close()
        except InvalidAccessTokenError as exc:
            refreshed_token = self.refresh_access_token(active_token, force=True, event=f"{event}:invalid_access_token")
            if refreshed_token and refreshed_token != active_token:
                try:
                    backend = OpenAIBackendAPI(refreshed_token)
                    try:
                        result = backend.get_user_info()
                    finally:
                        backend.close()
                except InvalidAccessTokenError as retry_exc:
                    if self._record_invalid_token_seen(
                        refreshed_token,
                        event,
                        str(retry_exc),
                        defer_invalid_removal=defer_invalid_removal,
                    ):
                        self.remove_invalid_token(refreshed_token, event)
                    raise
                active_token = refreshed_token
            else:
                if self._record_invalid_token_seen(
                    active_token,
                    event,
                    str(exc),
                    defer_invalid_removal=defer_invalid_removal,
                ):
                    self.remove_invalid_token(active_token, event)
                raise
        self._record_refresh_success(active_token)
        return self.update_account(active_token, result)

    # ---- 刷新进度追踪 ----

    def _prune_progress_dict(self, store: dict[str, dict]) -> None:
        """惰性淘汰过期进度记录（调用方须已持有对应锁）。

        以 created_at（monotonic）为基准，超过 progress_ttl_seconds 的记录删除。
        仅在 init/get 路径顺带清理（update/finish 不触发，完成后由 get 轮询清理），
        不引入后台线程，长期运行内存有界。
        使用 monotonic 时钟避免系统时间跳变/NTP 校时影响 TTL 判定。
        节流（红队 R5）：记录数超阈值（>100）时，同一字典距上次清理 <60s 跳过，
        防 SSE 高频轮询下大 dict O(n) 全扫退化；少量记录全扫成本低不节流，
        保证 TTL 语义在小规模下精确（测试与常见运维场景）。
        """
        store_id = id(store)
        now = time.monotonic()
        if len(store) > 100 and now - self._last_prune_at.get(store_id, 0.0) < 60.0:
            return
        self._last_prune_at[store_id] = now
        cutoff = now - self.progress_ttl_seconds
        expired = [pid for pid, item in store.items() if float(item.get("created_at") or 0) < cutoff]
        for pid in expired:
            store.pop(pid, None)

    def init_refresh_progress(self, progress_id: str, total: int) -> None:
        """初始化刷新进度记录。"""
        with self._refresh_progress_lock:
            self._prune_progress_dict(self._refresh_progress)
            self._refresh_progress[progress_id] = {
                "total": total,
                "processed": 0,
                "done": False,
                "error": None,
                "status_counts": {"正常": 0, "限流": 0, "异常": 0, "禁用": 0},
                "total_quota": 0,
                "created_at": time.monotonic(),
            }

    def update_refresh_progress(self, progress_id: str, token: str) -> None:
        """刷新单个账号后，更新进度计数。"""
        account = self.get_account(token)
        status = str(account.get("status") or "正常").strip() if account else "正常"
        quota = max(0, int(account.get("quota") or 0)) if account else 0

        with self._refresh_progress_lock:
            progress = self._refresh_progress.get(progress_id)
            if progress is None:
                return
            progress["processed"] += 1
            progress["status_counts"][status] = progress["status_counts"].get(status, 0) + 1
            progress["total_quota"] += quota

    def finish_refresh_progress(self, progress_id: str, result: dict | None = None, error: str | None = None) -> None:
        """标记刷新完成。"""
        with self._refresh_progress_lock:
            progress = self._refresh_progress.get(progress_id)
            if progress is None:
                return
            progress["done"] = True
            progress["result"] = result
            if error:
                progress["error"] = error

    @staticmethod
    def _public_progress(progress: dict | None) -> dict | None:
        """对外返回的进度视图：剥离进程内 monotonic 计时字段，避免污染 API 契约。"""
        if not progress:
            return None
        public = dict(progress)
        public.pop("created_at", None)
        return public

    def get_refresh_progress(self, progress_id: str) -> dict | None:
        """查询刷新进度。"""
        with self._refresh_progress_lock:
            self._prune_progress_dict(self._refresh_progress)
            return self._public_progress(self._refresh_progress.get(progress_id))

    def clean_refresh_progress(self, progress_id: str) -> None:
        """清理过期进度记录。"""
        with self._refresh_progress_lock:
            self._refresh_progress.pop(progress_id, None)

    # ---- 重新登录进度追踪 ----

    def init_relogin_progress(self, progress_id: str, total: int) -> None:
        """初始化重新登录进度记录。"""
        with self._relogin_progress_lock:
            self._prune_progress_dict(self._relogin_progress)
            self._relogin_progress[progress_id] = {
                "total": total,
                "processed": 0,
                "done": False,
                "error": None,
                "results": [],
                "created_at": time.monotonic(),
            }

    def update_relogin_progress(self, progress_id: str, token: str, status: str, error: str | None = None) -> None:
        """更新单个重新登录进度。当所有账号处理完毕时自动标记完成。"""
        with self._relogin_progress_lock:
            progress = self._relogin_progress.get(progress_id)
            if progress is None:
                return
            progress["processed"] += 1
            progress["results"].append({
                "token": anonymize_token(token),
                "status": status,
                "error": error,
            })
            if progress["processed"] >= progress["total"]:
                progress["done"] = True

    def finish_relogin_progress(self, progress_id: str, result: dict | None = None, error: str | None = None) -> None:
        """标记重新登录完成。"""
        with self._relogin_progress_lock:
            progress = self._relogin_progress.get(progress_id)
            if progress is None:
                return
            progress["done"] = True
            progress["result"] = result
            if error:
                progress["error"] = error

    def get_relogin_progress(self, progress_id: str) -> dict | None:
        """查询重新登录进度。"""
        with self._relogin_progress_lock:
            self._prune_progress_dict(self._relogin_progress)
            return self._public_progress(self._relogin_progress.get(progress_id))

    def clean_relogin_progress(self, progress_id: str) -> None:
        """清理过期进度记录。"""
        with self._relogin_progress_lock:
            self._relogin_progress.pop(progress_id, None)

    def _prioritize_refresh_tokens(self) -> dict[str, list[str]]:
        """将账号 token 分为三级优先级：
        P0: 紧急（熔断/异常/access_token即将过期<30分钟）
        P1: 常规（即将过期30min~24h）
        P2: 低优（健康账号）
        """
        p0: list[str] = []
        p1: list[str] = []
        p2: list[str] = []
        for token in self.list_all_access_tokens():
            acct = self.get_account(token)
            if not acct:
                continue
            status = str(acct.get("status") or "").strip()
            if status in ("异常", "限流"):
                p0.append(token)
                continue
            try:
                remaining = self._token_expires_in(token)
                if remaining is not None:
                    if remaining < 1800:
                        p0.append(token)
                        continue
                    elif remaining < 86400:
                        p1.append(token)
                        continue
            except Exception:
                pass
            p2.append(token)
        return {"p0": p0, "p1": p1, "p2": p2}

    def _adaptive_max_workers(self, base: int = 10) -> int:
        """根据连续 429 计数动态调整并发数。"""
        count = getattr(self, "_consecutive_429_count", 0)
        if count >= 3:
            return max(2, base // (2 ** (count - 2)))
        return base

    def _record_429_for_adaptive(self) -> None:
        self._consecutive_429_count = getattr(self, "_consecutive_429_count", 0) + 1

    def _record_429_success_for_adaptive(self) -> None:
        if getattr(self, "_consecutive_429_count", 0) > 0:
            self._consecutive_429_count = 0

    def refresh_accounts(
        self,
        access_tokens: list[str],
        progress_id: str | None = None,
        defer_invalid_removal: bool = True,
        priority_level: str | None = None,
    ) -> dict[str, Any]:
        access_tokens = list(dict.fromkeys(token for token in access_tokens if token))
        if not access_tokens:
            items = self.list_accounts()
            result = {"refreshed": 0, "errors": [], "items": items, "relogined": 0}
            if progress_id:
                self.finish_refresh_progress(progress_id, result)
            return result

        refreshed = 0
        errors = []
        base_workers = {"p0": 10, "p1": 5, "p2": 2}.get(priority_level or "", 10)
        max_workers = min(self._adaptive_max_workers(base_workers), len(access_tokens))

        if progress_id:
            self.init_refresh_progress(progress_id, len(access_tokens))

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = {
                executor.submit(self.fetch_remote_info, token, "refresh_accounts", defer_invalid_removal): token
                for token in access_tokens
            }
            for future in as_completed(futures):
                token = futures[future]
                try:
                    account = future.result()
                except (KeyboardInterrupt, SystemExit):
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
                except Exception as exc:
                    error_str = str(exc)
                    if "429" in error_str or "rate limit" in error_str.lower():
                        self._record_429_for_adaptive()
                    else:
                        self._record_429_success_for_adaptive()
                    # TLS/代理连接错误是网络问题，不计入账号失败
                    from services.image_failure import is_tls_connection_error
                    if not is_tls_connection_error(error_str):
                        errors.append({"token": anonymize_token(token), "error": error_str})
                else:
                    if account is not None:
                        refreshed += 1

                if progress_id:
                    self.update_refresh_progress(progress_id, token)
        except (KeyboardInterrupt, SystemExit):
            if progress_id:
                self.finish_refresh_progress(progress_id, error="cancelled")
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True, cancel_futures=True)

        # 自动重新登录异常账号（仅当配置开启时）
        relogined = 0
        if config.auto_relogin_after_refresh:
            for token in access_tokens:
                account = self.get_account(token)
                if not account:
                    continue
                status = str(account.get("status") or "").strip()
                if status != "异常":
                    continue
                email = str(account.get("email") or "").strip()
                password = str(account.get("password") or "").strip()
                if not email or not password:
                    continue
                t = Thread(
                    target=self._password_re_login_thread,
                    args=(token, email, password, "auto_relogin_after_refresh"),
                    daemon=True,
                )
                t.start()
                relogined += 1

        result = {
            "refreshed": refreshed,
            "errors": errors,
            "items": self.list_accounts(),
            "relogined": relogined,
        }

        if progress_id:
            self.finish_refresh_progress(progress_id, result)

        return result

    def recover_abnormal_accounts(self, access_tokens: list[str]) -> dict[str, Any]:
        """v2.9.0：自动恢复异常账号。

        策略（双路径，覆盖纯 token 账号 + 密码账号）：
        1. 先对所有异常账号调 fetch_remote_info（会用 refresh_token 换新 access_token，
           路径 A/B 恢复）。纯 token 账号（有 refresh_token）这条路径即可恢复。
        2. fetch_remote_info 失败后，若账号有 email+password，再起密码重登线程兜底。
        3. 无 refresh_token 也无 password 的账号，无法恢复，跳过。
        并发：max_workers=min(config.abnormal_auto_recover_max_workers, len(tokens))，避免雪崩。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from threading import Thread

        access_tokens = list(dict.fromkeys(token for token in access_tokens if token))
        if not access_tokens:
            return {"recovered": 0, "failed": 0, "skipped": 0, "items": self.list_accounts()}

        max_workers = min(config.abnormal_auto_recover_max_workers, len(access_tokens))
        recovered = 0
        failed = 0
        skipped = 0
        password_relogin_tokens: list[str] = []

        # 第一阶段：fetch_remote_info（refresh_token 换 token 路径）
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = {
                executor.submit(self.fetch_remote_info, token, "abnormal_auto_recover", True): token
                for token in access_tokens
            }
            for future in as_completed(futures):
                token = futures[future]
                try:
                    account = future.result()
                except Exception:
                    # fetch_remote_info 失败 → 看是否有 password 走第二阶段
                    acct = self.get_account(token)
                    if acct and str(acct.get("email") or "").strip() and str(acct.get("password") or "").strip():
                        password_relogin_tokens.append(token)
                    else:
                        failed += 1
                else:
                    if account is not None and str(account.get("status") or "") != "异常":
                        recovered += 1
                        log_service.add(
                            LOG_TYPE_ACCOUNT,
                            "异常账号自动恢复成功",
                            {"token": anonymize_token(token), "email": account.get("email", "")},
                        )
                    else:
                        # fetch 没异常但状态仍异常 → 尝试密码重登
                        acct = self.get_account(token)
                        if acct and str(acct.get("email") or "").strip() and str(acct.get("password") or "").strip():
                            password_relogin_tokens.append(token)
                        else:
                            failed += 1
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        # 第二阶段：密码重登兜底（仅带 password 的账号）
        for token in password_relogin_tokens:
            acct = self.get_account(token)
            if not acct:
                continue
            email = str(acct.get("email") or "").strip()
            password = str(acct.get("password") or "").strip()
            if not email or not password:
                continue
            t = Thread(
                target=self._password_re_login_thread,
                args=(token, email, password, "abnormal_auto_recover"),
                daemon=True,
            )
            t.start()
            # 不等线程完成（异步），记一次尝试
            log_service.add(
                LOG_TYPE_ACCOUNT,
                "异常账号触发密码重登",
                {"token": anonymize_token(token), "email": email},
            )

        skipped = len(access_tokens) - recovered - failed - len(password_relogin_tokens)
        return {
            "recovered": recovered,
            "failed": failed,
            "skipped": skipped,
            "password_relogin_triggered": len(password_relogin_tokens),
            "items": self.list_accounts(),
        }

    def re_login_accounts(self, access_tokens: list[str], progress_id: str | None = None) -> dict[str, Any]:
        """对选中账号执行密码重新登录流程。

        仅对包含 email + password 的账号有效。
        登录成功后自动将状态设为"正常"。
        """
        access_tokens = list(dict.fromkeys(token for token in access_tokens if token))
        if not access_tokens:
            result = {"relogined": 0, "skipped": 0, "errors": [], "items": self.list_accounts()}
            if progress_id:
                self.finish_relogin_progress(progress_id, result)
            return result

        if progress_id:
            self.init_relogin_progress(progress_id, len(access_tokens))

        relogined = 0
        skipped = 0
        errors = []

        for token in access_tokens:
            account = self.get_account(token)
            if not account:
                errors.append({"token": anonymize_token(token), "error": "账号不存在"})
                if progress_id:
                    self.update_relogin_progress(progress_id, token, "跳过", "账号不存在")
                continue

            email = str(account.get("email") or "").strip()
            password = str(account.get("password") or "").strip()
            if not email or not password:
                skipped += 1
                if progress_id:
                    self.update_relogin_progress(progress_id, token, "跳过", "无邮箱密码")
                continue

            # 在新线程中执行密码重新登录
            t = Thread(
                target=self._password_re_login_thread,
                args=(token, email, password, "manual_relogin", progress_id),
                daemon=True,
            )
            t.start()
            relogined += 1

        result = {
            "relogined": relogined,
            "skipped": skipped,
            "errors": errors,
            "items": self.list_accounts(),
        }
        if progress_id:
            # 如果所有账号都已同步处理完毕（没有启动线程），直接标记完成
            if relogined == 0:
                self.finish_relogin_progress(progress_id, result)
            else:
                # 有线程在运行，等线程结束后再完成
                pass
        return result

    def build_export_items(self, access_tokens: list[str] | None = None) -> list[dict[str, str]]:
        target_tokens = set(token for token in (access_tokens or []) if token)
        with self._lock:
            accounts = [
                dict(item)
                for item in self._accounts.values()
                if not target_tokens or str(item.get("access_token") or "") in target_tokens
            ]

        items: list[dict[str, str]] = []
        for account in accounts:
            access_token = str(account.get("access_token") or "").strip()
            refresh_token = str(account.get("refresh_token") or "").strip()
            id_token = str(account.get("id_token") or "").strip()
            if not access_token or not refresh_token or not id_token:
                continue

            access_payload = self._decode_jwt_payload(access_token)
            id_payload = self._decode_jwt_payload(id_token)
            auth_claim = access_payload.get("https://api.openai.com/auth")
            auth_claim = auth_claim if isinstance(auth_claim, dict) else {}
            profile_claim = access_payload.get("https://api.openai.com/profile")
            profile_claim = profile_claim if isinstance(profile_claim, dict) else {}

            email = (
                str(account.get("email") or "").strip()
                or str(profile_claim.get("email") or "").strip()
                or str(id_payload.get("email") or "").strip()
            )
            account_id = (
                str(account.get("account_id") or "").strip()
                or str(auth_claim.get("chatgpt_account_id") or "").strip()
                or str(account.get("user_id") or "").strip()
            )
            item = {
                "type": str(account.get("export_type") or "codex"),
                "email": email,
                "account_id": account_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "id_token": id_token,
                "expired": self._timestamp_to_iso(access_payload.get("exp")),
                "last_refresh": self._timestamp_to_iso(access_payload.get("iat")),
            }
            password = str(account.get("password") or "").strip()
            if password:
                item["password"] = password
            items.append(item)
        return items

    def get_stats(self) -> dict:
        with self._lock:
            items = list(self._accounts.values())
        total = len(items)
        active = sum(1 for a in items if a.get("status") == "正常")
        limited = sum(1 for a in items if a.get("status") == "限流")
        abnormal = sum(1 for a in items if a.get("status") == "异常")
        disabled = sum(1 for a in items if a.get("status") == "禁用")
        total_quota = sum(max(0, int(a.get("quota") or 0)) for a in items if a.get("status") == "正常")
        total_success = sum(int(a.get("success") or 0) for a in items)
        total_fail = sum(int(a.get("fail") or 0) for a in items)
        by_type = {}
        for a in items:
            t = a.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "total": total,
            "cumulative_total": self._cumulative_total,
            "active": active,
            "limited": limited,
            "abnormal": abnormal,
            "disabled": disabled,
            "total_quota": total_quota,
            "total_success": total_success,
            "total_fail": total_fail,
            "by_type": by_type,
        }

    def account_health(self) -> dict:
        stats = self.get_stats()
        return {
            "healthy": stats["active"] > 0,
            "status": "ok" if stats["active"] > 0 else "degraded",
            **stats,
        }

    # ---- 自愈：自动替换不健康账号 ----

    def _list_backup_candidate_tokens(self, excluded_tokens: set[str] | None = None) -> list[str]:
        """列出备用池候选账号：status=healthy 且 quota > 20 且未被主调度选取。

        从正常账号中筛选未被排除的、符合健康条件的 token。
        """
        excluded = set(excluded_tokens or set())
        with self._lock:
            return [
                item["access_token"]
                for item in self._accounts.values()
                if item.get("status") == "正常"
                and "replaced_by" not in item or not item.get("replaced_by")
                and int(item.get("quota") or 0) > 20
                and self._account_health_tier(item) == self._HEALTHY
                and (token := item.get("access_token") or "")
                and token not in excluded
            ]

    def _auto_replace_unhealthy(self) -> dict[str, int]:
        """自动替换不健康账号：health_score < 20 且持续 1 小时以上。

        从备用池选取替代：status=healthy 且 quota > 20 且未被主调度选取。
        配置 self_heal_auto_replace_enabled 控制开关（默认关）。
        替换操作：标记旧账号为 replaced 状态，新账号自动加入调度池。
        """
        if not config.self_heal_auto_replace_enabled:
            return {"replaced": 0, "skipped": 0, "no_backup": 0}

        now = datetime.now(UTC)
        replaced = 0
        skipped = 0
        no_backup = 0
        unhealthy_tokens: list[str] = []

        with self._lock:
            for item in self._accounts.values():
                token = item.get("access_token") or ""
                if not token:
                    continue
                score = float(item.get("health_score") or 0.0)
                if score >= 20:
                    continue
                below_since = item.get("health_score_below_20_since")
                if not below_since:
                    continue
                try:
                    since = datetime.fromisoformat(str(below_since).replace("Z", "+00:00"))
                except Exception:
                    continue
                if (now - since).total_seconds() < 3600:
                    skipped += 1
                    continue
                unhealthy_tokens.append(token)

        if not unhealthy_tokens:
            return {"replaced": 0, "skipped": 0, "no_backup": 0}

        for token in unhealthy_tokens:
            backup_tokens = self._list_backup_candidate_tokens(excluded_tokens={token})
            if not backup_tokens:
                no_backup += 1
                continue
            backup_token = backup_tokens[0]
            backup_account = self.get_account(backup_token)
            if not backup_account:
                no_backup += 1
                continue
            # 标记旧账号为 replaced
            self.update_account(token, {
                "status": "replaced",
                "replaced_by": backup_token,
                "quota": 0,
            }, quiet=True)
            # 更新健康评分
            self._update_health_score(token)
            replaced += 1
            log_service.add(
                LOG_TYPE_ACCOUNT,
                "自动替换不健康账号",
                {
                    "old_token": anonymize_token(token),
                    "new_token": anonymize_token(backup_token),
                    "reason": "health_score_below_20_for_1h",
                },
            )

        return {"replaced": replaced, "skipped": skipped, "no_backup": no_backup}


account_service = AccountService(
    config.get_storage_backend(),
    progress_ttl_seconds=config.progress_ttl_seconds,
)
