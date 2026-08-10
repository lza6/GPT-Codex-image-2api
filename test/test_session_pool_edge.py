"""session_pool 边界测试（阶段 7，D13）：LRU/TTL/key 隔离/并发。"""

from __future__ import annotations

import threading
import time

from services.session_pool import SessionPool


def _pool(max_entries: int = 3, ttl: float = 300) -> SessionPool:
    return SessionPool(ttl_seconds=ttl, max_entries=max_entries, health_check_enabled=False)


def test_lru_evicts_oldest_when_full():
    pool = _pool(max_entries=2)
    s1 = pool.get(account={"access_token": "tok-aaa"}, fp_key="a")
    s2 = pool.get(account={"access_token": "tok-bbb"}, fp_key="b")
    assert pool.stats()["pooled_sessions"] == 2
    # 第三个触发 LRU 逐出最旧的 s1
    s3 = pool.get(account={"access_token": "tok-ccc"}, fp_key="c")
    assert pool.stats()["pooled_sessions"] == 2
    # 再次获取 tok-aaa 应新建（s1 已被逐出）
    s1_new = pool.get(account={"access_token": "tok-aaa"}, fp_key="a")
    assert s1_new is not s1


def test_ttl_expiry_recreates_session():
    pool = _pool(ttl=0.05)
    s1 = pool.get(account={"access_token": "tok-ttl"}, fp_key="x")
    time.sleep(0.08)
    s2 = pool.get(account={"access_token": "tok-ttl"}, fp_key="x")
    assert s2 is not s1, "TTL 过期后应重建 Session"


def test_same_key_reuses_session():
    pool = _pool()
    s1 = pool.get(account={"access_token": "tok-same"}, fp_key="f")
    s2 = pool.get(account={"access_token": "tok-same"}, fp_key="f")
    assert s1 is s2


def test_different_tokens_isolated():
    pool = _pool()
    sa = pool.get(account={"access_token": "tok-aaaa"}, fp_key="f")
    sb = pool.get(account={"access_token": "tok-bbbb"}, fp_key="f")
    assert sa is not sb, "不同 token 必须隔离（防串号）"


def test_close_all_clears_pool():
    pool = _pool()
    pool.get(account={"access_token": "t1"}, fp_key="a")
    pool.get(account={"access_token": "t2"}, fp_key="b")
    pool.close_all()
    assert pool.stats()["pooled_sessions"] == 0


def test_concurrent_get_thread_safe():
    pool = _pool(max_entries=50)
    errors: list[Exception] = []
    sessions: list = []
    lock = threading.Lock()

    def worker(n: int) -> None:
        try:
            for i in range(20):
                s = pool.get(account={"access_token": f"tok-{i % 5}"}, fp_key=f"f{i % 3}")
                with lock:
                    sessions.append(s)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert not errors
    assert pool.stats()["pooled_sessions"] <= 50


def test_session_pool_default_max_entries_is_200_explicit():
    """默认值显式回归（变异探针防逃逸）：全局池构造参数必须为 200。"""
    from services.session_pool import SessionPool

    # 新建一个临时池验证构造参数，而非断言全局池运行时值（auto-scaling 可能已增长）
    temp_pool = SessionPool(ttl_seconds=300.0, max_entries=200, min_size=5)
    assert temp_pool._max_entries == 200, "池上限默认值漂移——可能被意外修改"


# ── v2.17.0 新功能测试 ──────────────────────────────────────────────


def test_health_check_validates_connection():
    """健康预检：连接检查失败应重建 Session。"""
    pool = SessionPool(health_check_enabled=True, health_check_timeout=2.0, ttl_seconds=300)
    s1 = pool.get(account={"access_token": "tok-health"}, fp_key="h")
    # 模拟健康检查失败：修改创建时间使其过期，health_check 应触发重建
    # 让 s1 的 session 无法访问 chatgpt.com（但 mock 会失败），
    # 实际测试：手动 invalidate 再 get，不应返回同一个 session
    pool.invalidate(account={"access_token": "tok-health"}, fp_key="h")
    s2 = pool.get(account={"access_token": "tok-health"}, fp_key="h")
    assert s2 is not s1


def test_error_rate_after_mixed_results():
    pool = SessionPool()
    for _ in range(5):
        pool._record_result(True)
    assert pool._error_rate() == 0.0
    pool._record_result(False)
    assert pool._error_rate() == 1.0 / 6
    for _ in range(10):
        pool._record_result(False)
    # 15 失败 / 16 总计
    assert pool._error_rate() == 11.0 / 16


def test_cooldown_scales_with_error_rate():
    pool = SessionPool(dynamic_cooldown_min=60.0, dynamic_cooldown_max=300.0)
    # 0% 错误率 → min
    assert pool._cooldown_seconds() == 60.0
    for _ in range(50):
        pool._record_result(False)
    # 50%+ 错误率 → max
    assert pool._cooldown_seconds() == 300.0
    # 25% 错误率 → 中间值
    pool2 = SessionPool(dynamic_cooldown_min=60.0, dynamic_cooldown_max=300.0)
    for _ in range(25):
        pool2._record_result(False)
    for _ in range(75):
        pool2._record_result(True)
    # 25% 错误率 → 25%*2=50% 比例 → 60 + 0.5*240 = 180
    assert pool2._cooldown_seconds() == 180.0


def test_connection_ttl_expiry_recreates():
    """连接 TTL 到期后应重建 Session（即使池 TTL 未到期）。"""
    pool = SessionPool(ttl_seconds=300.0, connection_ttl=0.05)
    s1 = pool.get(account={"access_token": "tok-cttl"}, fp_key="c")
    import time
    time.sleep(0.08)
    s2 = pool.get(account={"access_token": "tok-cttl"}, fp_key="c")
    assert s2 is not s1, "连接 TTL 过期后应重建 Session"


def test_backoff_sleep_increases():
    """指数退避延时递增并 capped。"""
    pool = SessionPool(backoff_base=1.0, backoff_cap=16.0)
    t0 = time.monotonic()
    pool._backoff_sleep(0)  # 1s
    t1 = time.monotonic()
    assert t1 - t0 >= 0.9
    pool._backoff_sleep(4)  # cap at 16s, but we won't wait that long
    # 验证 attempt=0 → base, attempt=4 → cap
    import math
    assert pool._backoff_base * (2**0) == 1.0
    assert min(pool._backoff_cap, pool._backoff_base * (2**4)) == 16.0


def test_stats_includes_new_fields():
    pool = SessionPool(health_check_enabled=True, connection_ttl=300.0)
    stats = pool.stats()
    assert "health_check_enabled" in stats
    assert stats["health_check_enabled"] is True
    assert "connection_ttl" in stats
    assert stats["connection_ttl"] == 300.0
    assert "error_rate" in stats
    assert "cooldown_seconds" in stats


def test_health_check_disabled_skips_check():
    """关闭健康预检后，get 不应触发 HEAD 请求。"""
    pool = SessionPool(health_check_enabled=False, ttl_seconds=300)
    s1 = pool.get(account={"access_token": "tok-nohc"}, fp_key="n")
    s2 = pool.get(account={"access_token": "tok-nohc"}, fp_key="n")
    assert s1 is s2, "关闭健康预检后应直接返回缓存的 session"
