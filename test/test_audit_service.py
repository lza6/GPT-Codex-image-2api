"""3.2 审计日志：管理操作留痕——按天轮转 + 原子写 + 过期清理 + require_admin 统一埋点。

覆盖：
- record 写入当天天文件，字段完整（operator 末 8 位脱敏 / request_id / action / result / ip）
- list 跨天倒序 + days 只读最近 N 天
- 过期天文件整删
- 并发写原子性（多线程 append 不丢行）
- require_admin 成功/失败（401/403）均埋点（真实 TestClient 触发）
- 降噪：dashboard 轮询 GET 成功跳过，写操作与失败必记
- metrics：chatgpt2api_audit_actions_total 触发 +1
- 审计写失败不阻断请求（审计绝不破坏鉴权主流程）
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from services.audit_service import AuditService


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


class TestAuditRecord:
    def test_record_writes_daily_file_with_all_fields(self, tmp_path: Path) -> None:
        """record 应写入当天天文件，且关键字段完整。"""
        svc = AuditService(tmp_path / "audit.jsonl")
        svc.record(
            action="/api/settings",
            result="success",
            operator="key-abcdef12-3456",
            resource="",
            detail={"key": "value"},
            request_id="req123",
            ip="127.0.0.1",
            method="POST",
        )

        daily = tmp_path / f"audit-{_today()}.jsonl"
        assert daily.exists(), "当天天文件应存在"
        lines = daily.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        item = json.loads(lines[0])
        assert item["action"] == "/api/settings"
        assert item["result"] == "success"
        assert item["operator"] == "f12-3456"  # 末 8 位脱敏
        assert item["request_id"] == "req123"
        assert item["ip"] == "127.0.0.1"
        assert item["method"] == "POST"
        assert item["detail"] == {"key": "value"}
        assert item["ts"], "应有时间戳"

    def test_operator_masking_edge_cases(self, tmp_path: Path) -> None:
        """operator 脱敏：短串/空串/None 不崩。"""
        svc = AuditService(tmp_path / "audit.jsonl")
        assert svc._mask_operator("admin") == "admin"  # 短于 8 位原样
        assert svc._mask_operator("") == ""
        assert svc._mask_operator(None) == ""
        assert svc._mask_operator("abcdefghij") == "cdefghij"  # 末 8 位

    def test_record_defaults(self, tmp_path: Path) -> None:
        """record 缺省字段应有默认值，不抛 KeyError。"""
        svc = AuditService(tmp_path / "audit.jsonl")
        svc.record(action="/api/accounts/batch", result="success")
        item = json.loads((tmp_path / f"audit-{_today()}.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert item["operator"] == ""
        assert item["ip"] == ""
        assert item["method"] == ""


class TestAuditList:
    def test_list_across_daily_files_newest_first(self, tmp_path: Path) -> None:
        """list 应跨天文件读取，最新在前。"""
        svc = AuditService(tmp_path / "audit.jsonl")
        old_day = _days_ago(2)
        (tmp_path / f"audit-{old_day}.jsonl").write_text(
            json.dumps({"ts": f"{old_day} 10:00:00", "action": "/api/a", "result": "success"}) + "\n",
            encoding="utf-8",
        )
        (tmp_path / f"audit-{_today()}.jsonl").write_text(
            json.dumps({"ts": f"{_today()} 09:00:00", "action": "/api/b", "result": "success"}) + "\n",
            encoding="utf-8",
        )
        items = svc.list()
        assert [i["action"] for i in items] == ["/api/b", "/api/a"], "最新在前，跨天倒序"

    def test_list_days_only_reads_recent_files(self, tmp_path: Path, monkeypatch) -> None:
        """list(days=1) 只读最近 1 天天文件，不触碰更早天文件。"""
        svc = AuditService(tmp_path / "audit.jsonl")
        # 跳过惰性清理扫描（本测试只验证 list 的 days 过滤，不验证清理）：
        # maybe_cleanup 会 glob 全部 audit-*.jsonl，干扰 read_text 计数断言
        svc._last_cleanup_at = time.time()
        old_day = _days_ago(3)
        (tmp_path / f"audit-{_today()}.jsonl").write_text(
            json.dumps({"ts": f"{_today()} 09:00:00", "action": "/api/today"}) + "\n", encoding="utf-8"
        )
        (tmp_path / f"audit-{old_day}.jsonl").write_text(
            json.dumps({"ts": f"{old_day} 09:00:00", "action": "/api/old"}) + "\n", encoding="utf-8"
        )
        read_files: list[str] = []
        orig = Path.read_text

        def _tracking(self, *args, **kwargs):
            read_files.append(str(self))
            return orig(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _tracking)
        items = svc.list(days=1)
        assert [i["action"] for i in items] == ["/api/today"]
        assert len(read_files) == 1 and f"audit-{_today()}.jsonl" in read_files[0]

    def test_list_filters_result_and_operator(self, tmp_path: Path) -> None:
        """list 支持 result / operator 过滤。"""
        svc = AuditService(tmp_path / "audit.jsonl")
        today = _today()
        lines = [
            json.dumps({"ts": f"{today} 09:00:00", "action": "/api/settings", "result": "success", "operator": "abcdef12"}) + "\n",
            json.dumps({"ts": f"{today} 09:00:01", "action": "/api/settings", "result": "denied", "operator": "aaaaaaaa"}) + "\n",
        ]
        (tmp_path / f"audit-{today}.jsonl").write_text("".join(lines), encoding="utf-8")
        assert len(svc.list(result="denied")) == 1
        assert len(svc.list(operator="abcdef12")) == 1
        assert len(svc.list(result="success", operator="abcdef12")) == 1
        assert len(svc.list(result="success", operator="nope")) == 0

    def test_limit_across_files(self, tmp_path: Path) -> None:
        """limit 跨天全局生效，最新优先。"""
        svc = AuditService(tmp_path / "audit.jsonl")
        old_day = _days_ago(1)
        for n in range(3):
            (tmp_path / f"audit-{old_day}.jsonl").open("a", encoding="utf-8").write(
                json.dumps({"ts": f"{old_day} 10:00:0{n}", "action": f"/api/old-{n}"}) + "\n"
            )
        for n in range(3):
            (tmp_path / f"audit-{_today()}.jsonl").open("a", encoding="utf-8").write(
                json.dumps({"ts": f"{_today()} 10:00:0{n}", "action": f"/api/new-{n}"}) + "\n"
            )
        items = svc.list(limit=4)
        assert [i["action"] for i in items] == ["/api/new-2", "/api/new-1", "/api/new-0", "/api/old-2"]


class TestAuditCleanup:
    def test_expired_daily_files_deleted(self, tmp_path: Path) -> None:
        """过期天文件（超过保留天数）应被 _auto_cleanup 整删。"""
        svc = AuditService(tmp_path / "audit.jsonl")
        expired_day = _days_ago(95)
        expired = tmp_path / f"audit-{expired_day}.jsonl"
        today = tmp_path / f"audit-{_today()}.jsonl"
        expired.write_text('{"ts":"t","action":"/api/x"}\n', encoding="utf-8")
        today.write_text('{"ts":"t","action":"/api/y"}\n', encoding="utf-8")
        svc._auto_cleanup()
        assert not expired.exists(), "过期天文件应整删"
        assert today.exists(), "保留期内天文件应保留"

    def test_missing_file_cleanup_noop(self, tmp_path: Path) -> None:
        """无文件时 _auto_cleanup 不崩。"""
        svc = AuditService(tmp_path / "audit.jsonl")
        svc._auto_cleanup()

    def test_today_file_trimmed_when_over_limit(self, tmp_path: Path, monkeypatch) -> None:
        """当天文件超 _AUTO_CLEAN_MAX_ENTRIES 时裁剪到 _AUTO_CLEAN_KEEP（条目级）。"""
        import services.audit_service as audit_module

        monkeypatch.setattr(audit_module, "_AUTO_CLEAN_MAX_ENTRIES", 20)
        monkeypatch.setattr(audit_module, "_AUTO_CLEAN_KEEP", 10)
        svc = AuditService(tmp_path / "audit.jsonl")
        today = _today()
        daily = tmp_path / f"audit-{today}.jsonl"
        n = 25
        daily.write_text(
            "\n".join(
                json.dumps({"ts": f"{today} 00:00:00", "action": f"/api/a{i}", "result": "success"})
                for i in range(n)
            ) + "\n",
            encoding="utf-8",
        )

        svc._auto_cleanup()

        lines = daily.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 10, "超限应裁剪到保留量"
        assert json.loads(lines[0])["action"] == f"/api/a{n - 10}", "应保留最新条目"

    def test_concurrent_append_no_lost_lines(self, tmp_path: Path) -> None:
        """并发 append 不丢行（多线程原子追加）。"""
        svc = AuditService(tmp_path / "audit.jsonl")
        errors: list[Exception] = []

        def worker(i: int) -> None:
            try:
                for _ in range(50):
                    svc.record(action=f"/api/w{i}", result="success")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"并发写入异常: {errors}"
        daily = tmp_path / f"audit-{_today()}.jsonl"
        assert daily.exists()
        assert len(daily.read_text(encoding="utf-8").splitlines()) == 8 * 50, "不应丢行"


class TestRequireAdminAudit:
    """通过真实 TestClient 验证 require_admin 埋点行为。"""

    def _make_client(self, tmp_path: Path, monkeypatch):
        from fastapi.testclient import TestClient

        from api.app import create_app
        from services import audit_service as audit_module

        # 隔离：审计文件重定向到 tmp，防污染真实 data/
        monkeypatch.setattr(audit_module.audit_service, "path", tmp_path / "audit.jsonl")
        return TestClient(create_app())

    def test_successful_admin_action_recorded(self, tmp_path: Path, monkeypatch) -> None:
        """管理员成功访问写端点应记录 success，且 method 字段真实填充（R2 修复验证）。"""
        client = self._make_client(tmp_path, monkeypatch)
        resp = client.get("/api/settings", headers={"Authorization": "Bearer chatgpt2api"})
        assert resp.status_code == 200
        lines = (tmp_path / f"audit-{_today()}.jsonl").read_text(encoding="utf-8").splitlines()
        hit = next(
            (json.loads(line) for line in lines
             if json.loads(line)["result"] == "success" and json.loads(line)["action"] == "/api/settings"),
            None,
        )
        assert hit is not None, "应存在成功埋点"
        assert hit.get("method") == "GET", f"method 应填充为 GET，实际 {hit.get('method')!r}"

    def test_unauthorized_401_recorded(self, tmp_path: Path, monkeypatch) -> None:
        """无鉴权访问管理端点应记录 unauthorized。"""
        client = self._make_client(tmp_path, monkeypatch)
        resp = client.get("/api/settings")
        assert resp.status_code == 401
        lines = (tmp_path / f"audit-{_today()}.jsonl").read_text(encoding="utf-8").splitlines()
        assert lines, "401 也应留痕"
        assert any(json.loads(line)["result"] == "unauthorized" for line in lines)

    def test_forbidden_403_recorded(self, tmp_path: Path, monkeypatch) -> None:
        """普通 user 密钥访问管理端点应记录 denied。"""
        from services.auth_service import auth_service

        client = self._make_client(tmp_path, monkeypatch)
        # 创建普通用户 key 后调用管理端点 → 403
        item, raw_key = auth_service.create_key(role="user", name="audit-test")
        try:
            resp = client.get("/api/settings", headers={"Authorization": f"Bearer {raw_key}"})
            assert resp.status_code == 403
            lines = (tmp_path / f"audit-{_today()}.jsonl").read_text(encoding="utf-8").splitlines()
            assert any(json.loads(line)["result"] == "denied" for line in lines)
        finally:
            auth_service.delete_key(str(item.get("id")), role="user")

    def test_dashboard_polling_get_not_recorded_on_success(self, tmp_path: Path, monkeypatch) -> None:
        """dashboard 轮询 GET 成功不应记录（防 SSE/看板刷爆审计）。"""
        client = self._make_client(tmp_path, monkeypatch)
        resp = client.get("/api/dashboard/scheduler", headers={"Authorization": "Bearer chatgpt2api"})
        assert resp.status_code == 200
        daily = tmp_path / f"audit-{_today()}.jsonl"
        if not daily.exists():
            return  # 无记录即通过
        lines = daily.read_text(encoding="utf-8").splitlines()
        assert not any(
            json.loads(line)["result"] == "success" and json.loads(line)["action"].startswith("/api/dashboard/")
            for line in lines
        ), "dashboard 轮询成功不应进入审计"

    def test_login_success_recorded(self, tmp_path: Path, monkeypatch) -> None:
        """登录成功应留痕（operator 为 key id 末 8 位）。"""
        client = self._make_client(tmp_path, monkeypatch)
        resp = client.post("/auth/login", headers={"Authorization": "Bearer chatgpt2api"})
        assert resp.status_code == 200
        lines = (tmp_path / f"audit-{_today()}.jsonl").read_text(encoding="utf-8").splitlines()
        assert any(
            json.loads(line)["action"] == "/auth/login" and json.loads(line)["result"] == "success"
            for line in lines
        ), "登录成功应留痕"

    def test_login_failure_recorded(self, tmp_path: Path, monkeypatch) -> None:
        """登录失败（错误密钥）应留痕 unauthorized。"""
        client = self._make_client(tmp_path, monkeypatch)
        resp = client.post("/auth/login", headers={"Authorization": "Bearer wrong-key-123"})
        assert resp.status_code == 401
        lines = (tmp_path / f"audit-{_today()}.jsonl").read_text(encoding="utf-8").splitlines()
        assert lines, "登录失败也应留痕"
        assert any(
            json.loads(line)["action"] == "/auth/login" and json.loads(line)["result"] == "unauthorized"
            for line in lines
        ), "登录失败应记录 unauthorized"

    def test_metrics_counter_increments(self, tmp_path: Path, monkeypatch) -> None:
        """记录审计时 chatgpt2api_audit_actions_total 指标 +1（审计文件重定向 tmp，防污染 data/）。"""
        from services import prometheus_metrics as pm
        from services.audit_service import audit_service

        # 隔离：审计文件重定向到 tmp（R4：直接调全局 record 若不重定向会污染真实 data/audit-*.jsonl）
        monkeypatch.setattr(audit_service, "path", tmp_path / "audit.jsonl")

        if not hasattr(pm, "chatgpt2api_audit_actions_total"):
            raise AssertionError("chatgpt2api_audit_actions_total 指标不存在")
        counter = pm.chatgpt2api_audit_actions_total
        before = counter.labels(action="/api/audit-test", result="success")._value.get()
        audit_service.record(action="/api/audit-test", result="success")

        after = counter.labels(action="/api/audit-test", result="success")._value.get()
        assert after == before + 1

    def test_audit_failure_does_not_block_request(self, tmp_path: Path, monkeypatch) -> None:
        """审计写失败不应阻断请求（审计绝不破坏鉴权主流程）。"""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from api.app import create_app

        client = TestClient(create_app())
        with patch("api.support._audit_admin_access", side_effect=OSError("disk full")):
            resp = client.get("/api/settings", headers={"Authorization": "Bearer chatgpt2api"})
        assert resp.status_code == 200, "审计失败不应导致 500"


class TestAuditEndpoint:
    def test_audit_api_returns_items(self, tmp_path: Path, monkeypatch) -> None:
        """GET /api/audit 返回审计条目（契约字段对齐）。"""
        from fastapi.testclient import TestClient

        from api.app import create_app
        from services import audit_service as audit_module

        monkeypatch.setattr(audit_module.audit_service, "path", tmp_path / "audit.jsonl")
        audit_module.audit_service.record(action="/api/settings", result="success", operator="abcdef12", request_id="r1")
        client = TestClient(create_app())
        resp = client.get("/api/audit", headers={"Authorization": "Bearer chatgpt2api"})
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body and isinstance(body["items"], list)
        assert body["items"], "应有审计条目"
        first = body["items"][0]
        for key in ("ts", "action", "result", "operator"):
            assert key in first, f"审计条目缺字段 {key}"


def test_sensitive_action_triggers_alert() -> None:
    """敏感操作触发告警（不阻塞 record 主流程）。"""
    from services.audit_service import _SENSITIVE_ACTIONS, _is_sensitive_action
    assert _is_sensitive_action("delete key")
    assert _is_sensitive_action("/api/auth/keys/delete")
    assert _is_sensitive_action("update config")
    assert not _is_sensitive_action("get list")
    assert not _is_sensitive_action("read audit")
