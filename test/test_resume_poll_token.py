"""C9/P0-2：resume_poll 原账号优先 + 匿名 token 修复。

历史 bug：图片轮询超时后 resume_poll 用 `OpenAIBackendAPI()`（无 access_token）走
匿名链路续等——上游图片挂在已登录会话上，匿名 token 无权读取该 conversation，
超时续等必然失败。修复：任务记录原账号 email，恢复时按 email 找回 token 重连。

验证矩阵：
1. 任务记录原账号 email → 恢复时按 email 找到 token，backend 用该 token 构建。
2. 账号已删除（email 找不到）→ 抛错并标记任务失败，不再静默匿名续等。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services import image_task_service as its


def _make_service(tmp_path) -> its.ImageTaskService:  # noqa: ANN001
    return its.ImageTaskService(
        tmp_path / "image_tasks.json",
        generation_handler=MagicMock(),
        edit_handler=MagicMock(),
    )


def _seed_error_task(service: its.ImageTaskService, *, email: str = "") -> str:
    """直接往任务表塞一个超时失败任务（模拟 _run_task 超时后的状态）。"""
    task_id = "task-c9-1"
    owner = its._owner_id({"id": "u1"})
    key = its._task_key(owner, task_id)
    with service._lock:
        service._tasks[key] = {
            "id": task_id,
            "owner_id": owner,
            "status": its.TASK_STATUS_ERROR,
            "mode": "generate",
            "model": "gpt-image-2",
            "error": "ChatGPT 生图超时（已等待 300 秒）。",
            "conversation_id": "conv-abc",
            "created_at": its._now_iso(),
            "updated_at": its._now_iso(),
            "created_ts": 0.0,
        }
        if email:
            service._tasks[key]["account_email"] = email
    return task_id


def test_resume_poll_uses_original_account_token(tmp_path) -> None:
    """任务带 account_email 时，恢复轮询必须按 email 找回 token 构建 backend。"""
    service = _make_service(tmp_path)
    task_id = _seed_error_task(service, email="plus@example.com")

    fake_account = {"access_token": "tok-original-123"}
    captured: dict[str, object] = {}

    class _FakeBackend:
        def __init__(self, token: str = "") -> None:
            captured["token"] = token

        def _poll_image_results(self, conversation_id: str, timeout: float):  # noqa: ARG002
            return (["file-1"], [])

        def resolve_conversation_image_urls(self, *a, **k):  # noqa: ANN002, ANN003
            return ["https://img/1.png"]

        def download_image_bytes(self, urls):  # noqa: ANN001
            return [b"png-bytes"]

        def close(self) -> None:
            pass

    with (
        patch("services.account_service.account_service.get_account_by_email", return_value=fake_account) as mock_by_email,
        patch("services.openai_backend_api.OpenAIBackendAPI", _FakeBackend),
    ):
        service.resume_poll({"id": "u1"}, task_id, extra_timeout_secs=5.0)
        # 等后台线程跑完
        import time

        deadline = time.time() + 5
        while time.time() < deadline:
            with service._lock:
                status = service._tasks[its._task_key(its._owner_id({"id": "u1"}), task_id)]["status"]
            if status != its.TASK_STATUS_RUNNING:
                break
            time.sleep(0.05)

    mock_by_email.assert_called_once_with("plus@example.com")
    assert captured.get("token") == "tok-original-123", (
        f"resume_poll 必须用原账号 token 构建 backend，实际 token={captured.get('token')!r}"
    )


def test_resume_poll_marks_failed_when_account_gone(tmp_path) -> None:
    """原账号已被删除时：任务置为失败并给出明确错误，禁止匿名链路静默续等。"""
    service = _make_service(tmp_path)
    task_id = _seed_error_task(service, email="gone@example.com")

    with (
        patch("services.account_service.account_service.get_account_by_email", return_value=None),
        patch("services.openai_backend_api.OpenAIBackendAPI") as mock_backend_cls,
    ):
        service.resume_poll({"id": "u1"}, task_id, extra_timeout_secs=5.0)
        import time

        deadline = time.time() + 5
        while time.time() < deadline:
            with service._lock:
                task = service._tasks[its._task_key(its._owner_id({"id": "u1"}), task_id)]
            if task["status"] != its.TASK_STATUS_RUNNING:
                break
            time.sleep(0.05)

    mock_backend_cls.assert_not_called()
    with service._lock:
        task = service._tasks[its._task_key(its._owner_id({"id": "u1"}), task_id)]
    assert task["status"] == its.TASK_STATUS_ERROR
    assert "gone@example.com" in str(task.get("error")), "错误信息必须指明原账号已不可用"


def test_resume_poll_without_email_falls_back_to_anonymous(tmp_path) -> None:
    """历史任务（无 account_email）保持匿名链路行为，不回归。"""
    service = _make_service(tmp_path)
    task_id = _seed_error_task(service, email="")

    class _FakeBackend:
        def __init__(self, token: str = "") -> None:
            pass

        def _poll_image_results(self, *a, **k):  # noqa: ANN002, ANN003
            return ([], [])

        def close(self) -> None:
            pass

    with patch("services.openai_backend_api.OpenAIBackendAPI", _FakeBackend):
        service.resume_poll({"id": "u1"}, task_id, extra_timeout_secs=1.0)
        import time

        deadline = time.time() + 5
        while time.time() < deadline:
            with service._lock:
                task = service._tasks[its._task_key(its._owner_id({"id": "u1"}), task_id)]
            if task["status"] != its.TASK_STATUS_RUNNING:
                break
            time.sleep(0.05)

    with service._lock:
        task = service._tasks[its._task_key(its._owner_id({"id": "u1"}), task_id)]
    assert task["status"] == its.TASK_STATUS_ERROR  # 匿名找不到图 → 失败，但流程走通
    assert "未找到图片" in str(task.get("error"))


def test_resume_poll_rejects_second_concurrent_resume(tmp_path) -> None:
    """审查 P2-5：resume_inflight 竞态守卫——首次 resume 进行中，第二次并发 resume 必须拒绝，
    防双线程轮询同一 conversation（双扣配额/双写结果）。"""
    import threading

    service = _make_service(tmp_path)
    task_id = _seed_error_task(service, email="plus@example.com")

    hold = threading.Event()

    class _SlowBackend:
        def __init__(self, token: str = "") -> None:
            pass

        def _poll_image_results(self, *a, **k):  # noqa: ANN002, ANN003
            hold.wait(3)  # 让线程保持运行，resume_inflight 持续置位
            return ([], [])

        def close(self) -> None:
            pass

    with patch("services.openai_backend_api.OpenAIBackendAPI", _SlowBackend):
        # 第一次 resume 启动后台线程（resume_inflight=True）
        service.resume_poll({"id": "u1"}, task_id, extra_timeout_secs=5.0)
        # 第二次必须被拦截
        with pytest.raises(ValueError, match="already being resumed"):
            service.resume_poll({"id": "u1"}, task_id, extra_timeout_secs=5.0)
        hold.set()  # 放行后台线程结束

    import time

    # 等待后台线程结束（inflight 在 finally 清除，需等它——状态先置 ERROR 后清 inflight）
    deadline = time.time() + 5
    while time.time() < deadline:
        with service._lock:
            task = service._tasks[its._task_key(its._owner_id({"id": "u1"}), task_id)]
        if "resume_inflight" not in task:
            break
        time.sleep(0.05)
    # 线程结束后 resume_inflight 被 finally 清除 → 再次 resume 不再报"already"
    with service._lock:
        task = service._tasks[its._task_key(its._owner_id({"id": "u1"}), task_id)]
    assert "resume_inflight" not in task, "resume 结束后必须清除 in-flight 标记"
    assert task["status"] == its.TASK_STATUS_ERROR
