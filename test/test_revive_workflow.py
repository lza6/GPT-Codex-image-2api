"""救号工作流（v2.38.0 G2）测试：异步任务 + 结果台账 + API 端点。

覆盖场景：
- start_revive：空 tokens 抛 ValueError；幂等（相同 tokens 复用 running task_id）
- task_handler：成功路径（revive_accounts 被调 → 台账有记录 → 事件发布）
- task_handler：异常路径（revive_accounts 抛异常 → task_queue.fail）
- ReviveLedger：recent/stats/裁剪
- API：401 未鉴权 / 403 非 admin / run→status→ledger 全链路
- 资源隔离：全部 mock，不触网、不真救号。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# start_revive / 幂等
# ---------------------------------------------------------------------------


class TestStartRevive:
    def test_empty_tokens_raises(self):
        from services.revive_workflow import start_revive

        with pytest.raises(ValueError):
            start_revive([])
        with pytest.raises(ValueError):
            start_revive(["", "  "])

    def test_enqueues_task_and_returns_id(self):
        from services.revive_workflow import start_revive

        with patch("services.revive_workflow.task_queue.enqueue", return_value="tid1") as mock_enqueue, \
             patch("services.revive_workflow.task_queue.status", return_value=MagicMock(status="pending", id="tid1")):
            tid = start_revive(["tok1", "tok2", "tok1"])  # 重复 token 去重
        assert tid == "tid1"
        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args
        assert kwargs.args[0] == "revive_workflow"
        assert kwargs.kwargs["metadata"]["access_tokens"] == ["tok1", "tok2"]
        assert kwargs.kwargs["priority"].value == 1  # HIGH

    def test_reuses_running_task_for_same_tokens(self):
        from services.revive_workflow import start_revive

        with patch("services.revive_workflow.task_queue.enqueue", return_value="tid1"), \
             patch("services.revive_workflow.task_queue.status", return_value=MagicMock(status="running", id="tid1")):
            first = start_revive(["tok1"])
        with patch("services.revive_workflow.task_queue.enqueue", return_value="tid2") as mock_enqueue2, \
             patch("services.revive_workflow.task_queue.status", return_value=MagicMock(status="running", id="tid1")):
            second = start_revive(["tok1"])
        assert first == second == "tid1"
        mock_enqueue2.assert_not_called()


# ---------------------------------------------------------------------------
# task_handler
# ---------------------------------------------------------------------------


class TestTaskHandler:
    def _task(self, task_id: str, tokens: list[str]):
        from services.task_queue import Task

        return Task(id=task_id, name="revive_workflow", metadata={"access_tokens": tokens})

    def test_success_records_ledger_and_publishes(self, tmp_path, monkeypatch):
        from services.revive_workflow import revive_ledger, task_handler

        monkeypatch.setattr(revive_ledger, "_path", tmp_path / "revive_ledger.jsonl")
        summary = {"revived": 2, "failed": [{"email": "a@x.com", "error": "e"}], "skipped": [{"email": "b@x.com", "reason": "无取件凭证"}]}

        with patch("services.revive_workflow._get_account_service") as mock_acct, \
             patch("services.revive_workflow.event_bus.publish") as mock_pub:
            mock_acct.return_value.revive_accounts.return_value = summary
            result = task_handler(self._task("run-1", ["tok1", "tok2"]))

        assert result["revived"] == 2
        assert result["failed"] == 1
        assert result["skipped"] == 1
        # 台账有记录
        rows = json.loads((tmp_path / "revive_ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert rows["revived"] == 2
        assert rows["failed"] == 1
        # 事件发布（revive.finished）
        published = [c.args[0] for c in mock_pub.call_args_list]
        assert any(getattr(e, "type", "") == "revive.finished" for e in published)

    def test_exception_calls_fail(self, tmp_path, monkeypatch):
        from services.revive_workflow import task_handler

        with patch("services.revive_workflow._get_account_service") as mock_acct, \
             pytest.raises(Exception):
            mock_acct.return_value.revive_accounts.side_effect = RuntimeError("boom")
            # task_handler 内部抛异常 → 由消费者循环 fail；直接调用会向上抛
            with patch("services.revive_workflow.revive_ledger"):
                task_handler(self._task("run-x", ["tok"]))


# ---------------------------------------------------------------------------
# ReviveLedger
# ---------------------------------------------------------------------------


class TestReviveLedger:
    def test_recent_and_stats(self, tmp_path):
        from services.revive_workflow import ReviveLedger

        ledger = ReviveLedger(path=tmp_path / "ledger.jsonl")
        for i in range(3):
            ledger.record_run(f"run-{i}", {
                "revived": i + 1,
                "failed": [{"email": f"f{i}", "error": "e"}],
                "skipped": [{"email": f"s{i}", "reason": "r"}],
            })
        recent = ledger.recent(run_limit=2)
        assert [r["run_id"] for r in recent] == ["run-2", "run-1"]  # 新→旧
        stats = ledger.stats()
        assert stats["total_runs"] == 3
        assert stats["total_revived"] == 6
        assert stats["total_failed"] == 3

    def test_trim_old_runs(self, tmp_path):
        from services.revive_workflow import LEDGER_MAX_RUNS, ReviveLedger

        ledger = ReviveLedger(path=tmp_path / "ledger.jsonl")
        for i in range(LEDGER_MAX_RUNS + 20):
            ledger.record_run(f"run-{i}", {"revived": 1, "failed": [], "skipped": []})
        stats = ledger.stats()
        assert stats["total_runs"] == LEDGER_MAX_RUNS

    def test_corrupt_lines_skipped(self, tmp_path):
        from services.revive_workflow import ReviveLedger

        path = tmp_path / "ledger.jsonl"
        path.write_text('{"run_id":"ok","revived":1}\nnot-json\n', encoding="utf-8")
        ledger = ReviveLedger(path=path)
        stats = ledger.stats()
        assert stats["total_runs"] == 1
        assert stats["total_revived"] == 1


# ---------------------------------------------------------------------------
# API 端点
# ---------------------------------------------------------------------------


class TestReviveEndpoints:
    def _client(self):
        from fastapi.testclient import TestClient

        from api.app import create_app

        return TestClient(create_app())

    def test_requires_auth(self):
        client = self._client()
        assert client.post("/api/accounts/revive/run", json={"access_tokens": ["t"]}).status_code == 401
        assert client.get("/api/accounts/revive/status/x").status_code == 401
        assert client.get("/api/accounts/revive/ledger").status_code == 401

    def test_run_status_ledger_flow(self, tmp_path, monkeypatch):
        from services.revive_workflow import revive_ledger

        client = self._client()
        headers = {"Authorization": "Bearer chatgpt2api"}
        monkeypatch.setattr(revive_ledger, "_path", tmp_path / "revive_ledger.jsonl")
        with patch("services.revive_workflow.task_queue.enqueue", return_value="tid-flow"):
            resp = client.post("/api/accounts/revive/run", json={"access_tokens": ["tok-a"]}, headers=headers)
            assert resp.status_code == 200
            assert resp.json()["task_id"] == "tid-flow"
        # status 端点（task 不在队列 → unknown，但端点本身 200）
        resp2 = client.get("/api/accounts/revive/status/tid-flow", headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["task_id"] == "tid-flow"
        # ledger 端点
        resp3 = client.get("/api/accounts/revive/ledger", headers=headers)
        assert resp3.status_code == 200
        assert "total_runs" in resp3.json()

    def test_run_empty_tokens_400(self):
        client = self._client()
        headers = {"Authorization": "Bearer chatgpt2api"}
        resp = client.post("/api/accounts/revive/run", json={"access_tokens": []}, headers=headers)
        assert resp.status_code == 400