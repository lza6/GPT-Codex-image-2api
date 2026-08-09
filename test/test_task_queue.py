from __future__ import annotations

import time
import unittest

from services.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_ERROR,
    TASK_STATUS_PENDING,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCESS,
    TaskPriority,
    TaskQueue,
)


class TestTaskQueue(unittest.TestCase):
    def test_enqueue_returns_task_id(self):
        q = TaskQueue()
        tid = q.enqueue("test task", priority=TaskPriority.NORMAL)
        self.assertIsInstance(tid, str)
        self.assertTrue(len(tid) > 0)

    def test_enqueue_with_custom_id(self):
        q = TaskQueue()
        tid = q.enqueue("custom", task_id="my-id-123")
        self.assertEqual(tid, "my-id-123")

    def test_dequeue_fifo_within_same_priority(self):
        q = TaskQueue()
        t1 = q.enqueue("first", priority=TaskPriority.NORMAL)
        t2 = q.enqueue("second", priority=TaskPriority.NORMAL)
        task1 = q.dequeue()
        task2 = q.dequeue()
        self.assertEqual(task1.name, "first")
        self.assertEqual(task2.name, "second")

    def test_priority_ordering(self):
        q = TaskQueue()
        q.enqueue("low", priority=TaskPriority.LOW)
        q.enqueue("critical", priority=TaskPriority.CRITICAL)
        q.enqueue("high", priority=TaskPriority.HIGH)
        # 应该按优先级出队：CRITICAL → HIGH → LOW
        self.assertEqual(q.dequeue().name, "critical")
        self.assertEqual(q.dequeue().name, "high")
        self.assertEqual(q.dequeue().name, "low")

    def test_dequeue_sets_running_status(self):
        q = TaskQueue()
        tid = q.enqueue("test")
        task = q.dequeue()
        self.assertEqual(task.status, TASK_STATUS_RUNNING)
        self.assertIsNotNone(task.started_at)

    def test_dequeue_returns_none_when_empty(self):
        q = TaskQueue()
        self.assertIsNone(q.dequeue())

    def test_dequeue_skips_cancelled(self):
        q = TaskQueue()
        q.enqueue("cancelled", task_id="c1")
        q.enqueue("valid", task_id="v1")
        q.cancel("c1")
        task = q.dequeue()
        self.assertEqual(task.name, "valid")

    def test_status(self):
        q = TaskQueue()
        tid = q.enqueue("test")
        task = q.status(tid)
        self.assertEqual(task.status, TASK_STATUS_PENDING)
        q.dequeue()
        task = q.status(tid)
        self.assertEqual(task.status, TASK_STATUS_RUNNING)

    def test_status_unknown(self):
        q = TaskQueue()
        self.assertIsNone(q.status("nonexistent"))

    def test_status_batch(self):
        q = TaskQueue()
        t1 = q.enqueue("a", task_id="t1")
        t2 = q.enqueue("b", task_id="t2")
        results = q.status_batch(["t1", "t2", "t3"])
        self.assertEqual(results["t1"].name, "a")
        self.assertEqual(results["t2"].name, "b")
        self.assertIsNone(results["t3"])

    def test_cancel_pending(self):
        q = TaskQueue()
        tid = q.enqueue("cancel me")
        self.assertTrue(q.cancel(tid))
        self.assertEqual(q.status(tid).status, TASK_STATUS_CANCELLED)

    def test_cannot_cancel_running(self):
        q = TaskQueue()
        tid = q.enqueue("running")
        q.dequeue()
        self.assertFalse(q.cancel(tid))

    def test_cancel_unknown(self):
        q = TaskQueue()
        self.assertFalse(q.cancel("nonexistent"))

    def test_complete(self):
        q = TaskQueue()
        tid = q.enqueue("test")
        q.dequeue()
        q.complete(tid, result={"ok": True})
        task = q.status(tid)
        self.assertEqual(task.status, TASK_STATUS_SUCCESS)
        self.assertEqual(task.result, {"ok": True})
        self.assertIsNotNone(task.completed_at)

    def test_fail(self):
        q = TaskQueue()
        tid = q.enqueue("test")
        q.dequeue()
        q.fail(tid, error="something went wrong")
        task = q.status(tid)
        self.assertEqual(task.status, TASK_STATUS_ERROR)
        self.assertEqual(task.error, "something went wrong")

    def test_dequeue_many(self):
        q = TaskQueue()
        for i in range(10):
            q.enqueue(f"task-{i}", priority=TaskPriority.NORMAL)
        tasks = q.dequeue_many(5)
        self.assertEqual(len(tasks), 5)
        self.assertEqual(tasks[0].name, "task-0")
        self.assertEqual(tasks[4].name, "task-4")

    def test_stats(self):
        q = TaskQueue()
        self.assertEqual(q.stats()["total"], 0)
        q.enqueue("a", task_id="t1")
        q.enqueue("b", task_id="t2", priority=TaskPriority.CRITICAL)
        q.dequeue()  # 出队 CRITICAL 优先的 t2
        q.complete("t1")  # t1 仍在 pending，标记为 success
        stats = q.stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["pending"], 0)  # t2 已出队（running），t1 已 complete
        self.assertEqual(stats["running"], 1)  # t2 在运行中
        self.assertEqual(stats["success"], 1)

    def test_cleanup_removes_old_tasks(self):
        q = TaskQueue()
        q.enqueue("old", task_id="old")
        q.dequeue()
        q.complete("old")
        # 手动将 completed_at 设为过去
        with q._lock:
            task = q._tasks["old"]
            task.completed_at = time.time() - 100
        count = q.cleanup(max_age_seconds=10)
        self.assertEqual(count, 1)
        self.assertIsNone(q.status("old"))

    def test_cleanup_keeps_recent_tasks(self):
        q = TaskQueue()
        q.enqueue("recent", task_id="r1")
        q.dequeue()
        q.complete("r1")
        count = q.cleanup(max_age_seconds=3600)
        self.assertEqual(count, 0)
        self.assertIsNotNone(q.status("r1"))

    def test_cleanup_keeps_pending(self):
        q = TaskQueue()
        q.enqueue("pending", task_id="p1")
        count = q.cleanup(max_age_seconds=0)
        self.assertEqual(count, 0)  # pending 不是终态，不清理

    def test_register_handler_and_start_consumer(self):
        q = TaskQueue()
        results = []
        def handler(task):
            results.append(task.name)
            return "done"
        q.register_handler("test_task", handler)
        q.start_consumer()
        q.enqueue("test_task", task_id="t1")
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if q.status("t1") and q.status("t1").status == TASK_STATUS_SUCCESS:
                break
            time.sleep(0.05)
        q.stop_consumer()
        self.assertEqual(results, ["test_task"])
        self.assertEqual(q.status("t1").status, TASK_STATUS_SUCCESS)
        self.assertEqual(q.status("t1").result, "done")

    def test_consumer_no_handler_fails_task(self):
        q = TaskQueue()
        q.start_consumer()
        q.enqueue("unknown_task", task_id="t1")
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if q.status("t1") and q.status("t1").status != TASK_STATUS_PENDING:
                break
            time.sleep(0.05)
        q.stop_consumer()
        self.assertEqual(q.status("t1").status, TASK_STATUS_ERROR)
        self.assertIn("no handler", q.status("t1").error)

    def test_consumer_handler_exception_fails_task(self):
        q = TaskQueue()
        def handler(task):
            raise RuntimeError("handler failed")
        q.register_handler("fail_task", handler)
        q.start_consumer()
        q.enqueue("fail_task", task_id="t1")
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if q.status("t1") and q.status("t1").status != TASK_STATUS_PENDING:
                break
            time.sleep(0.05)
        q.stop_consumer()
        self.assertEqual(q.status("t1").status, TASK_STATUS_ERROR)
        self.assertIn("handler failed", q.status("t1").error)

    def test_start_consumer_idempotent(self):
        q = TaskQueue()
        q.start_consumer()
        thread1 = q._consumer_thread
        q.start_consumer()
        thread2 = q._consumer_thread
        self.assertIs(thread1, thread2)
        q.stop_consumer()


if __name__ == "__main__":
    unittest.main()