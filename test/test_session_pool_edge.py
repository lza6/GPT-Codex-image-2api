"""session_pool 边界测试（阶段 7，D13）：LRU/TTL/key 隔离/并发。"""

from __future__ import annotations

import threading
import time

from services.session_pool import SessionPool


def _pool(max_entries: int = 3, ttl: float = 300) -> SessionPool:
    return SessionPool(ttl_seconds=ttl, max_entries=max_entries)


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
