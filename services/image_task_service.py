from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config
from services.content_filter import request_text
from services.log_service import LOG_TYPE_CALL, log_service
from services.protocol import openai_v1_image_edit, openai_v1_image_generations
from services.task_queue import TaskPriority, task_queue

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_ERROR = "error"
TERMINAL_STATUSES = {TASK_STATUS_SUCCESS, TASK_STATUS_ERROR}
UNFINISHED_STATUSES = {TASK_STATUS_QUEUED, TASK_STATUS_RUNNING}

# C8/P1-3：prompt 短窗口去重窗口（秒）。窗口内同 owner+mode+model+prompt 的
# 重复提交直接返回已有任务，防止前端重试/双击导致同一 prompt 重复扣配额。
PROMPT_DEDUP_WINDOW_SECS = 120.0


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _timestamp(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:26], fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _clean(value: object, default: str = "") -> str:
    return str(value or default).strip()


def _owner_id(identity: dict[str, object]) -> str:
    return _clean(identity.get("id")) or "anonymous"


def _task_key(owner_id: str, task_id: str) -> str:
    return f"{owner_id}:{task_id}"


def _collect_image_urls(data: list[Any]) -> list[str]:
    urls: list[str] = []
    for item in data:
        if isinstance(item, dict):
            url = item.get("url")
            if isinstance(url, str) and url:
                urls.append(url)
    return urls


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    item = {
        "id": task.get("id"),
        "status": task.get("status"),
        "mode": task.get("mode"),
        "model": task.get("model"),
        "size": task.get("size"),
        "quality": task.get("quality"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }
    if task.get("conversation_id"):
        item["conversation_id"] = task.get("conversation_id")
    if task.get("account_email"):
        item["account_email"] = task.get("account_email")
    if task.get("deduped"):
        item["deduped"] = True
    if task.get("data") is not None:
        item["data"] = task.get("data")
    if task.get("usage") is not None:
        item["usage"] = task.get("usage")
    if task.get("error"):
        item["error"] = task.get("error")
    if task.get("progress"):
        item["progress"] = task.get("progress")
    if task.get("duration_ms") is not None:
        item["duration_ms"] = task.get("duration_ms")
    if task.get("status") in (TASK_STATUS_RUNNING, TASK_STATUS_QUEUED):
        if task.get("status") == TASK_STATUS_RUNNING:
            # RUNNING 状态仅在 started_ts 被设置后（image_stream_resolve_start）才计时
            base_ts = task.get("started_ts")
        else:
            # QUEUED 状态从 created_ts 开始计时（排队等待中）
            base_ts = task.get("created_ts") or task.get("updated_ts")
        if base_ts:
            item["elapsed_secs"] = round(time.time() - base_ts, 1)
    return item


class ImageTaskService:
    def __init__(
        self,
        path: Path,
        *,
        generation_handler: Callable[[dict[str, Any]], dict[str, Any]] = openai_v1_image_generations.handle,
        edit_handler: Callable[[dict[str, Any]], dict[str, Any]] = openai_v1_image_edit.handle,
        retention_days_getter: Callable[[], int] | None = None,
    ):
        self.path = path
        self.generation_handler = generation_handler
        self.edit_handler = edit_handler
        self.retention_days_getter = retention_days_getter or (lambda: config.image_retention_days)
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._tasks = self._load_locked()
            changed = self._recover_unfinished_locked()
            changed = self._cleanup_locked() or changed
            if changed:
                self._save_locked()

    def submit_generation(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        prompt: str,
        model: str,
        size: str | None,
        quality: str = "auto",
        base_url: str = "",
        seed: int | None = None,  # 3.1.3：固定随机种子（实验性）
    ) -> dict[str, Any]:
        payload = {
            "prompt": prompt,
            "model": model,
            "n": 1,
            "size": size,
            "quality": quality,
            "seed": seed,
            "response_format": "url",
            "base_url": base_url,
        }
        return self._submit(identity, client_task_id=client_task_id, mode="generate", payload=payload)

    def submit_edit(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        prompt: str,
        model: str,
        size: str | None,
        quality: str = "auto",
        base_url: str = "",
        images: list[tuple[bytes, str, str]] | None = None,
        masks: list[tuple[bytes, str, str]] | None = None,
        seed: int | None = None,  # 3.1.3：固定随机种子（实验性）
    ) -> dict[str, Any]:
        payload = {
            "prompt": prompt,
            "images": images or [],
            "mask": masks or [],
            "model": model,
            "n": 1,
            "size": size,
            "quality": quality,
            "seed": seed,
            "response_format": "url",
            "base_url": base_url,
        }
        return self._submit(identity, client_task_id=client_task_id, mode="edit", payload=payload)

    def list_tasks(self, identity: dict[str, object], task_ids: list[str]) -> dict[str, Any]:
        owner = _owner_id(identity)
        requested_ids = [_clean(task_id) for task_id in task_ids if _clean(task_id)]
        with self._lock:
            if self._cleanup_locked():
                self._save_locked()
            items = []
            missing_ids = []
            for task_id in requested_ids:
                task = self._tasks.get(_task_key(owner, task_id))
                if task is None:
                    missing_ids.append(task_id)
                else:
                    items.append(_public_task(task))
            if not requested_ids:
                items = [
                    _public_task(task)
                    for task in self._tasks.values()
                    if task.get("owner_id") == owner
                ]
                items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
                missing_ids = []
            return {"items": items, "missing_ids": missing_ids}

    def _submit(
        self,
        identity: dict[str, object],
        *,
        client_task_id: str,
        mode: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = _clean(client_task_id)
        if not task_id:
            raise ValueError("client_task_id is required")
        owner = _owner_id(identity)
        key = _task_key(owner, task_id)
        now = _now_iso()
        should_start = False
        with self._lock:
            cleaned = self._cleanup_locked()
            task = self._tasks.get(key)
            if task is not None:
                if cleaned:
                    self._save_locked()
                return _public_task(task)
            # C8/P1-3：短窗口 prompt 去重——窗口内同 owner+mode+model+prompt 已有任务，
            # 直接返回该任务（标 deduped），不再起新线程重复扣配额。
            new_prompt = _clean(payload.get("prompt"))
            new_model = _clean(payload.get("model"), "gpt-image-2")
            if new_prompt:
                now_ts = time.time()
                for existing in self._tasks.values():
                    if existing.get("owner_id") != owner:
                        continue
                    if existing.get("mode") != mode:
                        continue
                    if _clean(existing.get("prompt")) != new_prompt:
                        continue
                    if _clean(existing.get("model"), "gpt-image-2") != new_model:
                        continue
                    if now_ts - float(existing.get("created_ts") or 0) > PROMPT_DEDUP_WINDOW_SECS:
                        continue
                    existing["deduped"] = True
                    self._save_locked()
                    return _public_task(existing)
            task = {
                "id": task_id,
                "owner_id": owner,
                "status": TASK_STATUS_QUEUED,
                "mode": mode,
                "model": new_model,
                "size": _clean(payload.get("size")),
                "quality": _clean(payload.get("quality"), "auto"),
                "prompt": new_prompt,
                "created_at": now,
                "updated_at": now,
                "created_ts": time.time(),
            }
            self._tasks[key] = task
            self._save_locked()
            should_start = True

        if should_start:
            # 通过任务队列提交（优先级 CRITICAL），消费者已启动时走队列；
            # 消费者未启动（如测试环境）回退直接起线程
            if task_queue._consumer_thread and task_queue._consumer_thread.is_alive():
                task_queue.enqueue(
                    "image_generation" if mode == "generate" else "image_edit",
                    priority=TaskPriority.CRITICAL,
                    metadata={
                        "key": key,
                        "mode": mode,
                        "payload": payload,
                        "identity": dict(identity),
                        "model": _clean(payload.get("model"), "gpt-image-2"),
                    },
                )
            else:
                threading.Thread(
                    target=self._run_task,
                    args=(key, mode, payload, dict(identity), _clean(payload.get("model"), "gpt-image-2")),
                    name=f"image-task-{task_id[:16]}",
                    daemon=True,
                ).start()
        return _public_task(task)

    def _run_task(
        self,
        key: str,
        mode: str,
        payload: dict[str, Any],
        identity: dict[str, object],
        model: str,
    ) -> None:
        started = time.time()
        self._update_task(key, status=TASK_STATUS_RUNNING, error="")
        from services.event_bus import IMAGE_TASK_COMPLETED, Event, event_bus  # noqa: F811
        # 创建进度回调，每个步骤完成后更新任务状态
        def progress_callback(step: str) -> None:
            if step == "image_stream_resolve_start":
                self._update_task(key, started_ts=time.time())
            self._update_task(key, progress=step)
        # 将进度回调添加到 payload 中（handler 会提取并传递给 ConversationRequest）
        payload_with_progress = {**payload, "progress_callback": progress_callback}
        try:
            handler = self.edit_handler if mode == "edit" else self.generation_handler
            result = handler(payload_with_progress)
            if not isinstance(result, dict):
                raise RuntimeError("image task returned streaming result unexpectedly")
            data = result.get("data")
            account_email = _clean(result.get("_account_email") or result.get("account_email"))
            if not isinstance(data, list) or not data:
                upstream = _clean(result.get("message"))
                if upstream:
                    message = upstream
                else:
                    message = "号池中没有可用账号或所有账号均被限流，请检查号池状态（账号额度、是否被封禁、是否到达生图上限）"
                error = RuntimeError(message)
                if account_email:
                    setattr(error, "account_email", account_email)
                raise error
            usage = result.get("usage")
            duration_ms = int((time.time() - started) * 1000)
            self._update_task(key, status=TASK_STATUS_SUCCESS, data=data, usage=usage, error="", duration_ms=duration_ms)
            event_bus.publish(Event(IMAGE_TASK_COMPLETED, {
                "task_id": key.split(":", 1)[-1],
                "mode": mode,
                "model": model,
                "status": TASK_STATUS_SUCCESS,
                "account_email": account_email,
                "duration_ms": duration_ms,
            }))
            self._log_call(
                identity,
                mode,
                model,
                started,
                "调用完成",
                request_preview=request_text(payload.get("prompt")),
                urls=_collect_image_urls(data),
                account_email=account_email,
            )
        except Exception as exc:
            error_message = str(exc) or "image task failed"
            account_email = _clean(getattr(exc, "account_email", ""))
            conversation_id = _clean(getattr(exc, "conversation_id", ""))
            duration_ms = int((time.time() - started) * 1000)
            self._update_task(key, status=TASK_STATUS_ERROR, error=error_message, data=[],
                              duration_ms=duration_ms,
                              **({"conversation_id": conversation_id} if conversation_id else {}),
                              **({"account_email": account_email} if account_email else {}))
            event_bus.publish(Event(IMAGE_TASK_COMPLETED, {
                "task_id": key.split(":", 1)[-1],
                "mode": mode,
                "model": model,
                "status": TASK_STATUS_ERROR,
                "account_email": account_email,
                "duration_ms": duration_ms,
            }))
            self._log_call(
                identity,
                mode,
                model,
                started,
                "调用失败",
                request_preview=request_text(payload.get("prompt")),
                status="failed",
                error=error_message,
                account_email=account_email,
            )

    def _log_call(
        self,
        identity: dict[str, object],
        mode: str,
        model: str,
        started: float,
        suffix: str,
        *,
        request_preview: str = "",
        status: str = "success",
        error: str = "",
        urls: list[str] | None = None,
        account_email: str = "",
    ) -> None:
        endpoint = "/v1/images/edits" if mode == "edit" else "/v1/images/generations"
        summary_prefix = "图生图" if mode == "edit" else "文生图"
        detail = {
            "key_id": identity.get("id"),
            "key_name": identity.get("name"),
            "role": identity.get("role"),
            "endpoint": endpoint,
            "model": model,
            "started_at": datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": _now_iso(),
            "duration_ms": int((time.time() - started) * 1000),
            "status": status,
        }
        if request_preview:
            detail["request_text"] = request_preview
        if error:
            detail["error"] = error
        if account_email:
            detail["account_email"] = account_email
        if urls:
            detail["urls"] = list(dict.fromkeys(urls))
        # v2.9.0：失败日志简述加失败阶段标签（让用户看到具体原因而非统一"调用失败"）
        final_suffix = suffix
        if status == "failed" and error:
            phase = _classify_failure_phase(error)
            if phase:
                final_suffix = f"{suffix}·{phase}"
                detail["failure_phase"] = phase
        try:
            log_service.add(LOG_TYPE_CALL, f"{summary_prefix}{final_suffix}", detail)
        except Exception:
            pass

    def _update_task(self, key: str, **updates: Any) -> None:
        with self._lock:
            task = self._tasks.get(key)
            if task is None:
                return
            task.update(updates)
            task["updated_at"] = _now_iso()
            task["updated_ts"] = time.time()
            # B4：落盘失败（磁盘满/文件占用）只记日志不抛出——内存态已更新，
            # 若此处抛异常会让 _run_task 的 except 分支二次崩溃，任务卡死 RUNNING
            try:
                self._save_locked()
            except Exception:
                logging.getLogger(__name__).warning(
                    "image task save failed (in-memory state kept): key=%s", key,
                    exc_info=True,
                )

    def _load_locked(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        raw_items = raw.get("tasks") if isinstance(raw, dict) else raw
        if not isinstance(raw_items, list):
            return {}
        tasks: dict[str, dict[str, Any]] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            task_id = _clean(item.get("id"))
            owner = _clean(item.get("owner_id"))
            if not task_id or not owner:
                continue
            status = _clean(item.get("status"))
            if status not in {TASK_STATUS_QUEUED, TASK_STATUS_RUNNING, TASK_STATUS_SUCCESS, TASK_STATUS_ERROR}:
                status = TASK_STATUS_ERROR
            task = {
                "id": task_id,
                "owner_id": owner,
                "status": status,
                "mode": "edit" if item.get("mode") == "edit" else "generate",
                "model": _clean(item.get("model"), "gpt-image-2"),
                "size": _clean(item.get("size")),
                "quality": _clean(item.get("quality"), "auto"),
                "created_at": _clean(item.get("created_at"), _now_iso()),
                "updated_at": _clean(item.get("updated_at"), _clean(item.get("created_at"), _now_iso())),
                "created_ts": item.get("created_ts"),
                "updated_ts": item.get("updated_ts"),
                "started_ts": item.get("started_ts"),
                "duration_ms": item.get("duration_ms"),
            }
            # D-B1：加载时保留 conversation_id / account_email（resume_poll 依赖的关键字段）。
            # 此前白名单丢弃这两个字段 → 重启后旧超时任务无法 resume（打穿 C9 原账号优先修复）
            conversation_id = _clean(item.get("conversation_id"))
            if conversation_id:
                task["conversation_id"] = conversation_id
            account_email = _clean(item.get("account_email"))
            if account_email:
                task["account_email"] = account_email
            data = item.get("data")
            if isinstance(data, list):
                task["data"] = data
            usage = item.get("usage")
            if isinstance(usage, dict):
                task["usage"] = usage
            error = _clean(item.get("error"))
            if error:
                task["error"] = error
            tasks[_task_key(owner, task_id)] = task
        return tasks

    def _save_locked(self) -> None:
        # D-B3：统一原子写（唯一 tmp + replace + Windows 瞬态锁重试），
        # 替代固定 .tmp 名——原实现并发写者互相覆盖、崩溃留半写文件
        from services.storage.json_storage import _atomic_write_text

        items = sorted(self._tasks.values(), key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        _atomic_write_text(self.path, json.dumps({"tasks": items}, ensure_ascii=False, indent=2) + "\n")

    def _recover_unfinished_locked(self) -> bool:
        changed = False
        for task in self._tasks.values():
            if task.get("status") in UNFINISHED_STATUSES:
                task["status"] = TASK_STATUS_ERROR
                task["error"] = "服务已重启，未完成的图片任务已中断"
                task["updated_at"] = _now_iso()
                changed = True
        return changed

    def _cleanup_locked(self) -> bool:
        try:
            retention_days = max(1, int(self.retention_days_getter()))
        except Exception:
            retention_days = 30
        cutoff = time.time() - retention_days * 86400
        removed_keys = [
            key
            for key, task in self._tasks.items()
            if task.get("status") in TERMINAL_STATUSES and _timestamp(task.get("updated_at")) < cutoff
        ]
        for key in removed_keys:
            self._tasks.pop(key, None)
        return bool(removed_keys)

    def resume_poll(
        self,
        identity: dict[str, object],
        task_id: str,
        extra_timeout_secs: float = 30.0,
    ) -> dict[str, Any]:
        """恢复对已超时任务的轮询，额外等待 extra_timeout_secs 秒。"""
        owner = _owner_id(identity)
        key = _task_key(owner, _clean(task_id))
        with self._lock:
            task = self._tasks.get(key)
            if task is None:
                raise ValueError("task not found")
            if task.get("status") != TASK_STATUS_ERROR:
                raise ValueError("task is not in error state")
            error_msg = _clean(task.get("error"))
            if "超时" not in error_msg:
                raise ValueError("task error is not a timeout error")
            conversation_id = _clean(task.get("conversation_id"))
            if not conversation_id:
                raise ValueError("task has no conversation_id")
            mode = task.get("mode", "generate")
            model = task.get("model", "gpt-image-2")
            # B1 竞态守卫：resume_inflight 置位期间拒绝再次 resume，
            # 防并发重试导致双线程轮询同一 conversation（双扣配额/双写结果）
            if task.get("resume_inflight"):
                raise ValueError("task is already being resumed")
            # 将任务状态重置为 running
            self._update_task(key, status=TASK_STATUS_RUNNING, error="", resume_inflight=True)

        # 启动新线程继续轮询
        # 通过任务队列提交（优先级 CRITICAL）或直接起线程
        if task_queue._consumer_thread and task_queue._consumer_thread.is_alive():
            task_queue.enqueue(
                "image_resume_poll",
                priority=TaskPriority.CRITICAL,
                metadata={
                    "key": key,
                    "conversation_id": conversation_id,
                    "extra_timeout_secs": extra_timeout_secs,
                    "identity": dict(identity),
                    "mode": mode,
                    "model": model,
                },
            )
        else:
            threading.Thread(
                target=self._run_resume_poll,
                args=(key, conversation_id, extra_timeout_secs, dict(identity), mode, model),
                name=f"image-resume-{_clean(task_id)[:16]}",
                daemon=True,
            ).start()
        return _public_task(task)

    def _run_resume_poll(
        self,
        key: str,
        conversation_id: str,
        extra_timeout_secs: float,
        identity: dict[str, object],
        mode: str,
        model: str,
    ) -> None:
        """后台线程：继续轮询已有 conversation_id 的图片结果。"""
        started = time.time()
        backend = None
        try:
            from services.account_service import account_service
            from services.openai_backend_api import OpenAIBackendAPI
            from services.protocol.conversation import (
                _image_items_from_urls,
                _passthrough_items_to_data,
                format_image_result,
            )

            # C9/P0-2 修复：图片挂在已登录会话上，匿名 token 无权读取该 conversation，
            # 必须按任务记录的原账号 email 找回 token 重连；email 缺失（历史任务）回退匿名。
            account_email = ""
            with self._lock:
                task_snapshot = self._tasks.get(key) or {}
                account_email = _clean(task_snapshot.get("account_email"))
            resume_token = ""
            if account_email:
                account = account_service.get_account_by_email(account_email)
                if not account:
                    raise RuntimeError(
                        f"原账号 {account_email} 已不在号池，无法恢复超时任务的轮询。"
                    )
                resume_token = _clean(account.get("access_token"))
            # 第七轮 B7 修复：OpenAIBackendAPI 无 proxy_url 形参（此前调用即 TypeError，
            # resume-poll 路径必崩且零测试）。代理经 proxy_settings 全局配置在
            # session_pool 内生效，backend 无需显式传代理。
            backend = OpenAIBackendAPI(resume_token) if resume_token else OpenAIBackendAPI()
            file_ids, sediment_ids = backend._poll_image_results(
                conversation_id,
                extra_timeout_secs,
            )
            if not file_ids and not sediment_ids:
                raise RuntimeError(
                    f"继续等待 {extra_timeout_secs} 秒后仍未找到图片结果。"
                )

            image_urls = backend.resolve_conversation_image_urls(
                conversation_id, file_ids, sediment_ids, poll=False,
            )
            if not image_urls:
                raise RuntimeError("图片 URL 解析失败")

            image_items = _image_items_from_urls(backend, image_urls, "")
            # 获取 task 的原始 prompt（从 _public_task 的 mode 判断）
            with self._lock:
                task = self._tasks.get(key)
                _clean(task.get("quality"), "auto") if task else "auto"
                _clean(task.get("size")) if task else None
            if config.image_passthrough_enabled:
                data = _passthrough_items_to_data(image_items, "")
            else:
                data = format_image_result(
                    image_items,
                    "",  # prompt 已不重要，结果已经拿到了
                    "b64_json",
                    "",
                    int(time.time()),
                )["data"]
            self._update_task(key, status=TASK_STATUS_SUCCESS, data=data, error="", duration_ms=int((time.time() - started) * 1000))
            self._log_call(
                identity,
                mode,
                model,
                started,
                "调用完成（续轮询）",
                status="success",
                urls=_collect_image_urls(data),
            )
        except Exception as exc:
            error_message = str(exc) or "resume poll failed"
            duration_ms = int((time.time() - started) * 1000)
            self._update_task(key, status=TASK_STATUS_ERROR, error=error_message, data=[], duration_ms=duration_ms)
            self._log_call(
                identity,
                mode,
                model,
                started,
                "调用失败（续轮询）",
                status="failed",
                error=error_message,
            )
        finally:
            # B1：无论成败，结束续轮询后清除 in-flight 标记，允许再次 resume
            try:
                with self._lock:
                    current = self._tasks.get(key)
                    if current is not None:
                        current.pop("resume_inflight", None)
                        self._save_locked()
            except Exception:
                pass  # 落盘失败不阻塞 backend 关闭
            if backend is not None:
                backend.close()


image_task_service = ImageTaskService(DATA_DIR / "image_tasks.json")


def _classify_failure_phase(error: str) -> str:
    """v2.9.0：从错误信息识别失败阶段，返回简短标签供日志展示。"""
    err = (error or "").lower()
    if "no available image quota" in err or "no available" in err:
        return "无可用账号"
    if "circuit" in err and "open" in err:
        return "熔断器OPEN"
    if "quota" in err and ("zero" in err or "exhausted" in err or "=0" in err):
        return "额度耗尽"
    if "cloudflare" in err or "cf-mitigated" in err or "just a moment" in err or "cf_clearance" in err:
        return "CF拦截"
    if "401" in err or "invalid_access_token" in err or "app_session_terminated" in err:
        return "token失效"
    if "429" in err or "rate_limit" in err or "限流" in err:
        return "上游限流"
    if "timeout" in err or "超时" in err:
        return "网络超时"
    if "content_policy" in err or "policy" in err:
        return "内容政策"
    if "no_image_generated" in err or "completed without generating" in err:
        return "未生成图片"
    if "tls" in err or "connection" in err or "ssl" in err:
        return "连接错误"
    return ""
