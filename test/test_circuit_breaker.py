"""熔断器单元测试 + 文本/图片链路熔断接线测试。

TDD RED：熔断器组件已存在但无测试；文本取号链路（get_text_access_token /
stream_text_deltas）未接熔断，是本文件要驱动实现的缺口。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


class CircuitBreakerStateMachineTests(unittest.TestCase):
    """熔断器状态机：closed→open→half_open→closed。"""

    def _breaker(self):
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from services.circuit_breaker import CircuitBreaker
        return CircuitBreaker(failure_threshold=3, recovery_timeout=0.05, half_open_max_calls=2)

    def test_initial_state_closed_and_allows(self):
        b = self._breaker()
        self.assertTrue(b.allow_request(), "初始应为 closed，允许请求")

    def test_trips_open_after_threshold_failures(self):
        b = self._breaker()
        for _ in range(3):
            b.record_failure()
        self.assertFalse(b.allow_request(), "连续失败达阈值应熔断，拒绝请求")

    def test_open_recovers_to_half_open_after_timeout(self):
        import time
        b = self._breaker()
        for _ in range(3):
            b.record_failure()
        self.assertFalse(b.allow_request())
        time.sleep(0.06)  # 超过 recovery_timeout
        # half_open 状态下 allow_request 应返回 True（允许试探）
        self.assertTrue(b.allow_request(), "冷却期后应转 half_open 允许试探")

    def test_half_open_success_restores_closed(self):
        import time
        b = self._breaker()
        for _ in range(3):
            b.record_failure()
        time.sleep(0.06)
        b.allow_request()  # 触发 half_open
        b.record_success()
        b.record_success()  # half_open_max_calls=2
        # 恢复 closed 后失败计数清零
        b.record_failure()
        self.assertTrue(b.allow_request(), "half_open 连续成功应恢复 closed")

    def test_half_open_failure_retrips(self):
        import time
        b = self._breaker()
        for _ in range(3):
            b.record_failure()
        time.sleep(0.06)
        b.allow_request()  # half_open
        b.record_failure()  # 半开再失败
        self.assertFalse(b.allow_request(), "half_open 再失败应立即重新熔断")


class CircuitBreakerDefaultThresholdTests(unittest.TestCase):
    """默认阈值回归：生产默认 5 次熔断是调度/熔断契约的一部分，改动必须显式。

    由变异探针（scripts/mutation_probe.py）驱动补全：failure_threshold 5→6
    变异曾逃逸（全部测试仍绿），说明默认值无人看守。
    """

    def test_default_failure_threshold_is_five(self):
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from services.circuit_breaker import CircuitBreaker
        b = CircuitBreaker()
        self.assertEqual(b.failure_threshold, 5, "默认熔断阈值被改动——若为有意调整，请同步更新本测试与文档")

    def test_registry_default_threshold_is_five(self):
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from services.circuit_breaker import circuit_breaker_registry
        b = circuit_breaker_registry.get("mutation-probe-threshold-check")
        try:
            self.assertEqual(b.failure_threshold, 5, "全局注册表默认阈值被改动")
        finally:
            circuit_breaker_registry.remove("mutation-probe-threshold-check")


class TextStreamCircuitBreakerWiringTests(unittest.TestCase):
    """文本流式链路熔断接线：stream_text_deltas 应检查熔断并记录成败。"""

    def test_text_backend_skips_circuit_open_token(self):
        """text_backend：取号后若该 token 熔断 open，应换号或抛错，不打到上游。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from services.circuit_breaker import circuit_breaker_registry
        from services.protocol import conversation

        # 制造一个熔断 open 的 token
        fake_token = "fake-open-token-xyz"
        breaker = circuit_breaker_registry.get(fake_token)
        for _ in range(5):
            breaker.record_failure()
        self.assertFalse(breaker.allow_request(), "前置：token 应已熔断")

        # text_backend 内部取号若拿到熔断 token，必须跳过/抛错而非直接实例化
        # 通过 monkeypatch get_text_access_token 返回熔断 token 验证接线存在
        import services.account_service as acct
        orig = acct.account_service.get_text_access_token
        acct.account_service.get_text_access_token = lambda *a, **k: fake_token
        try:
            try:
                conversation.text_backend(model="auto")
                # 若返回了 backend，说明未检查熔断（缺口）；应抛 RuntimeError
                self.fail("text_backend 未检查熔断，返回了熔断 token 的 backend")
            except RuntimeError:
                pass  # 预期：熔断 open 应快速失败
        finally:
            acct.account_service.get_text_access_token = orig
            circuit_breaker_registry.remove(fake_token)


if __name__ == "__main__":
    unittest.main()


class TestCircuitBreakerConcurrency:
    """熔断器并发状态迁移 + 注册表并发 get/remove 线程安全（阶段 7，D13）。"""

    def test_concurrent_state_transitions_thread_safe(self):
        import threading
        from services.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=100, recovery_timeout=0.01, half_open_max_calls=50)
        errors: list[Exception] = []

        def worker(n: int) -> None:
            try:
                for _ in range(200):
                    breaker.record_failure()
                    breaker.record_success()
                    breaker.allow_request()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not errors

    def test_registry_concurrent_get_remove_thread_safe(self):
        import threading
        from services.circuit_breaker import CircuitBreakerRegistry

        registry = CircuitBreakerRegistry()
        errors: list[Exception] = []

        def worker(n: int) -> None:
            try:
                for i in range(50):
                    registry.get(f"tok-{i % 10}")
                    registry.remove(f"tok-{i % 10}")
                    registry.all_status()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not errors


class TestHalfOpenPartialTransitions:
    """HALF_OPEN 部分成功部分失败的迁移（阶段 7，D13）。"""

    def test_half_open_success_then_failure_reopens(self):
        import time
        from services.circuit_breaker import CircuitBreaker

        b = CircuitBreaker(failure_threshold=3, recovery_timeout=0.05, half_open_max_calls=3)
        for _ in range(3):
            b.record_failure()
        assert not b.allow_request()
        time.sleep(0.06)
        assert b.allow_request()  # HALF_OPEN
        b.record_success()  # 半开成功 1 次
        b.record_failure()  # 半开失败 → 立即回 OPEN
        assert not b.allow_request()

    def test_half_open_full_success_closes(self):
        import time
        from services.circuit_breaker import CircuitBreaker

        b = CircuitBreaker(failure_threshold=3, recovery_timeout=0.05, half_open_max_calls=2)
        for _ in range(3):
            b.record_failure()
        time.sleep(0.06)
        b.allow_request()
        b.record_success()
        b.record_success()  # 达 half_open_max_calls → CLOSED
        assert b.allow_request()
