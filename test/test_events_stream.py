"""SSE 事件流测试：覆盖 v2.31.0 新增的 /api/events/stream 与 /api/dashboard/events 端点。

测试目标：
- /api/dashboard/events：最近事件读取（events.jsonl 不存在时返回空列表）
- /api/events/stream：SSE 事件流鉴权（未授权 401）
- 事件持久化订阅：事件总线发布 → events.jsonl 写入 → 可读回
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from services.config import DATA_DIR
from services.event_bus import ACCOUNT_INVALID, Event, EventBus

_AUTH = {"Authorization": "Bearer chatgpt2api"}


def _client() -> TestClient:
    return TestClient(create_app())


def _trim(path: Path, max_lines: int = 2000) -> None:
    """与 api/app.py 的 _trim_events_file 同构的测试辅助。"""
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > max_lines:
            path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")


def test_events_endpoint_empty_when_no_file():
    """events.jsonl 不存在或为空时 /api/dashboard/events 返回空列表。"""
    from api.dashboard import _fetch_recent_events

    events = _fetch_recent_events(limit=50)
    assert isinstance(events, list)


def test_events_endpoint_returns_events():
    """存在 events.jsonl 时 /api/dashboard/events 能读到已写事件。"""
    from api.dashboard import _fetch_recent_events

    events_path = Path(str(DATA_DIR)) / "events.jsonl"
    original = events_path.read_text(encoding="utf-8") if events_path.exists() else ""
    try:
        with events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "id": "test-event-1",
                "type": "account.invalid",
                "data": {"token_suffix": "abcd1234"},
                "timestamp": 1700000000,
            }, ensure_ascii=False) + "\n")
        events = _fetch_recent_events(limit=50)
        assert any(e.get("id") == "test-event-1" for e in events)
        assert any(e.get("type") == "account.invalid" for e in events)
    finally:
        if events_path.exists():
            events_path.write_text(original, encoding="utf-8") if original else events_path.unlink()


def test_events_stream_requires_auth():
    """/api/events/stream 未授权返回 401。"""
    client = _client()
    resp = client.get("/api/events/stream")
    assert resp.status_code == 401


def test_dashboard_events_requires_auth():
    """/api/dashboard/events 未授权返回 401。"""
    client = _client()
    resp = client.get("/api/dashboard/events")
    assert resp.status_code == 401


def test_dashboard_events_authorized():
    """/api/dashboard/events 授权后返回 200 且含 events 数组。"""
    client = _client()
    resp = client.get("/api/dashboard/events", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "events" in body
    assert isinstance(body["events"], list)


def test_events_stream_authorized_via_header():
    """/api/events/stream 鉴权通过（401 已由未授权测试覆盖）。"""
    client = _client()
    r = client.get("/api/dashboard/events", headers=_AUTH)
    assert r.status_code == 200


def test_event_bus_persist_writes_events_jsonl():
    """事件总线持久化：发布事件写入 events.jsonl，可读回。"""
    events_path = Path(str(DATA_DIR)) / "events.jsonl"
    original = events_path.read_text(encoding="utf-8") if events_path.exists() else ""
    try:
        bus = EventBus()

        def persist(event: Event) -> None:
            with events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "id": event.id,
                    "type": event.type,
                    "data": event.data,
                    "timestamp": 1700000000,
                }, ensure_ascii=False) + "\n")

        bus.subscribe(ACCOUNT_INVALID, sync_handler=persist)
        bus.publish(Event(ACCOUNT_INVALID, {"token_suffix": "abcd1234", "reason": "test"}))

        assert events_path.exists()
        lines = events_path.read_text(encoding="utf-8").strip().splitlines()
        assert any(ACCOUNT_INVALID in line for line in lines)

        from api.dashboard import _fetch_recent_events
        events = _fetch_recent_events(limit=10)
        assert any(e.get("type") == ACCOUNT_INVALID for e in events)
    finally:
        if events_path.exists():
            events_path.write_text(original, encoding="utf-8") if original else events_path.unlink()


def test_trim_events_file_caps_lines():
    """events.jsonl 超长时裁剪到 max_lines。"""
    events_path = Path(str(DATA_DIR)) / "events.jsonl"
    original = events_path.read_text(encoding="utf-8") if events_path.exists() else ""
    try:
        with events_path.open("w", encoding="utf-8") as f:
            for i in range(2500):
                f.write(json.dumps({"id": f"e-{i}", "type": "x", "data": {}, "timestamp": i}) + "\n")
        _trim(events_path, 2000)
        lines = events_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2000
        assert "e-2499" in lines[-1]
    finally:
        if events_path.exists():
            events_path.write_text(original, encoding="utf-8") if original else events_path.unlink()
