"""账号标签/详情/CSV 导出端点测试：v2.31.0 补齐三个断链端点。

测试目标：
- GET /api/accounts/tags：返回去重后的 label 标签列表（含 count）
- POST /api/accounts/detail：按 token 返回账号详情；不存在 404
- POST /api/accounts/export-csv：返回 CSV；空 ids 400
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from api.app import create_app
from services.account_service import account_service

_AUTH = {"Authorization": "Bearer chatgpt2api"}


def _client() -> TestClient:
    return TestClient(create_app())


class TestAccountTags:
    def test_tags_empty_without_accounts(self, monkeypatch) -> None:
        """无账号时返回空标签列表。"""
        monkeypatch.setattr(account_service, "list_accounts", lambda: [])
        client = _client()
        r = client.get("/api/accounts/tags", headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["tags"] == []

    def test_tags_deduplicated_labels(self, monkeypatch) -> None:
        """多个账号共用同一 label 时去重并统计 count。"""
        accounts = [
            {"access_token": "t1", "label": "vip"},
            {"access_token": "t2", "label": "vip"},
            {"access_token": "t3", "label": "normal"},
            {"access_token": "t4", "label": ""},
        ]
        monkeypatch.setattr(account_service, "list_accounts", lambda: accounts)
        client = _client()
        r = client.get("/api/accounts/tags", headers=_AUTH)
        assert r.status_code == 200
        tags = r.json()["tags"]
        by_name = {t["name"]: t for t in tags}
        assert by_name["vip"]["count"] == 2
        assert by_name["normal"]["count"] == 1
        # 空 label 不进入标签列表
        assert "t4" not in by_name

    def test_tags_requires_auth(self) -> None:
        """未授权 401。"""
        client = _client()
        r = client.get("/api/accounts/tags")
        assert r.status_code == 401


class TestAccountDetail:
    def test_detail_not_found(self, monkeypatch) -> None:
        """token 不存在时 404。"""
        monkeypatch.setattr(account_service, "get_account", lambda token: None)
        client = _client()
        r = client.post("/api/accounts/detail", json={"access_token": "ghost"}, headers=_AUTH)
        assert r.status_code == 404

    def test_detail_returns_account(self, monkeypatch) -> None:
        """存在账号时返回完整字段。"""
        account = {
            "access_token": "tok-1",
            "email": "a@b.com",
            "status": "正常",
            "quota": 100,
            "type": "chatgpt",
            "label": "vip",
        }
        monkeypatch.setattr(account_service, "get_account", lambda token: account if token == "tok-1" else None)
        client = _client()
        r = client.post("/api/accounts/detail", json={"access_token": "tok-1"}, headers=_AUTH)
        assert r.status_code == 200
        item = r.json()["item"]
        assert item["email"] == "a@b.com"
        assert item["status"] == "正常"

    def test_detail_empty_token_400(self) -> None:
        """空 token 返回 400。"""
        client = _client()
        r = client.post("/api/accounts/detail", json={"access_token": ""}, headers=_AUTH)
        assert r.status_code == 400


class TestAccountExportCsv:
    def test_export_csv_empty_ids_400(self) -> None:
        """空 ids 返回 400（无导出项）。"""
        from services.account_service import account_service as _as

        original = _as.build_export_items
        _as.build_export_items = lambda ids: []
        try:
            client = _client()
            r = client.post("/api/accounts/export-csv", json={"format": "csv", "ids": []}, headers=_AUTH)
            assert r.status_code == 400
        finally:
            _as.build_export_items = original

    def test_export_csv_returns_rows(self, monkeypatch) -> None:
        """有导出项时返回 CSV，含列头。"""
        monkeypatch.setattr(
            account_service,
            "build_export_items",
            lambda ids: [
                {
                    "access_token": "tok-1",
                    "email": "a@b.com",
                    "type": "chatgpt",
                    "status": "正常",
                    "quota": 100,
                }
            ],
        )
        client = _client()
        r = client.post("/api/accounts/export-csv", json={"format": "csv", "ids": ["tok-1"]}, headers=_AUTH)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        content = r.content.decode("utf-8")
        assert "access_token" in content
        assert "tok-1" in content
