"""Tracing 中间件单测。"""
from __future__ import annotations

from services.tracing import TracedMiddleware, get_trace_id, set_trace_id


class TestTracing:
    def test_trace_id_isolation(self):
        """同一线程内 trace_id 应正确设置和读取。"""
        set_trace_id("test-trace-1")
        assert get_trace_id() == "test-trace-1"

    def test_trace_id_reset(self):
        """trace_id 应能被重置。"""
        set_trace_id("test-trace-2")
        set_trace_id("")
        assert get_trace_id() == ""

    def test_trace_id_default_empty(self):
        """未设置时 trace_id 默认空字符串。"""
        # 使用新线程确保 contextvar 未被污染
        import threading

        result = []

        def _check():
            result.append(get_trace_id())

        t = threading.Thread(target=_check)
        t.start()
        t.join()
        assert result[0] == ""
