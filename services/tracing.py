"""6.1-6.3：完整请求追踪系统。

功能：
- Span（TraceSpan）dataclass：name/start/end/duration_ms/status/error/attributes
- Tracer 上下文管理器：with tracer.span("op") 自动记录耗时
- 慢请求阈值可配置，超过阈值的 span 持久化到 data/traces/slow-YYYY-MM-DD.jsonl
- 5xx 错误追踪到 data/traces/error-YYYY-MM-DD.jsonl
- 分布式追踪（X-Trace-ID 头透传）
- 通过 contextvars 传递 trace_id，被 metrics_service 和 log_service 消费
- 零额外依赖，零启动开销
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("chatgpt2api_trace_id", default="")
_span_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("chatgpt2api_span_id", default="")


def get_trace_id() -> str:
    return _trace_id_ctx.get()


def set_trace_id(trace_id: str) -> None:
    _trace_id_ctx.set(trace_id)


@dataclass
class TraceSpan:
    name: str
    trace_id: str
    span_id: str
    parent_id: str = ""
    start: float = 0.0
    end: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str = ""

    @property
    def duration_ms(self) -> float:
        if self.end > 0 and self.start > 0:
            return (self.end - self.start) * 1000
        return 0.0

    @property
    def start_time(self) -> float:
        return self.start

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self.attributes)

    @property
    def is_slow(self) -> bool:
        return self.status == "slow"


Span = TraceSpan


class Tracer:
    def __init__(self, max_spans: int = 10000) -> None:
        self._spans: list[TraceSpan] = []
        self._max_spans = max_spans
        self._slow_threshold_ms: float = 5000.0
        self._sample_rate: float = 1.0
        self._traces_dir: Path | None = None
        self._lock = Lock()

    def configure(self, sample_rate: float = 1.0, slow_threshold_ms: float = 5000.0, traces_dir: Path | None = None) -> None:
        self._sample_rate = max(0.0, min(1.0, sample_rate))
        self._slow_threshold_ms = max(0.0, slow_threshold_ms)
        self._traces_dir = traces_dir
        if self._traces_dir is not None:
            self._traces_dir.mkdir(parents=True, exist_ok=True)

    @property
    def slow_threshold_ms(self) -> float:
        return self._slow_threshold_ms

    @slow_threshold_ms.setter
    def slow_threshold_ms(self, value: float) -> None:
        self._slow_threshold_ms = max(0.0, float(value))

    def span(self, name: str, metadata: dict[str, Any] | None = None) -> _SimpleSpanContext:
        trace_id = get_trace_id() or uuid.uuid4().hex[:16]
        parent_id = _span_id_ctx.get()
        return _SimpleSpanContext(self, name, trace_id, parent_id, metadata or {})

    def start_span(self, name: str, trace_id: str = "", parent_id: str = "") -> SpanContext:
        if not trace_id:
            trace_id = uuid.uuid4().hex[:16]
        return SpanContext(self, name, trace_id, parent_id)

    def _record_span(self, span: TraceSpan) -> None:
        with self._lock:
            self._spans.append(span)
            if len(self._spans) > self._max_spans:
                self._spans = self._spans[-self._max_spans:]
        if span.duration_ms > self._slow_threshold_ms and self._traces_dir is not None:
            self._write_trace(span, "slow")
        if span.status == "error" and self._traces_dir is not None:
            self._write_trace(span, "error")

    def _write_trace(self, span: TraceSpan, kind: str) -> None:
        if self._traces_dir is None:
            return
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        path = self._traces_dir / f"{kind}-{today}.jsonl"
        entry = {"name": span.name, "trace_id": span.trace_id, "span_id": span.span_id, "parent_id": span.parent_id, "start_time": span.start_time, "duration_ms": round(span.duration_ms, 1), "status": span.status, "error": span.error, "attributes": {k: v for k, v in span.attributes.items() if k != "duration_ms"}}
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("写%s追踪文件失败 %s: %s", kind, path, exc)

    def get_slow_traces(self, limit: int = 50) -> list[TraceSpan]:
        with self._lock:
            slow = [s for s in self._spans if s.duration_ms > self._slow_threshold_ms or s.status == "slow"]
        return sorted(slow, key=lambda s: s.start, reverse=True)[:limit]

    def get_all_traces(self, limit: int = 50) -> list[TraceSpan]:
        with self._lock:
            result = list(self._spans)
        return sorted(result, key=lambda s: s.start, reverse=True)[:limit]

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._spans)
            slow = sum(1 for s in self._spans if s.duration_ms > self._slow_threshold_ms or s.status == "slow")
            errors = sum(1 for s in self._spans if s.status == "error")
            avg_duration = sum(s.duration_ms for s in self._spans) / total if total else 0.0
            max_duration = max((s.duration_ms for s in self._spans), default=0.0)
            return {"total_spans": total, "slow_spans": slow, "error_spans": errors, "avg_duration_ms": round(avg_duration, 1), "max_duration_ms": round(max_duration, 1), "buffer_capacity": self._max_spans, "slow_threshold_ms": self._slow_threshold_ms, "sample_rate": self._sample_rate, "traces_dir": str(self._traces_dir) if self._traces_dir else ""}


class _SimpleSpanContext:
    def __init__(self, tracer: Tracer, name: str, trace_id: str, parent_id: str, metadata: dict[str, Any]) -> None:
        self._tracer = tracer
        self._span = TraceSpan(name=name, trace_id=trace_id, span_id=uuid.uuid4().hex[:16], parent_id=parent_id, start=time.time(), attributes=dict(metadata))

    def __enter__(self) -> TraceSpan:
        return self._span

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._span.end = time.time()
        self._span.attributes["duration_ms"] = self._span.duration_ms
        if exc_type is not None:
            self._span.status = "error"
            self._span.error = str(exc_val)[:200] if exc_val else exc_type.__name__
        elif self._span.duration_ms > self._tracer.slow_threshold_ms:
            self._span.status = "slow"
        self._tracer._record_span(self._span)


class SpanContext:
    def __init__(self, tracer: Tracer, name: str, trace_id: str, parent_id: str = "") -> None:
        self._tracer = tracer
        self._span = TraceSpan(name=name, trace_id=trace_id, span_id=uuid.uuid4().hex[:16], parent_id=parent_id, start=time.time())
        self._span_id_snapshot: str = ""

    @property
    def span_id(self) -> str:
        return self._span.span_id

    @property
    def span(self) -> TraceSpan:
        return self._span

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.attributes[key] = value

    def end_span(self) -> None:
        self._span.end = time.time()
        self._span.attributes["duration_ms"] = self._span.duration_ms
        if self._span.status == "error" and not self._span.error:
            self._span.error = "unknown error"
        _span_id_ctx.set(self._span_id_snapshot)
        self._tracer._record_span(self._span)

    def __enter__(self) -> SpanContext:
        self._span_id_snapshot = _span_id_ctx.get()
        _span_id_ctx.set(self._span.span_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._span.end = time.time()
        self._span.attributes["duration_ms"] = self._span.duration_ms
        if exc_type is not None:
            self._span.status = "error"
            self._span.error = str(exc_val)[:500] if exc_val else exc_type.__name__
        _span_id_ctx.set(self._span_id_snapshot)
        self._tracer._record_span(self._span)


tracer = Tracer()


class TracedMiddleware:
    def __init__(self, app, sample_rate: float = 1.0, slow_threshold_ms: float = 5000.0, traces_dir: Path | None = None) -> None:
        self.app = app
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self.slow_threshold_ms = max(0.0, slow_threshold_ms)
        self.traces_dir = traces_dir

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        headers_str = {k.decode("utf-8", errors="replace"): v.decode("utf-8", errors="replace") for k, v in headers.items()}
        upstream_trace_id = headers_str.get("x-trace-id", "")
        upstream_request_id = headers_str.get("x-request-id", "")
        trace_id = upstream_trace_id or upstream_request_id or uuid.uuid4().hex[:16]
        set_trace_id(trace_id)
        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        status_code = [200]
        error_msg = [""]

        async def _send_wrapper(message):
            if message["type"] == "http.response.start":
                status_code[0] = message.get("status", 200)
            await send(message)

        with tracer.start_span(f"{method} {path}", trace_id=trace_id) as ctx:
            ctx.set_attribute("method", method)
            ctx.set_attribute("path", path)
            if upstream_trace_id:
                ctx.set_attribute("upstream_trace_id", upstream_trace_id)
            if upstream_request_id:
                ctx.set_attribute("upstream_request_id", upstream_request_id)
            try:
                await self.app(scope, receive, _send_wrapper)
            except Exception as exc:
                error_msg[0] = str(exc)[:200]
                ctx.set_attribute("error", error_msg[0])
                raise
            finally:
                ctx.set_attribute("http.status_code", status_code[0])
                if 500 <= status_code[0] <= 599:
                    ctx.span.status = "error"
                    ctx.span.error = error_msg[0] or f"HTTP {status_code[0]}"
                if ctx.span.duration_ms > self.slow_threshold_ms:
                    ctx.span.status = "slow"
        set_trace_id("")
