"""3.1.1：/api/logs 支持按 account_email 过滤（模糊匹配，含过滤+分页+缺参兼容）。

数据来源：log_service 日志条目 detail.account_email 已落盘，本测试只验证
LogService.list 的过滤语义与缺参兼容。
"""

from __future__ import annotations

import json

from services.log_service import LogService


def _make_entry(entry_id: str, ts: str, summary: str, account_email: str = "", status: str = "success") -> dict:
    return {
        "id": entry_id,
        "time": ts,
        "type": "调用",
        "summary": summary,
        "detail": {"account_email": account_email, "status": status},
    }


def _write_logs(path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")


class TestLogsAccountFilter:
    def test_filter_exact_email(self, tmp_path) -> None:
        service = LogService(tmp_path / "logs.jsonl")
        _write_logs(service.path, [
            _make_entry("1", "2026-08-05 10:00:00", "call-a", account_email="user-a@example.com"),
            _make_entry("2", "2026-08-05 10:01:00", "call-b", account_email="user-b@example.com"),
            _make_entry("3", "2026-08-05 10:02:00", "call-c", account_email="user-a@example.com"),
        ])
        items = service.list(account_email="user-a@example.com")
        assert [i["summary"] for i in items] == ["call-c", "call-a"]

    def test_filter_partial_email(self, tmp_path) -> None:
        """模糊匹配：末 8 位 / 邮箱子串均可命中。"""
        service = LogService(tmp_path / "logs.jsonl")
        _write_logs(service.path, [
            _make_entry("1", "2026-08-05 10:00:00", "call-a", account_email="user-a@example.com"),
            _make_entry("2", "2026-08-05 10:01:00", "call-b", account_email="user-b@example.com"),
            _make_entry("3", "2026-08-05 10:02:00", "call-c", account_email="another@example.com"),
        ])
        items = service.list(account_email="user-a")
        assert [i["summary"] for i in items] == ["call-a"]

    def test_filter_no_match_empty(self, tmp_path) -> None:
        """account_email 无匹配记录时应返回空列表。"""
        service = LogService(tmp_path / "logs.jsonl")
        _write_logs(service.path, [
            _make_entry("1", "2026-08-05 10:00:00", "call-a", account_email="user-a@example.com"),
            _make_entry("2", "2026-08-05 10:01:00", "call-b", account_email="user-b@example.com"),
        ])
        items = service.list(account_email="ghost@example.com")
        assert items == []

    def test_filter_case_insensitive(self, tmp_path) -> None:
        """邮箱过滤大小写不敏感：大写查询应命中小写存储。"""
        service = LogService(tmp_path / "logs.jsonl")
        _write_logs(service.path, [
            _make_entry("1", "2026-08-05 10:00:00", "call-a", account_email="user-a@example.com"),
            _make_entry("2", "2026-08-05 10:01:00", "call-b", account_email="user-b@example.com"),
        ])
        items = service.list(account_email="USER-A@EXAMPLE.COM")
        assert [i["summary"] for i in items] == ["call-a"]

    def test_filter_combines_with_type_and_date(self, tmp_path) -> None:
        service = LogService(tmp_path / "logs.jsonl")
        _write_logs(service.path, [
            _make_entry("1", "2026-08-04 10:00:00", "call-a", account_email="user-a@example.com"),
            _make_entry("2", "2026-08-05 10:01:00", "call-a", account_email="user-a@example.com"),
            _make_entry("3", "2026-08-05 10:02:00", "call-b", account_email="user-a@example.com"),
        ])
        items = service.list(
            type="调用", start_date="2026-08-05", end_date="2026-08-05", account_email="user-a@example.com"
        )
        assert [i["summary"] for i in items] == ["call-b", "call-a"]

    def test_missing_param_behavior_unchanged(self, tmp_path) -> None:
        service = LogService(tmp_path / "logs.jsonl")
        _write_logs(service.path, [
            _make_entry("1", "2026-08-05 10:00:00", "call-a", account_email="user-a@example.com"),
            _make_entry("2", "2026-08-05 10:01:00", "call-b"),
        ])
        items = service.list()
        assert len(items) == 2

    def test_email_from_internal_field_matches(self, tmp_path) -> None:
        """内部字段 _account_email（响应内联）也应命中过滤。"""
        service = LogService(tmp_path / "logs.jsonl")
        entries = [
            {"id": "1", "time": "2026-08-05 10:00:00", "type": "调用", "summary": "call-a",
             "detail": {"_account_email": "user-x@example.com"}},
            {"id": "2", "time": "2026-08-05 10:01:00", "type": "调用", "summary": "call-b",
             "detail": {"account_email": "user-a@example.com"}},
        ]
        _write_logs(service.path, entries)
        items = service.list(account_email="user-x")
        assert [i["summary"] for i in items] == ["call-a"]


class TestLogsAccountFilterApi:
    """GET /api/logs?account_email=X 端到端只返回该账号记录（TestClient 真实过滤链路）。"""

    AUTH_HEADER = {"Authorization": "Bearer chatgpt2api"}

    @staticmethod
    def _make_client(tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from api import system as system_module
        from api.app import create_app
        from services import audit_service as audit_module

        service = LogService(tmp_path / "logs.jsonl")
        monkeypatch.setattr(system_module, "log_service", service)
        # 隔离审计文件：require_admin 成功埋点防污染真实 data/
        monkeypatch.setattr(audit_module.audit_service, "path", tmp_path / "audit.jsonl")
        return TestClient(create_app()), service

    def test_account_email_filter_only_matching(self, tmp_path, monkeypatch) -> None:
        """带 account_email 时只返回该账号记录，响应结构保持 items/total。"""
        from api.response_cache import response_cache

        response_cache.invalidate("/api/logs")
        client, service = self._make_client(tmp_path, monkeypatch)
        _write_logs(service.path, [
            _make_entry("1", "2026-08-05 10:00:00", "call-a", account_email="user-a@example.com"),
            _make_entry("2", "2026-08-05 10:01:00", "call-b", account_email="user-b@example.com"),
            _make_entry("3", "2026-08-05 10:02:00", "call-c", account_email="user-a@example.com"),
        ])
        resp = client.get("/api/logs", params={"account_email": "user-a@example.com"}, headers=self.AUTH_HEADER)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert all(i["detail"]["account_email"] == "user-a@example.com" for i in body["items"])

    def test_account_email_filter_case_insensitive(self, tmp_path, monkeypatch) -> None:
        """API 层大小写不敏感：大写查询命中小写存储。"""
        from api.response_cache import response_cache

        response_cache.invalidate("/api/logs")
        client, service = self._make_client(tmp_path, monkeypatch)
        _write_logs(service.path, [
            _make_entry("1", "2026-08-05 10:00:00", "call-a", account_email="user-a@example.com"),
            _make_entry("2", "2026-08-05 10:01:00", "call-b", account_email="user-b@example.com"),
        ])
        resp = client.get("/api/logs", params={"account_email": "USER-A@EXAMPLE.COM"}, headers=self.AUTH_HEADER)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["summary"] == "call-a"

    def test_account_email_filter_combined_with_type(self, tmp_path, monkeypatch) -> None:
        """account_email 与 type 组合：只返回该账号且类型匹配的记录。"""
        from api.response_cache import response_cache

        response_cache.invalidate("/api/logs")
        client, service = self._make_client(tmp_path, monkeypatch)
        _write_logs(service.path, [
            _make_entry("1", "2026-08-05 10:00:00", "call-a", account_email="user-a@example.com"),
            _make_entry("2", "2026-08-05 10:01:00", "call-b", account_email="user-a@example.com"),
            _make_entry("3", "2026-08-05 10:02:00", "call-c", account_email="user-b@example.com"),
        ])
        resp = client.get(
            "/api/logs",
            params={"account_email": "user-a@example.com", "type": "调用"},
            headers=self.AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert all(i["detail"]["account_email"] == "user-a@example.com" for i in body["items"])

    def test_account_email_filter_no_match_empty(self, tmp_path, monkeypatch) -> None:
        """无匹配账号时返回空 items 与 total=0。"""
        from api.response_cache import response_cache

        response_cache.invalidate("/api/logs")
        client, service = self._make_client(tmp_path, monkeypatch)
        _write_logs(service.path, [
            _make_entry("1", "2026-08-05 10:00:00", "call-a", account_email="user-a@example.com"),
        ])
        resp = client.get("/api/logs", params={"account_email": "ghost@example.com"}, headers=self.AUTH_HEADER)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

