"""Session 池单元测试 + 池化接线测试。

覆盖：
- SessionPool 核心行为：同 key 复用、TTL 过期重建、LRU 逐出、invalidate、线程安全、release 不拆连接
- OpenAIBackendAPI 池化接线：同账号两次实例化复用同一 Session（TLS 只握手一次的结构性前提）
"""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]


def _new_pool(ttl: float = 300.0, max_entries: int = 200):
    import sys
    sys.path.insert(0, str(ROOT_DIR))
    from services.session_pool import SessionPool
    return SessionPool(ttl_seconds=ttl, max_entries=max_entries)


def _fake_account(token: str, proxy_url: str = "") -> dict:
    return {"access_token": token, "email": f"{token[:4]}@x.com", "_test_proxy": proxy_url}


class SessionPoolCoreTests(unittest.TestCase):
    """SessionPool 核心语义。"""

    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT_DIR))

    def test_same_account_same_session(self):
        pool = _new_pool()
        with patch("services.session_pool.proxy_settings") as ps:
            ps.get_profile.return_value = type("P", (), {"proxy_url": ""})()
            ps.build_session_kwargs.return_value = {}
            s1 = pool.get(account=_fake_account("tok-a"))
            s2 = pool.get(account=_fake_account("tok-a"))
            self.assertIs(s1, s2, "同账号两次获取应复用同一 Session")

    def test_distinct_accounts_distinct_sessions(self):
        """池化 key 含账号标识：同代理不同账号不得共享 Session（防指纹/Authorization 串扰）。"""
        pool = _new_pool()
        with patch("services.session_pool.proxy_settings") as ps:
            ps.get_profile.return_value = type("P", (), {"proxy_url": "http://p:8080"})()
            ps.build_session_kwargs.return_value = {}
            s1 = pool.get(account=_fake_account("tok-a"))
            s2 = pool.get(account=_fake_account("tok-b"))
            self.assertIsNot(s1, s2, "同代理不同账号共享 Session 会覆盖 Authorization 串号")

    def test_ttl_expiry_rebuilds(self):
        pool = _new_pool(ttl=0.05)
        with patch("services.session_pool.proxy_settings") as ps:
            ps.get_profile.return_value = type("P", (), {"proxy_url": ""})()
            ps.build_session_kwargs.return_value = {}
            s1 = pool.get(account=_fake_account("tok-a"))
            import time
            time.sleep(0.06)
            s2 = pool.get(account=_fake_account("tok-a"))
            self.assertIsNot(s1, s2, "TTL 过期应重建 Session")

    def test_lru_eviction(self):
        pool = _new_pool(max_entries=3)
        with patch("services.session_pool.proxy_settings") as ps:
            ps.get_profile.return_value = type("P", (), {"proxy_url": ""})()
            ps.build_session_kwargs.return_value = {}
            sessions = [pool.get(account=_fake_account(f"tok-{i}")) for i in range(3)]
            # 第 4 个触发逐出最老的 tok-0
            pool.get(account=_fake_account("tok-3"))
            self.assertLessEqual(len(pool._sessions), 3, "超过 max_entries 应逐出最老条目")

    def test_invalidate_removes(self):
        pool = _new_pool()
        acct = _fake_account("tok-a")
        with patch("services.session_pool.proxy_settings") as ps:
            ps.get_profile.return_value = type("P", (), {"proxy_url": ""})()
            ps.build_session_kwargs.return_value = {}
            s1 = pool.get(account=acct)
            pool.invalidate(account=acct)
            s2 = pool.get(account=acct)
            self.assertIsNot(s1, s2, "invalidate 后应重建 Session")

    def test_concurrent_get_thread_safe(self):
        pool = _new_pool()
        with patch("services.session_pool.proxy_settings") as ps:
            ps.get_profile.return_value = type("P", (), {"proxy_url": ""})()
            ps.build_session_kwargs.return_value = {}
            results = []
            def worker():
                results.append(pool.get(account=_fake_account("tok-a")))
            threads = [threading.Thread(target=worker) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertTrue(all(r is results[0] for r in results), "并发获取同账号应全部复用同一 Session")

    def test_release_does_not_close_connection(self):
        """池化 Session 的 release 必须不拆底层连接，否则复用失效。"""
        pool = _new_pool()
        with patch("services.session_pool.proxy_settings") as ps:
            ps.get_profile.return_value = type("P", (), {"proxy_url": ""})()
            ps.build_session_kwargs.return_value = {}
            s = pool.get(account=_fake_account("tok-a"))
            pool.release(s)
            # release 后连接池仍持有该 session（未被关闭移除）
            self.assertIn(s, [sess for sess, _ in pool._sessions.values()],
                          "release 不得移除/关闭池化 Session")


class BackendPoolingWiringTests(unittest.TestCase):
    """OpenAIBackendAPI 应走 session_pool 复用 Session，而非每次新建。"""

    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT_DIR))

    def test_backend_reuses_pooled_session(self):
        from services.session_pool import session_pool
        from services.openai_backend_api import OpenAIBackendAPI

        token = "pool-wiring-test-token"
        account = {"access_token": token, "email": "pool@x.com"}
        with patch("services.openai_backend_api.account_service") as acct, \
             patch("services.session_pool.proxy_settings") as ps:
            acct.get_account.return_value = account
            ps.get_profile.return_value = type("P", (), {"proxy_url": ""})()
            ps.build_session_kwargs.return_value = {}
            session_pool.invalidate(account=account)
            b1 = OpenAIBackendAPI(access_token=token)
            b1.close()  # close 不得拆掉池化连接
            b2 = OpenAIBackendAPI(access_token=token)
            self.assertIs(b1.session, b2.session,
                          "同账号两次实例化应复用同一池化 Session（TLS 只握手一次）")
            session_pool.invalidate(account=account)


if __name__ == "__main__":
    unittest.main()
