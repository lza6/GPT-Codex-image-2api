"""ProxyPool 粘性选择 + 免费池清理单元测试。

覆盖：
  - select_sticky 同 key 复用 / 节点失效重绑 / 池空 None / 不同 key 不同节点
  - 粘性绑定 save→load 持久化
  - prune_free 只动 source==free，不误伤 manual/kookeey/import
"""
from __future__ import annotations

import time

from services.proxy_pool import ProxyPool


def _add_free(pool: ProxyPool, url: str, host: str = "") -> None:
    pool.add_structured({
        "url": url,
        "host": host or url.split("://")[1].split(":")[0],
        "port": 1000,
        "protocol": "http",
        "source": "free",
    }, weight=1)


class TestSelectSticky:
    def _pool(self) -> ProxyPool:
        pool = ProxyPool()  # persist_path=None，不落盘
        for i in range(3):
            _add_free(pool, f"http://node{i + 1}:1000")
        return pool

    def test_same_key_reuses_same_node(self) -> None:
        pool = self._pool()
        e1 = pool.select_sticky("a@x.com")
        e2 = pool.select_sticky("a@x.com")
        assert e1 is not None and e2 is not None
        assert e1.url == e2.url
        assert e1 is e2  # 同一 entry 对象

    def test_key_normalized_case_insensitive(self) -> None:
        pool = self._pool()
        e1 = pool.select_sticky("A@X.com")
        e2 = pool.select_sticky("  a@x.com ")
        assert e1 is not None and e2 is not None
        assert e1.url == e2.url

    def test_different_keys_different_nodes(self) -> None:
        pool = self._pool()
        e1 = pool.select_sticky("a@x.com")
        e2 = pool.select_sticky("b@x.com")
        assert e1 is not None and e2 is not None
        assert e1.url != e2.url

    def test_empty_pool_returns_none(self) -> None:
        pool = ProxyPool()
        assert pool.select_sticky("a@x.com") is None

    def test_rebind_when_bound_node_fails(self) -> None:
        pool = self._pool()
        e1 = pool.select_sticky("a@x.com")
        assert e1 is not None
        # 让绑定节点失效
        pool._proxies[e1.url].healthy = False
        pool._rebuild_healthy()
        e2 = pool.select_sticky("a@x.com")
        assert e2 is not None
        assert e2.url != e1.url
        # 重绑后再次调用仍稳定
        e3 = pool.select_sticky("a@x.com")
        assert e3 is not None and e3.url == e2.url

    def test_round_robin_distributes_across_keys(self) -> None:
        pool = self._pool()
        picked = {pool.select_sticky(f"user{i}@x.com").url for i in range(9)}
        assert len(picked) == 3  # 三个节点都被用到


class TestStickyPersistence:
    def test_sticky_save_load_roundtrip(self, tmp_path) -> None:
        path = tmp_path / "proxies.json"
        pool = ProxyPool(persist_path=path)
        _add_free(pool, "http://node1:1000")
        e1 = pool.select_sticky("a@x.com")
        assert e1 is not None

        # 重新加载（模拟重启）
        pool2 = ProxyPool(persist_path=path)
        e2 = pool2.select_sticky("a@x.com")
        assert e2 is not None
        assert e2.url == e1.url

    def test_sticky_binding_survives_save(self) -> None:
        pool = ProxyPool()
        _add_free(pool, "http://node1:1000")
        e1 = pool.select_sticky("a@x.com")
        assert e1 is not None
        assert pool._sticky.get("a@x.com") == e1.url


class TestPruneFree:
    def _mixed_pool(self) -> ProxyPool:
        pool = ProxyPool()
        _add_free(pool, "http://free1:1000")
        _add_free(pool, "http://free2:1000")
        for source, host in (("manual", "m1"), ("kookeey", "k1"), ("import", "i1")):
            pool.add_structured({
                "url": f"http://{host}:1000", "host": host, "port": 1000,
                "protocol": "http", "source": source,
            }, weight=1)
        return pool

    def test_prune_free_removes_unhealthy_free_only(self) -> None:
        pool = self._mixed_pool()
        pool._proxies["http://free2:1000"].healthy = False
        pool._rebuild_healthy()
        removed = pool.prune_free()
        assert removed == 1
        urls = {e["url"] for e in pool.get_all()}
        assert "http://free1:1000" in urls
        assert "http://free2:1000" not in urls
        # manual/kookeey/import 不误伤
        assert "http://m1:1000" in urls
        assert "http://k1:1000" in urls
        assert "http://i1:1000" in urls

    def test_prune_free_max_total(self) -> None:
        pool = ProxyPool()
        for i in range(5):
            _add_free(pool, f"http://free{i}:1000")
        pool.add_structured({
            "url": "http://manual:1000", "host": "manual", "port": 1000,
            "protocol": "http", "source": "manual",
        }, weight=1)
        removed = pool.prune_free(max_total=3)
        assert removed == 2
        free_urls = [e["url"] for e in pool.get_all() if e["source"] == "free"]
        assert len(free_urls) == 3
        # manual 条目不受 max_total 影响
        assert any(e["url"] == "http://manual:1000" for e in pool.get_all())

    def test_prune_free_keep_alive(self) -> None:
        pool = ProxyPool()
        _add_free(pool, "http://free1:1000")
        _add_free(pool, "http://free2:1000")
        # last_check 默认 0 → 不算超龄
        assert pool.prune_free(keep_alive=60) == 0
        # 标记超龄
        pool._proxies["http://free1:1000"].last_check = time.time() - 3600
        assert pool.prune_free(keep_alive=60) == 1

    def test_prune_free_no_free_noop(self) -> None:
        pool = ProxyPool()
        pool.add_structured({
            "url": "http://manual:1000", "host": "manual", "port": 1000,
            "protocol": "http", "source": "manual",
        }, weight=1)
        assert pool.prune_free(max_total=0) == 0
        assert len(pool.get_all()) == 1
