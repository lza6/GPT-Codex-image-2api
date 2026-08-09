from __future__ import annotations

import hashlib
import itertools
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    """结构化日志服务（4.1 起按天轮转切分）。

    - 写入：当天文件 `logs-YYYY-MM-DD.jsonl`（不再写单一日志文件）。
    - 读取：`list(days=N)` 只读最近 N 天天文件（默认全量，向后兼容旧调用方），
      `start_date` 更早时自动扩展文件范围（不丢历史）。
    - 迁移：旧 `logs.jsonl` 首次访问时惰性迁移到天文件并 rename 备份，幂等。
    - 清理：过期天文件整删（文件级），当天文件超限裁剪（条目级）。
    """

    # 过期天文件保留天数（与 usage_agg WINDOW_DAYS=90 对齐，保证缓存重建不丢历史）
    _LOG_RETENTION_DAYS = 90

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._log_dir = self.path.parent
        self._add_count = 0
        # 读-改-写路径（delete/_auto_cleanup/迁移）进程内互斥（第七轮 B16 部分缓解：
        # append 快路径不加锁，但覆写类操作必须互斥防 lost-update）
        import threading
        self._write_lock = threading.Lock()
        self._migrated = False

    # ---- 按天路径 ----
    @staticmethod
    def _day_from_name(name: str) -> str:
        """从 `logs-YYYY-MM-DD.jsonl` 提取日期；非天文件返回空串。"""
        if name.startswith("logs-") and name.endswith(".jsonl"):
            return name[5:-6]
        return ""

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _daily_path(self, day: str) -> Path:
        return self._log_dir / f"logs-{day}.jsonl"

    def _daily_files(self) -> list[Path]:
        """所有天文件，按日期升序（旧→新）。"""
        return sorted(self._log_dir.glob("logs-*.jsonl"))

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
    def _matches_filters(item: dict[str, Any], *, type: str = "", start_date: str = "", end_date: str = "", account_email: str = "", event: str = "", request_id: str = "", result: str = "") -> bool:
        # 兼容 text 格式 'time' 与 json 格式 'ts'（json 无 'time' 键，否则日期筛选全失效）
        t = str(item.get("time") or item.get("ts") or "")
        day = t[:10]
        if type and item.get("type") != type:
            return False
        if start_date and day < start_date:
            return False
        if end_date and day > end_date:
            return False
        if account_email:
            # 3.1.1：按账号过滤（模糊匹配）。account_email 可能落在 detail 或内联 _account_email，
            # 用递归收集器统一查找，避免字段位置漂移导致过滤失效。
            needle = account_email.lower()
            emails = _collect_account_emails(item)
            if not any(needle in (email or "").lower() for email in emails):
                return False
        # 字段级过滤（event/request_id/result）——在 detail 子对象里查，兼容结构化日志
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        if event and str(detail.get("event") or "") != event:
            return False
        if request_id and str(item.get("request_id") or detail.get("request_id") or "") != request_id:
            return False
        if result and str(detail.get("result") or "") != result:
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

    def _item_day(self, item: dict[str, Any]) -> str:
        """从条目提取 `YYYY-MM-DD`（兼容 text 'time' / json 'ts' / 历史 'created_at'）。"""
        t = str(item.get("time") or item.get("ts") or item.get("created_at") or "")
        return t[:10]

    def _ensure_migrated(self) -> None:
        """旧 `logs.jsonl` 惰性迁移到天文件（幂等、线程安全、失败不崩）。

        触发点：首次 add/list/delete 前。迁移完成后把旧文件 rename 成
        `logs.jsonl.legacy`（保留备份防误删，同时保证下次不再触发二次迁移）。
        """
        legacy = self.path
        if self._migrated or not legacy.exists():
            self._migrated = True
            return
        with self._write_lock:
            if self._migrated or not legacy.exists():
                return
            batches: dict[str, list[str]] = {}
            try:
                raw_lines = legacy.read_text(encoding="utf-8").splitlines()
            except OSError:
                self._migrated = True
                return
            for line_number, raw_line in enumerate(raw_lines):
                item = self._parse_line(raw_line, line_number)
                if item is None:
                    continue
                day = self._item_day(item) or self._today_str()
                batches.setdefault(day, []).append(self._serialize_item(item))
            for day, lines in batches.items():
                target = self._daily_path(day)
                with target.open("a", encoding="utf-8") as fh:
                    fh.write("\n".join(lines))
                    if lines:
                        fh.write("\n")
            try:
                legacy.rename(self._log_dir / "logs.jsonl.legacy")
            except OSError:
                pass
            self._migrated = True

    def migrate_legacy(self) -> None:
        """公开迁移入口：启动时调用，确保旧 logs.jsonl 在 usage_agg watcher 前完成迁移。"""
        self._ensure_migrated()

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
        # 4.1：先迁移旧单文件，再写当天文件（避免旧数据永久滞留 logs.jsonl）
        self._ensure_migrated()
        target = self._daily_path(self._today_str())
        with target.open("a", encoding="utf-8") as file:
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
        """日志按天裁剪，防止无限增长（互斥+原子写）。

        两级清理（4.1）：
        1. 文件级：删除超过 _LOG_RETENTION_DAYS 的过期天文件（不再整文件重写）。
        2. 条目级：当天文件超 _AUTO_CLEAN_MAX_ENTRIES 裁剪到 _AUTO_CLEAN_KEEP。

        失败必须可观测（第七轮 review #2：此前 except: pass 静默吞，
        清理持续失败会磁盘写满而无任何痕迹）。
        """
        try:
            today = self._today_str()
            with self._write_lock:
                # 文件级：过期天文件整删（按文件名日期，避免逐行重写）
                cutoff = (datetime.now() - timedelta(days=self._LOG_RETENTION_DAYS)).strftime("%Y-%m-%d")
                for path in self._daily_files():
                    day = self._day_from_name(path.name)
                    if day and day < cutoff:
                        try:
                            path.unlink()
                        except OSError:
                            pass
                # 条目级：当天文件超限裁剪
                today_path = self._daily_path(today)
                if not today_path.exists():
                    return
                lines = today_path.read_text(encoding="utf-8").splitlines()
                if len(lines) <= self._AUTO_CLEAN_MAX_ENTRIES:
                    return
                kept = lines[-self._AUTO_CLEAN_KEEP:]
                from services.storage.json_storage import _atomic_write_text
                _atomic_write_text(today_path, "\n".join(kept) + "\n")
        except Exception:
            import logging
            logging.getLogger(__name__).warning("log auto-cleanup failed", exc_info=True)

    def _scan_min_day(self, days: int | None, start_date: str, end_date: str) -> str | None:
        """文件扫描下界日期：days=N 给最近 N 天；start_date/end_date 任一更早时扩展到覆盖（不丢历史）。

        注意：end_date 只设过去某天（无 start_date）时，days 不得把文件范围截到 end_date 之后，
        否则过滤结果恒为空（用户明确要看更早日志）。
        """
        today = datetime.now().date()
        min_day: str | None = None
        if days is not None and days > 0:
            min_day = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        for bound in (start_date[:10], end_date[:10]):
            if bound and bound < (min_day or "9999-12-31"):
                min_day = bound
        return min_day

    def list(self, type: str = "", start_date: str = "", end_date: str = "", account_email: str = "", limit: int = 200, days: int | None = None, event: str = "", request_id: str = "", result: str = "") -> list[dict[str, Any]]:
        """读取日志，按天文件分片（4.1）。

        - `days=N`：只读最近 N 天天文件（limit 凑够 early-exit，不触碰更早文件）。
        - 不传 days（None）：读全部天文件，向后兼容旧调用方（前端日志页/契约守卫）。
        - `start_date`/`end_date` 更早时自动扩展文件范围（见 _scan_min_day），保证日期筛选不丢历史。
        - 返回最新在前（跨文件新→旧、文件内行倒序）。
        """
        self._ensure_migrated()
        min_day = self._scan_min_day(days, start_date, end_date)
        files = [p for p in self._daily_files() if not min_day or self._day_from_name(p.name) >= min_day]
        items: list[dict[str, Any]] = []
        # 跨文件：新→旧；文件内：行倒序
        for path in reversed(files):
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for line_number in range(len(lines) - 1, -1, -1):
                item = self._parse_line(lines[line_number], line_number)
                if item is None:
                    continue
                if not self._matches_filters(item, type=type, start_date=start_date, end_date=end_date, account_email=account_email, event=event, request_id=request_id, result=result):
                    continue
                items.append(item)
                if len(items) >= limit:
                    return items
        return items

    def delete(self, ids: list[str]) -> dict[str, int]:
        target_ids = {str(item or "").strip() for item in ids if str(item or "").strip()}
        if not target_ids:
            return {"removed": 0}
        self._ensure_migrated()
        removed = 0
        with self._write_lock:
            # 跨天文件删除：每文件读-改-原子写（低频管理操作，逐文件处理即可）
            for path in self._daily_files():
                if not path.exists():
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
                kept_lines: list[str] = []
                local_removed = 0
                for line_number, raw_line in enumerate(lines):
                    item = self._parse_line(raw_line, line_number)
                    if item is None:
                        kept_lines.append(raw_line)
                        continue
                    if str(item.get("id") or "") in target_ids:
                        local_removed += 1
                        continue
                    kept_lines.append(self._serialize_item(item))
                if local_removed == 0:
                    continue
                removed += local_removed
                content = "\n".join(kept_lines)
                if content:
                    content += "\n"
                from services.storage.json_storage import _atomic_write_text
                _atomic_write_text(path, content)
        return {"removed": removed}

    # ---- 聚合统计 ----

    def aggregate(self, filter: dict[str, Any], group_by: str = "type", period: str = "day") -> list[dict[str, Any]]:
        """按维度聚合统计日志。

        Args:
            filter: 筛选条件（同 list 的 type/start_date/end_date 等）
            group_by: 分组维度：type / status / hour
            period: 时间粒度：day / hour
        Returns:
            [{"group": str, "count": int, "period": str}, ...]
        """
        self._ensure_migrated()
        items = self.list(**{k: v for k, v in filter.items() if v}, limit=100000)
        buckets: dict[str, int] = {}
        for item in items:
            detail = item.get("detail") or {}
            if group_by == "type":
                key = str(item.get("type") or "unknown")
            elif group_by == "status":
                key = str(detail.get("status") or "unknown")
            elif group_by == "hour":
                ts = item.get("time") or item.get("ts") or ""
                key = str(ts)[:13] if period == "hour" else str(ts)[:10]
            else:
                key = "unknown"
            buckets[key] = buckets.get(key, 0) + 1
        return sorted([{"group": k, "count": v} for k, v in buckets.items()], key=lambda x: -x["count"])

    # ---- CSV 导出 ----

    def export_csv(self, filter: dict[str, Any]) -> str:
        """导出日志为 CSV 格式字符串。"""
        self._ensure_migrated()
        items = self.list(**{k: v for k, v in filter.items() if v}, limit=50000)
        lines = ["id,time,type,summary,status,error"]
        for item in items:
            item_id = str(item.get("id", "")).replace(",", " ")
            ts = str(item.get("time") or item.get("ts") or "")
            typ = str(item.get("type", "")).replace(",", " ")
            summary = str(item.get("summary", "")).replace(",", " ").replace('"', "'")
            detail = item.get("detail") or {}
            status = str(detail.get("status", "")).replace(",", " ")
            error = str(detail.get("error", "")).replace(",", " ").replace('"', "'")
            lines.append(f"{item_id},{ts},{typ},{summary},{status},{error}")
        return "\n".join(lines)

    # ---- 归档 ----

    def archive(self, before_days: int = 90) -> dict[str, Any]:
        """归档过期日志到压缩文件。

        将超过 before_days 的天文件打包为 data/logs-archive-YYYYMMDD.zip
        然后删除原文件。
        """
        import zipfile

        self._ensure_migrated()
        cutoff = (datetime.now() - timedelta(days=before_days)).strftime("%Y-%m-%d")
        archive_path = self._log_dir / f"logs-archive-{datetime.now().strftime('%Y%m%d')}.zip"
        archived = 0
        archived_files = []

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in self._daily_files():
                day = self._day_from_name(path.name)
                if day and day < cutoff:
                    zf.write(path, arcname=path.name)
                    archived_files.append(path.name)
                    archived += 1
                    path.unlink()

        return {"archived": archived, "files": archived_files, "archive_path": str(archive_path)}


log_service = LogService(DATA_DIR / "logs.jsonl")


# ---- 运行时日志级别动态调整 ----

_LOG_LEVEL_MAP = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def apply_log_levels(levels: list[str]) -> dict[str, object]:
    """运行时动态调整日志级别，无需重启。

    1. 持久化到 config.json 的 log_levels 字段（utils/log.py Logger 据此过滤）。
    2. 同步调整 Python logging 模块的日志级别，让文件 handler 和直接
       logging.getLogger(__name__) 的模块也立即生效。
    3. 返回当前生效的级别列表。
    """
    allowed = {"debug", "info", "warning", "error"}
    normalized = [level for item in levels if (level := str(item or "").strip().lower()) in allowed]
    if not normalized:
        normalized = ["info", "warning", "error"]

    # 持久化到 config.json
    from services.config import config
    config.update({"log_levels": normalized})

    # 同步调整 Python logging 模块级别（影响文件 handler + 直接 logging.getLogger 的模块）
    min_level = min(_LOG_LEVEL_MAP[l] for l in normalized)
    for logger_name in ("chatgpt2api", ""):
        logger = logging.getLogger(logger_name)
        logger.setLevel(min_level)
        for handler in logger.handlers:
            handler.setLevel(min_level)

    return {"levels": normalized}


def get_log_levels() -> dict[str, object]:
    """返回当前日志级别设置。"""
    from services.config import config
    return {"levels": config.log_levels}


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
        content = exc.to_openai_error()
        # 补 conversation_id 到 debug，便于调用方后续找回
        conv_id = getattr(exc, "conversation_id", "")
        if conv_id:
            err = content.get("error") or {}
            existing_debug = err.get("debug") or {}
            err["debug"] = {**existing_debug, "conversation_id": conv_id}
        return JSONResponse(status_code=int(exc.status_code), content=content)
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
