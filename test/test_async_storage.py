"""异步存储后端测试（v3.0 异步化存储层）。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from services.storage.async_bridge import AsyncToSyncStorageBackend
from services.storage.async_database import AsyncDatabaseStorageBackend


@pytest.fixture
def async_backend():
    """创建异步内存 SQLite 后端。"""
    backend = AsyncDatabaseStorageBackend("sqlite:///:memory:")
    yield backend
    asyncio.run(backend.dispose())


@pytest.fixture
def bridge_backend(async_backend):
    """创建桥接适配器包装的同步后端。"""
    return AsyncToSyncStorageBackend(async_backend)


@pytest.mark.asyncio
class TestAsyncDatabaseStorageBackend:
    """异步数据库存储后端单元测试。"""

    _SAMPLE_ACCOUNTS: list[dict[str, Any]] = [
        {"access_token": "tok1", "email": "a@b.com", "quota": 100, "status": "正常"},
        {"access_token": "tok2", "email": "c@d.com", "quota": 50, "status": "正常"},
    ]

    _SAMPLE_KEYS: list[dict[str, Any]] = [
        {"id": "key1", "role": "admin", "key_hash": "abc123"},
        {"id": "key2", "role": "user", "key_hash": "def456"},
    ]

    async def test_save_and_load_accounts(self, async_backend):
        """保存账号后能正确加载。"""
        await async_backend.save_accounts(self._SAMPLE_ACCOUNTS)
        loaded = await async_backend.load_accounts()
        assert len(loaded) == 2
        assert loaded[0]["access_token"] == "tok1"
        assert loaded[1]["access_token"] == "tok2"

    async def test_overwrite_removes_stale_entries(self, async_backend):
        """全量保存模式下，旧数据中被移除的条目应被删除。"""
        await async_backend.save_accounts(self._SAMPLE_ACCOUNTS)
        await async_backend.save_accounts([
            {"access_token": "tok1", "email": "a@b.com", "quota": 200},
        ])
        loaded = await async_backend.load_accounts()
        assert len(loaded) == 1
        assert loaded[0]["access_token"] == "tok1"
        assert loaded[0]["quota"] == 200

    async def test_save_and_load_auth_keys(self, async_backend):
        """保存鉴权密钥后能正确加载。"""
        await async_backend.save_auth_keys(self._SAMPLE_KEYS)
        loaded = await async_backend.load_auth_keys()
        assert len(loaded) == 2
        keys = {k["id"]: k for k in loaded}
        assert keys["key1"]["key_hash"] == "abc123"
        assert keys["key2"]["key_hash"] == "def456"

    async def test_health_check(self, async_backend):
        """健康检查返回正常状态。"""
        health = await async_backend.health_check()
        assert health["status"] == "healthy"
        assert health["backend"] == "async_database"
        assert health["account_count"] == 0
        assert health["auth_key_count"] == 0

    async def test_health_check_with_data(self, async_backend):
        """健康检查反映实际数据量。"""
        await async_backend.save_accounts(self._SAMPLE_ACCOUNTS)
        await async_backend.save_auth_keys(self._SAMPLE_KEYS)
        health = await async_backend.health_check()
        assert health["account_count"] == 2
        assert health["auth_key_count"] == 2

    async def test_get_backend_info(self, async_backend):
        """后端信息返回正确类型。"""
        info = await async_backend.get_backend_info()
        assert info["type"] == "async_database"
        assert info["db_type"] == "sqlite"

    async def test_duplicate_key_raises(self, async_backend):
        """重复 key 在单次保存中应报错。"""
        with pytest.raises(ValueError, match="Duplicate"):
            await async_backend.save_accounts([
                {"access_token": "tok1"},
                {"access_token": "tok1"},  # 重复
            ])

    async def test_empty_accounts(self, async_backend):
        """空账号列表保存再加载应为空列表。"""
        await async_backend.save_accounts([])
        loaded = await async_backend.load_accounts()
        assert loaded == []

    async def test_corrupted_json_skipped(self, async_backend):
        """损坏的 JSON 数据应跳过不报错。"""
        # 直接插入损坏数据
        from sqlalchemy import text
        async with async_backend._engine.begin() as conn:
            await conn.run_sync(AsyncAccountModel.metadata.create_all)
            await conn.execute(
                text("INSERT INTO accounts (access_token, data) VALUES (:k, :d)"),
                {"k": "bad", "d": "{invalid json}"},
            )
        loaded = await async_backend.load_accounts()
        assert len(loaded) == 0

    async def test_update_existing_account(self, async_backend):
        """更新已有账号的数据。"""
        await async_backend.save_accounts(self._SAMPLE_ACCOUNTS)
        # 只更新一个账号
        await async_backend.save_accounts([
            {"access_token": "tok1", "email": "a@b.com", "quota": 999},
        ])
        loaded = await async_backend.load_accounts()
        assert len(loaded) == 1
        assert loaded[0]["quota"] == 999


class TestAsyncBridge:
    """同步桥接适配器测试。"""

    def test_bridge_load_accounts(self, bridge_backend):
        """通过桥接加载账号。"""
        bridge_backend.save_accounts([
            {"access_token": "tok1", "email": "a@b.com"},
        ])
        loaded = bridge_backend.load_accounts()
        assert len(loaded) == 1

    def test_bridge_load_auth_keys(self, bridge_backend):
        """通过桥接加载鉴权密钥。"""
        bridge_backend.save_auth_keys([
            {"id": "k1", "role": "admin", "key_hash": "abc"},
        ])
        loaded = bridge_backend.load_auth_keys()
        assert len(loaded) == 1

    def test_bridge_health_check(self, bridge_backend):
        """通过桥接健康检查。"""
        health = bridge_backend.health_check()
        assert health["status"] == "healthy"

    def test_bridge_backend_info(self, bridge_backend):
        """通过桥接后端信息。"""
        info = bridge_backend.get_backend_info()
        assert info["type"] == "async_database"


# 为兼容非 asyncio 上下文，加载 AsyncAccountModel（仅用于损坏数据测试）
from services.storage.async_database import AsyncAccountModel as AsyncAccountModel  # noqa: E402,F811