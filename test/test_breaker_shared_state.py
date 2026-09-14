"""熔断器多 Worker 共享状态测试（v2.39.0 G3）。

覆盖场景：
- 无 Redis（conftest 已钉死 REDIS_URL=""）→ registry 自动 Local，行为与历史一致
- 伪造共享 store（内存 dict + 锁，模拟 Redis 语义）注入两个独立 CircuitBreaker
  → worker A record_failure 到熔断 → worker B 读 state==OPEN 且 allow_request False
- 半开恢复跨实例：A 触发 OPEN → 模拟冷却 → B 读到 HALF_OPEN → B record_success×N → A 读 CLOSED
- store 不可用（构造抛异常）→ SharedBreakerStateStore 降级不炸
"""

from __future__ import annotations

import threading
from unittest.mock import patch

from services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
    SharedBreakerStateStore,
    _LocalStore,
)


class _FakeSharedBackend:
    """内存 dict + 锁的假共享 state（模拟 Redis 语义：set 存 dict、get 读回 dict）。

    支持 SharedStateBackend 的原子 incr 原语（B1 修复依赖：失败计数走 incr 不走 read-modify-write）。
    """

    def __init__(self) -> None:
        self._d: dict[str, object] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            return self._d.get(key)

    def set(self, key: str, value, ttl_seconds: float | None = None) -> None:
        with self._lock:
            self._d[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._d.pop(key, None)

    def incr(self, key: str, amount: int = 1, ttl_seconds: float | None = None) -> int:
        """原子 incr（模拟 Redis INCRBY / Local 锁内累加）。"""
        with self._lock:
            current = self._d.get(key)
            try:
                base = int(current)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                base = 0
            new_value = base + amount
            self._d[key] = new_value
            return new_value

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._d.keys())

    def backend_name(self) -> str:
        return "fake-redis"


def _make_pair(backend, key="tok-shared-1"):
    store = SharedBreakerStateStore(backend=backend)
    breaker_a = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0, half_open_max_calls=2, key=key, state_store=store)
    breaker_b = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0, half_open_max_calls=2, key=key, state_store=store)
    return breaker_a, breaker_b


class TestCrossInstanceSharedState:
    def test_failure_in_worker_a_observed_by_worker_b(self):
        backend = _FakeSharedBackend()
        a, b = _make_pair(backend)
        assert b.allow_request()
        for _ in range(3):
            a.record_failure()
        # worker B（独立实例、独立锁）应看到 OPEN
        assert b.state.value == "open"
        assert not b.allow_request()

    def test_half_open_recovery_cross_instance(self):
        backend = _FakeSharedBackend()
        a, b = _make_pair(backend)
        for _ in range(3):
            a.record_failure()
        assert not b.allow_request()

        # 模拟冷却期已过：monkeypatch 两个实例的时间基准一致即可
        opened_at_before = a._read_state()["opened_at"]
        fake_now = opened_at_before + 31.0
        with patch("services.circuit_breaker.time.monotonic", return_value=fake_now):
            assert b.state.value == "half_open"  # B 触发冷却迁移
            b.record_success()  # 半开成功 1
            b.record_success()  # 半开成功 2 -> 达 half_open_max_calls → CLOSED

        # A（独立实例）读回应为 CLOSED
        assert a.state.value == "closed"
        assert a.allow_request()

    def test_half_open_failure_retrips_cross_instance(self):
        backend = _FakeSharedBackend()
        a, b = _make_pair(backend)
        for _ in range(3):
            a.record_failure()
        opened_at_before = a._read_state()["opened_at"]
        with patch("services.circuit_breaker.time.monotonic", return_value=opened_at_before + 31.0):
            assert b.state.value == "half_open"
            b.record_failure()  # 半开再失败 → 立即重新 OPEN
        assert not a.allow_request()
        assert a.state.value == "open"

    def test_registry_uses_shared_store_automatically(self):
        # conftest 已钉死 REDIS_URL="" → get_shared_state() 返回 Local → 行为与历史一致
        reg = CircuitBreakerRegistry()
        breaker = reg.get("tok-local-1")
        breaker.record_failure()
        assert "tok-local-1" in reg.all_status()
        assert reg._store.backend_name() == "local"
        reg.remove("tok-local-1")

    def test_shared_store_handles_backend_failure(self):
        class _BoomBackend:
            def get(self, key):
                raise RuntimeError("redis down")
            def set(self, key, value, ttl_seconds=None):
                raise RuntimeError("redis down")
            def delete(self, key):
                raise RuntimeError("redis down")
            def keys(self):
                raise RuntimeError("redis down")
            def backend_name(self):
                raise RuntimeError("redis down")

        store = SharedBreakerStateStore(backend=_BoomBackend())
        breaker = CircuitBreaker(key="tok-down", state_store=store)
        # 不抛异常：读不到状态按 closed，allow_request True
        assert breaker.allow_request()
        breaker.record_failure()  # 写失败只告警不抛
        assert breaker.allow_request()

    def test_store_json_roundtrip_keeps_dict(self):
        """RedisBackend.set 会 JSON 序列化 dict；读回必须是 dict 才能被 _read_state 消费。"""
        import json

        state = {"state": "open", "failure_count": 0, "success_count_half_open": 0, "opened_at": 123.0}
        raw = json.dumps(state, ensure_ascii=False)
        back = json.loads(raw)
        assert isinstance(back, dict)
        assert back["state"] == "open"


class TestConcurrentFailureCounting:
    """B1 修复回归：多实例并发 record_failure 不丢失败计数（阈值判定正确触发熔断）。

    修复前的 read-modify-write（读 state dict → 内存 +1 → 写回）在两个实例并发时
    会互相覆盖：A 读 3、B 读 3、各写回 4 → 阈值 5 永远不触发。修复后失败计数走
    store.incr 原子原语（Local 锁内 / Redis INCRBY），计数不丢。
    """

    def test_concurrent_failures_across_instances_trip_correctly(self):
        """8 线程 × 5 次并发 record_failure（同一共享 store）→ 阈值正确触发 OPEN。"""
        from concurrent.futures import ThreadPoolExecutor

        backend = _FakeSharedBackend()
        threshold = 5
        store = SharedBreakerStateStore(backend=backend)
        breakers = [
            CircuitBreaker(
                failure_threshold=threshold,
                recovery_timeout=30.0,
                half_open_max_calls=2,
                key="tok-concurrent",
                state_store=store,
            )
            for _ in range(8)
        ]

        def hammer(breaker):
            for _ in range(5):
                breaker.record_failure()

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(hammer, breakers))

        # 总失败 40 次 ≥ 阈值 5 → 所有实例都应读到 OPEN（计数经原子 incr 不丢）
        for i, breaker in enumerate(breakers):
            assert breaker.state == CircuitState.OPEN, f"breaker[{i}] 未熔断（丢计数）"
            assert not breaker.allow_request()

    def test_failure_count_matches_incr_total(self):
        """单实例 record_failure N 次 → 原子计数 == N（无覆盖丢失）。"""
        backend = _FakeSharedBackend()
        store = SharedBreakerStateStore(backend=backend)
        breaker = CircuitBreaker(
            failure_threshold=100, recovery_timeout=30.0, half_open_max_calls=2,
            key="tok-count", state_store=store,
        )
        for _ in range(7):
            breaker.record_failure()
        assert store.failure_count("tok-count") == 7

    def test_recovery_resets_count_and_reaccumulates(self):
        """半开恢复 CLOSED → reset_failures → 失败计数从 0 重新累计。"""
        backend = _FakeSharedBackend()
        store = SharedBreakerStateStore(backend=backend)
        breaker = CircuitBreaker(
            failure_threshold=2, recovery_timeout=0.05, half_open_max_calls=1,
            key="tok-recover", state_store=store,
        )
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        # 冷却期到转半开
        import time as _time

        _time.sleep(0.08)
        assert breaker.state == CircuitState.HALF_OPEN
        # 半开 1 次成功即恢复
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        # 计数已清零，重新累计到阈值才熔断
        assert store.failure_count("tok-recover") == 0
        breaker.record_failure()
        assert store.failure_count("tok-recover") == 1
        assert breaker.state == CircuitState.CLOSED  # 未达阈值不熔断
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN  # 达阈值熔断

    def test_local_store_incr_thread_safe(self):
        """_LocalStore.incr 在多线程下计数不丢（模拟单 worker 无 shared_state 场景）。"""
        from concurrent.futures import ThreadPoolExecutor

        store = _LocalStore()

        def incr_ten():
            for _ in range(10):
                store.incr("tok-threadsafe")

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _: incr_ten(), range(8)))
        assert store._data.get("tok-threadsafe") == 80