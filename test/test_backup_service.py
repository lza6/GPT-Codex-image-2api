"""备份完整性校验测试（III-06）：上传后自动比对 sha256，损坏触发告警，正常一致不告警。

边界：
- 全部 mock，不真实上传 R2（不触网）
- 备份状态文件写 tmp（monkeypatch BACKUP_STATE_FILE），不污染真实 data/backup_state.json
- tamper 场景只发布 backup.checksum_mismatch，绝不发布 backup.failure（避免双重告警）
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

import services.backup_service as bs
from services.backup_service import BackupChecksumError, BackupService

PAYLOAD = b"backup-payload-data-12345"

# 受控备份配置（encrypt=False，rotation_keep=0，上传/读回全部被 mock）
BACKUP_SETTINGS = {
    "enabled": True,
    "provider": "cloudflare_r2",
    "account_id": "acc",
    "access_key_id": "key",
    "secret_access_key": "secret",
    "bucket": "bucket",
    "prefix": "backups",
    "interval_minutes": 360,
    "rotation_keep": 0,
    "encrypt": False,
    "passphrase": "",
    "include": {},
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fake_r2_client(remote_bytes: bytes) -> MagicMock:
    """假 R2 客户端：upload_bytes 记录 key，download_bytes 返回给定远端内容。"""
    client = MagicMock()
    client.prefix = "backups"
    client.validate = MagicMock()
    client.upload_bytes = MagicMock(
        side_effect=lambda key, payload, content_type, metadata=None: {
            "key": key,
            "etag": _sha256(payload),
        }
    )
    client.download_bytes = MagicMock(return_value=remote_bytes)
    client.list_objects = MagicMock(return_value=[])
    client.delete_object = MagicMock()
    client.close = MagicMock()
    return client


@contextmanager
def _patched_env(svc: BackupService, fake_client: MagicMock):
    """组装一次 run_backup 的 mock 环境。yield publish mock（供断言告警事件）。"""
    with (
        patch.object(bs, "CloudflareR2Client", return_value=fake_client),
        patch.object(bs.config, "get_backup_settings", return_value=BACKUP_SETTINGS),
        patch.object(svc, "_build_backup_archive", return_value=PAYLOAD),
        patch("services.event_bus.event_bus.publish") as mock_publish,
    ):
        yield mock_publish


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """备份状态文件改写到 tmp，隔离真实 data/backup_state.json。"""
    import services.config as config_module

    monkeypatch.setattr(config_module, "BACKUP_STATE_FILE", tmp_path / "backup_state.json")
    return tmp_path / "backup_state.json"


def test_checksum_mismatch_raises_and_publishes_checksum_alert(isolated_state):
    """tamper 场景：上传后读回内容与本地 sha256 不一致 → 抛 BackupChecksumError + 只发 checksum 告警。"""
    tampered = PAYLOAD + b"-tampered"
    fake = _fake_r2_client(tampered)
    svc = BackupService()
    svc._running = False

    with _patched_env(svc, fake) as mock_publish:
        with pytest.raises(BackupChecksumError):
            svc.run_backup(trigger="manual")

    # 发布了 checksum 事件，未发布 backup.failure（避免双重告警）
    published_types = [call.args[0].type for call in mock_publish.call_args_list]
    assert "backup.checksum_mismatch" in published_types
    assert "backup.failure" not in published_types

    # 状态记录 mismatch + 本地 sha256 + 校验错误
    from services.config import load_backup_state

    state = load_backup_state()
    assert state["last_status"] == "error"
    assert state["last_verify_status"] == "mismatch"
    assert state["last_sha256"] == _sha256(PAYLOAD)
    assert "本地 sha256" in (state["last_verify_error"] or "")
    assert state["last_object_key"]  # 对象 key 已记录，便于人工定位并删除损坏对象


def test_checksum_match_no_alert(isolated_state):
    """正常一致：不告警，verify_status=verified，状态成功。"""
    fake = _fake_r2_client(PAYLOAD)
    svc = BackupService()
    svc._running = False

    with _patched_env(svc, fake) as mock_publish:
        result = svc.run_backup(trigger="manual")

    assert result["verify_status"] == "verified"
    assert result["sha256"] == _sha256(PAYLOAD)
    assert result["verify_remote_sha256"] == _sha256(PAYLOAD)
    assert mock_publish.call_count == 0  # 无任何事件/告警

    from services.config import load_backup_state

    state = load_backup_state()
    assert state["last_status"] == "success"
    assert state["last_verify_status"] == "verified"
    assert state["last_sha256"] == _sha256(PAYLOAD)
    assert state["last_error"] is None


def test_checksum_readback_failure_is_unavailable_not_alert(isolated_state):
    """读回失败（网络/凭证问题）：标记 unverified，不告警 checksum，备份仍成功（避免误报）。"""
    fake = _fake_r2_client(PAYLOAD)
    fake.download_bytes = MagicMock(side_effect=RuntimeError("network down"))
    svc = BackupService()
    svc._running = False

    with _patched_env(svc, fake) as mock_publish:
        result = svc.run_backup(trigger="manual")

    assert result["verify_status"] == "unavailable"
    assert mock_publish.call_count == 0  # 传输问题不触发 checksum 告警

    from services.config import load_backup_state

    state = load_backup_state()
    assert state["last_status"] == "success"
    assert state["last_verify_status"] == "unavailable"


def test_upload_failure_publishes_backup_failure_not_checksum(isolated_state):
    """上传链路失败：走既有 BACKUP_FAILURE 告警路径，不触发 checksum 告警。"""
    fake = _fake_r2_client(PAYLOAD)
    fake.upload_bytes = MagicMock(side_effect=RuntimeError("upload network error"))
    svc = BackupService()
    svc._running = False

    with _patched_env(svc, fake) as mock_publish:
        with pytest.raises(RuntimeError):
            svc.run_backup(trigger="manual")

    published_types = [call.args[0].type for call in mock_publish.call_args_list]
    assert "backup.failure" in published_types
    assert "backup.checksum_mismatch" not in published_types

    from services.config import load_backup_state

    state = load_backup_state()
    assert state["last_status"] == "error"
    assert state["last_verify_status"] is None


def test_normalize_backup_state_persists_verify_fields():
    """备份状态新增字段经归一化后保留；旧状态（缺新字段）不报错。"""
    from services.config import _normalize_backup_state

    normalized = _normalize_backup_state({
        "last_status": "error",
        "last_sha256": "abc123",
        "last_verify_status": "mismatch",
        "last_verify_error": "boom",
    })
    assert normalized["last_sha256"] == "abc123"
    assert normalized["last_verify_status"] == "mismatch"
    assert normalized["last_verify_error"] == "boom"

    old = _normalize_backup_state({"last_status": "success"})
    assert old["last_sha256"] is None
    assert old["last_verify_status"] is None
    assert old["last_verify_error"] is None


def test_checksum_event_registered_and_mapped():
    """backup.checksum_mismatch 已进 ALL_EVENTS、事件→告警映射、告警默认事件列表。"""
    from services.alert_service import DEFAULT_EVENTS
    from services.event_bus import ALL_EVENTS, BACKUP_CHECKSUM_MISMATCH
    from services.event_bus_init import _ALERT_EVENT_MAP

    assert BACKUP_CHECKSUM_MISMATCH in ALL_EVENTS
    assert _ALERT_EVENT_MAP[BACKUP_CHECKSUM_MISMATCH] == "backup_checksum_mismatch"
    assert "backup_checksum_mismatch" in DEFAULT_EVENTS


def test_checksum_alert_sent_via_webhook():
    """checksum 告警经 AlertService.send 走多通道发出（webhook 通道 + 去重指纹）。"""
    from services.alert_service import AlertService

    with patch("services.alert_service.requests.post") as mock_post:
        svc = AlertService(
            webhook_url="https://example.invalid/hook",
            events=["backup_checksum_mismatch"],
        )
        sent = svc.send("backup_checksum_mismatch", {
            "error": "tamper-detected-unique",
            "trigger": "manual",
            "object_key": "backups/backup-1.tar.gz",
        })

    assert sent is True
    body = mock_post.call_args.kwargs["json"]
    assert body["event"] == "backup_checksum_mismatch"
    assert body["error"] == "tamper-detected-unique"


def test_backups_endpoint_state_includes_verify_fields():
    """/api/backups 响应 state 包含新增校验字段（后端字段与前端类型对齐，向后兼容）。"""
    from fastapi.testclient import TestClient

    from api.app import create_app

    client = TestClient(create_app())
    key = os.environ.get("CHATGPT2API_AUTH_KEY", "chatgpt2api")
    headers = {"Authorization": f"Bearer {key}"}

    state = {
        "running": False,
        "last_status": "success",
        "last_finished_at": "2026-08-12T00:00:00Z",
        "last_object_key": "backups/backup-1.tar.gz",
        "last_sha256": "abc123",
        "last_verify_status": "verified",
        "last_verify_error": None,
    }
    with (
        patch.object(bs.backup_service, "list_backups", return_value=[]),
        patch.object(bs.backup_service, "get_settings", return_value={}),
        patch.object(bs.backup_service, "get_status", return_value=state),
    ):
        resp = client.get("/api/backups", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["state"]["last_verify_status"] == "verified"
    assert data["state"]["last_sha256"] == "abc123"
    assert data["state"]["last_verify_error"] is None
