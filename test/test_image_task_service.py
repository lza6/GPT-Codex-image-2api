from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from services.image_task_service import ImageTaskService, _owner_id, _task_key

OWNER = {"id": "owner-1", "name": "Owner", "role": "admin"}
OTHER_OWNER = {"id": "owner-2", "name": "Other", "role": "user"}


def wait_for_task(service: ImageTaskService, identity: dict[str, object], task_id: str, status: str, timeout: float = 2.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        result = service.list_tasks(identity, [task_id])
        last = (result.get("items") or [None])[0]
        if last and last.get("status") == status:
            return last
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {status}, last={last}")


class ImageTaskServiceTests(unittest.TestCase):
    def make_service(self, path: Path, handler=None) -> ImageTaskService:
        return ImageTaskService(
            path,
            generation_handler=handler or (lambda _payload: {"data": [{"url": "http://example.test/image.png"}]}),
            edit_handler=handler or (lambda _payload: {"data": [{"url": "http://example.test/edit.png"}]}),
            retention_days_getter=lambda: 30,
        )

    def test_duplicate_submit_uses_existing_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            calls = 0

            def handler(_payload):
                nonlocal calls
                calls += 1
                time.sleep(0.05)
                return {"data": [{"url": "http://example.test/image.png"}]}

            service = self.make_service(Path(tmp_dir) / "image_tasks.json", handler)
            first = service.submit_generation(
                OWNER,
                client_task_id="task-1",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            second = service.submit_generation(
                OWNER,
                client_task_id="task-1",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )

            self.assertEqual(first["id"], "task-1")
            self.assertEqual(second["id"], "task-1")
            task = wait_for_task(service, OWNER, "task-1", "success")
            self.assertEqual(task["data"][0]["url"], "http://example.test/image.png")
            self.assertEqual(calls, 1)

    def test_different_owner_cannot_query_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self.make_service(Path(tmp_dir) / "image_tasks.json")
            service.submit_generation(
                OWNER,
                client_task_id="private-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )

            wait_for_task(service, OWNER, "private-task", "success")
            result = service.list_tasks(OTHER_OWNER, ["private-task"])

            self.assertEqual(result["items"], [])
            self.assertEqual(result["missing_ids"], ["private-task"])

    def test_success_task_persists_to_new_service_instance(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            service = self.make_service(path)
            service.submit_generation(
                OWNER,
                client_task_id="persisted-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            wait_for_task(service, OWNER, "persisted-task", "success")

            reloaded = self.make_service(path)
            result = reloaded.list_tasks(OWNER, ["persisted-task"])

            self.assertEqual(result["missing_ids"], [])
            self.assertEqual(result["items"][0]["status"], "success")
            self.assertEqual(result["items"][0]["data"][0]["url"], "http://example.test/image.png")

    def test_startup_marks_unfinished_tasks_as_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "queued-task",
                                "owner_id": "owner-1",
                                "status": "queued",
                                "mode": "generate",
                                "model": "gpt-image-2",
                                "created_at": "2099-01-01 00:00:00",
                                "updated_at": "2099-01-01 00:00:00",
                            },
                            {
                                "id": "running-task",
                                "owner_id": "owner-1",
                                "status": "running",
                                "mode": "generate",
                                "model": "gpt-image-2",
                                "created_at": "2099-01-01 00:00:00",
                                "updated_at": "2099-01-01 00:00:00",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            service = self.make_service(path)
            result = service.list_tasks(OWNER, ["queued-task", "running-task"])

            self.assertEqual([item["status"] for item in result["items"]], ["error", "error"])
            self.assertTrue(all("已中断" in item.get("error", "") for item in result["items"]))

    def test_load_preserves_conversation_id_and_account_email(self):
        """审查 P2-5：_load_locked 必须保留 conversation_id/account_email（resume_poll 依赖），
        此前白名单丢弃这两个字段会打穿 C9 原账号优先修复。"""
        from datetime import datetime, timedelta

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "image_tasks.json"
            # 2026-09-15：原写死 2026-08-01 早于 _cleanup_locked 的 retention 30 天 cutoff
            # → 启动即删 → list_tasks 空（时间腐蚀）。改相对未来时间避免随日期推进再次腐坏。
            future_ts = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
            path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "timeout-task",
                                "owner_id": "owner-1",
                                "status": "error",
                                "mode": "generate",
                                "model": "gpt-image-2",
                                "conversation_id": "conv-abc-123",
                                "account_email": "plus@example.com",
                                "error": "ChatGPT 生图超时",
                                "created_at": future_ts,
                                "updated_at": future_ts,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            service = self.make_service(path)
            result = service.list_tasks(OWNER, ["timeout-task"])
            item = result["items"][0]
            self.assertEqual(item["conversation_id"], "conv-abc-123")
            self.assertEqual(item["account_email"], "plus@example.com")

    def test_update_task_save_failure_does_not_raise(self):
        """审查 P2-5：_update_task 落盘失败必须只记日志不抛出（内存态先更新），
        否则 _run_task 的 except 分支二次崩溃，任务永久卡死 RUNNING。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            from unittest.mock import patch

            service = self.make_service(Path(tmp_dir) / "image_tasks.json")
            service.submit_generation(
                OWNER,
                client_task_id="save-fail-task",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            wait_for_task(service, OWNER, "save-fail-task", "success")

            with patch.object(ImageTaskService, "_save_locked", side_effect=OSError("disk full")):
                # 不应抛异常
                service._update_task(
                    _task_key(_owner_id(OWNER), "save-fail-task"),
                    status="error",
                    error="manual",
                )
            # 内存态已更新（即使落盘失败）
            result = service.list_tasks(OWNER, ["save-fail-task"])
            self.assertEqual(result["items"][0]["error"], "manual")

    def test_submit_generation_payload_carries_provider(self):
        """Phase 4：submit_generation 将 provider 写入 handler payload。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            seen: list[dict] = []

            def handler(payload):
                seen.append(payload)
                return {"data": [{"url": "http://example.test/image.png"}]}

            service = self.make_service(Path(tmp_dir) / "image_tasks.json", handler)
            service.submit_generation(
                OWNER,
                client_task_id="prov-gen-1",
                prompt="cat",
                model="grok-3-image",
                size=None,
                provider="grok",
                base_url="http://local.test",
            )
            wait_for_task(service, OWNER, "prov-gen-1", "success")
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0]["provider"], "grok")

    def test_submit_generation_provider_optional_none(self):
        """Phase 4：不传 provider 时 handler payload 中 provider 为 None。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            seen: list[dict] = []

            def handler(payload):
                seen.append(payload)
                return {"data": [{"url": "http://example.test/image.png"}]}

            service = self.make_service(Path(tmp_dir) / "image_tasks.json", handler)
            service.submit_generation(
                OWNER,
                client_task_id="prov-nop-1",
                prompt="cat",
                model="gpt-image-2",
                size=None,
                base_url="http://local.test",
            )
            wait_for_task(service, OWNER, "prov-nop-1", "success")
            self.assertEqual(len(seen), 1)
            self.assertIsNone(seen[0]["provider"])

    def test_submit_edit_payload_carries_provider(self):
        """Phase 4：submit_edit 将 provider 写入 handler payload。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            seen: list[dict] = []

            def handler(payload):
                seen.append(payload)
                return {"data": [{"url": "http://example.test/edit.png"}]}

            service = self.make_service(Path(tmp_dir) / "image_tasks.json", handler)
            service.submit_edit(
                OWNER,
                client_task_id="prov-edit-1",
                prompt="edit",
                model="grok-3-image",
                size=None,
                provider="grok",
                base_url="http://local.test",
                images=[(b"one", "one.png", "image/png")],
            )
            wait_for_task(service, OWNER, "prov-edit-1", "success")
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0]["provider"], "grok")


if __name__ == "__main__":
    unittest.main()
