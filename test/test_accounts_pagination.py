"""6.3：账号列表服务端分页——page/page_size 可选参数，向后兼容 + total 字段。

验证点：
- 不传分页参数 → 全量返回（向后兼容），仍带 total。
- page_size>0 时按 page 切片，total 为全量数。
- 越界 page 返回空 items（不崩），page<=0 归一为 1。
- 契约：响应含 items + total。
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _build_app_with_accounts(accounts: list[dict]):
    """构造带指定账号的应用（monkeypatch get_accounts_cached）。"""
    import api.accounts as accounts_module
    from api.app import create_app
    from api.response_cache import response_cache

    response_cache.invalidate()
    app = create_app()
    accounts_module.account_service.get_accounts_cached = lambda: accounts  # type: ignore[method-assign]
    return app


class TestAccountsPagination:
    def test_no_paging_returns_all_with_total(self) -> None:
        accounts = [{"access_token": f"tok-{i}", "status": "正常", "quota": 100, "success": 0, "fail": 0} for i in range(5)]
        app = _build_app_with_accounts(accounts)
        client = TestClient(app)
        resp = client.get("/api/accounts", headers={"Authorization": "Bearer chatgpt2api"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 5
        assert body["total"] == 5

    def test_page_size_slices(self) -> None:
        accounts = [{"access_token": f"tok-{i}", "status": "正常", "quota": 100, "success": 0, "fail": 0} for i in range(5)]
        app = _build_app_with_accounts(accounts)
        client = TestClient(app)
        resp = client.get("/api/accounts?page=2&page_size=2", headers={"Authorization": "Bearer chatgpt2api"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5
        # 第 2 页 = 索引 2,3
        assert body["items"][0]["access_token"] == "tok-2"
        assert body["items"][1]["access_token"] == "tok-3"

    def test_out_of_range_page_returns_empty(self) -> None:
        accounts = [{"access_token": f"tok-{i}", "status": "正常", "quota": 100, "success": 0, "fail": 0} for i in range(3)]
        app = _build_app_with_accounts(accounts)
        client = TestClient(app)
        resp = client.get("/api/accounts?page=99&page_size=10", headers={"Authorization": "Bearer chatgpt2api"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 3

    def test_page_lte_zero_normalized(self) -> None:
        accounts = [{"access_token": f"tok-{i}", "status": "正常", "quota": 100, "success": 0, "fail": 0} for i in range(3)]
        app = _build_app_with_accounts(accounts)
        client = TestClient(app)
        resp = client.get("/api/accounts?page=0&page_size=2", headers={"Authorization": "Bearer chatgpt2api"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 2  # page 归一为 1，取前 2 条

    def test_empty_accounts(self) -> None:
        app = _build_app_with_accounts([])
        client = TestClient(app)
        resp = client.get("/api/accounts?page=1&page_size=10", headers={"Authorization": "Bearer chatgpt2api"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0
