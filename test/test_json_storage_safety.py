"""JSON 存储安全语义回归（第七轮 B6/B7 修复的看护测试）。

- B6：原子写——并发写后文件必须是合法 JSON（tmp+replace，无半写状态）
- B7：损坏文件拒绝静默吞掉——load 抛 ValueError、health_check 报 unhealthy
"""

from __future__ import annotations

import concurrent.futures
import json

import pytest

from services.storage.json_storage import JSONStorageBackend


def _make_backend(tmp_path):
    return JSONStorageBackend(tmp_path / "accounts.json", tmp_path / "auth_keys.json")


class TestAtomicWrite:
    def test_concurrent_saves_leave_valid_json(self, tmp_path):
        backend = _make_backend(tmp_path)

        def write(i: int) -> None:
            backend.save_accounts([{"access_token": f"tok-{i % 5}", "seq": i}])

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(write, range(120)))

        data = json.loads((tmp_path / "accounts.json").read_text(encoding="utf-8"))
        assert isinstance(data, list) and data, "并发写后文件必须是合法非空 JSON 数组"
        assert "seq" in data[0]
        # tmp 文件不应残留（replace 成功后 tmp 即目标）
        assert not list(tmp_path.glob("*.tmp"))

    def test_auth_keys_atomic_write(self, tmp_path):
        backend = _make_backend(tmp_path)
        backend.save_auth_keys([{"id": "k1", "key_hash": "x" * 64}])
        data = json.loads((tmp_path / "auth_keys.json").read_text(encoding="utf-8"))
        assert data["items"][0]["id"] == "k1"
        assert not list(tmp_path.glob("*.tmp"))


class TestCorruptionFailsLoudly:
    def test_corrupted_accounts_raises(self, tmp_path):
        backend = _make_backend(tmp_path)
        (tmp_path / "accounts.json").write_text('{"半写损坏": [', encoding="utf-8")
        with pytest.raises(ValueError, match="存储文件损坏"):
            backend.load_accounts()

    def test_corrupted_auth_keys_raises(self, tmp_path):
        backend = _make_backend(tmp_path)
        (tmp_path / "auth_keys.json").write_text("not json at all", encoding="utf-8")
        with pytest.raises(ValueError, match="密钥存储文件损坏"):
            backend.load_auth_keys()

    def test_non_list_accounts_raises(self, tmp_path):
        backend = _make_backend(tmp_path)
        (tmp_path / "accounts.json").write_text('{"oops": true}', encoding="utf-8")
        with pytest.raises(ValueError, match="顶层必须是 JSON 数组"):
            backend.load_accounts()

    def test_missing_file_returns_empty(self, tmp_path):
        backend = _make_backend(tmp_path)
        assert backend.load_accounts() == []
        assert backend.load_auth_keys() == []

    def test_health_check_reports_unhealthy_on_corruption(self, tmp_path):
        backend = _make_backend(tmp_path)
        (tmp_path / "accounts.json").write_text("{损坏", encoding="utf-8")
        status = backend.health_check()
        assert status["status"] == "unhealthy", "损坏文件必须报 unhealthy（B7：不许监控全绿丢账号）"

    def test_health_check_healthy_when_valid(self, tmp_path):
        backend = _make_backend(tmp_path)
        backend.save_accounts([{"access_token": "tok-1"}])
        assert backend.health_check()["status"] == "healthy"
