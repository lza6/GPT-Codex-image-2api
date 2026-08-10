import pathlib
content = '''"""Tracing 系统单测。"""
from __future__ import annotations
from services.tracing import Span, Tracer, get_trace_id, set_trace_id, tracer


class TestTraceId:
    def test_trace_id_isolation(self):
        set_trace_id("test-trace-1")
        assert get_trace_id() == "test-trace-1"

    def test_trace_id_reset(self):
        set_trace_id("test-trace-2")
        set_trace_id("")
        assert get_trace_id() == ""

    def test_trace_id_default_empty(self):
        import threading
        result = []
        def _check():
            result.append(get_trace_id())
        t = threading.Thread(target=_check)
        t.start()
        t.join()
        assert result[0] == ""


class TestSpan:
    def test_span_defaults(self):
        span = Span(name="test", start_time=100.0)
        assert span.name == "test"
        assert span.status == "ok"
        assert span.duration_ms == 0.0
        assert span.error == ""

    def test_span_is_slow(self):
        span = Span(name="slow", start_time=100.0, status="slow")
        assert span.is_slow is True

    def test_span_not_slow(self):
        span = Span(name="ok", start_time=100.0, status="ok")
        assert span.is_slow is False

    def test_span_error(self):
        span = Span(name="err", start_time=100.0, status="error")
        assert span.is_slow is False


class TestTracer:
    def test_tracer_span_context_manager(self):
        t = Tracer(max_spans=10)
        t.slow_threshold_ms = 100000.0
        with t.span("test_op") as span:
            assert span.name == "test_op"
        assert span.duration_ms > 0
        assert span.status == "ok"

    def test_tracer_span_metadata(self):
        t = Tracer(max_spans=10)
        t.slow_threshold_ms = 100000.0
        with t.span("test_op", metadata={"key": "value"}):
            pass
        spans = t.get_all_traces()
        assert spans[0].metadata.get("key") == "value"

    def test_tracer_slow_span(self):
        t = Tracer(max_spans=10)
        t.slow_threshold_ms = 0.0
        with t.span("slow_op"):
            import time
            time.sleep(0.001)
        slow = t.get_slow_traces()
        assert len(slow) >= 1
        assert slow[0].name == "slow_op"

    def test_tracer_buffer_capacity(self):
        t = Tracer(max_spans=3)
        t.slow_threshold_ms = 100000.0
        for i in range(5):
            with t.span(f"op_{i}"):
                pass
        spans = t.get_all_traces()
        assert len(spans) == 3

    def test_tracer_clear(self):
        t = Tracer(max_spans=10)
        t.slow_threshold_ms = 100000.0
        with t.span("op"):
            pass
        assert len(t.get_all_traces()) == 1
        t.clear()
        assert len(t.get_all_traces()) == 0

    def test_tracer_get_stats(self):
        t = Tracer(max_spans=10)
        t.slow_threshold_ms = 100000.0
        with t.span("op1"):
            pass
        stats = t.get_stats()
        assert stats["total_spans"] == 1
        assert stats["slow_spans"] == 0
        assert stats["error_spans"] == 0
        assert stats["avg_duration_ms"] >= 0

    def test_tracer_get_stats_with_slow(self):
        t = Tracer(max_spans=10)
        t.slow_threshold_ms = 0.0
        with t.span("slow_op"):
            import time
            time.sleep(0.001)
        stats = t.get_stats()
        assert stats["slow_spans"] >= 1

    def test_tracer_get_all_traces_order(self):
        t = Tracer(max_spans=10)
        t.slow_threshold_ms = 100000.0
        with t.span("first"):
            pass
        with t.span("second"):
            pass
        spans = t.get_all_traces()
        assert spans[0].name == "second"
        assert spans[1].name == "first"

    def test_tracer_get_slow_traces_limit(self):
        t = Tracer(max_spans=10)
        t.slow_threshold_ms = 0.0
        for i in range(5):
            with t.span(f"op_{i}"):
                pass
        slow = t.get_slow_traces(limit=2)
        assert len(slow) == 2


class TestTracerErrors:
    def test_tracer_span_exception(self):
        t = Tracer(max_spans=10)
        t.slow_threshold_ms = 100000.0
        try:
            with t.span("error_op"):
                raise ValueError("test error")
        except ValueError:
            pass
        spans = t.get_all_traces()
        assert spans[0].status == "error"
        assert "test error" in spans[0].error


class TestTracingAPI:
    def test_traces_endpoint(self):
        from fastapi.testclient import TestClient
        from api.app import create_app
        app = create_app()
        client = TestClient(app)
        with tracer.span("test_api"):
            pass
        response = client.get("/api/tracing/traces")
        assert response.status_code == 200
        data = response.json()
        assert "spans" in data

    def test_traces_endpoint_slow_only(self):
        from fastapi.testclient import TestClient
        from api.app import create_app
        app = create_app()
        client = TestClient(app)
        tracer.slow_threshold_ms = 0.0
        with tracer.span("test_slow"):
            pass
        tracer.slow_threshold_ms = 5000.0
        response = client.get("/api/tracing/traces", params={"slow_only": True})
        assert response.status_code == 200
        data = response.json()
        assert len(data["spans"]) > 0

    def test_tracing_stats_endpoint(self):
        from fastapi.testclient import TestClient
        from api.app import create_app
        app = create_app()
        client = TestClient(app)
        response = client.get("/api/tracing/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_spans" in data
        assert "slow_spans" in data
        assert "avg_duration_ms" in data
'''
pathlib.Path('test/test_tracing.py').write_text(content, encoding='utf-8')
print(f'Written {len(content)} bytes, {content.count(chr(10))} lines')