from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

from services.storage.base import AsyncStorageBackend, StorageBackend


class AsyncToSyncStorageBackend(StorageBackend):
    """同步→异步桥接适配器。

    包装 AsyncStorageBackend，对外暴露同步 StorageBackend 接口。
    内部将同步调用转换为异步执行（通过线程池 asyncio.run 桥接），
    使现有同步消费者（AccountService、AuthService）无需修改即可使用异步后端。

    桥接策略：
    - 在 async 上下文中调用时：提交到线程池，在线程中 asyncio.run() 执行协程
    - 在同步上下文中调用时：直接 asyncio.run() 执行协程
    """

    def __init__(self, async_backend: AsyncStorageBackend):
        self._async = async_backend
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="async_bridge",
        )

    def _run_async(self, coro: Any) -> Any:
        """将协程同步化执行（跨 sync/async 边界安全）。"""
        try:
            asyncio.get_running_loop()
            # 已在 async 上下文中 → 提交到线程池执行
            fut: concurrent.futures.Future = self._executor.submit(asyncio.run, coro)
            return fut.result()
        except RuntimeError:
            # 同步上下文 → 直接 asyncio.run
            return asyncio.run(coro)

    def load_accounts(self) -> list[dict[str, Any]]:
        return self._run_async(self._async.load_accounts())

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        return self._run_async(self._async.save_accounts(accounts))

    def load_auth_keys(self) -> list[dict[str, Any]]:
        return self._run_async(self._async.load_auth_keys())

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        return self._run_async(self._async.save_auth_keys(auth_keys))

    def health_check(self) -> dict[str, Any]:
        return self._run_async(self._async.health_check())

    def get_backend_info(self) -> dict[str, Any]:
        return self._run_async(self._async.get_backend_info())

    def close(self) -> None:
        """释放线程池资源。"""
        self._executor.shutdown(wait=False)