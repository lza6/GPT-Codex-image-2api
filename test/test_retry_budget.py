"""统一重试预算测试。

规则：
- 幂等 GET：指数退避最多 N 次后放弃
- 流式首字节前失败：换账号最多重试 1 次
- 流式开始后失败：绝不重试，直接报错
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]


class RetryIdempotentGetTests(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT_DIR))

    def test_success_first_try_no_retry(self):
        from services.retry_budget import retry_idempotent_get
        calls = []
        with patch("services.retry_budget.time.sleep") as slp:
            result = retry_idempotent_get(lambda: calls.append(1) or "ok")
        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1)
        slp.assert_not_called()

    def test_retries_until_success(self):
        from services.retry_budget import retry_idempotent_get
        attempts = []
        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("boom")
            return "ok"
        with patch("services.retry_budget.time.sleep"):
            result = retry_idempotent_get(flaky, max_retries=2)
        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 3, "前两次失败、第三次成功")

    def test_gives_up_after_max_retries(self):
        from services.retry_budget import retry_idempotent_get
        attempts = []
        def always_fail():
            attempts.append(1)
            raise RuntimeError("boom")
        with patch("services.retry_budget.time.sleep"):
            with self.assertRaises(RuntimeError):
                retry_idempotent_get(always_fail, max_retries=2)
        self.assertEqual(len(attempts), 3, "max_retries=2 应共尝试 3 次后放弃")

    def test_non_retryable_raises_immediately(self):
        from services.retry_budget import retry_idempotent_get
        attempts = []
        def fail():
            attempts.append(1)
            raise ValueError("not retryable")
        with patch("services.retry_budget.time.sleep") as slp:
            with self.assertRaises(ValueError):
                retry_idempotent_get(fail, max_retries=2, retryable=lambda e: not isinstance(e, ValueError))
        self.assertEqual(len(attempts), 1, "不可重试异常应立即抛出")
        slp.assert_not_called()

    def test_backoff_is_exponential(self):
        from services.retry_budget import retry_idempotent_get
        def always_fail():
            raise RuntimeError("boom")
        with patch("services.retry_budget.time.sleep") as slp:
            with self.assertRaises(RuntimeError):
                retry_idempotent_get(always_fail, max_retries=2, base_delay=0.5)
        delays = [c.args[0] for c in slp.call_args_list]
        self.assertEqual(delays, [0.5, 1.0], "应按 2 倍指数退避")


class StreamRetryBudgetTests(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT_DIR))

    def test_pre_stream_first_failure_allows_one_switch(self):
        from services.retry_budget import can_retry_stream
        self.assertTrue(can_retry_stream(emitted=False, pre_stream_retries_used=0),
                        "首字节前首次失败应允许换账号重试")

    def test_pre_stream_second_failure_denied(self):
        from services.retry_budget import can_retry_stream
        self.assertFalse(can_retry_stream(emitted=False, pre_stream_retries_used=1),
                         "首字节前换账号重试最多 1 次")

    def test_after_stream_start_never_retries(self):
        from services.retry_budget import can_retry_stream
        self.assertFalse(can_retry_stream(emitted=True, pre_stream_retries_used=0),
                         "流式开始后绝不重试（防重复扣费/出图）")


class DefaultValueBoundaryTests(unittest.TestCase):
    """重试预算默认值精确断言（变异探针锚点，防逃逸）。"""

    def test_idempotent_get_max_retries_default_is_2(self):
        from services.retry_budget import IDEMPOTENT_GET_MAX_RETRIES
        self.assertEqual(IDEMPOTENT_GET_MAX_RETRIES, 2)
        self.assertNotEqual(IDEMPOTENT_GET_MAX_RETRIES, 3)

    def test_pre_stream_switch_max_retries_default_is_1(self):
        from services.retry_budget import PRE_STREAM_SWITCH_MAX_RETRIES
        self.assertEqual(PRE_STREAM_SWITCH_MAX_RETRIES, 1)

    def test_backoff_base_delay_default_is_half_second(self):
        import inspect

        from services.retry_budget import retry_idempotent_get
        sig = inspect.signature(retry_idempotent_get)
        self.assertEqual(sig.parameters["base_delay"].default, 0.5)
        self.assertNotEqual(sig.parameters["base_delay"].default, 1.0)


if __name__ == "__main__":
    unittest.main()
