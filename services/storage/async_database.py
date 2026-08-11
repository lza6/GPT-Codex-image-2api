from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Column, Integer, String, Text, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from services.storage.base import AsyncStorageBackend

AsyncBase = declarative_base()


class AsyncAccountModel(AsyncBase):
    """异步账号数据模型"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    access_token = Column(String(2048), unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False)  # JSON 格式存储完整账号数据


class AsyncAuthKeyModel(AsyncBase):
    """异步鉴权密钥数据模型"""
    __tablename__ = "auth_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String(255), unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False)


class AsyncDatabaseStorageBackend(AsyncStorageBackend):
    """异步数据库存储后端（使用 sqlalchemy.ext.asyncio）。

    支持 SQLite (aiosqlite) 和 PostgreSQL (asyncpg)。
    所有 I/O 操作非阻塞，不占用事件循环线程。
    """

    def __init__(
        self,
        database_url: str,
        *,
        sqlite_wal_mode: bool = True,
        sqlite_busy_timeout_ms: int = 5000,
        pool_size: int = 10,
        max_overflow: int = 5,
        pool_timeout: float = 30.0,
        pool_recycle: int = 3600,
        echo_pool: bool = False,
    ):
        self.database_url = database_url
        async_url = self._to_async_url(database_url)
        is_sqlite = async_url.startswith("sqlite")

        if is_sqlite:
            self._engine = create_async_engine(
                async_url,
                echo_pool=echo_pool,
                connect_args={
                    "timeout": 15,
                    "check_same_thread": False,
                },
            )
        else:
            self._engine = create_async_engine(
                async_url,
                pool_pre_ping=True,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_recycle=pool_recycle,
                echo_pool=echo_pool,
            )
        self._apply_sqlite_pragmas(sqlite_wal_mode, sqlite_busy_timeout_ms)
        self._AsyncSession = async_sessionmaker(self._engine, class_=AsyncSession)

    @staticmethod
    def _to_async_url(url: str) -> str:
        """将同步数据库 URL 转换为异步驱动 URL。"""
        if url.startswith("sqlite"):
            return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        if url.startswith("postgresql://") or url.startswith("postgres://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
                "postgres://", "postgresql+asyncpg://", 1
            )
        if url.startswith("mysql://"):
            return url.replace("mysql://", "mysql+aiomysql://", 1)
        return url

    def _apply_sqlite_pragmas(self, wal_mode: bool, busy_timeout_ms: int) -> None:
        """仅对 SQLite 引擎设置 PRAGMA；其他数据库跳过。"""
        if not self.database_url.startswith("sqlite"):
            return
        timeout = max(0, int(busy_timeout_ms))

        @event.listens_for(self._engine.sync_engine, "connect")
        def _set_connection_pragmas(dbapi_conn, _connection_record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute(f"PRAGMA busy_timeout={timeout}")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    async def _ensure_tables(self) -> None:
        """确保表已创建（幂等）。"""
        async with self._engine.begin() as conn:
            await conn.run_sync(AsyncBase.metadata.create_all)

    async def load_accounts(self) -> list[dict[str, Any]]:
        await self._ensure_tables()
        async with self._AsyncSession() as session:
            result = await session.execute(
                text("SELECT data FROM accounts ORDER BY id")
            )
            accounts: list[dict[str, Any]] = []
            for row in result:
                try:
                    account_data = json.loads(row[0])
                    if isinstance(account_data, dict):
                        accounts.append(account_data)
                except json.JSONDecodeError:
                    continue
            return accounts

    async def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        await self._ensure_tables()
        async with self._AsyncSession() as session:
            async with session.begin():
                await self._save_rows_async(session, AsyncAccountModel, accounts, "access_token")

    async def load_auth_keys(self) -> list[dict[str, Any]]:
        await self._ensure_tables()
        async with self._AsyncSession() as session:
            return await self._load_rows_async(session, AsyncAuthKeyModel)

    async def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        await self._ensure_tables()
        async with self._AsyncSession() as session:
            async with session.begin():
                await self._save_rows_async(session, AsyncAuthKeyModel, auth_keys, "id", "key_id")

    async def _load_rows_async(
        self,
        session: AsyncSession,
        model: type[AsyncAccountModel] | type[AsyncAuthKeyModel],
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select
        result = await session.execute(select(model))
        items: list[dict[str, Any]] = []
        for row in result.scalars().all():
            try:
                item_data = json.loads(row.data)
                if isinstance(item_data, dict):
                    items.append(item_data)
            except json.JSONDecodeError:
                continue
        return items

    async def _save_rows_async(
        self,
        session: AsyncSession,
        model: type[AsyncAccountModel] | type[AsyncAuthKeyModel],
        items: list[dict[str, Any]],
        source_key: str,
        target_key: str | None = None,
    ) -> None:
        from sqlalchemy import select

        key_column = target_key or source_key

        # 加载现有行
        result = await session.execute(select(model))
        existing_rows: dict[str, Any] = {}
        for row in result.scalars().all():
            key_value = str(getattr(row, key_column))
            existing_rows[key_value] = row

        incoming_keys: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            key_value = str(item.get(source_key) or "").strip()
            if not key_value:
                continue
            if key_value in incoming_keys:
                raise ValueError(f"Duplicate {source_key} in storage snapshot")
            incoming_keys.add(key_value)

            serialized_data = json.dumps(item, ensure_ascii=False)
            existing_row = existing_rows.get(key_value)
            if existing_row is None:
                session.add(
                    model(
                        **{key_column: key_value},
                        data=serialized_data,
                    )
                )
            elif existing_row.data != serialized_data:
                existing_row.data = serialized_data

        for key_value, row in existing_rows.items():
            if key_value not in incoming_keys:
                await session.delete(row)

    async def health_check(self) -> dict[str, Any]:
        try:
            await self._ensure_tables()
            async with self._AsyncSession() as session:
                await session.execute(text("SELECT 1"))
                result = await session.execute(
                    text("SELECT COUNT(*) FROM accounts")
                )
                count = result.scalar() or 0
                result = await session.execute(
                    text("SELECT COUNT(*) FROM auth_keys")
                )
                auth_key_count = result.scalar() or 0
                return {
                    "status": "healthy",
                    "backend": "async_database",
                    "database_url": self._mask_password(self.database_url),
                    "account_count": count,
                    "auth_key_count": auth_key_count,
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "async_database",
                "error": str(e),
            }

    async def get_backend_info(self) -> dict[str, Any]:
        db_type = "unknown"
        if "sqlite" in self.database_url:
            db_type = "sqlite"
        elif "postgresql" in self.database_url or "postgres" in self.database_url:
            db_type = "postgresql"
        elif "mysql" in self.database_url:
            db_type = "mysql"

        return {
            "type": "async_database",
            "db_type": db_type,
            "description": f"异步数据库存储 ({db_type})",
            "database_url": self._mask_password(self.database_url),
        }

    @staticmethod
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

    async def dispose(self) -> None:
        """释放引擎资源（测试/关闭时调用）。"""
        await self._engine.dispose()