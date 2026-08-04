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
