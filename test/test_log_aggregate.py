"""日志聚合/导出/归档测试：aggregate 聚合统计、export_csv CSV 导出、archive 归档压缩。

覆盖场景：
- aggregate 按 type/status/hour 分组
- aggregate 时间粒度 day/hour
- aggregate 空结果/缺字段兼容
- CSV 导出字段正确性
- CSV 导出空结果
- archive 归档过期天文件并删除原文件
- archive 无过期文件时静默跳过
- 过滤条件透传
"""

from __future__ import annotations

import json
import gzip
from datetime import datetime, timedelta
from pathlib import Path

from services.log_service import LogService


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _seed_daily_file(service: LogService, day: str, entries: list[dict]) -> None:
    """直接构造天文件（绕过 add，保证日期可控）。"""
    path = service._daily_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    if entries:
        lines += "\n"
    path.write_text(lines, encoding="utf-8")
    service._migrated = True


class TestLogAggregate:
    """日志聚合统计测试。"""

    def _make_service(self, tmp_path: Path) -> LogService:
        return LogService(tmp_path / "logs.jsonl")

    # ---- aggregate: type 分组 ----

    def test_aggregate_by_type(self, tmp_path) -> None:
        """aggregate 按 type 分组，统计各类型数量。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "req1", "detail": {"status": "success"}},
            {"ts": f"{today}T10:01:00", "type": "call", "summary": "req2", "detail": {"status": "fail"}},
            {"ts": f"{today}T10:02:00", "type": "image", "summary": "gen1", "detail": {"status": "success"}},
            {"ts": f"{today}T10:03:00", "type": "image", "summary": "gen2", "detail": {"status": "success"}},
            {"ts": f"{today}T10:04:00", "type": "call", "summary": "req3", "detail": {"status": "success"}},
        ])

        result = service.aggregate(filter={}, group_by="type")
        # 按 count 降序：call:3, image:2
        assert len(result) == 2
        assert result[0]["group"] == "call"
        assert result[0]["count"] == 3
        assert result[1]["group"] == "image"
        assert result[1]["count"] == 2

    def test_aggregate_by_status(self, tmp_path) -> None:
        """aggregate 按 detail.status 分组。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "req1", "detail": {"status": "success"}},
            {"ts": f"{today}T10:01:00", "type": "call", "summary": "req2", "detail": {"status": "fail"}},
            {"ts": f"{today}T10:02:00", "type": "call", "summary": "req3", "detail": {"status": "success"}},
            {"ts": f"{today}T10:03:00", "type": "call", "summary": "req4", "detail": {"status": "fail"}},
            {"ts": f"{today}T10:04:00", "type": "call", "summary": "req5", "detail": {"status": "success"}},
        ])

        result = service.aggregate(filter={}, group_by="status")
        assert len(result) == 2
        counts = {r["group"]: r["count"] for r in result}
        assert counts["success"] == 3
        assert counts["fail"] == 2

    # ---- aggregate: hour 分组 ----

    def test_aggregate_by_hour(self, tmp_path) -> None:
        """aggregate 按小时分组（group_by=hour, period=hour），从 ts 取前 13 位 YYYY-MM-DDTHH。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T09:15:00", "type": "call", "summary": "r1", "detail": {}},
            {"ts": f"{today}T09:45:00", "type": "call", "summary": "r2", "detail": {}},
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "r3", "detail": {}},
        ])

        result = service.aggregate(filter={}, group_by="hour", period="hour")
        assert len(result) == 2
        counts = {r["group"]: r["count"] for r in result}
        assert counts[f"{today}T09"] == 2
        assert counts[f"{today}T10"] == 1

    def test_aggregate_by_hour_day_period(self, tmp_path) -> None:
        """group_by=hour 且 period=day 时，从 ts 取前 10 位 YYYY-MM-DD。"""
        service = self._make_service(tmp_path)
        today = _today()
        yesterday = _days_ago(1)
        _seed_daily_file(service, today, [
            {"ts": f"{today}T09:00:00", "type": "call", "summary": "r1", "detail": {}},
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "r2", "detail": {}},
            {"ts": f"{yesterday}T09:00:00", "type": "call", "summary": "r3", "detail": {}},
        ])

        result = service.aggregate(filter={}, group_by="hour", period="day")
        assert len(result) == 2
        counts = {r["group"]: r["count"] for r in result}
        assert counts[today] == 2
        assert counts[yesterday] == 1

    # ---- aggregate: 空结果 ----

    def test_aggregate_empty(self, tmp_path) -> None:
        """aggregate 无日志时返回空列表。"""
        service = self._make_service(tmp_path)
        result = service.aggregate(filter={}, group_by="type")
        assert result == []

    def test_aggregate_no_matches(self, tmp_path) -> None:
        """aggregate 过滤条件无匹配时返回空列表。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "r1", "detail": {"status": "success"}},
        ])
        result = service.aggregate(filter={"type": "image"}, group_by="type")
        assert result == []

    # ---- aggregate: 缺字段兼容 ----

    def test_aggregate_missing_type_falls_to_unknown(self, tmp_path) -> None:
        """缺 type 字段的条目归入 unknown 分组。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "summary": "no-type", "detail": {}},
            {"ts": f"{today}T10:01:00", "type": "call", "summary": "has-type", "detail": {}},
        ])
        result = service.aggregate(filter={}, group_by="type")
        counts = {r["group"]: r["count"] for r in result}
        assert counts.get("unknown", 0) == 1
        assert counts.get("call", 0) == 1

    def test_aggregate_unknown_group_by(self, tmp_path) -> None:
        """未知 group_by 值归入 unknown 分组。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "r1", "detail": {}},
        ])
        result = service.aggregate(filter={}, group_by="nonexistent")
        assert len(result) == 1
        assert result[0]["group"] == "unknown"
        assert result[0]["count"] == 1

    # ---- aggregate: 过滤条件 ----

    def test_aggregate_respects_filter(self, tmp_path) -> None:
        """aggregate 应透传 filter 参数到 list，仅统计匹配条目。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "r1", "detail": {"status": "success"}},
            {"ts": f"{today}T10:01:00", "type": "image", "summary": "g1", "detail": {"status": "success"}},
            {"ts": f"{today}T10:02:00", "type": "call", "summary": "r2", "detail": {"status": "fail"}},
        ])
        result = service.aggregate(filter={"type": "call"}, group_by="status")
        counts = {r["group"]: r["count"] for r in result}
        assert counts["success"] == 1
        assert counts["fail"] == 1

    # ---- CSV 导出 ----

    def test_export_csv_columns(self, tmp_path) -> None:
        """CSV 导出列顺序正确：id,time,type,summary,status,error。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"id": "abc123", "ts": f"{today}T10:00:00", "type": "call", "summary": "test-request",
             "detail": {"status": "success"}},
        ])

        csv_text = service.export_csv(filter={})
        lines = csv_text.splitlines()
        assert len(lines) == 2  # header + 1 data row
        assert lines[0] == "id,time,type,summary,status,error"
        assert "abc123" in lines[1]
        assert "test-request" in lines[1]
        assert "success" in lines[1]

    def test_export_csv_handles_commas_in_fields(self, tmp_path) -> None:
        """CSV 导出中逗号分隔的字段应被替换为空格（防止列错位）。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"id": "id,1", "ts": f"{today}T10:00:00", "type": "call,urgent", "summary": "test,summary",
             "detail": {"status": "ok,good", "error": "err,msg"}},
        ])

        csv_text = service.export_csv(filter={})
        assert "," not in csv_text.splitlines()[1].split(",")[0], "id 中的逗号应被替换"

    def test_export_csv_empty(self, tmp_path) -> None:
        """CSV 导出无日志时仅返回 header。"""
        service = self._make_service(tmp_path)
        csv_text = service.export_csv(filter={})
        assert csv_text == "id,time,type,summary,status,error"

    def test_export_csv_respects_filter(self, tmp_path) -> None:
        """CSV 导出应透传 filter 参数。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"id": "1", "ts": f"{today}T10:00:00", "type": "call", "summary": "r1", "detail": {"status": "success"}},
            {"id": "2", "ts": f"{today}T10:01:00", "type": "image", "summary": "g1", "detail": {"status": "success"}},
        ])
        csv_text = service.export_csv(filter={"type": "image"})
        lines = csv_text.splitlines()
        assert len(lines) == 2  # header + 1
        assert "g1" in lines[1]
        assert "r1" not in lines[1]

    # ---- 归档 ----

    def test_archive_packs_expired_files(self, tmp_path) -> None:
        """archive 应打包过期天文件到 zip 并删除原文件。"""
        service = self._make_service(tmp_path)
        expired_day = _days_ago(95)
        today = _today()
        _seed_daily_file(service, expired_day, [
            {"ts": f"{expired_day}T10:00:00", "type": "call", "summary": "old", "detail": {}},
        ])
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "new", "detail": {}},
        ])

        result = service.archive(before_days=90)

        assert result["archived"] == 1
        assert len(result["files"]) == 1
        assert f"logs-{expired_day}.jsonl" in result["files"][0]
        # 原文件应被删除
        expired_path = service._daily_path(expired_day)
        assert not expired_path.exists(), "过期天文件应被删除"
        # 今天文件保留
        today_path = service._daily_path(today)
        assert today_path.exists(), "保留期内文件不应被删除"
        # 归档目录存在
        archive_path = Path(result["archive_path"])
        assert archive_path.exists(), "归档目录应存在"
        assert archive_path.is_dir()

        # 验证 gzip 内容
        gz_path = archive_path / f"logs-{expired_day}.jsonl.gz"
        assert gz_path.exists()
        import gzip
        content = gzip.decompress(gz_path.read_bytes()).decode("utf-8")
        assert "old" in content

        # 验证校验清单
        checksum_path = archive_path / "checksums.sha256"
        assert checksum_path.exists()

    def test_archive_no_expired_files(self, tmp_path) -> None:
        """无过期文件时 archive 应静默返回空结果。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "new", "detail": {}},
        ])

        result = service.archive(before_days=90)

        assert result["archived"] == 0
        assert result["files"] == []
        # 无过期文件时 archive_path 为空字符串
        # 今天文件应保留
        assert service._daily_path(today).exists()

    def test_archive_respects_before_days(self, tmp_path) -> None:
        """archive 的 before_days 参数控制归档阈值，只归档超过该天数的文件。"""
        service = self._make_service(tmp_path)
        old_day = _days_ago(60)
        today = _today()
        _seed_daily_file(service, old_day, [
            {"ts": f"{old_day}T10:00:00", "type": "call", "summary": "old", "detail": {}},
        ])
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "new", "detail": {}},
        ])

        # before_days=30：60 天前的文件过期，应归档
        result = service.archive(before_days=30)
        assert result["archived"] == 1

        # 重新创建旧文件，before_days=90：60 天文件不过期，不应归档
        _seed_daily_file(service, old_day, [
            {"ts": f"{old_day}T10:00:00", "type": "call", "summary": "old", "detail": {}},
        ])
        result2 = service.archive(before_days=90)
        assert result2["archived"] == 0

    def test_archive_idempotent(self, tmp_path) -> None:
        """archive 幂等：过期文件被归档后，再次 archive 应有 0 个新归档。"""
        service = self._make_service(tmp_path)
        expired_day = _days_ago(95)
        _seed_daily_file(service, expired_day, [
            {"ts": f"{expired_day}T10:00:00", "type": "call", "summary": "old", "detail": {}},
        ])

        result1 = service.archive(before_days=90)
        assert result1["archived"] == 1

        result2 = service.archive(before_days=90)
        assert result2["archived"] == 0  # 已归档，无剩余过期文件

    # ---- 边界：天文件空洞 ----

    def test_aggregate_handles_old_format_time(self, tmp_path) -> None:
        """兼容旧格式 time 字段（非 ts）。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"time": f"{today} 10:00:00", "type": "call", "summary": "old-fmt", "detail": {"status": "success"}},
        ])
        result = service.aggregate(filter={}, group_by="type")
        assert len(result) == 1
        assert result[0]["count"] == 1