"""账号分组代理池（一账号一 IP）+ 每节点图片并发限制 + 养号池 测试。

覆盖 services/proxy_pool.py 的 AccountProxyPool 与
services/account_service.py 的养号接入点。全部默认关闭（config 未配置时
enabled() 为 False、返回空串/直连），不改变现有直连/全局代理行为。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from services.account_service import AccountService
from services.proxy_pool import (
    AccountProxyPool,
    MAX_PROXY_NODE_IMAGE_CONCURRENCY_LIMIT,
    ProxyNodeSelection,
    _proxy_group_node_key,
    _proxy_node_id,
    proxy_node_image_concurrency_limit,
)


def _make_config() -> object:
    class FakeConfig:
        data = {
            "proxy_groups": [
                {
                    "id": "pool-1",
                    "enabled": True,
                    "nodes": [
                        {"id": "n1", "provider": "kookeey", "url": "http://u:p@node1:1000",
                         "enabled": True, "image_concurrency_limit": 2},
                        {"id": "n2", "provider": "kookeey", "url": "http://u:p@node2:1000",
                         "enabled": True, "image_concurrency_limit": 2},
                    ],
                },
                {"id": "pool-off", "enabled": False, "nodes": [
                    {"id": "n3", "provider": "x", "url": "http://u:p@node3:1000", "enabled": True}]},
            ],
            "account_groups": [
                {"id": "grp-a", "enabled": True, "proxy_group_id": "pool-1"},
                {"id": "grp-b", "enabled": True, "proxy": "http://direct-for-b:1234"},
            ],
        }

    return FakeConfig()


# ====================================================================
# AccountProxyPool：分组解析 / 节点选择 / 并发限制
# ====================================================================


class TestAccountProxyPool:
    def setup_method(self) -> None:
        self.pool = AccountProxyPool(_make_config())

    def _account(self, group_id: str, proxy: str = "") -> dict:
        return {"access_token": "t", "group_id": group_id, "proxy": proxy, "status": "正常", "quota": 100}

    def test_enabled_with_configured_groups(self) -> None:
        assert self.pool.enabled() is True

    def test_enabled_false_when_no_config(self) -> None:
        pool = AccountProxyPool()  # 真实 config 未配置 proxy_groups
        assert pool.enabled() is False
        assert pool.get_proxy_for_account({"group_id": "x"}) == ""

    def test_account_proxy_reference_group(self) -> None:
        assert self.pool._account_proxy_reference(self._account("grp-a")) == "group:pool-1"

    def test_account_proxy_reference_direct(self) -> None:
        assert self.pool._account_proxy_reference(self._account("grp-b")) == "http://direct-for-b:1234"

    def test_account_proxy_reference_unknown_group(self) -> None:
        assert self.pool._account_proxy_reference(self._account("grp-x")) == ""

    def test_get_proxy_for_account_sticky(self) -> None:
        acc = self._account("grp-a")
        p1 = self.pool.get_proxy_for_account(acc)
        assert p1
        p2 = self.pool.get_proxy_for_account({**acc, "proxy": p1})
        assert p1 == p2  # 粘性：同账号同节点

    def test_get_proxy_for_account_direct_url_group(self) -> None:
        acc = self._account("grp-b")
        assert self.pool.get_proxy_for_account(acc) == "http://direct-for-b:1234"

    def test_get_proxy_for_account_no_group_returns_empty(self) -> None:
        assert self.pool.get_proxy_for_account({"access_token": "t", "group_id": "", "proxy": ""}) == ""

    def test_rebind_when_bound_node_removed(self) -> None:
        """绑定节点被删除后自动重选（粘性校验失效 → 换节点）。"""
        acc = self._account("grp-a")
        acc["proxy"] = "http://u:p@removed-node:1000"  # 已不在分组内
        proxy = self.pool.get_proxy_for_account(acc)
        assert proxy in {"http://u:p@node1:1000", "http://u:p@node2:1000"}

    def test_node_selection_skips_capacity_full_nodes(self) -> None:
        """占满一个节点（limit=2）后，选择应落到另一节点。"""
        sel1 = self.pool._resolve_proxy_group("pool-1")
        self.pool.acquire_image_egress(sel1.proxy_url)
        self.pool.acquire_image_egress(sel1.proxy_url)
        sel2 = self.pool._resolve_proxy_group("pool-1")
        assert sel2.node_id != sel1.node_id
        # 释放后恢复可选
        self.pool.release_image_egress(sel1.proxy_url)
        self.pool.release_image_egress(sel1.proxy_url)

    def test_acquire_image_egress_blocks_at_capacity(self) -> None:
        sel = self.pool._resolve_proxy_group("pool-1")
        self.pool.acquire_image_egress(sel.proxy_url)
        self.pool.acquire_image_egress(sel.proxy_url)  # limit=2 已占满
        try:
            self.pool.acquire_image_egress(sel.proxy_url, deadline_monotonic=time.monotonic() + 0.2)
            assert False, "should timeout"
        except TimeoutError:
            pass
        self.pool.release_image_egress(sel.proxy_url)
        self.pool.release_image_egress(sel.proxy_url)

    def test_release_image_egress_no_spurious_side_effect(self) -> None:
        """未 acquire 直接 release 不应产生负计数。"""
        sel = self.pool._resolve_proxy_group("pool-1")
        self.pool.release_image_egress(sel.proxy_url)
        self.pool.release_image_egress(sel.proxy_url)

    def test_node_selection_carries_provider(self) -> None:
        sel = self.pool._resolve_proxy_group("pool-1")
        assert sel.provider == "kookeey"
        assert isinstance(sel, ProxyNodeSelection)


# ====================================================================
# 纯函数
# ====================================================================


class TestProxyPoolHelpers:
    def test_proxy_node_image_concurrency_limit_default(self) -> None:
        assert proxy_node_image_concurrency_limit({}) == 30

    def test_proxy_node_image_concurrency_limit_explicit(self) -> None:
        assert proxy_node_image_concurrency_limit({"image_concurrency_limit": "5"}) == 5
        assert proxy_node_image_concurrency_limit({"image_concurrency": 7}) == 7
        assert proxy_node_image_concurrency_limit({"max_image_concurrency": 9}) == 9

    def test_proxy_node_image_concurrency_limit_invalid_falls_back(self) -> None:
        assert proxy_node_image_concurrency_limit({"image_concurrency_limit": "abc"}) == 30

    def test_proxy_node_image_concurrency_limit_capped(self) -> None:
        assert proxy_node_image_concurrency_limit({"image_concurrency_limit": 999999}) == MAX_PROXY_NODE_IMAGE_CONCURRENCY_LIMIT

    def test_proxy_node_id(self) -> None:
        assert _proxy_node_id({"id": "x"}, 0) == "x"
        assert _proxy_node_id({"name": "y"}, 0) == "y"
        assert _proxy_node_id({}, 2) == "node-3"

    def test_proxy_group_node_key(self) -> None:
        assert _proxy_group_node_key("g", {"id": "n"}, 0) == "group:g:n"


# ====================================================================
# 养号池接入（account_aging）
# ====================================================================


class TestAccountAging:
    def _svc(self, tmp_path):
        from services.storage.json_storage import JSONStorageBackend

        storage = JSONStorageBackend(tmp_path / "accounts.json")
        return AccountService(storage)

    def _set_aging(self, enabled: bool = True, days: int = 7, auto_apply: bool = True) -> None:
        from services.config import config

        self._orig = config.data.get("account_aging")
        config.data["account_aging"] = {
            "enabled": enabled,
            "days": days,
            "auto_apply_to_new": auto_apply,
            "behaviors": ["manual_login", "low_frequency_first_days"],
        }

    def _restore_aging(self) -> None:
        from services.config import config

        if self._orig is None:
            config.data.pop("account_aging", None)
        else:
            config.data["account_aging"] = self._orig

    def test_new_account_enters_aging(self, tmp_path) -> None:
        self._set_aging(enabled=True, days=7)
        try:
            svc = self._svc(tmp_path)
            svc.add_accounts(["new-token"])
            acct = svc.get_account("new-token")
            assert acct["status"] == "养号中"
            # 养号期不进入图片调度
            assert svc._is_image_account_available(acct) is False
        finally:
            self._restore_aging()

    def test_aging_expired_dynamic_promotion(self, tmp_path) -> None:
        self._set_aging(enabled=True, days=7)
        try:
            svc = self._svc(tmp_path)
            svc._accounts["t"] = svc._normalize_account({
                "access_token": "t", "status": "养号中", "quota": 100,
                "created_at": (datetime.now(UTC) - timedelta(days=8)).isoformat(),
            })
            acct = svc.get_account("t")
            assert svc._effective_aging_status(acct) == "正常"
            assert svc._is_image_account_available(acct) is True
        finally:
            self._restore_aging()

    def test_promote_aged_accounts_persists(self, tmp_path) -> None:
        self._set_aging(enabled=True, days=7)
        try:
            svc = self._svc(tmp_path)
            svc._accounts["t1"] = svc._normalize_account({
                "access_token": "t1", "status": "养号中", "quota": 100,
                "created_at": (datetime.now(UTC) - timedelta(days=8)).isoformat(),
            })
            svc._accounts["t2"] = svc._normalize_account({
                "access_token": "t2", "status": "养号中", "quota": 100,
                "created_at": datetime.now(UTC).isoformat(),  # 未到期
            })
            assert svc.promote_aged_accounts() == 1
            assert svc.get_account("t1")["status"] == "正常"
            assert svc.get_account("t2")["status"] == "养号中"
        finally:
            self._restore_aging()

    def test_aging_disabled_no_effect(self, tmp_path) -> None:
        self._set_aging(enabled=False)
        try:
            svc = self._svc(tmp_path)
            svc.add_accounts(["new-token"])
            assert svc.get_account("new-token")["status"] == "正常"
        finally:
            self._restore_aging()


# ====================================================================
# 代理池接入 account_service（默认关闭）
# ====================================================================


class TestAccountServiceProxyBinding:
    def _svc(self, tmp_path):
        from services.storage.json_storage import JSONStorageBackend

        storage = JSONStorageBackend(tmp_path / "accounts.json")
        return AccountService(storage)

    def test_resolve_account_proxy_disabled_returns_empty(self, tmp_path) -> None:
        svc = self._svc(tmp_path)
        acc = {"access_token": "t", "group_id": "grp-a", "proxy": "", "status": "正常", "quota": 100}
        assert svc._resolve_account_proxy("t", acc) == ""

    def test_resolve_account_proxy_binds_and_persists(self, tmp_path) -> None:
        from services.config import config
        from services.proxy_pool import account_proxy_pool

        svc = self._svc(tmp_path)
        svc._accounts["t"] = svc._normalize_account({
            "access_token": "t", "group_id": "grp-a", "proxy": "", "status": "正常", "quota": 100,
        })
        pg_orig = config.data.get("proxy_groups")
        ag_orig = config.data.get("account_groups")
        config.data["proxy_groups"] = _make_config().data["proxy_groups"]
        config.data["account_groups"] = _make_config().data["account_groups"]
        try:
            assert account_proxy_pool.enabled() is True
            proxy = svc._resolve_account_proxy("t", svc.get_account("t"))
            assert proxy
            assert svc.get_account("t")["proxy"] == proxy  # 已持久化
            # 粘性：再次解析返回同一节点
            assert svc._resolve_account_proxy("t", svc.get_account("t")) == proxy
        finally:
            if pg_orig is None:
                config.data.pop("proxy_groups", None)
            else:
                config.data["proxy_groups"] = pg_orig
            if ag_orig is None:
                config.data.pop("account_groups", None)
            else:
                config.data["account_groups"] = ag_orig

    def test_egress_hold_balanced(self, tmp_path) -> None:
        """_acquire_account_proxy_and_egress / _release_account_egress 配对平衡。"""
        svc = self._svc(tmp_path)
        svc._accounts["t"] = svc._normalize_account({
            "access_token": "t", "group_id": "grp-a", "proxy": "http://u:p@node1:1000",
            "status": "正常", "quota": 100,
        })
        # 代理池关闭时 acquire/release 均为无副作用空操作
        svc._acquire_account_proxy_and_egress("t", svc.get_account("t"))
        assert svc._egress_holds.get("t") is None
        svc._release_account_egress("t")
        assert svc._egress_holds.get("t") is None
