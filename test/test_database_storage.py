import json

import pytest

from services.storage.database_storage import (
    AccountModel,
    AuthKeyModel,
    DatabaseStorageBackend,
)


def _account_rows(backend: DatabaseStorageBackend) -> dict[str, AccountModel]:
    session = backend.Session()
    try:
        return {
            row.access_token: row
            for row in session.query(AccountModel).order_by(AccountModel.id).all()
        }
    finally:
        session.close()


def test_save_accounts_preserves_existing_rows_and_updates_only_changed_data(tmp_path):
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'accounts.db'}")
    backend.save_accounts(
        [
            {"access_token": "token-a", "name": "A"},
            {"access_token": "token-b", "name": "B"},
        ]
    )

    before = _account_rows(backend)
    before_ids = {token: row.id for token, row in before.items()}
    before_b_data = before["token-b"].data

    backend.save_accounts(
        [
            {"access_token": "token-b", "name": "B"},
            {"access_token": "token-a", "name": "A updated"},
            {"access_token": "token-c", "name": "C"},
        ]
    )

    after = _account_rows(backend)
    assert set(after) == {"token-a", "token-b", "token-c"}
    assert after["token-a"].id == before_ids["token-a"]
    assert after["token-b"].id == before_ids["token-b"]
    assert after["token-b"].data == before_b_data
    assert json.loads(after["token-a"].data)["name"] == "A updated"


def test_save_accounts_deletes_only_rows_missing_from_new_snapshot(tmp_path):
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'accounts.db'}")
    backend.save_accounts(
        [
            {"access_token": "token-a", "name": "A"},
            {"access_token": "token-b", "name": "B"},
        ]
    )
    before = _account_rows(backend)
    token_b_id = before["token-b"].id

    backend.save_accounts([{"access_token": "token-b", "name": "B"}])

    after = _account_rows(backend)
    assert set(after) == {"token-b"}
    assert after["token-b"].id == token_b_id


def test_save_accounts_rejects_duplicate_tokens_and_rolls_back(tmp_path):
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'accounts.db'}")
    original = {"access_token": "token-a", "name": "A"}
    backend.save_accounts([original])

    with pytest.raises(ValueError, match="Duplicate access_token") as exc_info:
        backend.save_accounts(
            [
                {"access_token": "token-a", "name": "first update"},
                {"access_token": "token-a", "name": "second update"},
            ]
        )

    assert "token-a" not in str(exc_info.value)
    assert backend.load_accounts() == [original]


def test_save_accounts_rejects_duplicate_new_tokens_and_rolls_back(tmp_path):
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'accounts.db'}")
    original = {"access_token": "token-a", "name": "A"}
    backend.save_accounts([original])

    with pytest.raises(ValueError, match="Duplicate access_token") as exc_info:
        backend.save_accounts(
            [
                original,
                {"access_token": "token-b", "name": "first new"},
                {"access_token": "token-b", "name": "second new"},
            ]
        )

    assert "token-b" not in str(exc_info.value)
    assert backend.load_accounts() == [original]


def test_save_auth_keys_preserves_ids_with_target_key_mapping(tmp_path):
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'auth-keys.db'}")
    backend.save_auth_keys(
        [
            {"id": "key-a", "name": "A"},
            {"id": "key-b", "name": "B"},
        ]
    )

    session = backend.Session()
    try:
        before_ids = {
            row.key_id: row.id
            for row in session.query(AuthKeyModel).order_by(AuthKeyModel.id).all()
        }
    finally:
        session.close()

    backend.save_auth_keys(
        [
            {"id": "key-b", "name": "B"},
            {"id": "key-a", "name": "A updated"},
            {"id": "key-c", "name": "C"},
        ]
    )

    session = backend.Session()
    try:
        after = {
            row.key_id: row
            for row in session.query(AuthKeyModel).order_by(AuthKeyModel.id).all()
        }
        assert set(after) == {"key-a", "key-b", "key-c"}
        assert after["key-a"].id == before_ids["key-a"]
        assert after["key-b"].id == before_ids["key-b"]
        assert json.loads(after["key-a"].data)["name"] == "A updated"
    finally:
        session.close()


def test_save_auth_keys_rejects_duplicate_ids_and_rolls_back(tmp_path):
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'auth-keys.db'}")
    original = {"id": "key-a", "name": "A"}
    backend.save_auth_keys([original])

    with pytest.raises(ValueError, match="Duplicate id") as exc_info:
        backend.save_auth_keys(
            [
                {"id": "key-a", "name": "first update"},
                {"id": "key-a", "name": "second update"},
            ]
        )

    assert "key-a" not in str(exc_info.value)
    assert backend.load_auth_keys() == [original]


# ---------------------------------------------------------------------------
# SQLite 可靠性加固（阶段 1：WAL + busy_timeout + synchronous）
# ---------------------------------------------------------------------------


def _pragma(backend: DatabaseStorageBackend, name: str):
    from sqlalchemy import text as sa_text

    with backend.engine.connect() as conn:
        return conn.execute(sa_text(f"PRAGMA {name}")).scalar()


def test_sqlite_wal_mode_enabled_by_default(tmp_path):
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'wal.db'}")
    assert str(_pragma(backend, "journal_mode")).lower() == "wal"
    assert int(_pragma(backend, "busy_timeout")) == 5000
    assert int(_pragma(backend, "synchronous")) == 1  # NORMAL


def test_sqlite_wal_mode_disabled_falls_back_to_default_journal(tmp_path):
    backend = DatabaseStorageBackend(
        f"sqlite:///{tmp_path / 'nowal.db'}",
        sqlite_wal_mode=False,
    )
    assert str(_pragma(backend, "journal_mode")).lower() != "wal"


def test_sqlite_busy_timeout_configurable(tmp_path):
    backend = DatabaseStorageBackend(
        f"sqlite:///{tmp_path / 'timeout.db'}",
        sqlite_busy_timeout_ms=1234,
    )
    assert int(_pragma(backend, "busy_timeout")) == 1234


def test_sqlite_pragmas_not_applied_to_postgres_url():
    """非 SQLite URL 必须 early-return：不建立任何连接、不注册任何事件监听器。

    验证方式：若 early-return 被误删，函数会对 fake engine 调用 event.listens_for，
    SQLAlchemy 会因 fake 不是合法事件目标而抛 ArgumentError（测试红）；
    若进一步走到 engine.connect()，_FakeEngine.connect 抛 AssertionError（测试红）。
    通过即证明两个危险分支均未触及。
    """
    from services.storage.database_storage import DatabaseStorageBackend as _DSB

    class _FakeEngine:
        def connect(self):
            raise AssertionError("不应为非 SQLite 引擎建立连接")

    _DSB._apply_sqlite_pragmas(_FakeEngine(), "postgresql://u:p@h/db", True, 5000)


def test_sqlite_busy_timeout_zero_fails_fast_under_contention(tmp_path):
    """busy_timeout=0（立即报错）配置下，并发写应出现 locked 类错误——运维误配置的可见性测试。"""
    import threading

    db = tmp_path / "zero-timeout.db"
    backend = DatabaseStorageBackend(
        f"sqlite:///{db}",
        sqlite_busy_timeout_ms=0,
    )
    backend.save_accounts([{"access_token": "seed", "seq": 0}])

    locked_errors: list[str] = []

    def writer(n: int) -> None:
        try:
            for i in range(10):
                backend.save_accounts([{"access_token": f"t-{n}", "seq": i}])
        except Exception as exc:  # noqa: BLE001
            if "locked" in str(exc).lower():
                locked_errors.append(str(exc))

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    # timeout=0 高并发下至少应出现过一次锁冲突（证明配置真的生效、错误真的可见）
    assert locked_errors, "busy_timeout=0 高并发下未出现任何 locked 错误，疑似配置未生效"
    backend.engine.dispose()


def test_sqlite_concurrent_writes_no_database_locked(tmp_path):
    """WAL + busy_timeout 下，两个连接并发写不应立刻 database is locked。"""
    import threading
    import time

    db = tmp_path / "concurrent.db"
    backend = DatabaseStorageBackend(f"sqlite:///{db}")
    backend.save_accounts([{"access_token": "t-0", "seq": 0}])

    errors: list[Exception] = []

    def writer(start: int) -> None:
        try:
            for i in range(start, start + 15):
                backend.save_accounts([{"access_token": f"t-{i}", "seq": i}])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n * 15,)) for n in range(4)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    elapsed = time.perf_counter() - t0

    assert not [e for e in errors if "locked" in str(e).lower()], f"出现 database locked: {errors[:3]}"
    assert elapsed < 30, "并发写整体耗时异常（疑似死锁/长时间等待）"


# ---------------------------------------------------------------------------
# 配置接入验证（services/config.py）
# ---------------------------------------------------------------------------


def test_config_sqlite_properties_defaults():
    from services.config import config

    assert config.sqlite_wal_mode is True
    assert config.sqlite_busy_timeout_ms == 5000


def test_config_sqlite_properties_env_override(monkeypatch):
    from services.config import config

    monkeypatch.setenv("CHATGPT2API_SQLITE_WAL_MODE", "0")
    monkeypatch.setenv("CHATGPT2API_SQLITE_BUSY_TIMEOUT_MS", "3000")
    assert config.sqlite_wal_mode is False
    assert config.sqlite_busy_timeout_ms == 3000


def test_config_get_exposes_sqlite_fields():
    from services.config import config

    data = config.get()
    assert data["sqlite_wal_mode"] is True
    assert data["sqlite_busy_timeout_ms"] == 5000


def test_config_schema_validation_rejects_bad_types():
    from services.config import ConfigStore

    with pytest.raises(ValueError, match="sqlite_busy_timeout_ms"):
        ConfigStore._validate_schema({"sqlite_busy_timeout_ms": "abc"})
    with pytest.raises(ValueError, match="sqlite_wal_mode"):
        ConfigStore._validate_schema({"sqlite_wal_mode": "yes"})
    with pytest.raises(ValueError, match="不能为负数"):
        ConfigStore._validate_schema({"sqlite_busy_timeout_ms": -1})


def test_sqlite_synchronous_normal_applies_to_every_pooled_connection(tmp_path):
    """synchronous/busy_timeout 是每连接级 PRAGMA，连接池每条新连接都必须生效。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'pool.db'}")

    def fresh_connection_sync_level() -> int:
        with backend.engine.connect() as conn:
            return int(conn.execute(__import__("sqlalchemy").text("PRAGMA synchronous")).scalar())

    first = fresh_connection_sync_level()
    # 归还连接后再次获取（命中池化复用），以及 dispose 后强制新建连接
    second = fresh_connection_sync_level()
    backend.engine.dispose()
    third = fresh_connection_sync_level()

    assert first == second == third == 1  # NORMAL
    assert int(_pragma(backend, "busy_timeout")) == 5000


def test_sqlite_busy_timeout_default_is_5000_explicit():
    """默认值显式回归（变异探针防逃逸）：sqlite_busy_timeout_ms 必须为 5000。"""
    from services.config import config

    assert config.sqlite_busy_timeout_ms == 5000, "默认值漂移——可能被意外修改"


# ---------------------------------------------------------------------------
# DatabaseStorageBackend 扩展覆盖：auth_keys 删除、异常数据、健康检查
# ---------------------------------------------------------------------------


def test_save_auth_keys_deletes_only_missing_rows(tmp_path):
    """save_auth_keys 应删除不在新快照中的行，保留已有行。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'auth-del.db'}")
    backend.save_auth_keys(
        [
            {"id": "key-a", "name": "A"},
            {"id": "key-b", "name": "B"},
            {"id": "key-c", "name": "C"},
        ]
    )

    backend.save_auth_keys(
        [
            {"id": "key-a", "name": "A"},
            {"id": "key-c", "name": "C updated"},
        ]
    )

    session = backend.Session()
    try:
        rows = {row.key_id: row for row in session.query(AuthKeyModel).all()}
        assert set(rows) == {"key-a", "key-c"}
        assert json.loads(rows["key-c"].data)["name"] == "C updated"
    finally:
        session.close()


def test_save_accounts_empty_items_clears_all(tmp_path):
    """传入空列表应清空所有账号数据。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'empty-acc.db'}")
    backend.save_accounts([{"access_token": "tok-a", "name": "A"}])
    backend.save_accounts([])
    assert backend.load_accounts() == []


def test_save_auth_keys_empty_items_clears_all(tmp_path):
    """传入空列表应清空所有密钥数据。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'empty-key.db'}")
    backend.save_auth_keys([{"id": "k-a", "name": "A"}])
    backend.save_auth_keys([])
    assert backend.load_auth_keys() == []


def test_save_accounts_skips_items_without_access_token(tmp_path):
    """缺少 access_token 的项应被跳过，不影响其他数据。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'skip.db'}")
    backend.save_accounts(
        [
            {"access_token": "tok-a", "name": "A"},
            {"name": "no-token"},
            {},
            {"access_token": "tok-b", "name": "B"},
        ]
    )
    loaded = backend.load_accounts()
    assert len(loaded) == 2
    tokens = {a["access_token"] for a in loaded}
    assert tokens == {"tok-a", "tok-b"}


def test_save_auth_keys_skips_items_without_id(tmp_path):
    """缺少 id 的密钥项应被跳过。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'skip-key.db'}")
    backend.save_auth_keys(
        [
            {"id": "k-a", "name": "A"},
            {"name": "no-id"},
            {},
        ]
    )
    loaded = backend.load_auth_keys()
    assert len(loaded) == 1
    assert loaded[0]["id"] == "k-a"


def test_load_accounts_corrupted_json_skips_bad_row(tmp_path):
    """数据库中某行 data 字段损坏时，load_accounts 应跳过该行不中断。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'corrupt.db'}")
    backend.save_accounts([{"access_token": "good", "name": "good"}])

    # 手动插入损坏行
    from sqlalchemy import text as sa_text

    session = backend.Session()
    try:
        session.execute(
            sa_text(
                "INSERT INTO accounts (access_token, data) VALUES (:token, :data)"
            ),
            {"token": "bad", "data": "not valid json at all"},
        )
        session.commit()
    finally:
        session.close()

    loaded = backend.load_accounts()
    assert len(loaded) == 1
    assert loaded[0]["access_token"] == "good"


def test_load_auth_keys_corrupted_json_skips_bad_row(tmp_path):
    """auth_keys 表某行 data 损坏时，load_auth_keys 应跳过该行。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'corrupt-key.db'}")
    backend.save_auth_keys([{"id": "good", "name": "good"}])

    from sqlalchemy import text as sa_text

    session = backend.Session()
    try:
        session.execute(
            sa_text("INSERT INTO auth_keys (key_id, data) VALUES (:id, :data)"),
            {"id": "bad", "data": "{{{corrupted}}"},
        )
        session.commit()
    finally:
        session.close()

    loaded = backend.load_auth_keys()
    assert len(loaded) == 1
    assert loaded[0]["id"] == "good"


def test_save_accounts_preserves_extra_fields(tmp_path):
    """保存的账号应保留额外字段（如 email, proxy 等）。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'extra.db'}")
    backend.save_accounts(
        [
            {
                "access_token": "tok-a",
                "name": "A",
                "email": "a@example.com",
                "proxy": "http://proxy:8080",
                "extra": {"nested": True},
            }
        ]
    )
    loaded = backend.load_accounts()
    assert len(loaded) == 1
    assert loaded[0]["email"] == "a@example.com"
    assert loaded[0]["proxy"] == "http://proxy:8080"
    assert loaded[0]["extra"] == {"nested": True}


def test_health_check_healthy(tmp_path):
    """健康检查应返回 healthy 状态及账号/密钥数量。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'health.db'}")
    backend.save_accounts([{"access_token": "tok-a", "name": "A"}])
    backend.save_auth_keys([{"id": "k-a", "name": "A"}])

    status = backend.health_check()
    assert status["status"] == "healthy"
    assert status["backend"] == "database"
    assert status["account_count"] == 1
    assert status["auth_key_count"] == 1
    # SQLite 无密码，database_url 应包含路径
    assert "health.db" in status["database_url"]


def test_health_check_no_tables(tmp_path):
    """空数据库健康检查应返回 healthy 且 count 为 0。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'empty-health.db'}")
    status = backend.health_check()
    assert status["status"] == "healthy"
    assert status["account_count"] == 0
    assert status["auth_key_count"] == 0


def test_get_backend_info_returns_correct_type(tmp_path):
    """get_backend_info 应正确返回存储类型为 sqlite。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'info.db'}")
    info = backend.get_backend_info()
    assert info["type"] == "database"
    assert info["db_type"] == "sqlite"


def test_save_accounts_handles_large_batch(tmp_path):
    """大批量账号保存应正确完成（验证批量 upsert 性能）。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'batch.db'}")
    accounts = [
        {"access_token": f"tok-{i}", "name": f"Account {i}", "seq": i}
        for i in range(100)
    ]
    backend.save_accounts(accounts)
    loaded = backend.load_accounts()
    assert len(loaded) == 100
    tokens = {a["access_token"] for a in loaded}
    assert tokens == {f"tok-{i}" for i in range(100)}


def test_save_accounts_removes_duplicates_in_second_batch(tmp_path):
    """第二次保存时移除已删除的账号，同时保留新添加的。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'remove-add.db'}")
    backend.save_accounts(
        [
            {"access_token": "tok-a", "name": "A"},
            {"access_token": "tok-b", "name": "B"},
            {"access_token": "tok-c", "name": "C"},
        ]
    )
    # 移除 B 和 C，添加 D
    backend.save_accounts(
        [
            {"access_token": "tok-a", "name": "A"},
            {"access_token": "tok-d", "name": "D"},
        ]
    )
    loaded = backend.load_accounts()
    assert len(loaded) == 2
    tokens = {a["access_token"] for a in loaded}
    assert tokens == {"tok-a", "tok-d"}


def test_save_auth_keys_removes_duplicates_in_second_batch(tmp_path):
    """第二次保存时移除已删除的密钥，同时保留新添加的。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'remove-add-key.db'}")
    backend.save_auth_keys(
        [
            {"id": "k-a", "name": "A"},
            {"id": "k-b", "name": "B"},
            {"id": "k-c", "name": "C"},
        ]
    )
    # 移除 B 和 C，添加 D
    backend.save_auth_keys(
        [
            {"id": "k-a", "name": "A"},
            {"id": "k-d", "name": "D"},
        ]
    )
    loaded = backend.load_auth_keys()
    assert len(loaded) == 2
    ids = {k["id"] for k in loaded}
    assert ids == {"k-a", "k-d"}
