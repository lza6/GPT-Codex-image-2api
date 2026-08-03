from __future__ import annotations

import hashlib
import itertools
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from services.config import DATA_DIR
from services.protocol.error_response import anthropic_error_response, openai_error_response
from utils.helper import anthropic_sse_stream, sse_json_stream

LOG_TYPE_CALL = "call"
LOG_TYPE_ACCOUNT = "account"
INTERNAL_RESPONSE_KEYS = {"_account_email", "_conversation_id"}


class LogService:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._add_count = 0
        # 读-改-写路径（delete/_auto_cleanup）进程内互斥（第七轮 B16 部分缓解：
        # append 快路径不加锁，但覆写类操作必须互斥防 lost-update）
        import threading
        self._write_lock = threading.Lock()

    @staticmethod
    def _legacy_id(raw_line: str, line_number: int) -> str:
        payload = f"{line_number}:{raw_line}".encode("utf-8", errors="ignore")
        return hashlib.sha1(payload).hexdigest()[:24]

    def _parse_line(self, raw_line: str, line_number: int) -> dict[str, Any] | None:
        try:
            item = json.loads(raw_line)
        except Exception:
            return None
        if not isinstance(item, dict):
            return None
        parsed = dict(item)
        parsed["id"] = str(parsed.get("id") or self._legacy_id(raw_line, line_number))
        return parsed

    @staticmethod
    def _serialize_item(item: dict[str, Any]) -> str:
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _matches_filters(item: dict[str, Any], *, type: str = "", start_date: str = "", end_date: str = "") -> bool:
        # 兼容 text 格式 'time' 与 json 格式 'ts'（json 无 'time' 键，否则日期筛选全失效）
        t = str(item.get("time") or item.get("ts") or "")
        day = t[:10]
        if type and item.get("type") != type:
            return False
        if start_date and day < start_date:
            return False
        if end_date and day > end_date:
            return False
        return True

    def _structured_item(self, type: str, summary: str, detail: dict[str, Any]) -> dict[str, Any]:
        """构造结构化 JSON 日志条目（LOG_FORMAT=json 时使用）。"""
        try:
            from services.metrics_service import get_request_id
            request_id = get_request_id()
        except Exception:
            request_id = ""
        return {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "level": "info",
            "logger": "chatgpt2api",
            "request_id": request_id,
            "type": type,
            "summary": summary,
            "detail": detail,
        }

    def add(self, type: str, summary: str = "", detail: dict[str, Any] | None = None, **data: Any) -> None:
        detail = detail or data
        # 统一注入 request_id（text 和 json 格式都带，保证全链路追踪一致）
        try:
            from services.metrics_service import get_request_id
            request_id = get_request_id()
            if request_id and "request_id" not in detail:
                detail = {**detail, "request_id": request_id}
        except Exception:
            pass
        if os.getenv("LOG_FORMAT", "").strip().lower() == "json":
            item = self._structured_item(type, summary, detail)
        else:
            item = {
                "id": uuid4().hex,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "type": type,
                "summary": summary,
                "detail": detail,
            }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(self._serialize_item(item) + "\n")
        # 惰性清理：每 200 条检查一次，避免高频 I/O
        self._add_count += 1
        if self._add_count >= 200:
            self._add_count = 0
            self._auto_cleanup()

    # ---- 自动清理 ----
    _AUTO_CLEAN_MAX_ENTRIES = 5000
    _AUTO_CLEAN_KEEP = 3000

    def _auto_cleanup(self) -> None:
        """日志条数超限时自动裁剪到保留量，防止无限增长（互斥+原子写）。

        失败必须可观测（第七轮 review #2：此前 except: pass 静默吞，
        清理持续失败会磁盘写满而无任何痕迹）。
        """
        try:
            if not self.path.exists():
                return
            with self._write_lock:
                lines = self.path.read_text(encoding="utf-8").splitlines()
                if len(lines) <= self._AUTO_CLEAN_MAX_ENTRIES:
                    return
                kept = lines[-self._AUTO_CLEAN_KEEP:]
                from services.storage.json_storage import _atomic_write_text
                _atomic_write_text(self.path, "\n".join(kept) + "\n")
        except Exception:
            import logging
            logging.getLogger(__name__).warning("log auto-cleanup failed", exc_info=True)

    def list(self, type: str = "", start_date: str = "", end_date: str = "", limit: int = 200) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items: list[dict[str, Any]] = []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for line_number in range(len(lines) - 1, -1, -1):
            item = self._parse_line(lines[line_number], line_number)
            if item is None:
                continue
            if not self._matches_filters(item, type=type, start_date=start_date, end_date=end_date):
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items

    def delete(self, ids: list[str]) -> dict[str, int]:
        target_ids = {str(item or "").strip() for item in ids if str(item or "").strip()}
        if not self.path.exists() or not target_ids:
            return {"removed": 0}
        with self._write_lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            kept_lines: list[str] = []
            removed = 0
            for line_number, raw_line in enumerate(lines):
                item = self._parse_line(raw_line, line_number)
                if item is None:
                    kept_lines.append(raw_line)
                    continue
                if str(item.get("id") or "") in target_ids:
                    removed += 1
                    continue
                kept_lines.append(self._serialize_item(item))
            content = "\n".join(kept_lines)
            if content:
                content += "\n"
            from services.storage.json_storage import _atomic_write_text
            _atomic_write_text(self.path, content)
        return {"removed": removed}


log_service = LogService(DATA_DIR / "logs.jsonl")


def _collect_urls(value: object) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "url" and isinstance(item, str):
                urls.append(item)
            elif key == "urls" and isinstance(item, list):
                urls.extend(str(url) for url in item if isinstance(url, str))
            else:
                urls.extend(_collect_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_collect_urls(item))
    return urls


def _collect_account_emails(value: object) -> list[str]:
    emails: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"_account_email", "account_email"} and isinstance(item, str) and item.strip():
                emails.append(item.strip())
            else:
                emails.extend(_collect_account_emails(item))
    elif isinstance(value, list):
        for item in value:
            emails.extend(_collect_account_emails(item))
    return emails


def _collect_conversation_ids(value: object) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "_conversation_id" and isinstance(item, str) and item.strip():
                ids.append(item.strip())
            else:
                ids.extend(_collect_conversation_ids(item))
    elif isinstance(value, list):
        for item in value:
            ids.extend(_collect_conversation_ids(item))
    return ids


def _strip_internal_response_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _strip_internal_response_fields(item)
            for key, item in value.items()
            if key not in INTERNAL_RESPONSE_KEYS
        }
    if isinstance(value, list):
        return [_strip_internal_response_fields(item) for item in value]
    return value


def _request_excerpt(text: object, limit: int = 1000) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _build_local_no_quota_debug() -> dict[str, Any]:
    """本地账号池拒选调试摘要：脱敏账号快照，便于一眼看出是限流/无配额/被熔断。"""
    try:
        from services.account_service import account_service

        accounts = list(account_service.list_accounts() or [])
        summary = [
            {
                "email": str(a.get("email") or "").strip(),
                "status": str(a.get("status") or "").strip(),
                "quota": a.get("quota"),
                "restore_at": a.get("restore_at"),
                "plan_type": str(a.get("type") or "").strip(),
                "source_type": str(a.get("source_type") or "").strip(),
            }
            for a in accounts[:10]
        ]
        return {
            "kind": "local_no_quota",
            "reason": "账号池内全部限流/无配额（未发起上游请求）",
            "tried_accounts": len(accounts),
            "accounts_summary": summary,
            "hint": "等待 restore_at 恢复，或到 accounts 页添加更多账号",
        }
    except Exception:  # noqa: BLE001
        return {"kind": "local_no_quota", "reason": "账号池内全部限流/无配额"}


def _build_upstream_http_debug(exc: Exception) -> dict[str, Any]:
    """上游 HTTP 错误调试摘要：状态码 + retry_after + 原始 body。"""
    body = getattr(exc, "body", None)
    if isinstance(body, (dict, list)):
        body_repr: Any = body
    else:
        body_repr = str(body or "")[:1000]
    return {
        "kind": "upstream_http",
        "reason": "OpenAI 上游返回非 2xx",
        "upstream_status_code": getattr(exc, "status_code", None),
        "upstream_retry_after": getattr(exc, "retry_after", None),
        "upstream_context": getattr(exc, "context", ""),
        "upstream_body": body_repr,
    }


def _image_error_response(exc: Exception) -> JSONResponse:
    from services.protocol.conversation import public_image_error_message

    message = public_image_error_message(str(exc))
    if "no available image quota" in message.lower():
        # 直接构造 JSONResponse：openai_error_payload 白名单只挑 message/type/param/code，
        # 会丢掉 debug 字段，所以这里不走 openai_error_response。
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": "no available image quota",
                    "type": "insufficient_quota",
                    "param": None,
                    "code": "insufficient_quota",
                    "debug": _build_local_no_quota_debug(),
                }
            },
        )
    if hasattr(exc, "to_openai_error") and hasattr(exc, "status_code"):
        return JSONResponse(status_code=int(exc.status_code), content=exc.to_openai_error())
    # UpstreamHTTPError：透传上游真实状态码/body 便于调试
    from utils.helper import UpstreamHTTPError

    if isinstance(exc, UpstreamHTTPError):
        debug = _build_upstream_http_debug(exc)
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": message,
                    "type": "upstream_error",
                    "param": None,
                    "code": f"upstream_http_{exc.status_code}",
                    "debug": debug,
                }
            },
        )
    return openai_error_response(message, 502)


def _protocol_error_response(exc: Exception, status_code: int, sse: str) -> JSONResponse:
    message = str(exc)
    if sse == "anthropic":
        return anthropic_error_response(message, status_code)
    return openai_error_response(message, status_code)


def _next_item(items):
    try:
        return True, next(items)
    except StopIteration:
        return False, None


@dataclass
class LoggedCall:
    identity: dict[str, object]
    endpoint: str
    model: str
    summary: str
    started: float = field(default_factory=time.time)
    request_text: str = ""
    request_shape: dict[str, int] | None = None

    async def run(self, handler, *args, sse: str = "openai"):
        from services.protocol.conversation import ImageGenerationError

        try:
            result = await run_in_threadpool(handler, *args)
        except ImageGenerationError as exc:
            self.log("调用失败", status="failed", error=str(exc), account_email=getattr(exc, "account_email", ""),
                     conversation_id=getattr(exc, "conversation_id", ""))
            return _image_error_response(exc)
        except HTTPException as exc:
            self.log("调用失败", status="failed", error=str(exc.detail))
            raise
        except Exception as exc:
            self.log("调用失败", status="failed", error=str(exc), account_email=getattr(exc, "account_email", ""))
            if self.endpoint.startswith("/v1/images"):
                return _image_error_response(exc)
            return _protocol_error_response(exc, 502, sse)

        if isinstance(result, dict):
            self.log("调用完成", result)
            response = dict(result)
            response.pop("_account_email", None)
            return response

        sender = anthropic_sse_stream if sse == "anthropic" else sse_json_stream
        try:
            has_first, first = await run_in_threadpool(_next_item, result)
        except ImageGenerationError as exc:
            self.log("调用失败", status="failed", error=str(exc), account_email=getattr(exc, "account_email", ""),
                     conversation_id=getattr(exc, "conversation_id", ""))
            return _image_error_response(exc)
        except HTTPException as exc:
            self.log("调用失败", status="failed", error=str(exc.detail))
            raise
        except Exception as exc:
            self.log("调用失败", status="failed", error=str(exc), account_email=getattr(exc, "account_email", ""))
            if self.endpoint.startswith("/v1/images"):
                return _image_error_response(exc)
            return _protocol_error_response(exc, 502, sse)
        if not has_first:
            self.log("流式调用结束")
            return StreamingResponse(sender(()), media_type="text/event-stream")
        return StreamingResponse(sender(self.stream(itertools.chain([first], result))), media_type="text/event-stream")

    def stream(self, items):
        urls: list[str] = []
        account_emails: list[str] = []
        conversation_ids: list[str] = []
        failed = False
        try:
            for item in items:
                urls.extend(_collect_urls(item))
                account_emails.extend(_collect_account_emails(item))
                conversation_ids.extend(_collect_conversation_ids(item))
                yield _strip_internal_response_fields(item)
        except Exception as exc:
            failed = True
            self.log(
                "流式调用失败",
                status="failed",
                error=str(exc),
                urls=urls,
                account_email=(account_emails[0] if account_emails else getattr(exc, "account_email", "")),
                conversation_id=(conversation_ids[0] if conversation_ids else getattr(exc, "conversation_id", "")),
            )
            if self.endpoint.startswith("/v1/images") and not hasattr(exc, "to_openai_error"):
                from services.protocol.conversation import ImageGenerationError, public_image_error_message

                raise ImageGenerationError(public_image_error_message(str(exc))) from exc
            raise
        finally:
            if not failed:
                self.log("流式调用结束", urls=urls, account_email=account_emails[0] if account_emails else "",
                         conversation_id=conversation_ids[0] if conversation_ids else "")

    def log(self, suffix: str, result: object = None, status: str = "success", error: str = "",
            urls: list[str] | None = None, account_email: str = "", conversation_id: str = "") -> None:
        # 读取请求级 request_id，实现全链路追踪（配合 metrics 中间件）
        try:
            from services.metrics_service import get_request_id
            request_id = get_request_id()
        except Exception:
            request_id = ""
        detail = {
            "key_id": self.identity.get("id"),
            "key_name": self.identity.get("name"),
            "role": self.identity.get("role"),
            "endpoint": self.endpoint,
            "model": self.model,
            "started_at": datetime.fromtimestamp(self.started).strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration_ms": int((time.time() - self.started) * 1000),
            "status": status,
        }
        if request_id:
            detail["request_id"] = request_id
        request_excerpt = _request_excerpt(self.request_text)
        if request_excerpt:
            detail["request_text"] = request_excerpt
        if self.request_shape:
            detail["request_shape"] = self.request_shape
        if error:
            detail["error"] = error
        email = str(account_email or "").strip()
        if not email:
            emails = _collect_account_emails(result)
            email = emails[0] if emails else ""
        if email:
            detail["account_email"] = email
        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            conv_ids = _collect_conversation_ids(result)
            conv_id = conv_ids[0] if conv_ids else ""
        if conv_id:
            detail["conversation_id"] = conv_id
        collected_urls = [*(urls or []), *_collect_urls(result)]
        if collected_urls and not self.endpoint.startswith("/v1/search"):
            detail["urls"] = list(dict.fromkeys(collected_urls))
        log_service.add(LOG_TYPE_CALL, f"{self.summary}{suffix}", detail)
