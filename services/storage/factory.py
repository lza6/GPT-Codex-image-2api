from __future__ import annotations

import os
from pathlib import Path

from services.config import config
from services.storage.base import StorageBackend
from services.storage.database_storage import DatabaseStorageBackend
from services.storage.git_storage import GitStorageBackend
from services.storage.json_storage import JSONStorageBackend


def create_storage_backend(data_dir: Path) -> StorageBackend:
    """
    根据环境变量创建存储后端

    环境变量：
    - STORAGE_BACKEND: json|sqlite|postgres|git (默认 json)
    - DATABASE_URL: 数据库连接字符串 (用于 sqlite/postgres)
    - STORAGE_ASYNC_ENABLED: true|false (默认 false，启用异步数据库后端)
    - GIT_REPO_URL: Git 仓库地址 (用于 git)
    - GIT_TOKEN: Git 访问令牌 (用于 git)
    - GIT_BRANCH: Git 分支 (默认 main)
    - GIT_FILE_PATH: Git 仓库中的文件路径 (默认 accounts.json)
    """
    backend_type = os.getenv("STORAGE_BACKEND", "json").lower().strip()
    async_enabled = _is_async_enabled()

    print(f"[storage] Initializing storage backend: {backend_type}")
    if async_enabled and backend_type in ("sqlite", "postgres", "postgresql", "mysql", "database"):
        print(f"[storage] Async mode enabled for {backend_type}")

    if backend_type == "json":
        file_path = data_dir / "accounts.json"
        auth_keys_path = data_dir / "auth_keys.json"
        print(f"[storage] Using JSON storage: {file_path}")
        return JSONStorageBackend(file_path, auth_keys_path)

    elif backend_type in ("sqlite", "postgres", "postgresql", "mysql", "database"):
        database_url = os.getenv("DATABASE_URL", "").strip()

        if not database_url:
            database_url = f"sqlite:///{data_dir / 'accounts.db'}"
            print(f"[storage] No DATABASE_URL provided, using local SQLite: {database_url}")
        else:
            print(f"[storage] Using database storage: {_mask_password(database_url)}")

        if async_enabled:
            from services.storage.async_bridge import AsyncToSyncStorageBackend
            from services.storage.async_database import AsyncDatabaseStorageBackend

            async_backend = AsyncDatabaseStorageBackend(
                database_url,
                sqlite_wal_mode=config.sqlite_wal_mode,
                sqlite_busy_timeout_ms=config.sqlite_busy_timeout_ms,
            )
            return AsyncToSyncStorageBackend(async_backend)
        else:
            return DatabaseStorageBackend(
                database_url,
                sqlite_wal_mode=config.sqlite_wal_mode,
                sqlite_busy_timeout_ms=config.sqlite_busy_timeout_ms,
            )

    elif backend_type == "git":
        repo_url = os.getenv("GIT_REPO_URL", "").strip()
        token = os.getenv("GIT_TOKEN", "").strip()
        branch = os.getenv("GIT_BRANCH", "main").strip()
        file_path = os.getenv("GIT_FILE_PATH", "accounts.json").strip()
        auth_keys_file_path = os.getenv("GIT_AUTH_KEYS_FILE_PATH", "auth_keys.json").strip()

        if not repo_url:
            raise ValueError(
                "GIT_REPO_URL is required when using git storage backend. "
                "Please set GIT_REPO_URL environment variable."
            )

        print(f"[storage] Using Git storage: {_mask_token(repo_url)}, branch: {branch}, file: {file_path}")

        cache_dir = data_dir / "git_cache"
        return GitStorageBackend(
            repo_url=repo_url,
            token=token,
            branch=branch,
            file_path=file_path,
            auth_keys_file_path=auth_keys_file_path,
            local_cache_dir=cache_dir,
        )

    else:
        raise ValueError(
            f"Unknown storage backend: {backend_type}. "
            f"Supported backends: json, sqlite, postgres, git"
        )


def _is_async_enabled() -> bool:
    """检查是否启用异步存储后端。"""
    env_val = os.getenv("STORAGE_ASYNC_ENABLED")
    if env_val is not None:
        return env_val.strip().lower() in ("1", "true", "yes", "on")
    return bool(config.storage_async_enabled)


def _mask_password(url: str) -> str:
    if "://" not in url:
        return url
    try:
        protocol, rest = url.split("://", 1)
        if "@" in rest:
            credentials, host = rest.split("@", 1)
            if ":" in credentials:
                username, _ = credentials.split(":", 1)
                return f"{protocol}://{username}:****@{host}"
        return url
    except Exception:
        return url


def _mask_token(url: str) -> str:
    if "@" in url and "://" in url:
        protocol, rest = url.split("://", 1)
        if "@" in rest:
            _, host = rest.split("@", 1)
            return f"{protocol}://****@{host}"
    return url