"""III-04 慢查询清零 + 基准化测试。

覆盖：
- slow_query_report.py：结构化 JSON 输出（热点清单/数量/分级）、阈值断言退出码
- 存储优化：JSON 内容去重写（无谓覆写消除）、DB _save_rows 优化形态行为
- Prometheus 埋点：c2api_storage_operation_duration_seconds 直方图写入
"""

from __future__ import annotations

import json
from pathlib import Path

from prometheus_client import REGISTRY, generate_latest
from prometheus_client.parser import text_string_to_metric_families

import scripts.slow_query_report as sqr
from services.storage import database_storage, json_storage
from services.storage.database_storage import DatabaseStorageBackend
from services.storage.json_storage import JSONStorageBackend

# ---------------------------------------------------------------------------
# 报告脚本：结构化 JSON + 热点分级
# ---------------------------------------------------------------------------


def test_build_report_data_structure(tmp_path):
    """build_report_data 返回 CI 可断言的完整结构（热点/分级/阈值）。"""
    data = sqr.build_report_data(
        [{"name": "a.json", "size": 10, "entries": 1, "lines": 1}],
        {"backend_found": True, "tables": ["accounts"], "indexes": ["access_token"], "warnings": []},
        "20260812_000000",
        "reports/slowquery/20260812_000000.md",
        max_hotspots=2,
    )
    assert data["generated_at"]
    assert data["report_file"] == "reports/slowquery/20260812_000000.md"
    assert data["data_files_count"] == 1
    assert data["thresholds"] == {"max_hotspots": 2}
    assert data["sqlite"]["tables"] == ["accounts"]

    hs = data["hotspots"]
    assert hs["total"] == len(sqr.HOTSPOTS) > 0
    assert hs["total"] == hs["resolved"] + hs["accepted_degradation"] + hs["unresolved"]
    assert len(hs["items"]) == hs["total"]
    for item in hs["items"]:
        # 每个热点必须明确分级，且不可静默归零（拒绝伪造）
        assert item["status"] in {"resolved", "accepted_degradation"}
        assert item["name"]
        assert item["location"]
        assert item["reason"], "可接受降级/已解决必须写明理由"


def test_build_report_data_no_unresolved_hotspots():
    """验收门禁：unresolved 必须为 0（热点 = 0 或全部注明可接受降级）。"""
    data = sqr.build_report_data([], {"backend_found": True, "tables": [], "indexes": [], "warnings": []}, "s", "r.md")
    assert data["hotspots"]["unresolved"] == 0


def test_write_report_files_writes_json_alongside_md(tmp_path, monkeypatch):
    """默认双份输出：.md 报告 + 同名结构化 .json。"""
    monkeypatch.setattr(sqr, "ROOT", tmp_path)
    monkeypatch.setattr(sqr, "DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir()

    md_path = sqr.write_report_files(
        sqr.scan_data_files(),
        sqr.check_sqlite_indexes(),
    )
    assert md_path.exists()
    json_path = md_path.with_suffix(".json")
    assert json_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["hotspots"]["total"] == len(sqr.HOTSPOTS)
    assert payload["hotspots"]["unresolved"] == 0
    assert payload["report_file"] == md_path.relative_to(tmp_path).as_posix()


def test_main_threshold_exit_codes(tmp_path, monkeypatch, capsys):
    """--max-hotspots 超限返回非零（CI 断言）；缺省返回 0（不破坏 run_all_guards）。"""
    monkeypatch.setattr(sqr, "ROOT", tmp_path)
    monkeypatch.setattr(sqr, "DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir()

    assert sqr.main([]) == 0
    total = len(sqr.HOTSPOTS)
    assert sqr.main(["--max-hotspots", str(total)]) == 0
    assert sqr.main(["--max-hotspots", str(total - 1)]) == 1
    capsys.readouterr()


# ---------------------------------------------------------------------------
# JSON 存储：内容去重写（消除无谓整文件覆写）
# ---------------------------------------------------------------------------


def test_json_save_skips_write_when_content_unchanged(tmp_path, monkeypatch):
    """相同内容二次保存应跳过原子写（慢查询热点『整文件覆写』缓解）。"""
    calls: list[Path] = []
    original = json_storage._atomic_write_text

    def counting(path, content, **kwargs):  # noqa: ANN001
        calls.append(Path(path))
        return original(path, content, **kwargs)

    monkeypatch.setattr(json_storage, "_atomic_write_text", counting)
    backend = JSONStorageBackend(tmp_path / "accounts.json", tmp_path / "auth_keys.json")

    backend.save_accounts([{"access_token": "tok-a", "name": "A"}])
    assert len(calls) == 1
    backend.save_accounts([{"access_token": "tok-a", "name": "A"}])  # 内容未变
    assert len(calls) == 1, "内容未变时应跳过写盘"
    backend.save_accounts([{"access_token": "tok-a", "name": "A updated"}])
    assert len(calls) == 2, "内容变化时必须写盘"


def test_json_save_auth_keys_skips_write_when_unchanged(tmp_path, monkeypatch):
    calls: list[Path] = []
    original = json_storage._atomic_write_text

    def counting(path, content, **kwargs):  # noqa: ANN001
        calls.append(Path(path))
        return original(path, content, **kwargs)

    monkeypatch.setattr(json_storage, "_atomic_write_text", counting)
    backend = JSONStorageBackend(tmp_path / "accounts.json", tmp_path / "auth_keys.json")
    keys = [{"id": "k1", "key_hash": "x" * 64}]

    backend.save_auth_keys(keys)
    assert len(calls) == 1
    backend.save_auth_keys(keys)  # 内容未变
    assert len(calls) == 1


def test_json_save_unchanged_still_persists_valid_file(tmp_path):
    """去重写跳过的是 I/O，不是数据本身——文件仍须可解析、数据完整。"""
    backend = JSONStorageBackend(tmp_path / "accounts.json", tmp_path / "auth_keys.json")
    accounts = [{"access_token": "tok-a", "name": "A"}]
    backend.save_accounts(accounts)
    backend.save_accounts(accounts)  # 跳过写盘
    assert backend.load_accounts() == accounts
    assert json.loads((tmp_path / "accounts.json").read_text(encoding="utf-8")) == accounts


# ---------------------------------------------------------------------------
# DB 存储：_save_rows 优化形态行为回归
# ---------------------------------------------------------------------------


def test_db_save_rows_bulk_delete_removes_only_missing(tmp_path):
    """批量删除（synchronize_session=False）只删缺失行，保留行 ID/data 稳定。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'opt.db'}")
    backend.save_accounts(
        [
            {"access_token": "t-a", "name": "A"},
            {"access_token": "t-b", "name": "B"},
            {"access_token": "t-c", "name": "C"},
        ]
    )
    session = backend.Session()
    try:
        before_ids = {row.access_token: row.id for row in session.query(database_storage.AccountModel).all()}
    finally:
        session.close()

    backend.save_accounts([{"access_token": "t-b", "name": "B updated"}])  # 删除 a/c，改 b

    loaded = backend.load_accounts()
    assert [a["access_token"] for a in loaded] == ["t-b"]
    assert loaded[0]["name"] == "B updated"
    session = backend.Session()
    try:
        row = session.query(database_storage.AccountModel).filter_by(access_token="t-b").one()
        assert row.id == before_ids["t-b"], "保留行 ID 必须稳定"
    finally:
        session.close()


def test_db_save_rows_add_only_no_duplicate_rows(tmp_path):
    """新增路径 add_all 后行数正确、无重复。"""
    backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'addonly.db'}")
    backend.save_accounts([{"access_token": f"tok-{i}", "name": f"N{i}"} for i in range(50)])
    assert len(backend.load_accounts()) == 50
    backend.save_accounts([{"access_token": f"tok-{i}", "name": f"N{i}"} for i in range(50)])
    assert len(backend.load_accounts()) == 50, "重复保存不得产生重复行"


# ---------------------------------------------------------------------------
# Prometheus 埋点：存储操作直方图
# ---------------------------------------------------------------------------


def _storage_count(backend: str, operation: str) -> float:
    output = generate_latest(REGISTRY).decode()
    target = "c2api_storage_operation_duration_seconds_count"
    for family in text_string_to_metric_families(output):
        for sample in family.samples:
            if sample.name == target and sample.labels == {"backend": backend, "operation": operation}:
                return sample.value
    return 0.0


def test_record_storage_operation_writes_histogram():
    """record_storage_operation 写入直方图 count（P50/P95 由 Prometheus 侧聚合）。"""
    from services.prometheus_metrics import record_storage_operation

    before = _storage_count("json", "save_accounts")
    record_storage_operation("json", "save_accounts", 0.002)
    assert _storage_count("json", "save_accounts") >= before + 1


def test_storage_backends_emit_operation_metrics(tmp_path):
    """真实 JSON/DB 后端操作触发计时埋点（基准化生效）。"""
    from services.prometheus_metrics import storage_operation_timer

    js_backend = JSONStorageBackend(tmp_path / "acc.json", tmp_path / "key.json")
    js_backend.save_accounts([{"access_token": "t", "name": "A"}])
    assert _storage_count("json", "save_accounts") >= 1
    js_backend.load_accounts()
    assert _storage_count("json", "load_accounts") >= 1

    db_backend = DatabaseStorageBackend(f"sqlite:///{tmp_path / 'op-metrics.db'}")
    db_backend.save_accounts([{"access_token": "t", "name": "A"}])
    assert _storage_count("database", "save_accounts") >= 1
    db_backend.load_accounts()
    assert _storage_count("database", "load_accounts") >= 1

    # contextmanager 形式可直接使用
    with storage_operation_timer("database", "health_check"):
        pass
    assert _storage_count("database", "health_check") >= 1
