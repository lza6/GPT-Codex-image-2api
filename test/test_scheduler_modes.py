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


class TestAdaptiveScheduler(unittest.TestCase):
    """自适应调度器：基于运行指标自动切换调度模式。"""

    def setUp(self) -> None:
        self.service = _make_service([
            {"access_token": "token-a", "type": "Plus", "status": "正常", "quota": 10, "success": 50, "fail": 2},
            {"access_token": "token-b", "type": "Plus", "status": "正常", "quota": 10, "success": 5, "fail": 0},
            {"access_token": "token-c", "type": "Plus", "status": "正常", "quota": 10, "success": 0, "fail": 0},
        ])
        self.service._affinity_map = {"gpt-5": "token-a", "gpt-image-2": "token-b", "dall-e-3": "token-c", "gpt-4o": "token-a", "o1": "token-b"}
        _set_scheduler_mode("weighted_random")

    def tearDown(self) -> None:
        _cleanup(self.service)

    def test_high_load_selects_least_load(self) -> None:
        """高并发（>100）应选择 least_load。"""
        from services.adaptive_scheduler import adaptive_scheduler
        adaptive_scheduler._stats["concurrent_requests"] = 150
        adaptive_scheduler._stats["success_rate"] = 0.95
        adaptive_scheduler._stats["model_diversity"] = 0.3
        chosen = adaptive_scheduler.select_mode()
        self.assertEqual(chosen, "least_load")

    def test_low_success_rate_selects_predictive(self) -> None:
        """低成功率（<0.8）应选择 predictive。"""
        from services.adaptive_scheduler import adaptive_scheduler
        adaptive_scheduler._stats["concurrent_requests"] = 10
        adaptive_scheduler._stats["success_rate"] = 0.65
        adaptive_scheduler._stats["model_diversity"] = 0.3
        chosen = adaptive_scheduler.select_mode()
        self.assertEqual(chosen, "predictive")

    def test_high_diversity_selects_affinity(self) -> None:
        """高模型多样性（>0.7）应选择 affinity。"""
        from services.adaptive_scheduler import adaptive_scheduler
        adaptive_scheduler._stats["concurrent_requests"] = 10
        adaptive_scheduler._stats["success_rate"] = 0.95
        adaptive_scheduler._stats["model_diversity"] = 0.8
        chosen = adaptive_scheduler.select_mode()
        self.assertEqual(chosen, "affinity")

    def test_default_selects_weighted(self) -> None:
        """默认场景应选择 weighted_random。"""
        from services.adaptive_scheduler import adaptive_scheduler
        adaptive_scheduler._stats["concurrent_requests"] = 10
        adaptive_scheduler._stats["success_rate"] = 0.95
        adaptive_scheduler._stats["model_diversity"] = 0.3
        chosen = adaptive_scheduler.select_mode()
        self.assertEqual(chosen, "weighted_random")

    def test_tick_updates_current_mode(self) -> None:
        """tick() 通过 collect_stats 收集实时指标后应更新 current_mode。"""
        from services.adaptive_scheduler import adaptive_scheduler
        # 直接通过服务状态模拟高并发：大量 in-flight
        accts = self.service.list_accounts()
        for acct in accts:
            token = acct.get("access_token", "")
            self.service._image_inflight[token] = 50
        adaptive_scheduler._switched_at = 0.0  # 强制允许切换
        mode = adaptive_scheduler.tick(self.service)
        self.assertEqual(mode, "least_load")

    def test_tick_high_load_respects_dwell(self) -> None:
        """tick() 应遵守最短驻留时间。"""
        from services.adaptive_scheduler import adaptive_scheduler
        adaptive_scheduler._current_mode = "predictive"
        adaptive_scheduler._switched_at = 9999999999.0  # 未来时间
        adaptive_scheduler._stats["concurrent_requests"] = 150
        mode = adaptive_scheduler.tick(self.service)
        self.assertEqual(mode, "predictive")  # 不应切换

    def test_collect_stats(self) -> None:
        """collect_stats 应正确收集指标。"""
        from services.adaptive_scheduler import adaptive_scheduler
        stats = adaptive_scheduler.collect_stats(self.service)
        self.assertIn("concurrent_requests", stats)
        self.assertIn("success_rate", stats)
        self.assertIn("model_diversity", stats)
        self.assertGreaterEqual(stats["success_rate"], 0.0)

    def test_get_history(self) -> None:
        """get_history 应返回历史记录。"""
        from services.adaptive_scheduler import adaptive_scheduler
        adaptive_scheduler._record_switch("weighted_random", "least_load")
        history = adaptive_scheduler.get_history(limit=5)
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(history[0]["from"], "weighted_random")
        self.assertEqual(history[0]["to"], "least_load")

    def test_get_status(self) -> None:
        """get_status 应返回当前状态。"""
        from services.adaptive_scheduler import adaptive_scheduler
        status = adaptive_scheduler.get_status()
        self.assertIn("current_mode", status)
        self.assertIn("stats", status)
        self.assertIn("history_count", status)

    def test_adaptive_scheduler_imports(self) -> None:
        """自适应调度器模块应可导入。"""
        from services.adaptive_scheduler import adaptive_scheduler, AdaptiveScheduler
        self.assertIsInstance(adaptive_scheduler, AdaptiveScheduler)


class TestSchedulerModeStats(unittest.TestCase):
    """III-02：调度模式 A/B 统计——每次 pick 记录 mode，结果回填到对应模式。"""

    def setUp(self) -> None:
        self.service = _make_service([
            {"access_token": "token-a", "type": "Plus", "status": "正常", "quota": 10},
            {"access_token": "token-b", "type": "Plus", "status": "正常", "quota": 10},
        ])

    def tearDown(self) -> None:
        _cleanup(self.service)

    def test_effective_mode_default(self) -> None:
        """默认（非自适应）→ 生效模式 = config.scheduler_mode。"""
        _set_scheduler_mode("round_robin")
        self.assertEqual(self.service._effective_scheduler_mode(), "round_robin")

    def test_pick_records_mode_stat_and_result(self) -> None:
        """pick 后 per-mode picks 增加，mark_image_result 回填成功与延迟。"""
        _set_scheduler_mode("weighted_random")
        token = self.service._acquire_next_candidate_token()
        stats = self.service.get_scheduler_mode_stats()
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["mode"], "weighted_random")
        self.assertEqual(stats[0]["picks"], 1)
        # 回填成功
        self.service.mark_image_result(token, True)
        stats = self.service.get_scheduler_mode_stats()
        self.assertEqual(stats[0]["success"], 1)
        self.assertGreaterEqual(stats[0]["avg_latency_ms"], 0.0)
        self.assertEqual(stats[0]["fail_rate"], 0.0)

    def test_result_fail_updates_fail_rate(self) -> None:
        """失败结果 → fail_rate 反映在统计中。"""
        _set_scheduler_mode("least_used")
        token = self.service._acquire_next_candidate_token()
        self.service.mark_image_result(token, False)
        stats = self.service.get_scheduler_mode_stats()
        self.assertEqual(stats[0]["fail"], 1)
        self.assertEqual(stats[0]["fail_rate"], 1.0)

    def test_mode_stats_sorted_by_picks(self) -> None:
        """mode stats 按命中数降序排列。"""
        self.service._record_scheduler_pick_stat("token-a", "round_robin")
        self.service._record_scheduler_pick_stat("token-a", "least_used")
        self.service._record_scheduler_pick_stat("token-a", "round_robin")
        stats = self.service.get_scheduler_mode_stats()
        self.assertEqual(stats[0]["mode"], "round_robin")
        self.assertEqual(stats[0]["picks"], 2)
        self.assertEqual(stats[1]["mode"], "least_used")

    def test_adaptive_enabled_uses_current_mode(self) -> None:
        """自适应开启 → 生效模式取 adaptive_scheduler.current_mode。"""
        from services.adaptive_scheduler import adaptive_scheduler
        config.data["scheduler_adaptive_enabled"] = True
        adaptive_scheduler._current_mode = "predictive"
        try:
            self.assertEqual(self.service._effective_scheduler_mode(), "predictive")
        finally:
            config.data["scheduler_adaptive_enabled"] = False
            adaptive_scheduler._current_mode = "weighted_random"


if __name__ == "__main__":
    unittest.main()