from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Column, Integer, String, Text, create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

from services.storage.base import StorageBackend

Base = declarative_base()


class AccountModel(Base):
    """账号数据模型"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    access_token = Column(String(2048), unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False)  # JSON 格式存储完整账号数据


class AuthKeyModel(Base):
    """鉴权密钥数据模型"""
    __tablename__ = "auth_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String(255), unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False)


class DatabaseStorageBackend(StorageBackend):
    """数据库存储后端（支持 SQLite、PostgreSQL、MySQL 等）"""

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
        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            echo_pool=echo_pool,
            connect_args=({
                "timeout": 15,
                "check_same_thread": False,
            } if database_url.startswith("sqlite") else {}),
        )
        # SQLite 可靠性加固（D8 收口）：WAL + busy_timeout 防多 worker 并发写损坏/锁失败
        self._apply_sqlite_pragmas(self.engine, database_url, sqlite_wal_mode, sqlite_busy_timeout_ms)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    @staticmethod
    def _apply_sqlite_pragmas(
        engine,
        database_url: str,
        wal_mode: bool,
        busy_timeout_ms: int,
    ) -> None:
        """仅对 SQLite 引擎设置 PRAGMA；其他数据库（PostgreSQL/MySQL）直接跳过。

        - journal_mode=WAL：读写不互斥，多 worker 并发写安全的标准解法；
          该模式持久化在 DB 文件头，初始化时设置一次即可
        - busy_timeout / synchronous=NORMAL：均为**每连接级** PRAGMA，
          必须经 DBAPI connect 事件在连接池每条新连接上重放，
          且参数为初始化期强转的 int（不经 SQL 文本拼接外部输入，零注入面）。
          注意：关闭 WAL 不联动关闭 synchronous=NORMAL（busy_timeout 亦始终生效），
          二者独立于 journal_mode 开关。
        """
        if not database_url.startswith("sqlite"):
            return
        timeout = max(0, int(busy_timeout_ms))

        @event.listens_for(engine, "connect")
        def _set_connection_pragmas(dbapi_conn, _connection_record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute(f"PRAGMA busy_timeout={timeout}")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

        with engine.connect() as conn:
            if wal_mode:
                conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.commit()

    def load_accounts(self) -> list[dict[str, Any]]:
        """从数据库加载账号数据"""
        session = self.Session()
        try:
            accounts = []
            for row in session.query(AccountModel).all():
                try:
                    account_data = json.loads(row.data)
                    if isinstance(account_data, dict):
                        accounts.append(account_data)
                except json.JSONDecodeError:
                    continue
            return accounts
        finally:
            session.close()

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存账号数据到数据库"""
        self._save_rows(AccountModel, accounts, "access_token")

    def load_auth_keys(self) -> list[dict[str, Any]]:
        """从数据库加载鉴权密钥数据"""
        return self._load_rows(AuthKeyModel)

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存鉴权密钥数据到数据库"""
        self._save_rows(AuthKeyModel, auth_keys, "id", "key_id")

    def _load_rows(self, model: type[AccountModel] | type[AuthKeyModel]) -> list[dict[str, Any]]:
        session = self.Session()
        try:
            items = []
            for row in session.query(model).all():
                try:
                    item_data = json.loads(row.data)
                    if isinstance(item_data, dict):
                        items.append(item_data)
                except json.JSONDecodeError:
                    continue
            return items
        finally:
            session.close()

    def _save_rows(
        self,
        model: type[AccountModel] | type[AuthKeyModel],
        items: list[dict[str, Any]],
        source_key: str,
        target_key: str | None = None,
    ) -> None:
        session = self.Session()
        try:
            key_column = target_key or source_key
            existing_rows = {
                str(getattr(row, key_column)): row
                for row in session.query(model).all()
            }
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
                    session.delete(row)

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def health_check(self) -> dict[str, Any]:
        """健康检查"""
        try:
            session = self.Session()
            try:
                # 尝试执行简单查询
                session.execute(text("SELECT 1"))
                count = session.query(AccountModel).count()
                auth_key_count = session.query(AuthKeyModel).count()
                return {
                    "status": "healthy",
                    "backend": "database",
                    "database_url": self._mask_password(self.database_url),
                    "account_count": count,
                    "auth_key_count": auth_key_count,
                }
            finally:
                session.close()
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "database",
                "error": str(e),
            }

    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        db_type = "unknown"
        if "sqlite" in self.database_url:
            db_type = "sqlite"
        elif "postgresql" in self.database_url or "postgres" in self.database_url:
            db_type = "postgresql"
        elif "mysql" in self.database_url:
            db_type = "mysql"
        
        return {
            "type": "database",
            "db_type": db_type,
            "description": f"数据库存储 ({db_type})",
            "database_url": self._mask_password(self.database_url),
        }

    @staticmethod
    def _mask_password(url: str) -> str:
        """隐藏数据库连接字符串中的密码"""
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
