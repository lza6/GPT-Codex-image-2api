"""前后端契约测试：验证 API 返回结构与前端类型定义一致。

不依赖外部服务，纯内存验证。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT_DIR / "config.json"


class ContractTests(unittest.TestCase):
    """验证后端 API 返回结构与前端类型定义一致。"""

    maxDiff = None

    def setUp(self):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            self.config = json.load(f)

    # ---- 配置项契约 ----

    def test_config_has_all_required_keys(self):
        """config.json 必须包含所有前端需要的配置项。"""
        required = [
            "auth-key", "proxy", "base_url",
            "refresh_account_interval_minute", "image_retention_days",
            "image_account_concurrency", "image_parallel_generation",
            "auto_remove_invalid_accounts", "auto_remove_rate_limited_accounts",
            "scheduler_mode", "scheduler_priority",
            "rate_limit_rpm", "rate_limit_per_ip_rpm", "workers",
        ]
        for key in required:
            self.assertIn(key, self.config, f"缺少配置项: {key}")

    def test_scheduler_mode_valid(self):
        """scheduler_mode 必须是合法值。"""
        mode = self.config.get("scheduler_mode", "round_robin")
        self.assertIn(mode, ("round_robin", "remaining_quota"))

    def test_workers_positive_int(self):
        """workers 必须是正整数。"""
        w = self.config.get("workers", 1)
        self.assertIsInstance(w, int)
        self.assertGreaterEqual(w, 1)

    def test_rate_limit_non_negative(self):
        """限流配置必须是非负整数。"""
        for key in ("rate_limit_rpm", "rate_limit_per_ip_rpm"):
            v = self.config.get(key, 0)
            self.assertIsInstance(v, int)
            self.assertGreaterEqual(v, 0)

    # ---- 调度系统契约 ----

    def test_scheduler_priority_format(self):
        """scheduler_priority 必须是 dict[str, int]。"""
        sp = self.config.get("scheduler_priority", {})
        self.assertIsInstance(sp, dict)
        for key, value in sp.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, int)
            self.assertGreaterEqual(value, -100)
            self.assertLessEqual(value, 100)

    # ---- 健康档位契约 ----

    def test_health_tier_hierarchy(self):
        """健康档位必须是 healthy > warm > risky 严格顺序。"""
        from services.account_service import AccountService
        tiers = AccountService._TIER_ORDER
        self.assertEqual(tiers, ("healthy", "warm", "risky"))

    def test_dispatch_score_ranges(self):
        """调度分必须在合理范围 [-100, 200]。"""
        from services.account_service import AccountService
        accounts = [
            {"status": "正常", "quota": 50, "success": 20, "fail": 0},
            {"status": "正常", "quota": 0, "success": 0, "fail": 10},
            {"status": "禁用", "quota": 0, "success": 0, "fail": 0},
        ]
        for a in accounts:
            tier = AccountService._account_health_tier(a)
            score = AccountService._account_dispatch_score(a, tier)
            self.assertGreaterEqual(score, -100)
            self.assertLessEqual(score, 200)

    # ---- 限流契约 ----

    def test_rate_limit_window(self):
        """限流窗口必须是 60 秒滑动窗口。"""
        from api.rate_limit import SlidingWindowLimiter
        limiter = SlidingWindowLimiter(max_requests=5)
        self.assertEqual(limiter.window_seconds, 60.0)
        self.assertEqual(limiter.max_requests, 5)
        # 前 5 个请求应通过
        for i in range(5):
            self.assertTrue(limiter.check("test"))
        # 第 6 个应拒绝
        self.assertFalse(limiter.check("test"))

    # ---- 配置项默认值契约 ----

    def test_config_defaults(self):
        """缺失配置项时应有合理的默认值。"""
        from services.config import config
        self.assertIn(config.scheduler_mode, ("round_robin", "remaining_quota"))
        self.assertGreaterEqual(config.rate_limit_rpm, 0)
        self.assertGreaterEqual(config.workers, 1)
        self.assertIn(config.storage_backend_type, ("json", "sqlite", "postgres", "git"))


if __name__ == "__main__":
    unittest.main()