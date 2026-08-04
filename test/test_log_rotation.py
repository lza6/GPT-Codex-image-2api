"""4.1：logs.jsonl 按天轮转切分——按天写入、list(days=N) 只读最近 N 天、过期天文件整删、
旧 logs.jsonl 一次性迁移无丢失、删除跨天文件。

慢查询根治：/api/logs 与前端日志页轮询不再每次全量读单一日志文件，改为按天文件分片读取。
同时保证 test_logs_account_filter（直接写 service.path）与既有行为兼容——迁移在
list/delete/_auto_cleanup 首次访问时惰性触发，旧 logs.jsonl 被迁移到天文件后 rename 备份。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from services.log_service import LogService


def _entry(entry_id: str, ts: str, summary: str, account_email: str = "") -> dict:
    return {
        "id": entry_id,
        "time": ts,
        "type": "调用",
        "summary": summary,
        "detail": {"account_email": account_email, "status": "success"},
    }


def _json_line(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


class TestLogRotation:
    def test_add_writes_daily_file(self, tmp_path) -> None:
        """add 应写入当天天文件，而非旧的 logs.jsonl。"""
        service = LogService(tmp_path / "logs.jsonl")
        service.add("调用", "call-a", {"status": "success"})

        daily = tmp_path / f"logs-{_today()}.jsonl"
        assert daily.exists(), "当天天文件应存在"
        assert not (tmp_path / "logs.jsonl").exists(), "不应再写旧单文件"

        lines = daily.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["summary"] == "call-a"

    def test_list_reads_across_daily_files_newest_first(self, tmp_path) -> None:
        """list 应跨天文件读取，最新在前（新文件内新行在前）。"""
        service = LogService(tmp_path / "logs.jsonl")
        # 直接构造两个天文件（绕过 add，保证日期可控）
        old_file = tmp_path / f"logs-{_days_ago(2)}.jsonl"
        new_file = tmp_path / f"logs-{_today()}.jsonl"
        old_file.write_text("\n".join([
            _json_line(_entry("o1", f"{_days_ago(2)} 10:00:00", "old-call")),
            _json_line(_entry("o2", f"{_days_ago(2)} 11:00:00", "old-call-2")),
        ]) + "\n", encoding="utf-8")
        new_file.write_text("\n".join([
            _json_line(_entry("n1", f"{_today()} 09:00:00", "new-call")),
        ]) + "\n", encoding="utf-8")

        items = service.list()
        summaries = [i["summary"] for i in items]
        assert summaries == ["new-call", "old-call-2", "old-call"], "最新在前，跨天倒序"

    def test_list_days_only_reads_recent_files(self, tmp_path, monkeypatch) -> None:
        """list(days=1) 只读最近 1 天天文件，不触碰更早天文件（mock 文件系统断言）。"""
        service = LogService(tmp_path / "logs.jsonl")
        today = _today()
        old_day = _days_ago(2)
        (tmp_path / f"logs-{today}.jsonl").write_text(
            _json_line(_entry("n1", f"{today} 09:00:00", "today-call")) + "\n", encoding="utf-8"
        )
        (tmp_path / f"logs-{old_day}.jsonl").write_text(
            _json_line(_entry("o1", f"{old_day} 09:00:00", "old-call")) + "\n", encoding="utf-8"
        )

        read_files: list[str] = []
        orig_read_text = Path.read_text

        def _tracking_read_text(self, *args, **kwargs):
            read_files.append(str(self))
            return orig_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _tracking_read_text)
        items = service.list(days=1)
        summaries = [i["summary"] for i in items]

        assert summaries == ["today-call"], "days=1 只应命中今天"
        assert len(read_files) == 1, f"只应读取 1 个文件，实际读取: {read_files}"
        assert f"logs-{today}.jsonl" in read_files[0], "应读取当天文件"
        assert f"logs-{old_day}.jsonl" not in read_files[0], "不应触碰更早天文件"

    def test_list_days_combined_with_start_date_expands(self, tmp_path) -> None:
        """days=1 但 start_date 更早时，文件范围应扩展到覆盖 start_date（不丢历史）。"""
        service = LogService(tmp_path / "logs.jsonl")
        today = _today()
        old_day = _days_ago(5)
        (tmp_path / f"logs-{today}.jsonl").write_text(
            _json_line(_entry("n1", f"{today} 09:00:00", "today-call")) + "\n", encoding="utf-8"
        )
        (tmp_path / f"logs-{old_day}.jsonl").write_text(
            _json_line(_entry("o1", f"{old_day} 09:00:00", "old-call")) + "\n", encoding="utf-8"
        )
        items = service.list(days=1, start_date=old_day)
        assert [i["summary"] for i in items] == ["today-call", "old-call"]

    def test_expired_daily_files_deleted_by_cleanup(self, tmp_path) -> None:
        """过期天文件（超过保留天数）应被 _auto_cleanup 整删，不再逐行重写。"""
        service = LogService(tmp_path / "logs.jsonl")
        today = _today()
        # 保留天数 = 90（与 usage_agg 窗口对齐），超过 90 天才整删
        expired_day = _days_ago(95)
        expired_file = tmp_path / f"logs-{expired_day}.jsonl"
        today_file = tmp_path / f"logs-{today}.jsonl"
        expired_file.write_text(_json_line(_entry("e1", f"{expired_day} 00:00:00", "expired")) + "\n", encoding="utf-8")
        today_file.write_text(_json_line(_entry("n1", f"{today} 00:00:00", "keep")) + "\n", encoding="utf-8")

        service._auto_cleanup()

        assert not expired_file.exists(), "过期天文件应被整删"
        assert today_file.exists(), "保留期内天文件不应被删"

    def test_today_file_trimmed_when_over_limit(self, tmp_path) -> None:
        """当天文件超过 _AUTO_CLEAN_MAX_ENTRIES 时裁剪到 _AUTO_CLEAN_KEEP。"""
        service = LogService(tmp_path / "logs.jsonl")
        today = _today()
        daily = tmp_path / f"logs-{today}.jsonl"
        n = service._AUTO_CLEAN_MAX_ENTRIES + 10
        daily.write_text(
            "\n".join(_json_line(_entry(f"id{i}", f"{today} 00:00:00", f"call-{i}")) for i in range(n)) + "\n",
            encoding="utf-8",
        )

        service._auto_cleanup()

        lines = daily.read_text(encoding="utf-8").splitlines()
        assert len(lines) == service._AUTO_CLEAN_KEEP, "超限应裁剪到保留量"
        assert json.loads(lines[0])["id"] == f"id{n - service._AUTO_CLEAN_KEEP}", "应保留最新条目"

    def test_delete_across_daily_files(self, tmp_path) -> None:
        """delete 应跨天文件删除匹配 id。"""
        service = LogService(tmp_path / "logs.jsonl")
        old_day = _days_ago(2)
        (tmp_path / f"logs-{old_day}.jsonl").write_text(
            "\n".join([
                _json_line(_entry("o1", f"{old_day} 10:00:00", "old-a")),
                _json_line(_entry("o2", f"{old_day} 11:00:00", "old-b")),
            ]) + "\n", encoding="utf-8"
        )
        (tmp_path / f"logs-{_today()}.jsonl").write_text(
            _json_line(_entry("n1", f"{_today()} 09:00:00", "new-a")) + "\n", encoding="utf-8"
        )

        result = service.delete(["o2", "n1"])

        assert result == {"removed": 2}
        remaining = service.list()
        assert [i["summary"] for i in remaining] == ["old-a"]
        assert all(i["id"] not in {"o2", "n1"} for i in remaining)

    def test_legacy_migration_no_loss_no_dup(self, tmp_path) -> None:
        """旧 logs.jsonl 首次访问时迁移到天文件：无丢失、无重复、旧文件 rename 备份。"""
        service = LogService(tmp_path / "logs.jsonl")
        legacy = tmp_path / "logs.jsonl"
        # 混合两个日期的旧数据
        d1 = _days_ago(1)
        d2 = _days_ago(3)
        legacy.write_text("\n".join([
            _json_line(_entry("a", f"{d1} 10:00:00", "call-a")),
            _json_line(_entry("b", f"{d2} 10:00:00", "call-b")),
            _json_line(_entry("c", f"{d1} 11:00:00", "call-c")),
        ]) + "\n", encoding="utf-8")

        # 触发迁移
        items = service.list()
        assert {i["id"] for i in items} == {"a", "b", "c"}, "迁移后无丢失"

        backup = tmp_path / "logs.jsonl.legacy"
        assert backup.exists(), "旧文件应 rename 备份而非静默删除"
        assert not legacy.exists(), "原 logs.jsonl 不应残留（避免二次迁移重复）"

        # 各天文件行数与旧文件一致（无重复）
        d1_lines = (tmp_path / f"logs-{d1}.jsonl").read_text(encoding="utf-8").splitlines()
        d2_lines = (tmp_path / f"logs-{d2}.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(d1_lines) == 2, "d1 两条应完整迁移"
        assert len(d2_lines) == 1, "d2 一条应完整迁移"

        # 再 list 一次不应重复计数（迁移幂等）
        assert len(service.list()) == 3

    def test_list_days_combined_with_end_date_expands(self, tmp_path) -> None:
        """days=1 但 end_date 只设过去某天（无 start_date）时，文件范围应扩展到覆盖 end_date。

        否则 days 会把文件范围截到 end_date 之后，导致过滤结果恒为空（用户明确要看更早日志）。
        """
        service = LogService(tmp_path / "logs.jsonl")
        today = _today()
        old_day = _days_ago(10)
        (tmp_path / f"logs-{today}.jsonl").write_text(
            _json_line(_entry("n1", f"{today} 09:00:00", "today-call")) + "\n", encoding="utf-8"
        )
        (tmp_path / f"logs-{old_day}.jsonl").write_text(
            _json_line(_entry("o1", f"{old_day} 09:00:00", "old-call")) + "\n", encoding="utf-8"
        )
        items = service.list(days=1, end_date=old_day)
        assert [i["summary"] for i in items] == ["old-call"], "end_date 更早时应读到历史，不被 days 截断"

    def test_legacy_migration_ignores_empty_or_missing(self, tmp_path) -> None:
        """无旧 logs.jsonl 或空文件时迁移应静默跳过，不影响新日志。"""
        service = LogService(tmp_path / "logs.jsonl")
        assert service.list() == [], "无旧文件时 list 为空"
        # 空旧文件
        (tmp_path / "logs.jsonl").write_text("", encoding="utf-8")
        assert service.list() == []

    def test_list_limits_across_files(self, tmp_path) -> None:
        """limit 应跨天文件全局生效（新文件优先凑够）。"""
        service = LogService(tmp_path / "logs.jsonl")
        old_day = _days_ago(1)
        (tmp_path / f"logs-{old_day}.jsonl").write_text(
            "\n".join(_json_line(_entry(f"o{i}", f"{old_day} 10:00:00", f"old-{i}")) for i in range(3)) + "\n",
            encoding="utf-8",
        )
        (tmp_path / f"logs-{_today()}.jsonl").write_text(
            "\n".join(_json_line(_entry(f"n{i}", f"{_today()} 10:00:00", f"new-{i}")) for i in range(3)) + "\n",
            encoding="utf-8",
        )

        items = service.list(limit=4)
        assert [i["summary"] for i in items] == ["new-2", "new-1", "new-0", "old-2"], "limit 跨文件全局生效，最新优先"
