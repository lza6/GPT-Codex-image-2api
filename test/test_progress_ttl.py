"""进度字典 TTL 惰性淘汰测试（阶段 2，D5 收口）。

红线：进度记录写入 TTL 内可读；超过 TTL 后读取返回 None 且被惰性淘汰；
读写线程安全；TTL 可经构造参数配置。
"""

from __future__ import annotations

import threading
import time

import pytest

from services.account_service import AccountService
from services.storage.json_storage import JSONStorageBackend


def _make_service(tmp_path, ttl: float = 3600.0) -> AccountService:
    backend = JSONStorageBackend(tmp_path / "accounts.json")
    return AccountService(backend, progress_ttl_seconds=ttl)


def test_progress_readable_within_ttl(tmp_path):
    svc = _make_service(tmp_path, ttl=3600)
    svc.init_refresh_progress("p1", total=3)
    progress = svc.get_refresh_progress("p1")
    assert progress is not None
    assert progress["total"] == 3
    assert progress["done"] is False


def test_progress_evicted_after_ttl(tmp_path):
    svc = _make_service(tmp_path, ttl=0.05)
    svc.init_refresh_progress("p-old", total=2)
    assert svc.get_refresh_progress("p-old") is not None
    time.sleep(0.08)
    assert svc.get_refresh_progress("p-old") is None
    # 惰性淘汰后字典内也不应残留
    assert "p-old" not in svc._refresh_progress


def test_relogin_progress_evicted_after_ttl(tmp_path):
    svc = _make_service(tmp_path, ttl=0.05)
    svc.init_relogin_progress("r1", total=1)
    time.sleep(0.08)
    assert svc.get_relogin_progress("r1") is None
    assert "r1" not in svc._relogin_progress


def test_unbounded_growth_capped_by_ttl(tmp_path):
    """模拟长时间运行：大量进度记录在 TTL 过期后被惰性清理，字典不无界增长。"""
    svc = _make_service(tmp_path, ttl=0.05)
    for i in range(200):
        svc.init_refresh_progress(f"bulk-{i}", total=1)
    time.sleep(0.08)
    # 触发一次惰性淘汰（任意读写均可）
    assert svc.get_refresh_progress("trigger") is None
    assert len(svc._refresh_progress) == 0


def test_concurrent_progress_access_thread_safe(tmp_path):
    svc = _make_service(tmp_path, ttl=3600)
    errors: list[Exception] = []

    def worker(n: int) -> None:
        try:
            for i in range(50):
                pid = f"t{n}-{i}"
                svc.init_refresh_progress(pid, total=1)
                svc.update_refresh_progress(pid, "nonexistent-token")
                svc.finish_refresh_progress(pid, result={"ok": True})
                svc.get_refresh_progress(pid)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert not errors, f"并发读写出现异常: {errors[:3]}"


def test_ttl_configurable_via_constructor(tmp_path):
    svc = _make_service(tmp_path, ttl=7200)
    assert svc.progress_ttl_seconds == 7200


def test_config_property_progress_ttl_seconds():
    from services.config import config

    assert config.progress_ttl_seconds == 3600


def test_config_progress_ttl_env_override(monkeypatch):
    from services.config import config

    monkeypatch.setenv("CHATGPT2API_PROGRESS_TTL_SECONDS", "1800")
    assert config.progress_ttl_seconds == 1800


def test_config_get_exposes_progress_ttl():
    from services.config import config

    assert config.get()["progress_ttl_seconds"] == 3600


def test_config_schema_validation_progress_ttl():
    from services.config import ConfigStore

    with pytest.raises(ValueError, match="progress_ttl_seconds"):
        ConfigStore._validate_schema({"progress_ttl_seconds": "abc"})
    with pytest.raises(ValueError, match="不能为负数"):
        ConfigStore._validate_schema({"progress_ttl_seconds": -1})


def test_progress_dicts_are_instance_isolated(tmp_path):
    """实例属性字典：短 TTL 实例的 prune 不得误删长 TTL 实例的记录（独立审查 Critical 1 防回归）。"""
    long_svc = _make_service(tmp_path / "long", ttl=3600)
    short_svc = _make_service(tmp_path / "short", ttl=0.05)
    long_svc.init_refresh_progress("shared-target", total=1)
    time.sleep(0.08)
    # 短 TTL 实例触发自己的 prune，不影响长 TTL 实例的字典
    short_svc.init_refresh_progress("short-lived", total=1)
    time.sleep(0.08)
    # 短 TTL 实例自己过期被清，但长 TTL 实例的记录不受影响
    assert short_svc.get_refresh_progress("short-lived") is None
    assert long_svc.get_refresh_progress("shared-target") is not None
