"""救号工作流（v2.38.0 G2）：异步救号任务 + 结果台账 + 可查状态。

目标：救号从「同步阻塞的 CLI/端点」升级为「任务队列异步 + 进度/结果可查」，
前端据此做救号工作台（分类 → 发起 → 逐账号进度 → 结果面板）。

设计：
- start_revive() 提交任务队列（HIGH 优先级），不阻塞调用方；
- task_handler 由 task_queue 消费者线程执行，调 account_service.revive_accounts 后
  落台账 + 发 revive.finished 事件（大批失败也能通知，不静默）；
- ReviveLedger 落盘 data/revive_ledger.jsonl（append + 锁 + 行数裁剪），
  recent()/stats() 供前端面板与看板使用。

红线：不删/不改既有 /api/accounts/revive 同步端点契约；task_queue/event_bus
既有 API 只使用不改动。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from services.event_bus import Event, event_bus
from services.storage.json_storage import _atomic_write_text
from services.task_queue import Task, TaskPriority, task_queue

logger = logging.getLogger(__name__)

REVIVE_TASK_NAME = "revive_workflow"
REVIVE_FINISHED_EVENT = "revive.finished"
LEDGER_MAX_RUNS = 200          # 台账最多保留 200 次 run，超出裁剪最旧
LEDGER_FAILURE_DETAIL_LIMIT = 20  # 每次 run 失败明细最多记 20 条


def _normalize_tokens(access_tokens: list[str]) -> list[str]:
    return list(dict.fromkeys(
        str(token or "").strip() for token in (access_tokens or []) if str(token or "").strip()
    ))


class ReviveLedger:
    """救号结果台账：append 落盘 + 线程安全 + 行数裁剪。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (Path(str(DATA_DIR)) / "revive_ledger.jsonl")
        self._lock = threading.Lock()

    def _read_all(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except (json.JSONDecodeError, TypeError):
                        continue
        except OSError:
            return []
        return rows

    def record_run(self, run_id: str, summary: dict[str, Any]) -> None:
        """追加一次 run 汇总；超过 LEDGER_MAX_RUNS 裁剪最旧。失败不抛（不阻断救号主流程）。"""
        try:
            with self._lock:
                rows = self._read_all()
                rows.append({
                    "run_id": run_id,
                    "ts": time.time(),
                    "revived": int(summary.get("revived") or 0),
                    "failed": len(summary.get("failed") or []),
                    "skipped": len(summary.get("skipped") or []),
                    "failures": [dict(x) for x in (summary.get("failed") or [])][:LEDGER_FAILURE_DETAIL_LIMIT],
                })
                if len(rows) > LEDGER_MAX_RUNS:
                    rows = rows[-LEDGER_MAX_RUNS:]
                content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
                _atomic_write_text(self._path, content)
        except Exception as exc:  # noqa: BLE001 - 台账失败不阻断救号
            logger.warning("救号台账落盘失败: %s", exc)

    def recent(self, run_limit: int = 5) -> list[dict[str, Any]]:
        """最近 N 次 run 汇总（新→旧）。"""
        with self._lock:
            rows = self._read_all()
            return list(reversed(rows[-run_limit:]))

    def stats(self) -> dict[str, Any]:
        """累计统计 + 最近 run。"""
        with self._lock:
            rows = self._read_all()
        total_revived = sum(int(r.get("revived") or 0) for r in rows)
        total_failed = sum(int(r.get("failed") or 0) for r in rows)
        total_skipped = sum(int(r.get("skipped") or 0) for r in rows)
        return {
            "total_runs": len(rows),
            "total_revived": total_revived,
            "total_failed": total_failed,
            "total_skipped": total_skipped,
            "recent": list(reversed(rows[-5:])),
        }


def _publish_revive_finished(summary: dict[str, Any]) -> None:
    """发布 revive.finished 事件（含计数），大批失败也通知。失败不阻断。"""
    try:
        event_bus.publish(Event(REVIVE_FINISHED_EVENT, {
            "revived": int(summary.get("revived") or 0),
            "failed": len(summary.get("failed") or []),
            "skipped": len(summary.get("skipped") or []),
            "source": "revive_workflow",
        }))
    except Exception as exc:  # noqa: BLE001
        logger.warning("救号完成事件发布失败: %s", exc)


def _get_account_service():
    """惰性取 account_service（延迟 import 防循环依赖 + 便于测试替换）。"""
    from services.account_service import account_service

    return account_service


def task_handler(task: Task) -> dict[str, Any]:
    """救号任务处理器：由 task_queue 消费者线程调用。

    完成/异常由 task_queue 统一 complete/fail（消费者循环已处理），
    本 handler 负责：执行救号 → 落台账 → 发完成事件 → 返回结果。
    """
    tokens = _normalize_tokens((task.metadata or {}).get("access_tokens") or [])
    if not tokens:
        raise ValueError("revive_workflow: access_tokens 为空")

    account_service = _get_account_service()
    summary = account_service.revive_accounts(tokens)
    if not isinstance(summary, dict):
        summary = {"revived": 0, "failed": [], "skipped": []}

    run_id = task.id
    revive_ledger.record_run(run_id, summary)
    _publish_revive_finished(summary)
    return {
        "run_id": run_id,
        "revived": int(summary.get("revived") or 0),
        "failed": len(summary.get("failed") or []),
        "skipped": len(summary.get("skipped") or []),
        "failed_detail": (summary.get("failed") or [])[:LEDGER_FAILURE_DETAIL_LIMIT],
    }


def start_revive(access_tokens: list[str]) -> str:
    """异步提交救号任务，返回 task_id。空 tokens 抛 ValueError。

    幂等：相同 tokens 若已有 pending/running 任务，复用该 task_id（防重复救号）。
    """
    tokens = _normalize_tokens(access_tokens)
    if not tokens:
        raise ValueError("access_tokens is required")

    sig = "|".join(tokens)
    with _RUN_LOCK:
        existing = _RUNNING_SIG.get(sig)
        if existing:
            t = task_queue.status(existing)
            if t and t.status in ("pending", "running"):
                return existing
        task_id = task_queue.enqueue(
            REVIVE_TASK_NAME,
            priority=TaskPriority.HIGH,
            metadata={"access_tokens": tokens, "_sig": sig},
        )
        _RUNNING_SIG[sig] = task_id
        # 惰性清理终止 sig（防无界增长）
        for key, tid in list(_RUNNING_SIG.items()):
            st = task_queue.status(tid)
            if st and st.status in ("success", "error", "cancelled"):
                _RUNNING_SIG.pop(key, None)
    return task_id


def get_revive_status(task_id: str) -> dict[str, Any]:
    """查救号任务状态。"""
    t = task_queue.status(task_id)
    if t is None:
        return {"task_id": task_id, "status": "unknown"}
    return {
        "task_id": t.id,
        "status": t.status,
        "result": t.result,
        "error": t.error,
        "elapsed": t.elapsed,
    }


revive_ledger = ReviveLedger()
_RUN_LOCK = threading.Lock()
_RUNNING_SIG: dict[str, str] = {}
