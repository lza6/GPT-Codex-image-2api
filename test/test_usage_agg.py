"""3.5.1：日志聚合缓存——增量追加正确、窗口裁剪正确、与旧全量扫描口径等价。

慢查询热点根治：/api/dashboard/usage 与 usage_forecast 不再每次全量扫 logs.jsonl，
改读按小时桶聚合的增量缓存。本测试验证增量逻辑不丢不重、口径不漂移。

口径等价说明：旧实现为精确 86400 秒窗口，缓存为整小时桶窗口（业务上近 24h 以
整小时近似，误差 ≤1 小时数据量）。等价对比测试使用全量扫描参考函数 full_scan_*，
样本时间戳取整点且位于窗口内非边界桶，保证两口径严格一致。
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from services.usage_agg import (
    WINDOW_DAYS,
    UsageAgg,
    full_scan_daily_success,
    full_scan_stats,
)


def _entry(created: str, summary: str, status: str = "success") -> dict:
    return {"time": created, "type": "调用", "summary": summary, "detail": {"status": status}}


def _append_logs(path, entries: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as file:
        for entry in entries:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _hour_start(ts: float, hours_back: int) -> datetime:
    return datetime.fromtimestamp(ts - hours_back * 3600).replace(minute=0, second=0, microsecond=0)


class TestUsageAgg:
    def test_incremental_ingest_no_dup_no_loss(self, tmp_path) -> None:
        cache = tmp_path / "usage_agg.json"
        logs = tmp_path / "logs.jsonl"
        agg = UsageAgg(cache, logs)
        now = time.time()

        # 第一批：3 条（2 成功 1 失败）
        _append_logs(logs, [
            _entry(_hour_start(now, 2).strftime("%Y-%m-%d %H:%M:%S"), "gpt-image-2"),
            _entry(_hour_start(now, 2).strftime("%Y-%m-%d %H:%M:%S"), "gpt-image-2", "failed"),
            _entry(_hour_start(now, 1).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o"),
        ])
        assert agg.ingest() == 3

        # 第二批：增量追加 2 条，应只计新增，不重算旧的
        _append_logs(logs, [
            _entry(_hour_start(now, 0).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o"),
            _entry(_hour_start(now, 0).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o", "failed"),
        ])
        assert agg.ingest() == 2

        stats = agg.stats_24h(now=now)
        assert stats["success_24h"] == 3  # gpt-image-2×1 + gpt-4o×2
        assert stats["failed_24h"] == 2  # gpt-image-2×1 + gpt-4o×1
        assert stats["total_24h"] == 5
        assert stats["by_summary"]["gpt-image-2"] == 2
        assert stats["by_summary"]["gpt-4o"] == 3

    def test_restart_loads_from_disk(self, tmp_path) -> None:
        cache = tmp_path / "usage_agg.json"
        logs = tmp_path / "logs.jsonl"
        now = time.time()
        _append_logs(logs, [_entry(_hour_start(now, 1).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o")])

        agg = UsageAgg(cache, logs)
        agg.ingest()
        agg.save()

        # 重启：新实例从磁盘恢复，无需全量重扫
        agg2 = UsageAgg(cache, logs)
        assert agg2.stats_24h(now=now)["success_24h"] == 1

        # 增量续传：重启后追加 1 条，只新增
        _append_logs(logs, [_entry(_hour_start(now, 0).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o")])
        assert agg2.ingest() == 1
        assert agg2.stats_24h(now=now)["success_24h"] == 2

    def test_window_prune(self, tmp_path) -> None:
        cache = tmp_path / "usage_agg.json"
        logs = tmp_path / "logs.jsonl"
        agg = UsageAgg(cache, logs)
        now = time.time()

        # 超窗样本（WINDOW_DAYS+2 天前）写入后应被裁剪
        ancient = datetime.fromtimestamp(now - (WINDOW_DAYS + 2) * 86400)
        _append_logs(logs, [
            _entry(ancient.strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o"),
            _entry(_hour_start(now, 0).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o"),
        ])
        agg.ingest()
        stats = agg.stats_24h(now=now)
        assert stats["success_24h"] == 1
        assert stats["by_summary"]["gpt-4o"] == 1

    def test_stats_equivalent_to_full_scan(self, tmp_path) -> None:
        """近 24h 口径等价：缓存聚合 vs 全量扫描参考，逐字段一致。"""
        cache = tmp_path / "usage_agg.json"
        logs = tmp_path / "logs.jsonl"
        now = time.time()
        _append_logs(logs, [
            _entry(_hour_start(now, 20).strftime("%Y-%m-%d %H:%M:%S"), "gpt-image-2"),
            _entry(_hour_start(now, 20).strftime("%Y-%m-%d %H:%M:%S"), "gpt-image-2", "failed"),
            _entry(_hour_start(now, 5).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o"),
            _entry(_hour_start(now, 1).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o", "failed"),
            _entry(_hour_start(now, 26).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o"),  # 超出 24h
        ])
        agg = UsageAgg(cache, logs)
        agg.ingest()
        cached = agg.stats_24h(now=now)
        legacy = full_scan_stats(logs, now=now)
        for key in ("success_24h", "failed_24h", "total_24h", "by_summary"):
            assert cached[key] == legacy[key], f"口径漂移: {key} {cached[key]} != {legacy[key]}"

    def test_daily_series_equivalent_to_full_scan(self, tmp_path) -> None:
        """近 N 天按天成功数口径等价（usage_forecast 消费）。"""
        cache = tmp_path / "usage_agg.json"
        logs = tmp_path / "logs.jsonl"
        now = time.time()
        _append_logs(logs, [
            _entry(_hour_start(now, 26).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o"),
            _entry(_hour_start(now, 26).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o", "failed"),
            _entry(_hour_start(now, 1).strftime("%Y-%m-%d %H:%M:%S"), "gpt-4o"),
        ])
        agg = UsageAgg(cache, logs)
        agg.ingest()
        cached = agg.daily_success_series(7, now=now)
        legacy = full_scan_daily_success(logs, 7, now=now)
        assert cached == legacy

    def test_empty_state(self, tmp_path) -> None:
        agg = UsageAgg(tmp_path / "usage_agg.json", tmp_path / "logs.jsonl")
        stats = agg.stats_24h(now=time.time())
        assert stats["success_24h"] == 0
        assert stats["failed_24h"] == 0
        assert stats["total_24h"] == 0
        assert stats["by_summary"] == {}

    def test_log_truncate_resets_offset_without_double_count(self, tmp_path) -> None:
        """反向批判修复：日志被 auto_cleanup 裁剪后 offset 失效，重置游标全量重建时
        必须清空计数，否则旧行被重复累加（double count）。"""
        cache = tmp_path / "usage_agg.json"
        logs = tmp_path / "logs.jsonl"
        agg = UsageAgg(cache, logs)
        now = time.time()
        ts = _hour_start(now, 1).strftime("%Y-%m-%d %H:%M:%S")
        _append_logs(logs, [_entry(ts, "gpt-4o") for _ in range(5)])
        assert agg.ingest() == 5
        assert agg.stats_24h(now=now)["success_24h"] == 5

        # 模拟 _auto_cleanup 裁剪：重写文件只留最后 2 条（文件变小，offset 失效）
        lines = logs.read_text(encoding="utf-8").splitlines()
        logs.write_text("\n".join(lines[-2:]) + "\n", encoding="utf-8")
        assert agg.ingest() == 2
        assert agg.stats_24h(now=now)["success_24h"] == 2, "裁剪后不得重复计数旧行"

    def test_usage_collector_never_full_scans_logs(self, monkeypatch) -> None:
        """3.5.1 慢查询根治：/api/dashboard/usage 改读聚合缓存后，
        _collect_log_stats 不得再调用 log_service.list 全量扫描 logs.jsonl。"""
        import api.dashboard as dashboard
        import services.log_service as log_service_module

        calls = {"n": 0}

        def _forbidden(*args, **kwargs):  # pragma: no cover - 触发即失败
            calls["n"] += 1
            raise AssertionError("usage 端点不应调用 log_service.list 全量扫描")

        monkeypatch.setattr(log_service_module.log_service, "list", _forbidden)
        result = dashboard._collect_log_stats()
        assert isinstance(result, dict)
        assert calls["n"] == 0
