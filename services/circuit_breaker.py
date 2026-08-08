"""上游调用熔断器：防止上游抖动导致请求排队打到坏账号雪崩。

状态机：
- CLOSED（正常）：请求正常通过
- OPEN（熔断）：连续失败达阈值，快速失败不请求上游
- HALF_OPEN（半开）：冷却期后试探，成功则恢复，失败则继续熔断
"""

from __future__ import annotations

import time
from enum import Enum
from threading import Lock
from typing import Any


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """单账号熔断器。"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        key: str = "",
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._key = key

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count_half_open = 0
        self._opened_at = 0.0
        self._lock = Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                # 冷却期到，转半开
                if time.monotonic() - self._opened_at >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count_half_open = 0
                    # v2.10.0：熔断状态转移指标
                    try:
                        from services.prometheus_metrics import record_circuit_breaker_transition
                        record_circuit_breaker_transition("open", "half_open")
                    except Exception:
                        pass
            return self._state

    def allow_request(self) -> bool:
        """是否允许发起请求。"""
        return self.state != CircuitState.OPEN

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count_half_open += 1
                if self._success_count_half_open >= self.half_open_max_calls:
                    # 半开连续成功，恢复闭合
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    # v2.10.0：熔断状态转移指标
                    try:
                        from services.prometheus_metrics import record_circuit_breaker_transition
                        record_circuit_breaker_transition("half_open", "closed")
                    except Exception:
                        pass
                    # 5.3：熔断恢复 → 推送恢复事件（复用告警通道 + 去重机制）
                    if self._key:
                        try:
                            from services.alert_service import send_alert

                            send_alert("circuit_breaker_closed", {"token_suffix": str(self._key)[-8:]})
                        except Exception:  # noqa: BLE001 - 告警绝不阻塞熔断主流程
                            pass
            elif self._state == CircuitState.OPEN:
                # C7/P1-2 竞态修复：请求放行时已判 OPEN 拒绝，若此后另一条路径把状态
                # 推进到 OPEN（并发 record_failure 触发熔断），迟到的 record_success 不得
                # 把 OPEN 直接拉回 CLOSED——否则刚熔断的上游被过早放行，失去熔断意义。
                # OPEN 只能经冷却转 HALF_OPEN 后再由连续成功恢复。
                return
            else:
                # CLOSED：正常路径清零失败计数
                self._failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                # 半开再失败，立即重新熔断
                self._trip()
                return
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._trip()

    def _trip(self) -> None:
        prev_state = self._state
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        self._failure_count = 0
        # v2.10.0：熔断状态转移指标
        try:
            from services.prometheus_metrics import record_circuit_breaker_transition
            record_circuit_breaker_transition(
                "half_open" if prev_state == CircuitState.HALF_OPEN else "closed",
                "open",
            )
        except Exception:
            pass
        # D18：熔断 OPEN 触发告警（token 末 8 位，不泄露完整 token）
        # 直接构造（非经注册表，key=""）时跳过告警——无账号上下文，告警无意义
        if not self._key:
            return
        try:
            from services.alert_service import send_alert

            send_alert("circuit_breaker_open", {"token_suffix": str(self._key)[-8:], "failure_threshold": self.failure_threshold})
        except Exception:  # noqa: BLE001 - 告警绝不阻塞熔断主流程
            pass

    def to_dict(self) -> dict[str, Any]:
        state = self.state
        remaining = 0.0
        if state == CircuitState.OPEN:
            remaining = max(0.0, self.recovery_timeout - (time.monotonic() - self._opened_at))
        return {
            "state": state.value,
            "failure_count": self._failure_count,
            "recover_in_seconds": round(remaining, 1),
        }


class CircuitBreakerRegistry:
    """按账号管理熔断器实例。

    生命周期（D4）：账号删除/轮换时经 remove() 显式清理；
    孤儿熔断器（对应账号已不存在的）经 prune_orphans() 惰性 TTL 淘汰，
    防注册表随运行时间无界增长。
    """

    def __init__(self, orphan_ttl_seconds: float = 86400.0, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._breakers: dict[str, CircuitBreaker] = {}
        self._last_seen: dict[str, float] = {}
        try:
            ttl = float(orphan_ttl_seconds)
        except (TypeError, ValueError):
            ttl = 86400.0
        # 允许亚秒级取值（测试与极端运维场景）；非正数回退默认 24h
        self._orphan_ttl = ttl if ttl > 0 else 86400.0
        self._lock = Lock()

    def get(self, key: str) -> CircuitBreaker:
        with self._lock:
            self._last_seen[key] = time.monotonic()
            breaker = self._breakers.get(key)
            if breaker is None:
                breaker = CircuitBreaker(key=key, **self._kwargs)
                self._breakers[key] = breaker
            return breaker

    def remove(self, key: str) -> None:
        with self._lock:
            self._breakers.pop(key, None)
            self._last_seen.pop(key, None)

    def prune_orphans(self) -> int:
        """惰性淘汰超过 TTL 未被访问的熔断器（monotonic 时钟）。返回淘汰数量。"""
        cutoff = time.monotonic() - self._orphan_ttl
        with self._lock:
            expired = [key for key, seen in self._last_seen.items() if seen < cutoff]
            for key in expired:
                self._breakers.pop(key, None)
                self._last_seen.pop(key, None)
            return len(expired)

    def all_status(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: breaker.to_dict() for key, breaker in self._breakers.items()}


# 全局注册表：429/5xx 连续 5 次熔断，30s 冷却，半开 3 次成功恢复
circuit_breaker_registry = CircuitBreakerRegistry(
    failure_threshold=5,
    recovery_timeout=30.0,
    half_open_max_calls=3,
)
