"""上游调用熔断器：防止上游抖动导致请求排队打到坏账号雪崩。

状态机：
- CLOSED（正常）：请求正常通过
- OPEN（熔断）：连续失败达阈值，快速失败不请求上游
- HALF_OPEN（半开）：冷却期后试探，成功则恢复，失败则继续熔断

v2.39.0（G3）：多 Worker 状态一致化——熔断器状态存储从进程内实例字段
抽象到 shared_state（Local/Redis 双实现，get_shared_state() 工厂自动选择）。
- 无 Redis（单 worker / 测试环境）：Local store，行为与历史完全一致。
- 有 Redis（多 worker）：跨进程共享同一键，熔断/恢复全 worker 可见。
- 不改变任何对外 API/事件/阈值语义（threshold=5 / cooldown=30s / half_open=3）。
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from threading import Lock, RLock
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ---------------------------------------------------------------------------
# 熔断状态存储抽象（多 worker 一致性的核心）
# ---------------------------------------------------------------------------


class BreakerStateStore(Protocol):
    """熔断状态存储协议（Local / Redis / 测试 fake 统一接口）。"""

    def get(self, key: str) -> dict[str, Any] | None: ...
    def set(self, key: str, value: dict[str, Any], ttl_seconds: float | None = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def keys(self) -> list[str]: ...
    def backend_name(self) -> str: ...


class _LocalStore:
    """进程内熔断状态存储（单 worker 默认，线程安全）。"""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: dict[str, Any], ttl_seconds: float | None = None) -> None:
        with self._lock:
            self._data[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())

    def backend_name(self) -> str:
        return "local"

    def incr_failure(self, key: str) -> int:
        """原子失败计数 +1（本地锁内，供测试/单 worker 无 shared_state 时使用）。"""
        with self._lock:
            current = int(self._data.get(f"{key}:fail", 0))
            new_value = current + 1
            self._data[f"{key}:fail"] = new_value
            return new_value

    def incr(self, key: str, amount: int = 1, ttl_seconds: float | None = None) -> int:
        """SharedStateBackend 协议的原子 incr 原语（供 SharedBreakerStateStore.incr_failure 使用）。"""
        with self._lock:
            current = self._data.get(key)
            try:
                base = int(current)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                base = 0
            new_value = base + amount
            self._data[key] = new_value
            return new_value

    def reset_failures(self, key: str) -> None:
        """清零失败计数（CLOSED/半开恢复时调用）。"""
        with self._lock:
            self._data.pop(f"{key}:fail", None)


class SharedBreakerStateStore:
    """包装 shared_state 的熔断状态存储（Local/Redis 自动选择，Redis 不可用自动降级 Local）。

    键名：c2api:cb:{key}（key = 账号 access_token，敏感信息不进键名哈希，仅做存储键）。
    """

    _PREFIX = "c2api:cb:"

    def __init__(self, backend=None) -> None:
        # backend 缺省时走 shared_state 工厂（自动 Local/Redis + 降级）；
        # 测试可注入 fake backend。
        if backend is None:
            from services.shared_state import get_shared_state

            backend = get_shared_state()
        self._backend = backend

    def _full_key(self, key: str) -> str:
        return f"{self._PREFIX}{key}"

    def get(self, key: str) -> dict[str, Any] | None:
        try:
            value = self._backend.get(self._full_key(key))
        except Exception:  # noqa: BLE001 - 状态读取失败降级为"无状态"（closed），绝不抛
            logger.warning("熔断状态读取失败(%s): 降级为 closed", key[-8:] if key else "")
            return None
        if isinstance(value, dict):
            return value
        return None

    def set(self, key: str, value: dict[str, Any], ttl_seconds: float | None = None) -> None:
        try:
            self._backend.set(self._full_key(key), value, ttl_seconds=ttl_seconds)
        except Exception:  # noqa: BLE001 - 写入失败只告警（进程内状态下次读不到会重建）
            logger.warning("熔断状态写入失败(%s)", key[-8:] if key else "")

    def delete(self, key: str) -> None:
        try:
            self._backend.delete(self._full_key(key))
        except Exception:  # noqa: BLE001
            logger.warning("熔断状态删除失败(%s)", key[-8:] if key else "")

    # -- 原子失败计数（B1 修复：消除多 worker read-modify-write 竞态）-------

    def incr_failure(self, key: str, ttl_seconds: float | None = None) -> int:
        """原子失败计数 +1 并返回新值。

        - Local backend：进程内自旋锁内 incr，原子。
        - Redis backend：INCRBY 原子 + 可选 TTL。
        键：{prefix}{key}:fail（独立于状态 dict，避免整对象重写覆盖丢计数）。
        """
        try:
            return int(self._backend.incr(f"{self._full_key(key)}:fail", 1, ttl_seconds))
        except Exception:  # noqa: BLE001 - 计数失败降级为 1（保守，宁可误熔断不丢计数）
            logger.warning("熔断失败计数 incr 失败(%s)", key[-8:] if key else "")
            return 1

    def reset_failures(self, key: str) -> None:
        """清零失败计数（CLOSED/半开恢复闭合时调用）。"""
        try:
            self._backend.delete(f"{self._full_key(key)}:fail")
        except Exception:  # noqa: BLE001
            logger.warning("熔断失败计数清除失败(%s)", key[-8:] if key else "")

    def failure_count(self, key: str) -> int:
        """读取当前失败计数（无则 0）。"""
        try:
            value = self._backend.get(f"{self._full_key(key)}:fail")
            return int(value or 0)
        except Exception:  # noqa: BLE001
            return 0

    def keys(self) -> list[str]:
        """返回原始 key（去掉前缀）。

        原子失败计数键 {key}:fail 也算该 key 的 breaker（record_failure-only 场景
        尚未写状态 dict，但熔断计数已存在）——从 :fail 键推导回原始 key。
        """
        try:
            raw_keys: set[str] = set()
            for k in self._backend.keys():
                if not k.startswith(self._PREFIX):
                    continue
                stripped = k[len(self._PREFIX):]
                if stripped.endswith(":fail"):
                    raw_keys.add(stripped[:-len(":fail")])
                else:
                    raw_keys.add(stripped)
            return list(raw_keys)
        except Exception:  # noqa: BLE001
            logger.warning("熔断状态列表读取失败")
            return []

    def backend_name(self) -> str:
        try:
            return self._backend.backend_name()
        except Exception:  # noqa: BLE001
            return "unknown"


# ---------------------------------------------------------------------------
# 熔断器
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """单账号熔断器（状态存储走 BreakerStateStore）。"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        key: str = "",
        state_store: BreakerStateStore | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._key = key
        # 无 store 时用进程内 Local（保持历史构造行为）
        self._store = state_store if state_store is not None else _LocalStore()
        # 实例锁：防并发读改写撕裂（store 自身保证原子性，此处再做一层乐观更新）
        self._lock = Lock()

    # -- 状态读写（唯一访问 store 的通道） ----------------------------------

    def _state_key(self) -> str:
        return self._key or "__default__"

    def _read_state(self) -> dict[str, Any]:
        value = self._store.get(self._state_key())
        if not isinstance(value, dict):
            # 无状态（record_failure-only 场景只有 :fail 键）或损坏数据 → 兜底 CLOSED dict
            # state 统一返回 CircuitState（绝不让 str 漏到 state getter 的 .value 调用）
            return {"state": CircuitState.CLOSED, "failure_count": 0, "success_count_half_open": 0, "opened_at": 0.0}
        # 缺字段兜底（兼容旧数据/损坏数据）
        try:
            state = CircuitState(str(value.get("state") or CircuitState.CLOSED.value))
        except ValueError:
            state = CircuitState.CLOSED
        return {
            "state": state,
            "failure_count": int(value.get("failure_count") or 0),
            "success_count_half_open": int(value.get("success_count_half_open") or 0),
            "opened_at": float(value.get("opened_at") or 0.0),
        }

    def _write_state(self, state: CircuitState, failure_count: int, success_count_half_open: int, opened_at: float) -> None:
        self._store.set(self._state_key(), {
            "state": state.value if isinstance(state, CircuitState) else state,
            "failure_count": failure_count,
            "success_count_half_open": success_count_half_open,
            "opened_at": opened_at,
        })

    # -- 对外 API ------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        with self._lock:
            data = self._read_state()
            if data["state"] == CircuitState.OPEN:
                # 冷却期到，转半开
                if time.monotonic() - data["opened_at"] >= self.recovery_timeout:
                    data["state"] = CircuitState.HALF_OPEN
                    data["success_count_half_open"] = 0
                    self._write_state(
                        data["state"], data["failure_count"], data["success_count_half_open"], data["opened_at"],
                    )
                    # 通过事件总线发布熔断状态转移
                    self._publish_transition(
                        "half_open",
                        "open", "half_open",
                        data={"token_suffix": str(self._key)[-8:] if self._key else ""},
                    )
            return data["state"]

    def allow_request(self) -> bool:
        """是否允许发起请求。"""
        return self.state != CircuitState.OPEN

    def record_success(self) -> None:
        with self._lock:
            data = self._read_state()
            if data["state"] == CircuitState.HALF_OPEN:
                data["success_count_half_open"] += 1
                if data["success_count_half_open"] >= self.half_open_max_calls:
                    # 半开连续成功，恢复闭合（清零失败计数）
                    self._write_state(CircuitState.CLOSED, 0, 0, 0.0)
                    self._reset_failure_count()
                    # 通过事件总线发布熔断恢复
                    self._publish_transition(
                        "closed",
                        "half_open", "closed",
                        data={"token_suffix": str(self._key)[-8:] if self._key else ""},
                    )
                else:
                    self._write_state(
                        data["state"], data["failure_count"], data["success_count_half_open"], data["opened_at"],
                    )
            elif data["state"] == CircuitState.OPEN:
                # C7/P1-2 竞态修复：请求放行时已判 OPEN 拒绝，若此后另一条路径把状态
                # 推进到 OPEN（并发 record_failure 触发熔断），迟到的 record_success 不得
                # 把 OPEN 直接拉回 CLOSED——否则刚熔断的上游被过早放行，失去熔断意义。
                # OPEN 只能经冷却转 HALF_OPEN 后再由连续成功恢复。
                return
            else:
                # CLOSED：正常路径清零失败计数（原子键）
                self._write_state(CircuitState.CLOSED, 0, 0, 0.0)
                self._reset_failure_count()

    def record_failure(self) -> None:
        with self._lock:
            data = self._read_state()
            if data["state"] == CircuitState.HALF_OPEN:
                # 半开再失败，立即重新熔断
                self._trip(data["state"])
                return
            # CLOSED：原子失败计数（多 worker 下不丢计数）
            count = self._incr_failure_count()
            if count >= self.failure_threshold:
                self._trip(data["state"])
                return

    def _incr_failure_count(self) -> int:
        """原子失败计数 +1（Local 锁内 / Redis INCRBY），返回新值。"""
        return self._store.incr_failure(self._state_key())

    def _reset_failure_count(self) -> None:
        """清零失败计数（闭合/半开恢复时）。"""
        self._store.reset_failures(self._state_key())

    def _trip(self, prev_state: CircuitState) -> None:
        opened_at = time.monotonic()
        self._write_state(CircuitState.OPEN, 0, 0, opened_at)
        # 通过事件总线发布熔断事件
        self._publish_transition(
            "open",
            "half_open" if prev_state == CircuitState.HALF_OPEN else "closed", "open",
            data={
                "token_suffix": str(self._key)[-8:] if self._key else "",
                "failure_threshold": self.failure_threshold,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        state = self.state
        data = self._read_state()
        # 失败计数展示统一从原子键读（CLOSED 累积/OPEN 归零——_trip 已 reset）
        failure_count = self._store.failure_count(self._state_key()) if state == CircuitState.CLOSED else 0
        remaining = 0.0
        if state == CircuitState.OPEN:
            remaining = max(0.0, self.recovery_timeout - (time.monotonic() - data["opened_at"]))
        return {
            "state": state.value,
            "failure_count": failure_count,
            "recover_in_seconds": round(remaining, 1),
        }

    # -- 事件发布（失败不阻断状态机） ----------------------------------------

    def _publish_transition(self, event_name: str, from_state: str, to_state: str, data: dict[str, Any]) -> None:
        try:
            from services.event_bus import Event, event_bus

            event_map = {
                "open": "circuit.open",
                "half_open": "circuit.half_open",
                "closed": "circuit.closed",
            }
            event_bus.publish(Event(event_map.get(event_name, event_name), {
                "from_state": from_state,
                "to_state": to_state,
                **data,
            }))
        except Exception:  # noqa: BLE001 - 事件发布失败不阻断熔断主流程
            pass


# ---------------------------------------------------------------------------
# 熔断器注册表
# ---------------------------------------------------------------------------


class CircuitBreakerRegistry:
    """按账号管理熔断器（状态统一走共享存储，多 worker 一致）。

    生命周期（D4）：账号删除/轮换时经 remove() 显式清理；
    孤儿熔断器（对应账号已不存在的）经 prune_orphans() 惰性 TTL 淘汰，
    防注册表随运行时间无界增长（Local 模式）。Redis 模式过期由键 TTL 兜底，
    prune_orphans 退化为惰性 no-op（返回 0）。
    """

    def __init__(self, orphan_ttl_seconds: float = 86400.0, **kwargs: Any) -> None:
        self._kwargs = kwargs
        try:
            ttl = float(orphan_ttl_seconds)
        except (TypeError, ValueError):
            ttl = 86400.0
        # 允许亚秒级取值（测试与极端运维场景）；非正数回退默认 24h
        self._orphan_ttl = ttl if ttl > 0 else 86400.0
        self._lock = Lock()
        # 共享状态存储（工厂自动 Local/Redis；无 Redis 降级 Local）
        self._store = SharedBreakerStateStore()
        # 惰性清理：距上次 prune <60s 跳过（防高频轮询全扫退化），测试可注入
        self._orphan_last_seen: dict[str, float] = {}
        self._last_prune_at = 0.0

    def get(self, key: str) -> CircuitBreaker:
        # 惰性清理孤儿（节流 60s）：状态统一写 store，key 访问记录用于 TTL 淘汰
        now = time.monotonic()
        with self._lock:
            self._orphan_last_seen[key] = now
            if now - self._last_prune_at >= 60.0:
                self._last_prune_at = now
                # 取出并释放锁后再 prune（避免与 store/其它锁嵌套死锁）
                needs_prune = True
            else:
                needs_prune = False
        if needs_prune:
            try:
                self.prune_orphans()
            except Exception:  # noqa: BLE001
                pass
        return CircuitBreaker(key=key, state_store=self._store, **self._kwargs)

    def remove(self, key: str) -> None:
        with self._lock:
            self._store.delete(key)
            # 原子失败计数键一并清理（防孤儿 :fail 键无界增长）
            self._store.reset_failures(key)
            self._orphan_last_seen.pop(key, None)

    def prune_orphans(self) -> int:
        """惰性淘汰超过 TTL 未被访问的熔断器（monotonic 时钟）。返回淘汰数量。

        Local 模式：按 last_seen 剪枝（内存记录，秒级精确）。
        Redis 模式：键 TTL 兜底，这里 no-op 返回 0（不扫描全部键，避免 SCAN 全量）。
        """
        try:
            if self._store.backend_name() != "local":
                return 0
        except Exception:  # noqa: BLE001
            return 0
        cutoff = time.monotonic() - self._orphan_ttl
        with self._lock:
            expired = [key for key, seen in self._orphan_last_seen.items() if seen < cutoff]
            for key in expired:
                self._store.delete(key)
                # 原子失败计数键一并清理（防孤儿 :fail 键在 store 里无界增长）
                self._store.reset_failures(key)
                self._orphan_last_seen.pop(key, None)
            return len(expired)

    def all_status(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for key in self._store.keys():
            breaker = CircuitBreaker(key=key, state_store=self._store, **self._kwargs)
            result[key] = breaker.to_dict()
        return result


# 全局注册表：429/5xx 连续 5 次熔断，30s 冷却，半开 3 次成功恢复
# （状态存储经 get_shared_state() 自动选择 Local/Redis）
circuit_breaker_registry = CircuitBreakerRegistry(
    failure_threshold=5,
    recovery_timeout=30.0,
    half_open_max_calls=3,
)
