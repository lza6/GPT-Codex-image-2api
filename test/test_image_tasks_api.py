from __future__ import annotations

import base64
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

AUTH_HEADERS = {"Authorization": "Bearer chatgpt2api"}
PNG_BYTES = b"\x89PNG\r\n\x1a\n"
DATA_IMAGE_URL = f"data:image/png;base64,{base64.b64encode(PNG_BYTES).decode('ascii')}"


class FakeImageTaskService:
    def __init__(self):
        self.generation_calls = []
        self.edit_calls = []

    def reset(self):
        self.generation_calls.clear()
        self.edit_calls.clear()

    def submit_generation(self, identity, **kwargs):
        self.generation_calls.append((identity, kwargs))
        return {
            "id": kwargs["client_task_id"],
            "status": "success",
            "mode": "generate",
            "created_at": "2026-01-01 00:00:00",
            "updated_at": "2026-01-01 00:00:00",
            "data": [{"url": f"{kwargs['base_url']}/images/fake.png"}],
        }

    def submit_edit(self, identity, **kwargs):
        self.edit_calls.append((identity, kwargs))
        return {
            "id": kwargs["client_task_id"],
            "status": "success",
            "mode": "edit",
            "created_at": "2026-01-01 00:00:00",
            "updated_at": "2026-01-01 00:00:00",
        }

    def list_tasks(self, identity, ids):
        return {
            "items": [
                {
                    "id": task_id,
                    "status": "success",
                    "mode": "generate",
                    "created_at": "2026-01-01 00:00:00",
                    "updated_at": "2026-01-01 00:00:00",
                    "data": [{"url": "http://testserver/images/fake.png"}],
                }
                for task_id in ids
                if task_id != "missing"
            ],
            "missing_ids": [task_id for task_id in ids if task_id == "missing"],
        }


class ImageTasksApiTests(unittest.TestCase):
    def setUp(self):
        import importlib

        import api.image_tasks
        importlib.reload(api.image_tasks)
        self._image_tasks_module = api.image_tasks
        self.fake_service = FakeImageTaskService()
        self.service_patcher = mock.patch.object(api.image_tasks, "image_task_service", self.fake_service)
        self.service_patcher.start()
        self.addCleanup(self.service_patcher.stop)
        app = FastAPI()
        app.include_router(self._image_tasks_module.create_router())
        self.client = TestClient(app)

    def test_create_generation_task(self):
        response = self.client.post(
            "/api/image-tasks/generations",
            headers=AUTH_HEADERS,
            json={"client_task_id": "gen-task-1", "prompt": "cat", "model": "gpt-image-2"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["id"], "gen-task-1")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(len(self.fake_service.generation_calls), 1)

    def test_create_generation_task_passes_provider(self):
        """Phase 4：文生图任务带 provider 字段应透传到 submit_generation。"""
        response = self.client.post(
            "/api/image-tasks/generations",
            headers=AUTH_HEADERS,
            json={"client_task_id": "gen-grok-1", "prompt": "cat", "model": "grok-3-image", "provider": "grok"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        kwargs = self.fake_service.generation_calls[-1][1]
        self.assertEqual(kwargs["provider"], "grok")

    def test_create_generation_task_provider_optional(self):
        """Phase 4：不传 provider 时 submit_generation 收到 None。"""
        response = self.client.post(
            "/api/image-tasks/generations",
            headers=AUTH_HEADERS,
            json={"client_task_id": "gen-nop-1", "prompt": "cat", "model": "gpt-image-2"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        kwargs = self.fake_service.generation_calls[-1][1]
        self.assertIsNone(kwargs["provider"])

    def test_create_edit_task_passes_provider(self):
        """Phase 4：图生图任务带 provider 字段应透传到 submit_edit。"""
        response = self.client.post(
            "/api/image-tasks/edits",
            headers=AUTH_HEADERS,
            data={
                "client_task_id": "edit-grok-1",
                "prompt": "edit",
                "model": "grok-3-image",
                "provider": "grok",
            },
            files=[("image", ("one.png", b"one", "image/png"))],
        )

        self.assertEqual(response.status_code, 200, response.text)
        kwargs = self.fake_service.edit_calls[-1][1]
        self.assertEqual(kwargs["provider"], "grok")

    def test_create_edit_task_provider_optional(self):
        """Phase 4：图生图不传 provider 时 submit_edit 收到 None。"""
        response = self.client.post(
            "/api/image-tasks/edits",
            headers=AUTH_HEADERS,
            data={
                "client_task_id": "edit-nop-1",
                "prompt": "edit",
                "model": "gpt-image-2",
            },
            files=[("image", ("one.png", b"one", "image/png"))],
        )
        self.assertEqual(response.status_code, 200, response.text)
        kwargs = self.fake_service.edit_calls[-1][1]
        self.assertIsNone(kwargs["provider"])

    def test_create_edit_task_accepts_multiple_images(self):
        """测试图片编辑任务接口支持多个上传图片。"""
        response = self.client.post(
            "/api/image-tasks/edits",
            headers=AUTH_HEADERS,
            data={"client_task_id": "edit-multi-1", "prompt": "edit", "model": "gpt-image-2"},
            files=[
                ("image", ("one.png", b"one", "image/png")),
                ("image", ("two.png", b"two", "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], "edit-multi-1")
        self.assertEqual(len(self.fake_service.edit_calls), 1)
        images = self.fake_service.edit_calls[0][1]["images"]
        self.assertEqual(len(images), 2)

    def test_create_edit_task_accepts_image_url(self):
        """测试图片编辑任务接口支持表单 image_url 引用。"""
        response = self.client.post(
            "/api/image-tasks/edits",
            headers=AUTH_HEADERS,
            data={
                "client_task_id": "edit-url-2",
                "prompt": "edit",
                "model": "gpt-image-2",
                "image_url": DATA_IMAGE_URL,
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.fake_service.edit_calls), 1)
        images = self.fake_service.edit_calls[0][1]["images"]
        self.assertEqual(images, [(PNG_BYTES, "image_url.png", "image/png")])

    def test_list_tasks_reports_missing_ids(self):
        # 先创建一个任务，再查询
        self.client.post(
            "/api/image-tasks/generations",
            headers=AUTH_HEADERS,
            json={"client_task_id": "list-task-1", "prompt": "cat", "model": "gpt-image-2"},
        )
        response = self.client.get("/api/image-tasks?ids=list-task-1,missing", headers=AUTH_HEADERS)

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["items"]], ["list-task-1"])
        self.assertEqual(payload["missing_ids"], ["missing"])


if __name__ == "__main__":
    unittest.main()
