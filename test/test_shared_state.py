"""共享状态抽象层测试（D16）：Local 实现 + 工厂降级 + TTL。"""

from __future__ import annotations

import time

from services.shared_state import LocalBackend, get_shared_state, reset_shared_state


class TestLocalBackend:
    def test_set_get(self):
        b = LocalBackend()
        b.set("k1", {"v": 42})
        assert b.get("k1") == {"v": 42}

    def test_get_missing_returns_none(self):
        assert LocalBackend().get("nope") is None

    def test_delete(self):
        b = LocalBackend()
        b.set("k", 1)
        b.delete("k")
        assert b.get("k") is None

    def test_incr(self):
        b = LocalBackend()
        assert b.incr("counter") == 1
        assert b.incr("counter", 5) == 6
        assert b.get("counter") == 6

    def test_ttl_expiry(self):
        b = LocalBackend()
        b.set("ephemeral", "x", ttl_seconds=0.05)
        assert b.get("ephemeral") == "x"
        time.sleep(0.08)
        assert b.get("ephemeral") is None

    def test_exists(self):
        b = LocalBackend()
        b.set("k", 1)
        assert b.exists("k")
        assert not b.exists("missing")

    def test_backend_name(self):
        assert LocalBackend().backend_name() == "local"


class TestFactory:
    def setup_method(self):
        reset_shared_state()

    def teardown_method(self):
        reset_shared_state()

    def test_defaults_to_local_without_redis_url(self, monkeypatch):
        from services.config import config

        monkeypatch.setattr(type(config), "redis_url", property(lambda self: ""))
        backend = get_shared_state()
        assert backend.backend_name() == "local"

    def test_degrades_to_local_when_redis_unavailable(self, monkeypatch):
        from services.config import config

        monkeypatch.setattr(type(config), "redis_url", property(lambda self: "redis://127.0.0.1:1/0"))
        # redis 包未装或连不上时降级 local（不抛异常）
        backend = get_shared_state()
        assert backend.backend_name() == "local"


class TestRateLimitShared:
    """限流走共享层（D16）：多进程计数一致性。"""

    def test_shared_path_uses_incr_when_redis_configured(self, monkeypatch):
        from api.rate_limit import SlidingWindowLimiter
        from services.config import config

        monkeypatch.setattr(type(config), "redis_url", property(lambda self: "redis://fake/0"))
        limiter = SlidingWindowLimiter(window_seconds=60, max_requests=2)

        # LocalBackend 模拟共享层（Redis 不可用时工厂降级 Local，行为一致）
        from services.shared_state import LocalBackend, reset_shared_state

        reset_shared_state()
        shared = LocalBackend()
        monkeypatch.setattr("services.shared_state.get_shared_state", lambda: shared)

        assert limiter.check("ip-1") is True
        assert limiter.check("ip-1") is True
        assert limiter.check("ip-1") is False  # 超限
        # 第二个"进程"（新 limiter 实例）共享同一计数
        limiter2 = SlidingWindowLimiter(window_seconds=60, max_requests=2)
        monkeypatch.setattr("services.shared_state.get_shared_state", lambda: shared)
        assert limiter2.check("ip-1") is False, "共享层下新实例应看到已累计的计数"

    def test_local_path_unchanged_without_redis(self, monkeypatch):
        from api.rate_limit import SlidingWindowLimiter
        from services.config import config

        monkeypatch.setattr(type(config), "redis_url", property(lambda self: ""))
        limiter = SlidingWindowLimiter(window_seconds=60, max_requests=1)
        assert limiter.check("ip-2") is True
        assert limiter.check("ip-2") is False
        # 无共享层时新实例计数独立（原行为）
        limiter2 = SlidingWindowLimiter(window_seconds=60, max_requests=1)
        assert limiter2.check("ip-2") is True
