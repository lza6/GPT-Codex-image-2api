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
