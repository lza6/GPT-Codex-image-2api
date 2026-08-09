"""3.5.1：日志聚合缓存——替代 /api/dashboard/usage 与 usage_forecast 的全量日志扫描。

慢查询热点根治：logs.jsonl 全量逐行读在日志量大时是每次 API 调用 O(N) 的负担。
本模块维护按小时桶聚合的增量缓存，后台任务每 60s 读日志尾部增量，
usage / usage_forecast 改读缓存，杜绝每次 API 调用全量扫日志。

- 聚合粒度：小时桶（近 24h 以整小时窗口近似，误差 ≤1 小时数据量，业务可忽略）。
- 窗口：保留近 90 天，超期裁剪。
- 一致性：落盘用 json_storage._atomic_write_text 原子写，防半写；
  多 worker 各自维护完整内存缓存（首次全量 ingest），原子写互相覆盖不损坏。
- full_scan_*：保留旧口径参考实现，供测试双算对比（证明缓存不漂移）。
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from services.storage.json_storage import _atomic_write_text

logger = logging.getLogger(__name__)

WINDOW_DAYS = 90
_HOUR_KEY_FMT = "%Y-%m-%dT%H"
_RECENT_MAXLEN = 50
_INGEST_INTERVAL_SECONDS = 60


def _parse_ts(created: str) -> float:
    """时间键兼容：text 'time' / json 'ts' / 历史 'created_at'。"""
    try:
        normalized = created[:19].replace("T", " ")
        return time.mktime(datetime.datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S").timetuple())
    except (ValueError, TypeError):
        return 0.0


class UsageAgg:
    """按小时桶聚合的增量缓存。线程安全（RLock），惰性加载，原子落盘。

    4.1 起支持两种日志形态：
    - 单文件模式（logs_path 是文件）：兼容旧单一日志文件（测试/旧部署）。
    - 按天模式（logs_path 是目录）：扫描 `logs-*.jsonl`，每文件独立 offset 增量读，
      新的一天文件出现只增量（不触发全量重建）；某文件被裁剪（offset>size）才全量重建。
    升级检测：旧缓存无 file_offsets 且当前为按天模式 → 判定发生按天切分升级，
    清空 hourly 全量重建（只信天文件，防 logs.jsonl 迁移历史重复计数）。
    """

    def __init__(self, cache_path: Path, logs_path: Path) -> None:
        self._cache_path = cache_path
        self._logs_path = logs_path
        self._is_daily = logs_path.is_dir()
        self._log_dir = logs_path if self._is_daily else logs_path.parent
        self._lock = threading.RLock()
        # hourly: {"2026-08-05T14": {"<summary>": {"success": n, "fail": n}}}
        self._hourly: dict[str, dict[str, dict[str, int]]] = {}
        self._recent: deque[dict[str, str]] = deque(maxlen=_RECENT_MAXLEN)
        # 每文件字节 offset（按天模式下 per-file；单文件模式下只有一个 key）
        self._file_offsets: dict[str, int] = {}
        self._load()

    def _discover_log_files(self) -> list[Path]:
        """按天模式：所有天文件（按日期升序）；单文件模式：仅该文件（存在时）。"""
        if self._is_daily:
            return sorted(self._log_dir.glob("logs-*.jsonl"))
        return [self._logs_path] if self._logs_path.exists() else []

    # ---- 持久化 ----
    def _load(self) -> None:
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            self._hourly = {str(key): value for key, value in (data.get("hourly") or {}).items()}
            recent = data.get("recent") or []
            self._recent = deque(
                [item for item in recent if isinstance(item, dict)][-_RECENT_MAXLEN:], maxlen=_RECENT_MAXLEN
            )
            self._file_offsets = {str(k): int(v) for k, v in (data.get("file_offsets") or {}).items()}
            cache_mode = str(data.get("mode") or "single")
            if self._is_daily and cache_mode != "daily":
                # 升级：旧缓存是单文件（或首次无缓存），当前按天切分 → 全量重建，
                # 只信天文件（logs.jsonl 迁移历史已在其中，防重复计数）。
                self._hourly = {}
                self._recent = deque(maxlen=_RECENT_MAXLEN)
                self._file_offsets = {}
            elif not self._is_daily and "last_log_offset" in data and not self._file_offsets:
                # 单文件模式：兼容旧字段（无 file_offsets 的旧缓存）
                self._file_offsets = {self._logs_path.name: int(data.get("last_log_offset") or 0)}
        except Exception:
            # 缓存缺失/损坏 → 空态重建（后续 ingest 全量补齐）
            self._hourly = {}
            self._recent = deque(maxlen=_RECENT_MAXLEN)
            self._file_offsets = {}

    def save(self) -> None:
        data = {
            "window_days": WINDOW_DAYS,
            "hourly": self._hourly,
            "recent": list(self._recent),
            "file_offsets": self._file_offsets,
            "mode": "daily" if self._is_daily else "single",
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        _atomic_write_text(self._cache_path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    # ---- 增量 ----
    def ingest(self) -> int:
        """读日志增量并更新计数。任一文件被裁剪（offset 失效）时全量重建。返回本次新增条数。"""
        files = self._discover_log_files()
        if not files:
            return 0
        with self._lock:
            # 单文件模式：被 _auto_cleanup 裁剪（变小）→ offset 失效 → 全量重建（防 double count）
            # 按天模式：某一天文件被裁剪（当天超限）→ 同样全量重建；新天文件出现只增量。
            stale = any(
                self._file_offsets.get(path.name, 0) > path.stat().st_size
                for path in files if path.exists()
            )
            if stale:
                self._file_offsets = {}
                self._hourly = {}
                self._recent = deque(maxlen=_RECENT_MAXLEN)
            added = 0
            for path in files:
                if not path.exists():
                    # 过期天文件被整删：移除其 offset，保留已聚合数据（prune 会清 90 天外）
                    self._file_offsets.pop(path.name, None)
                    continue
                offset = self._file_offsets.get(path.name, 0)
                with path.open("r", encoding="utf-8") as file:
                    file.seek(offset)
                    for raw_line in file:
                        item = self._parse_line(raw_line)
                        if item is not None:
                            self._apply(item)
                            added += 1
                    self._file_offsets[path.name] = file.tell()
            self._prune()
        return added

    @staticmethod
    def _parse_line(raw_line: str) -> dict[str, Any] | None:
        try:
            item = json.loads(raw_line)
        except Exception:
            return None
        return item if isinstance(item, dict) else None

    def _apply(self, item: dict[str, Any]) -> None:
        created = str(item.get("time") or item.get("ts") or item.get("created_at") or "")
        ts = _parse_ts(created)
        if ts <= 0:
            return
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        status = str(item.get("status") or detail.get("status") or "success")
        summary = str(item.get("summary") or "调用")
        hour_key = datetime.datetime.fromtimestamp(ts).strftime(_HOUR_KEY_FMT)
        counter = self._hourly.setdefault(hour_key, {}).setdefault(summary, {"success": 0, "fail": 0})
        if status == "failed":
            counter["fail"] = counter["fail"] + 1
        else:
            counter["success"] = counter["success"] + 1
        self._recent.append({"time": created, "summary": summary, "status": status})

    def _prune(self) -> None:
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=WINDOW_DAYS)).strftime(_HOUR_KEY_FMT)
        for key in [key for key in self._hourly if key < cutoff]:
            del self._hourly[key]

    # ---- 查询 ----
    def stats_for_window(self, hours: int, now: float | None = None) -> dict[str, Any]:
        """指定小时窗口用量：成功/失败/总量/按 summary 分布/最近记录。

        与 stats_24h 同口径，但窗口由 hours 参数控制，支持 1h/6h/24h/7d*24h/30d*24h。
        """
        now = time.time() if now is None else now
        window_sec = hours * 3600
        cutoff = now - window_sec
        cutoff_key = datetime.datetime.fromtimestamp(cutoff).strftime(_HOUR_KEY_FMT)
        success = 0
        failed = 0
        calls: dict[str, int] = {}
        with self._lock:
            for key, buckets in self._hourly.items():
                if key < cutoff_key:
                    continue
                for summary, counter in buckets.items():
                    calls[summary] = calls.get(summary, 0) + counter["success"] + counter["fail"]
                    success += counter["success"]
                    failed += counter["fail"]
            recent = [item for item in self._recent if _parse_ts(item.get("time") or "") >= cutoff][-20:]
            recent = list(reversed(recent))
        return {
            "success_24h": success,
            "failed_24h": failed,
            "total_24h": success + failed,
            "by_summary": calls,
            "recent": recent,
            "hours": hours,
        }

    def stats_24h(self, now: float | None = None) -> dict[str, Any]:
        """近 24h 用量（整小时窗口近似）：成功/失败/总量/按 summary 分布/最近记录。"""
        now = time.time() if now is None else now
        day_ago = now - 86400
        cutoff_key = datetime.datetime.fromtimestamp(day_ago).strftime(_HOUR_KEY_FMT)
        success = 0
        failed = 0
        calls: dict[str, int] = {}
        with self._lock:
            for key, buckets in self._hourly.items():
                if key < cutoff_key:
                    continue
                for summary, counter in buckets.items():
                    calls[summary] = calls.get(summary, 0) + counter["success"] + counter["fail"]
                    success += counter["success"]
                    failed += counter["fail"]
            # 最近 20 条 24h 内记录，新→旧（与旧实现同序）
            recent = [item for item in self._recent if _parse_ts(item.get("time") or "") >= day_ago][-20:]
            recent = list(reversed(recent))
        return {
            "success_24h": success,
            "failed_24h": failed,
            "total_24h": success + failed,
            "by_summary": calls,
            "recent": recent,
        }

    def daily_success_series(self, window_days: int, now: float | None = None) -> list[dict[str, Any]]:
        """近 N 天按天成功调用数（usage_forecast 消费）。"""
        now = time.time() if now is None else now
        cutoff = now - window_days * 86400
        buckets: dict[str, int] = {}
        with self._lock:
            for key, summary_counters in self._hourly.items():
                ts = _hour_key_to_ts(key)
                if ts < cutoff:
                    continue
                day = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                for counter in summary_counters.values():
                    buckets[day] = buckets.get(day, 0) + counter["success"]
        series: list[dict[str, Any]] = []
        for offset in range(window_days - 1, -1, -1):
            day = datetime.datetime.fromtimestamp(now - offset * 86400).strftime("%Y-%m-%d")
            series.append({"date": day, "calls": buckets.get(day, 0)})
        return series

    def totals(self) -> dict[str, Any]:
        """累计总量：总请求/成功/失败 + 按类型(summary)分布（全时段，不限 24h）。

        供看板「总被请求多少次/成功多少次/图片累计多少次」卡片。
        """
        total_success = 0
        total_fail = 0
        by_summary: dict[str, dict[str, int]] = {}
        with self._lock:
            for buckets in self._hourly.values():
                for summary, counter in buckets.items():
                    total_success += counter["success"]
                    total_fail += counter["fail"]
                    agg = by_summary.setdefault(summary, {"success": 0, "fail": 0})
                    agg["success"] += counter["success"]
                    agg["fail"] += counter["fail"]
        # 图片类调用合计（summary 含「图」的归并：文生图/图生图/图片编辑等）
        image_calls = sum(
            c["success"] + c["fail"]
            for s, c in by_summary.items()
            if any(tok in s for tok in ("图", "image", "文生", "图生"))
        )
        return {
            "total_requests": total_success + total_fail,
            "total_success": total_success,
            "total_fail": total_fail,
            "success_rate": round(total_success / (total_success + total_fail), 4) if (total_success + total_fail) else 0.0,
            "image_calls_total": image_calls,
            "by_type": by_summary,
        }


def _hour_key_to_ts(hour_key: str) -> float:
    try:
        return time.mktime(datetime.datetime.strptime(hour_key, _HOUR_KEY_FMT).timetuple())
    except (ValueError, TypeError):
        return 0.0


# ---- 旧口径参考实现（测试双算对比，证明缓存不漂移） ----


def full_scan_stats(logs_path: Path, now: float | None = None) -> dict[str, Any]:
    """近 24h 用量参考实现：读全量日志逐行聚合（与缓存 stats_24h 对比用）。"""
    now = time.time() if now is None else now
    day_ago = now - 86400
    success = 0
    failed = 0
    calls: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    if logs_path.exists():
        for raw_line in logs_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(raw_line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            created = str(item.get("time") or item.get("ts") or item.get("created_at") or "")
            ts = _parse_ts(created)
            if ts <= 0 or ts < day_ago:
                continue
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            status = str(item.get("status") or detail.get("status") or "success")
            summary = str(item.get("summary") or "调用")
            calls[summary] = calls.get(summary, 0) + 1
            if status == "failed":
                failed += 1
            else:
                success += 1
            recent.append({"time": created, "summary": summary, "status": status})
    return {
        "success_24h": success,
        "failed_24h": failed,
        "total_24h": success + failed,
        "by_summary": calls,
        "recent": recent[-20:][::-1],
    }


def full_scan_daily_success(logs_path: Path, window_days: int, now: float | None = None) -> list[dict[str, Any]]:
    """近 N 天按天成功数参考实现（与缓存 daily_success_series 对比用）。"""
    now = time.time() if now is None else now
    cutoff = now - window_days * 86400
    buckets: dict[str, int] = {}
    if logs_path.exists():
        for raw_line in logs_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(raw_line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            created = str(item.get("time") or item.get("ts") or item.get("created_at") or "")
            ts = _parse_ts(created)
            if ts <= 0 or ts < cutoff:
                continue
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            status = str(item.get("status") or detail.get("status") or "success")
            if status == "failed":
                continue
            day = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            buckets[day] = buckets.get(day, 0) + 1
    series: list[dict[str, Any]] = []
    for offset in range(window_days - 1, -1, -1):
        day = datetime.datetime.fromtimestamp(now - offset * 86400).strftime("%Y-%m-%d")
        series.append({"date": day, "calls": buckets.get(day, 0)})
    return series


# 全局单例：后台聚合任务与 usage / usage_forecast 端点共享
# 4.1 起按天切分：传 DATA_DIR 目录，扫描 logs-*.jsonl（多文件增量）；旧 data/logs.jsonl
# 由 log_service 首次访问时迁移到天文件，此处不再直接读单文件。
usage_agg = UsageAgg(DATA_DIR / "usage_agg.json", DATA_DIR)


def start_usage_agg_watcher(stop_event: threading.Event) -> threading.Thread:
    """后台聚合线程：启动即全量 ingest 初始化缓存，之后每 60s 增量 ingest + 落盘。

    慢查询根治的关键：usage / usage_forecast 端点改为读缓存，不再每次全量扫日志。
    多 worker 下各进程各自维护完整内存缓存（首次全量 ingest），原子写互不损坏。
    """

    def _run() -> None:
        try:
            usage_agg.ingest()
            usage_agg.save()
        except Exception:
            logger.warning("usage_agg 初始化 ingest 失败", exc_info=True)
        while not stop_event.wait(_INGEST_INTERVAL_SECONDS):
            try:
                if usage_agg.ingest() > 0:
                    usage_agg.save()
            except Exception:
                logger.warning("usage_agg 增量 ingest 失败", exc_info=True)

    thread = threading.Thread(target=_run, name="usage-agg-watcher", daemon=True)
    thread.start()
    return thread
