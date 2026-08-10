"""API Key 管理端点测试（/api/auth/keys）。

覆盖：CRUD + 撤销 + 鉴权 + 过期时间字段。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from services.config import config


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.auth_key}"}


def test_create_key(client: TestClient) -> None:
    import uuid
    name = f"test key {uuid.uuid4().hex[:8]}"
    resp = client.post("/api/auth/keys", json={
        "name": name,
        "role": "user",
        "quota": {"daily_requests": 100, "reset_cycle": "daily"},
    }, headers=_auth_header())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "item" in data
    assert "key" in data
    assert data["item"]["name"] == name
    assert data["item"]["quota"]["daily_requests"] == 100


def test_list_keys(client: TestClient) -> None:
    resp = client.get("/api/auth/keys", headers=_auth_header())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "items" in data
    admin_keys = [k for k in data["items"] if k["role"] == "admin"]
    assert len(admin_keys) >= 1


def test_update_key(client: TestClient) -> None:
    import uuid
    name = f"upd {uuid.uuid4().hex[:8]}"
    resp = client.post("/api/auth/keys", json={"name": name, "role": "user"}, headers=_auth_header())
    item = resp.json()["item"]
    key_id = item["id"]
    resp = client.post(f"/api/auth/keys/{key_id}", json={"enabled": False}, headers=_auth_header())
    assert resp.status_code == 200, resp.text
    assert resp.json()["item"]["enabled"] is False


def test_delete_key(client: TestClient) -> None:
    import uuid
    name = f"del {uuid.uuid4().hex[:8]}"
    resp = client.post("/api/auth/keys", json={"name": name, "role": "user"}, headers=_auth_header())
    key_id = resp.json()["item"]["id"]
    resp = client.delete(f"/api/auth/keys/{key_id}", headers=_auth_header())
    assert resp.status_code == 200, resp.text
    resp = client.get("/api/auth/keys", headers=_auth_header())
    ids = [k["id"] for k in resp.json()["items"]]
    assert key_id not in ids


def test_revoke_key(client: TestClient) -> None:
    import uuid
    name = f"rev {uuid.uuid4().hex[:8]}"
    resp = client.post("/api/auth/keys", json={"name": name, "role": "user"}, headers=_auth_header())
    key_id = resp.json()["item"]["id"]
    resp = client.post(f"/api/auth/keys/{key_id}/revoke", headers=_auth_header())
    assert resp.status_code == 200, resp.text
    assert resp.json()["item"]["enabled"] is False


def test_create_key_unauthorized(client: TestClient) -> None:
    resp = client.post("/api/auth/keys", json={"name": "x"})
    assert resp.status_code == 401


def test_create_key_expires_at(client: TestClient) -> None:
    import uuid
    name = f"exp {uuid.uuid4().hex[:8]}"
    resp = client.post("/api/auth/keys", json={
        "name": name,
        "role": "user",
        "expires_at": "2027-06-15",
    }, headers=_auth_header())
    assert resp.status_code == 200, resp.text
    assert resp.json()["item"]["expires_at"] == "2027-06-15"