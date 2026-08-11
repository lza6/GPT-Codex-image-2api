"""自适应调度器：根据运行指标自动切换调度模式。

基于运行指标（并发请求数/成功率/模型多样性）自动选择最优调度模式，
减少人工干预，提升高负载/高故障场景下的调度效率。
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


class AdaptiveScheduler:
    """自适应调度器：根据运行指标自动切换调度模式。

    MODES = ["weighted_random", "least_load", "predictive", "affinity"]

    切换规则：
    - 高负载（concurrent_requests > 100）→ least_load：避免单账号过载
    - 低成功率（success_rate < 0.8）→ predictive：按历史用量选配额最充足的账号
    - 高模型多样性（model_diversity > 0.7）→ affinity：同一模型路由到同一账号
    - 默认 → weighted_random：加权随机摊平磨损

    scheduler_adaptive_enabled 为 False 时退化到配置的固定模式（默认行为）。
    """

    MODES = ("weighted_random", "least_load", "predictive", "affinity")

    # 切换规则阈值
    _HIGH_CONCURRENT_THRESHOLD: int = 100
    _LOW_SUCCESS_RATE_THRESHOLD: float = 0.8
    _HIGH_MODEL_DIVERSITY_THRESHOLD: float = 0.7

    # 各模式最短驻留时间（秒），防止频繁切换抖动
    _MIN_DWELL_SECONDS: float = 120.0

    def __init__(self) -> None:
        self._current_mode: str = "weighted_random"
        self._switched_at: float = 0.0
        # 切换历史记录
        self._history: list[dict[str, object]] = []
        self._history_max: int = 100
        self._lock = Lock()

        # 运行指标缓存（由 collect_stats 填充）
        self._stats: dict[str, float] = {
            "concurrent_requests": 0.0,
            "success_rate": 1.0,
            "model_diversity": 0.0,
        }

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @property
    def stats(self) -> dict[str, float]:
        return dict(self._stats)

    def collect_stats(self, account_service: Any) -> dict[str, float]:
        """收集系统运行指标。

        参数：
            account_service: AccountService 实例，用于获取账号池状态。

        返回：
            {"concurrent_requests": float, "success_rate": float, "model_diversity": float}
        """
        accounts = account_service.list_accounts()
        total = len(accounts)
        inflight = sum(int(account_service._image_inflight.get(a.get("access_token", ""), 0)) for a in accounts)

        # 并发请求数：在途图片任务数
        concurrent = float(inflight)

        # 成功率：最近成功/(成功+失败)，无数据时视为 1.0
        total_success = sum(max(0, int(a.get("success") or 0)) for a in accounts)
        total_fail = sum(max(0, int(a.get("fail") or 0)) for a in accounts)
        total_calls = total_success + total_fail
        success_rate = total_success / max(1, total_calls)

        # 模型多样性：当前有调度记录的模型数占比
        unique_models = len(account_service._affinity_map)
        model_diversity = min(1.0, unique_models / max(1, total))

        self._stats = {
            "concurrent_requests": concurrent,
            "success_rate": round(success_rate, 4),
            "model_diversity": round(model_diversity, 4),
        }
        return self._stats

    def select_mode(self) -> str:
        """根据当前系统状态选择最优调度模式。

        返回选中的模式字符串。
        """
        stats = self._stats
        concurrent = stats.get("concurrent_requests", 0)
        success_rate = stats.get("success_rate", 1.0)
        model_diversity = stats.get("model_diversity", 0.0)

        # 高负载时使用最少负载
        if concurrent > self._HIGH_CONCURRENT_THRESHOLD:
            candidate = "least_load"
        # 成功率低时使用预测性调度
        elif success_rate < self._LOW_SUCCESS_RATE_THRESHOLD:
            candidate = "predictive"
        # 模型多样化时使用亲和性调度
        elif model_diversity > self._HIGH_MODEL_DIVERSITY_THRESHOLD:
            candidate = "affinity"
        else:
            candidate = "weighted_random"

        return candidate

    def _should_switch(self, candidate: str) -> bool:
        """判断是否真的需要切换，含最短驻留时间守卫。"""
        if candidate == self._current_mode:
            return False
        now = time.monotonic()
        elapsed = now - self._switched_at
        if elapsed < self._MIN_DWELL_SECONDS:
            logger.debug(
                "自适应调度跳过切换：%s -> %s（距上次切换仅 %.0fs，最短驻留 %.0fs）",
                self._current_mode, candidate, elapsed, self._MIN_DWELL_SECONDS,
            )
            return False
        return True

    def tick(self, account_service: Any) -> str:
        """自适应调度周期：收集指标 → 选择模式 → 切换（如需）。

        参数：
            account_service: AccountService 实例。

        返回：
            当前生效的调度模式字符串。
        """
        self.collect_stats(account_service)
        candidate = self.select_mode()
        if self._should_switch(candidate):
            previous = self._current_mode
            self._current_mode = candidate
            self._switched_at = time.monotonic()
            self._record_switch(previous, candidate)
            logger.info(
                "自适应调度切换：%s -> %s（并发=%.0f, 成功率=%.2f, 模型多样性=%.2f）",
                previous, candidate, self._stats.get("concurrent_requests", 0),
                self._stats.get("success_rate", 1.0), self._stats.get("model_diversity", 0.0),
            )
            # 记录 Prometheus 指标
            try:
                from services.prometheus_metrics import record_scheduler_mode_switch
                record_scheduler_mode_switch(previous, candidate)
            except Exception:
                pass
        return self._current_mode

    def _record_switch(self, previous: str, candidate: str) -> None:
        """记录一次模式切换事件到历史。"""
        with self._lock:
            entry: dict[str, object] = {
                "ts": time.time(),
                "from": previous,
                "to": candidate,
                "stats": dict(self._stats),
            }
            self._history.append(entry)
            if len(self._history) > self._history_max:
                self._history = self._history[-self._history_max:]

    def get_history(self, limit: int = 20) -> list[dict[str, object]]:
        """返回最近 N 次切换历史。"""
        with self._lock:
            return list(self._history[-limit:])

    def get_status(self) -> dict[str, object]:
        """返回自适应调度器当前状态。"""
        return {
            "current_mode": self._current_mode,
            "stats": dict(self._stats),
            "history_count": len(self._history),
            "switched_at": self._switched_at,
        }


# 全局单例
adaptive_scheduler = AdaptiveScheduler()