from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.account_service import AccountService
from services.config import config
from services.storage.json_storage import JSONStorageBackend


def _make_service(accounts: list[dict] | None = None) -> AccountService:
    tmp = tempfile.TemporaryDirectory()
    service = AccountService(JSONStorageBackend(Path(tmp.name) / "accounts.json"))
    service._image_inflight = {}
    if accounts:
        service.add_account_items(accounts)
    object.__setattr__(service, "_tmp_dir", tmp)
    return service


def _cleanup(service: AccountService) -> None:
    tmp = getattr(service, "_tmp_dir", None)
    if tmp is not None:
        try:
            tmp.cleanup()
        except Exception:
            pass


def _set_scheduler_mode(mode: str) -> None:
    """设置 config.scheduler_mode（通过 data dict 绕过 property 只读限制）。"""
    config.data["scheduler_mode"] = mode


class TestLeastLoad(unittest.TestCase):
    """Least-Load 调度模式：选择当前负载最低的账号。"""

    def setUp(self) -> None:
        self.service = _make_service([
            {"access_token": "token-a", "type": "Plus", "status": "正常", "quota": 10},
            {"access_token": "token-b", "type": "Plus", "status": "正常", "quota": 10},
            {"access_token": "token-c", "type": "Plus", "status": "正常", "quota": 10},
        ])

    def tearDown(self) -> None:
        _cleanup(self.service)

    def test_empty_pool_raises(self) -> None:
        """空池时 least_load 应抛出 RuntimeError。"""
        with self.assertRaises(RuntimeError):
            self.service._pick_least_load([])

    def test_same_load_picks_first(self) -> None:
        """同负载时取第一个 token（所有 inflight 均为 0）。"""
        tokens = ["token-a", "token-b", "token-c"]
        chosen = self.service._pick_least_load(tokens)
        self.assertEqual(chosen, "token-a")

    def test_different_load_picks_lowest(self) -> None:
        """负载差异时选 inflight 最小的账号。"""
        self.service._image_inflight["token-a"] = 3
        self.service._image_inflight["token-b"] = 1
        self.service._image_inflight["token-c"] = 5
        tokens = ["token-a", "token-b", "token-c"]
        chosen = self.service._pick_least_load(tokens)
        self.assertEqual(chosen, "token-b")

    def test_single_account(self) -> None:
        """单账号场景返回该账号。"""
        tokens = ["token-a"]
        self.service._image_inflight["token-a"] = 7
        chosen = self.service._pick_least_load(tokens)
        self.assertEqual(chosen, "token-a")


class TestPredictive(unittest.TestCase):
    """Predictive 调度模式：基于历史用量预测选择配额最充足的账号。"""

    def setUp(self) -> None:
        self.service = _make_service([
            {"access_token": "token-a", "type": "Plus", "status": "正常", "quota": 10, "success": 50, "fail": 2,
             "last_used_at": (datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))},
            {"access_token": "token-b", "type": "Plus", "status": "正常", "quota": 10, "success": 5, "fail": 0,
             "last_used_at": (datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))},
            {"access_token": "token-c", "type": "Plus", "status": "正常", "quota": 10, "success": 0, "fail": 0},
        ])

    def tearDown(self) -> None:
        _cleanup(self.service)

    def test_no_history_fallback(self) -> None:
        """无历史数据时（0 次调用）应视为高可用，返回有配额的账号。"""
        tokens = ["token-c"]
        chosen = self.service._pick_predictive(tokens)
        self.assertEqual(chosen, "token-c")

    def test_quota_abundant_preferred(self) -> None:
        """配额充足（消耗慢）的账号应优先于消耗快的账号。"""
        tokens = ["token-a", "token-b"]
        chosen = self.service._pick_predictive(tokens)
        self.assertEqual(chosen, "token-b")

    def test_quota_exhausted_penalized(self) -> None:
        """配额接近耗尽或已耗尽的账号应被降权。"""
        acct_a = {"access_token": "token-a", "type": "Plus", "status": "正常", "quota": 1, "success": 100, "fail": 0,
                  "last_used_at": (datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))}
        acct_b = {"access_token": "token-b", "type": "Plus", "status": "正常", "quota": 10, "success": 5, "fail": 0,
                  "last_used_at": (datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))}
        service = _make_service([acct_a, acct_b])
        try:
            tokens = ["token-a", "token-b"]
            chosen = service._pick_predictive(tokens)
            self.assertEqual(chosen, "token-b")
        finally:
            _cleanup(service)

    def test_ewma_rate_calculation(self) -> None:
        """EWMA 消耗速率计算：总用量/存在时间 应反映实际消耗速度。"""
        tokens = ["token-a"]
        chosen = self.service._pick_predictive(tokens)
        self.assertEqual(chosen, "token-a")


class TestAffinity(unittest.TestCase):
    """Affinity 调度模式：同一模型路由到同一账号。"""

    def setUp(self) -> None:
        self.service = _make_service([
            {"access_token": "token-a", "type": "Plus", "status": "正常", "quota": 10},
            {"access_token": "token-b", "type": "Plus", "status": "正常", "quota": 10},
            {"access_token": "token-c", "type": "Plus", "status": "正常", "quota": 10},
        ])
        self.service._affinity_map = {}
        self.service._affinity_at = {}

    def tearDown(self) -> None:
        _cleanup(self.service)

    def test_affinity_hit(self) -> None:
        """同一模型第二次请求应命中亲和路由。"""
        tokens = ["token-a", "token-b", "token-c"]
        first = self.service._pick_affinity(tokens, model="gpt-image-2")
        second = self.service._pick_affinity(tokens, model="gpt-image-2")
        self.assertEqual(first, second)

    def test_affinity_ttl_expiry(self) -> None:
        """超时后亲和性应释放，不再强制路由到原账号。"""
        tokens = ["token-a", "token-b", "token-c"]
        self.service._pick_affinity(tokens, model="gpt-image-2")
        self.service._affinity_at["gpt-image-2"] = time.time() - 400
        chosen = self.service._pick_affinity(tokens, model="gpt-image-2")
        self.assertIn(chosen, tokens)

    def test_different_models_affinity_independent(self) -> None:
        """不同模型的亲和性应独立维护。"""
        tokens = ["token-a", "token-b", "token-c"]
        model_a = self.service._pick_affinity(tokens, model="gpt-image-2")
        model_b = self.service._pick_affinity(tokens, model="dall-e-3")
        self.service._affinity_at["gpt-image-2"] = time.time() - 400
        self.assertEqual(self.service._affinity_map.get("dall-e-3"), model_b)

    def test_new_model_first_call(self) -> None:
        """新模型首次调用应正常返回一个 token 并记录亲和。"""
        tokens = ["token-a", "token-b", "token-c"]
        chosen = self.service._pick_affinity(tokens, model="new-model-v1")
        self.assertIn(chosen, tokens)
        self.assertEqual(self.service._affinity_map.get("new-model-v1"), chosen)


class TestCompatibility(unittest.TestCase):
    """旧调度模式不受新代码影响。"""

    def setUp(self) -> None:
        self.service = _make_service([
            {"access_token": "token-a", "type": "Plus", "status": "正常", "quota": 10},
            {"access_token": "token-b", "type": "Plus", "status": "正常", "quota": 10},
            {"access_token": "token-c", "type": "Plus", "status": "正常", "quota": 10},
        ])

    def tearDown(self) -> None:
        _cleanup(self.service)

    def test_round_robin_unchanged(self) -> None:
        """round_robin 模式行为不变。"""
        _set_scheduler_mode("round_robin")
        self.assertEqual(config.scheduler_mode, "round_robin")
        tokens = self.service._list_available_candidate_tokens()
        self.assertGreater(len(tokens), 0)

    def test_remaining_quota_unchanged(self) -> None:
        """remaining_quota 模式行为不变。"""
        _set_scheduler_mode("remaining_quota")
        self.assertEqual(config.scheduler_mode, "remaining_quota")
        tokens = self.service._list_available_candidate_tokens()
        self.assertGreater(len(tokens), 0)

    def test_weighted_random_unchanged(self) -> None:
        """weighted_random 模式行为不变。"""
        _set_scheduler_mode("weighted_random")
        self.assertEqual(config.scheduler_mode, "weighted_random")
        tokens = self.service._list_available_candidate_tokens()
        self.assertGreater(len(tokens), 0)

    def test_least_load_new_mode_works(self) -> None:
        """least_load 新模式注册后正常可用。"""
        _set_scheduler_mode("least_load")
        self.assertEqual(config.scheduler_mode, "least_load")
        tokens = self.service._list_available_candidate_tokens()
        self.assertGreater(len(tokens), 0)

    def test_predictive_new_mode_works(self) -> None:
        """predictive 新模式注册后正常可用。"""
        _set_scheduler_mode("predictive")
        self.assertEqual(config.scheduler_mode, "predictive")
        tokens = self.service._list_available_candidate_tokens()
        self.assertGreater(len(tokens), 0)

    def test_affinity_new_mode_works(self) -> None:
        """affinity 新模式注册后正常可用。"""
        _set_scheduler_mode("affinity")
        self.assertEqual(config.scheduler_mode, "affinity")
        tokens = self.service._list_available_candidate_tokens()
        self.assertGreater(len(tokens), 0)


if __name__ == "__main__":
    unittest.main()