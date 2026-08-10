"""log_service.py 升级改动测试：多维聚合、分页导出、归档增强、慢查询详情、可配置轮转。

覆盖场景：
- 1.1 多维聚合：provider / account_email / endpoint 分组 + 多维度组合查询
- 1.2 分页导出：CSV 分页、JSON 分页、可选 fields、分页边界
- 1.3 归档增强：gzip 压缩 + sha256 校验 + 归档索引
- 1.4 慢查询详情：写入 JSONL + 按日期/阈值查询
- 1.5 可配置轮转：size 模式、mixed 模式、max_size_mb 配置
"""

from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

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


class TestMultiDimensionAggregate:
    """1.1 多维聚合测试。"""

    def _make_service(self, tmp_path: Path) -> LogService:
        return LogService(tmp_path / "logs.jsonl")

    # ---- provider 分组 ----

    def test_aggregate_by_provider(self, tmp_path) -> None:
        """aggregate 按 provider 分组，从 detail 子对象取值。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "r1", "detail": {"provider": "chatgpt", "status": "success"}},
            {"ts": f"{today}T10:01:00", "type": "call", "summary": "r2", "detail": {"provider": "chatgpt", "status": "success"}},
            {"ts": f"{today}T10:02:00", "type": "call", "summary": "r3", "detail": {"provider": "grok", "status": "success"}},
            {"ts": f"{today}T10:03:00", "type": "call", "summary": "r4", "detail": {"provider": "claude", "status": "fail"}},
        ])

        result = service.aggregate(filter={}, group_by="provider")
        assert len(result) == 3
        counts = {r["group"]: r["count"] for r in result}
        assert counts["chatgpt"] == 2
        assert counts["grok"] == 1
        assert counts["claude"] == 1

    # ---- account_email 分组 ----

    def test_aggregate_by_account_email(self, tmp_path) -> None:
        """aggregate 按 account_email 分组，从 detail 子对象取值。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "r1", "detail": {"account_email": "a@test.com", "status": "success"}},
            {"ts": f"{today}T10:01:00", "type": "call", "summary": "r2", "detail": {"account_email": "a@test.com", "status": "success"}},
            {"ts": f"{today}T10:02:00", "type": "call", "summary": "r3", "detail": {"account_email": "b@test.com", "status": "fail"}},
        ])

        result = service.aggregate(filter={}, group_by="account_email")
        assert len(result) == 2
        counts = {r["group"]: r["count"] for r in result}
        assert counts["a@test.com"] == 2
        assert counts["b@test.com"] == 1

    # ---- endpoint 分组 ----

    def test_aggregate_by_endpoint(self, tmp_path) -> None:
        """aggregate 按 endpoint 分组，从 detail 子对象取值。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "r1", "detail": {"endpoint": "/v1/chat/completions", "status": "success"}},
            {"ts": f"{today}T10:01:00", "type": "call", "summary": "r2", "detail": {"endpoint": "/v1/images/generations", "status": "success"}},
            {"ts": f"{today}T10:02:00", "type": "call", "summary": "r3", "detail": {"endpoint": "/v1/chat/completions", "status": "success"}},
        ])

        result = service.aggregate(filter={}, group_by="endpoint")
        assert len(result) == 2
        counts = {r["group"]: r["count"] for r in result}
        assert counts["/v1/chat/completions"] == 2
        assert counts["/v1/images/generations"] == 1

    # ---- 多维度组合查询 ----

    def test_multi_dimension_aggregate_type_provider(self, tmp_path) -> None:
        """multi_dimension_aggregate 支持 type+provider 双维度组合。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "r1", "detail": {"provider": "chatgpt", "status": "success"}},
            {"ts": f"{today}T10:01:00", "type": "call", "summary": "r2", "detail": {"provider": "chatgpt", "status": "success"}},
            {"ts": f"{today}T10:02:00", "type": "call", "summary": "r3", "detail": {"provider": "grok", "status": "success"}},
            {"ts": f"{today}T10:03:00", "type": "image", "summary": "g1", "detail": {"provider": "chatgpt", "status": "success"}},
        ])

        result = service.multi_dimension_aggregate(filter={}, group_by=["type", "provider"])

        # 应该有 3 个组合
        assert len(result) == 3
        lookup = {}
        for r in result:
            dims = r["dimensions"]
            lookup[(dims["type"], dims["provider"])] = r["count"]

        assert lookup[("call", "chatgpt")] == 2
        assert lookup[("call", "grok")] == 1
        assert lookup[("image", "chatgpt")] == 1

    def test_multi_dimension_aggregate_empty(self, tmp_path) -> None:
        """无日志时 multi_dimension_aggregate 返回空列表。"""
        service = self._make_service(tmp_path)
        result = service.multi_dimension_aggregate(filter={}, group_by=["type", "provider"])
        assert result == []

    def test_multi_dimension_aggregate_missing_dim(self, tmp_path) -> None:
        """缺维度的条目归为 unknown。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"ts": f"{today}T10:00:00", "type": "call", "summary": "r1", "detail": {}},
            {"ts": f"{today}T10:01:00", "type": "call", "summary": "r2", "detail": {"provider": "chatgpt"}},
        ])

        result = service.multi_dimension_aggregate(filter={}, group_by=["type", "provider"])
        lookup = {}
        for r in result:
            dims = r["dimensions"]
            lookup[(dims["type"], dims["provider"])] = r["count"]

        assert lookup[("call", "unknown")] == 1
        assert lookup[("call", "chatgpt")] == 1


class TestPaginatedExport:
    """1.2 分页导出测试。"""

    def _make_service(self, tmp_path: Path) -> LogService:
        return LogService(tmp_path / "logs.jsonl")

    def _seed_many(self, service: LogService, n: int) -> None:
        """写入 n 条日志。"""
        today = _today()
        entries = []
        for i in range(n):
            entries.append({
                "id": f"id-{i:04d}",
                "ts": f"{today}T10:{i:02d}:00",
                "type": "call",
                "summary": f"req-{i}",
                "detail": {"status": "success", "duration_ms": i * 10},
            })
        _seed_daily_file(service, today, entries)

    # ---- CSV 分页 ----

    def test_export_csv_paginated_first_page(self, tmp_path) -> None:
        """CSV 分页导出第一页，返回 header + 数据行。"""
        service = self._make_service(tmp_path)
        self._seed_many(service, 25)

        result = service.export_csv_paginated(filter={}, page=1, page_size=10)

        assert result["total"] == 25
        assert result["page"] == 1
        assert result["page_size"] == 10
        assert result["total_pages"] == 3
        # 第一页包含 header + 10 行数据
        assert len(result["items"]) == 11
        assert result["items"][0] == "id,time,type,summary,status,error"
        # 最新在前
        assert "id-0024" in result["items"][1]

    def test_export_csv_paginated_second_page(self, tmp_path) -> None:
        """CSV 分页导出第二页，不应包含 header。"""
        service = self._make_service(tmp_path)
        self._seed_many(service, 25)

        result = service.export_csv_paginated(filter={}, page=2, page_size=10)

        assert result["page"] == 2
        assert len(result["items"]) == 10
        # 第二页不应包含 header
        assert result["items"][0].startswith("id-")

    def test_export_csv_paginated_with_fields(self, tmp_path) -> None:
        """CSV 分页导出 support fields 参数。"""
        service = self._make_service(tmp_path)
        self._seed_many(service, 5)

        result = service.export_csv_paginated(filter={}, page=1, page_size=5, fields=["id", "type"])

        assert result["items"][0] == "id,type"
        assert "id-0004" in result["items"][1]

    # ---- JSON 分页 ----

    def test_export_json_paginated(self, tmp_path) -> None:
        """JSON 分页导出返回 JSON 字符串行。"""
        service = self._make_service(tmp_path)
        self._seed_many(service, 25)

        result = service.export_json(filter={}, page=1, page_size=10)

        assert result["total"] == 25
        assert result["page"] == 1
        assert result["page_size"] == 10
        assert result["total_pages"] == 3
        assert len(result["items"]) == 10
        # 验证 JSON 可解析
        for line in result["items"]:
            parsed = json.loads(line)
            assert isinstance(parsed, dict)

    def test_export_json_paginated_with_fields(self, tmp_path) -> None:
        """JSON 分页导出 support fields 参数。"""
        service = self._make_service(tmp_path)
        self._seed_many(service, 5)

        result = service.export_json(filter={}, page=1, page_size=5, fields=["id", "type"])

        for line in result["items"]:
            parsed = json.loads(line)
            assert set(parsed.keys()) <= {"id", "type"}

    def test_export_json_paginated_empty(self, tmp_path) -> None:
        """无日志时分页导出返回空 items。"""
        service = self._make_service(tmp_path)

        result = service.export_json(filter={}, page=1, page_size=10)

        assert result["total"] == 0
        assert result["items"] == []

    # ---- export_csv 支持 fields ----

    def test_export_csv_with_fields(self, tmp_path) -> None:
        """export_csv 支持可选 fields 参数。"""
        service = self._make_service(tmp_path)
        today = _today()
        _seed_daily_file(service, today, [
            {"id": "abc", "ts": f"{today}T10:00:00", "type": "call", "summary": "test",
             "detail": {"status": "success", "error": "none"}},
        ])

        csv_text = service.export_csv(filter={}, fields=["id", "type"])
        lines = csv_text.splitlines()
        assert lines[0] == "id,type"
        assert "abc" in lines[1]


class TestArchiveIntegrity:
    """1.3 归档完整性测试。"""

    def _make_service(self, tmp_path: Path) -> LogService:
        return LogService(tmp_path / "logs.jsonl")

    def test_archive_gzip_sha256(self, tmp_path) -> None:
        """归档后生成 gzip 压缩文件 + sha256 校验清单 + 归档索引。"""
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

        # 归档路径存在
        archive_path = Path(result["archive_path"])
        assert archive_path.exists(), "归档目录应存在"
        assert archive_path.is_dir()

        # 校验 gzip 压缩文件
        gz_path = archive_path / f"logs-{expired_day}.jsonl.gz"
        assert gz_path.exists(), "gzip 压缩文件应存在"
        decompressed = gzip.decompress(gz_path.read_bytes()).decode("utf-8")
        assert "old" in decompressed

        # 校验 sha256 校验清单
        checksum_path = archive_path / "checksums.sha256"
        assert checksum_path.exists()
        checksum_content = checksum_path.read_text(encoding="utf-8")
        assert f"logs-{expired_day}.jsonl" in checksum_content

        # 校验 sha256 值与返回的 checksums 一致
        checksums = result["checksums"]
        assert f"logs-{expired_day}.jsonl" in checksums
        assert len(checksums[f"logs-{expired_day}.jsonl"]) == 64  # sha256 hex

        # 校验清单中哈希与 checksums 一致
        assert checksum_content.startswith(checksums[f"logs-{expired_day}.jsonl"])

        # 校验归档索引
        index_path = result["index_path"]
        assert Path(index_path).exists()
        index_data = json.loads(Path(index_path).read_text(encoding="utf-8"))
        assert isinstance(index_data, list)
        assert len(index_data) >= 1
        latest = index_data[-1]
        # 新格式索引不含 archived 字段，但应有 files/checksums/cutoff
        assert latest.get("files") == [f"logs-{expired_day}.jsonl"]
        assert "checksums" in latest

    def test_archive_checksum_verify_content(self, tmp_path) -> None:
        """归档后 sha256 校验值应与原始文件内容一致。"""
        service = self._make_service(tmp_path)
        expired_day = _days_ago(95)
        _seed_daily_file(service, expired_day, [
            {"ts": f"{expired_day}T10:00:00", "type": "call", "summary": "verify-me", "detail": {}},
        ])

        # 计算原始文件 bytes 的预期 sha256（archive 存储的是原始文件 bytes 的 sha256）
        fpath = service._daily_path(expired_day)
        raw_bytes = fpath.read_bytes()
        expected_sha256 = hashlib.sha256(raw_bytes).hexdigest()

        result = service.archive(before_days=90)

        checksums = result["checksums"]
        # checksums 的 key 是原始文件名（非 .gz），value 是原始文件 bytes 的 sha256
        raw_name = f"logs-{expired_day}.jsonl"
        assert raw_name in checksums, f"checksums 应包含原始文件名 {raw_name}"
        assert checksums[raw_name] == expected_sha256, "sha256 校验值应与原始内容匹配"
        assert result["archived"] == 1


class TestSlowQueryDetail:
    """1.4 慢查询详情测试。"""

    def _make_service(self, tmp_path: Path) -> LogService:
        return LogService(tmp_path / "logs.jsonl")

    def test_slow_query_detail_write(self, tmp_path, monkeypatch) -> None:
        """slow_query_detail 写入 data/slow_queries/slow_queries-YYYY-MM-DD.jsonl。"""
        from services.config import DATA_DIR
        service = self._make_service(tmp_path)

        # 临时替换 DATA_DIR 到 tmp_path 下
        monkeypatch.setattr("services.log_service.DATA_DIR", tmp_path)

        detail = {
            "duration_ms": 12345,
            "endpoint": "/v1/chat/completions",
            "model": "gpt-4",
            "account_email": "a@test.com",
        }
        service.slow_query_detail(detail)

        today = _today()
        slow_path = tmp_path / "slow_queries" / f"slow_queries-{today}.jsonl"
        assert slow_path.exists(), "慢查询文件应存在"

        lines = slow_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["duration_ms"] == 12345
        assert parsed["endpoint"] == "/v1/chat/completions"
        assert parsed["model"] == "gpt-4"
        assert "ts" in parsed  # 自动补 ts

    def test_slow_query_detail_append(self, tmp_path, monkeypatch) -> None:
        """多次写入 append 到同一文件，不覆盖。"""
        from services.config import DATA_DIR
        service = self._make_service(tmp_path)
        monkeypatch.setattr("services.log_service.DATA_DIR", tmp_path)

        service.slow_query_detail({"duration_ms": 1000, "endpoint": "/v1/chat"})
        service.slow_query_detail({"duration_ms": 2000, "endpoint": "/v1/image"})

        today = _today()
        slow_path = tmp_path / "slow_queries" / f"slow_queries-{today}.jsonl"
        lines = slow_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

    def test_list_slow_queries_by_threshold(self, tmp_path, monkeypatch) -> None:
        """list_slow_queries 按阈值过滤。"""
        from services.config import DATA_DIR
        service = self._make_service(tmp_path)
        monkeypatch.setattr("services.log_service.DATA_DIR", tmp_path)

        service.slow_query_detail({"duration_ms": 1000, "endpoint": "/v1/fast"})
        service.slow_query_detail({"duration_ms": 6000, "endpoint": "/v1/slow"})
        service.slow_query_detail({"duration_ms": 10000, "endpoint": "/v1/slower"})

        # 默认阈值 5000
        result = service.list_slow_queries()
        assert len(result) == 2
        assert result[0]["duration_ms"] == 10000
        assert result[1]["duration_ms"] == 6000

        # 自定义阈值
        result2 = service.list_slow_queries(threshold_ms=8000)
        assert len(result2) == 1
        assert result2[0]["duration_ms"] == 10000

    def test_list_slow_queries_by_date(self, tmp_path, monkeypatch) -> None:
        """list_slow_queries 按日期范围过滤。"""
        from services.config import DATA_DIR
        service = self._make_service(tmp_path)
        monkeypatch.setattr("services.log_service.DATA_DIR", tmp_path)

        # 手动写入不同日期的文件
        slow_dir = tmp_path / "slow_queries"
        slow_dir.mkdir(parents=True, exist_ok=True)
        old_day = _days_ago(3)
        old_path = slow_dir / f"slow_queries-{old_day}.jsonl"
        old_path.write_text(
            json.dumps({"duration_ms": 9000, "endpoint": "/v1/old"}, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        today = _today()
        today_path = slow_dir / f"slow_queries-{today}.jsonl"
        today_path.write_text(
            json.dumps({"duration_ms": 5000, "endpoint": "/v1/new"}, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        # 只查最近 1 天
        result = service.list_slow_queries(start_date=_days_ago(1), end_date=today, threshold_ms=4000)
        assert len(result) == 1
        assert result[0]["endpoint"] == "/v1/new"


class TestLogRotationStrategy:
    """1.5 可配置轮转策略测试。"""

    def _make_service(self, tmp_path: Path) -> LogService:
        return LogService(tmp_path / "logs.jsonl")

    def test_rotation_strategy_default_day(self, tmp_path) -> None:
        """默认轮转策略为 day（不触发 size 轮转）。"""
        service = self._make_service(tmp_path)
        assert service._log_rotation_strategy == "day"

    def test_size_rotation_renames_file(self, tmp_path, monkeypatch) -> None:
        """size 模式：单文件超 max_size_mb 时滚动重命名 .1 后缀。"""
        service = self._make_service(tmp_path)
        # 模拟 config.data 中 log_rotation 配置
        import services.config as cfg_mod
        monkeypatch.setitem(cfg_mod.config.data, "log_rotation", {"strategy": "size", "max_size_mb": 1})

        # 写入足够数据触发轮转
        today = _today()
        path = service._daily_path(today)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 写 2MB 数据
        big_line = "x" * 1024 * 100  # 100KB
        with path.open("w", encoding="utf-8") as f:
            for _ in range(25):  # 约 2.5MB
                f.write(big_line + "\n")

        # 触发轮转检查
        service._check_size_rotation()

        # 原文件应被重命名为 .1
        rotated = service._log_dir / f"logs-{today}.1.jsonl"
        assert rotated.exists(), "超限文件应被重命名为 .1"

    def test_mixed_rotation(self, tmp_path, monkeypatch) -> None:
        """mixed 模式：按天 + 超大小同时生效。"""
        service = self._make_service(tmp_path)
        # 模拟 config.data 中 log_rotation 配置
        import services.config as cfg_mod
        monkeypatch.setitem(cfg_mod.config.data, "log_rotation", {"strategy": "mixed", "max_size_mb": 1})

        # 验证策略为 mixed
        assert service._log_rotation_strategy == "mixed"

        # 验证 _check_size_rotation 在 mixed 模式下也会触发
        today = _today()
        path = service._daily_path(today)
        path.parent.mkdir(parents=True, exist_ok=True)
        big_line = "x" * 1024 * 100
        with path.open("w", encoding="utf-8") as f:
            for _ in range(25):
                f.write(big_line + "\n")

        service._check_size_rotation()

        rotated = service._log_dir / f"logs-{today}.1.jsonl"
        assert rotated.exists(), "mixed 模式下 size 轮转应生效"

    def test_rotation_config_read(self, tmp_path, monkeypatch) -> None:
        """_log_rotation_strategy 从 config 读取值。"""
        # 模拟 config 中有 log_rotation 配置
        import services.config as cfg_mod
        original_data = cfg_mod.config.data
        try:
            cfg_mod.config.data["log_rotation"] = {"strategy": "size", "max_size_mb": 200}
            service = self._make_service(tmp_path)
            assert service._log_rotation_strategy == "size"
            assert service._log_rotation_max_size_mb == 200
        finally:
            cfg_mod.config.data = original_data