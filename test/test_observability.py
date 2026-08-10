"""可观测性测试（D9 备份可见 + D15 优雅停机）。"""

from __future__ import annotations

import logging
from unittest.mock import patch


def test_backup_failure_logs_full_traceback(caplog, tmp_path, monkeypatch):
    """D9：备份失败时 logging.error 记录完整堆栈。"""
    # 测试隔离：备份状态文件改写到 tmp，避免污染真实 data/backup_state.json
    import services.config as config_module

    monkeypatch.setattr(config_module, "BACKUP_STATE_FILE", tmp_path / "backup_state.json")

    from services.backup_service import BackupService

    svc = BackupService()
    svc._running = False
    with patch.object(svc, "_run_backup_once", side_effect=RuntimeError("r2 upload failed")):
        with caplog.at_level(logging.ERROR):
            try:
                svc.run_backup(trigger="manual")
            except Exception:
                pass
    # 必须有 error 级日志且含异常信息
    assert any("r2 upload failed" in r.getMessage() or r.exc_info for r in caplog.records), \
        "备份失败未记录 error 日志"


def test_backup_failure_increments_prometheus_counter(tmp_path, monkeypatch):
    """D9：备份失败计数器 +1。"""
    from services import prometheus_metrics as pm

    if not hasattr(pm, "chatgpt2api_backup_failures_total"):
        raise AssertionError("chatgpt2api_backup_failures_total 指标不存在")

    before = pm.chatgpt2api_backup_failures_total._value.get()

    # 测试隔离：备份状态文件改写到 tmp，避免污染真实 data/backup_state.json
    import services.config as config_module

    monkeypatch.setattr(config_module, "BACKUP_STATE_FILE", tmp_path / "backup_state.json")

    from services.backup_service import BackupService

    svc = BackupService()
    svc._running = False
    with patch.object(svc, "_run_backup_once", side_effect=RuntimeError("boom")):
        try:
            svc.run_backup(trigger="manual")
        except Exception:
            pass
    after = pm.chatgpt2api_backup_failures_total._value.get()
    assert after == before + 1


def test_lifespan_shutdown_calls_close_all():
    """D15：lifespan shutdown 时 session_pool.close_all() 被调用。"""
    from api.app import create_app

    with patch("services.session_pool.session_pool.close_all") as mock_close:
        app = create_app()
        from fastapi.testclient import TestClient

        with TestClient(app):
            pass  # 进入并退出 lifespan
        assert mock_close.called, "lifespan shutdown 未调用 session_pool.close_all()"


def test_session_pool_close_all_closes_sessions():
    """D15：close_all 关闭所有池化 Session 并清空。"""
    from services.session_pool import SessionPool

    pool = SessionPool(ttl_seconds=300, max_entries=10, health_check_enabled=False)
    pool.get(account={"access_token": "t1"}, impersonate="chrome", verify=True, fp_key="fp1")
    pool.get(account={"access_token": "t2"}, impersonate="chrome", verify=True, fp_key="fp2")
    assert pool.stats()["pooled_sessions"] == 2
    pool.close_all()
    assert pool.stats()["pooled_sessions"] == 0
