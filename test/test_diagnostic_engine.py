"""诊断引擎单元测试。"""

from __future__ import annotations

import pytest

from services.diagnostic_engine import (
    DiagnosticResult, DiagnosticReport,
    CircuitBreakerCheck, AccountHealthCheck, NetworkCheck,
    StorageCheck, RateLimitCheck, SessionPoolCheck, ConfigConsistencyCheck,
    DiagnosticEngine, diagnostic_engine,
)


class TestDiagnosticResult:
    def test_default_ok(self):
        r = DiagnosticResult()
        assert r.status == "ok"
        assert r.severity == "info"

    def test_to_dict_in_report(self):
        report = DiagnosticReport()
        report.add(DiagnosticResult(check="test", status="ok", message="一切正常", severity="info"))
        report.add(DiagnosticResult(check="fail", status="error", message="出错了", severity="error"))
        assert report.summary["ok"] == 1
        assert report.summary["error"] == 1

    def test_duration(self):
        import time
        report = DiagnosticReport()
        report.started_at = time.time() - 1
        report.completed_at = time.time()
        assert report.duration_ms > 0


class TestDiagnosticEngine:
    def test_engine_has_7_checks(self):
        assert len(diagnostic_engine.checks) == 7

    @pytest.mark.asyncio
    async def test_diagnose_returns_report(self):
        report = await diagnostic_engine.diagnose()
        assert len(report.results) == 7
        assert report.started_at > 0
        assert report.completed_at > 0

    def test_get_last_report(self):
        import asyncio
        asyncio.run(diagnostic_engine.diagnose())
        report = diagnostic_engine.get_last_report()
        assert report is not None
        assert len(report["results"]) == 7

    @pytest.mark.asyncio
    async def test_circuit_breaker_check(self):
        check = CircuitBreakerCheck()
        result = await check.run()
        assert result.check == "circuit_breaker"
        assert result.status in ("ok", "warning", "error")

    @pytest.mark.asyncio
    async def test_account_health_check(self):
        check = AccountHealthCheck()
        result = await check.run()
        assert result.check == "account_health"
        assert result.status in ("ok", "warning", "error")

    @pytest.mark.asyncio
    async def test_network_check(self):
        check = NetworkCheck()
        result = await check.run()
        assert result.check == "network"
        assert result.status in ("ok", "warning", "error")

    @pytest.mark.asyncio
    async def test_storage_check(self):
        check = StorageCheck()
        result = await check.run()
        assert result.check == "storage"
        assert result.status in ("ok", "warning", "error")

    @pytest.mark.asyncio
    async def test_rate_limit_check(self):
        check = RateLimitCheck()
        result = await check.run()
        assert result.check == "rate_limit"

    @pytest.mark.asyncio
    async def test_session_pool_check(self):
        check = SessionPoolCheck()
        result = await check.run()
        assert result.check == "session_pool"

    @pytest.mark.asyncio
    async def test_config_consistency_check(self):
        check = ConfigConsistencyCheck()
        result = await check.run()
        assert result.check == "config_consistency"