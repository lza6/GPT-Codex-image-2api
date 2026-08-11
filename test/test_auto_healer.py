"""自动修复引擎单元测试。"""

from __future__ import annotations

import pytest

from services.diagnostic_engine import DiagnosticResult
from services.auto_healer import (
    HealingResult,
    StaleSessionHandler, DiskCleanupHandler, ProxyFailoverHandler,
    MemoryPressureHandler, ConfigRecoveryHandler, CircuitBreakerProbeHandler,
    AutoHealer, auto_healer,
)


class TestHealingResult:
    def test_default_not_healed(self):
        r = HealingResult()
        assert not r.healed

    def test_to_dict(self):
        r = HealingResult(healed=True, action="test", detail="ok", duration_ms=10.5)
        d = r.to_dict()
        assert d["healed"]
        assert d["action"] == "test"


class TestAutoHealer:
    def test_has_6_handlers(self):
        assert len(auto_healer.handlers) == 6

    def test_get_stats(self):
        stats = auto_healer.get_stats()
        assert "total_attempts" in stats
        assert "success_rate" in stats

    @pytest.mark.asyncio
    async def test_heal_no_handler(self):
        issue = DiagnosticResult(check="nonexistent", status="error", message="test")
        result = await auto_healer.heal(issue)
        assert not result.healed
        assert "无可用自动修复方案" in result.reason

    @pytest.mark.asyncio
    async def test_heal_stale_session(self):
        issue = DiagnosticResult(check="session_pool", status="warning", message="session expired", details={"session_key": "test_key"})
        handler = StaleSessionHandler()
        assert await handler.can_heal(issue)
        result = await handler.heal(issue)
        assert result.action == "session_rebuild"

    @pytest.mark.asyncio
    async def test_disk_cleanup_cannot_heal(self):
        issue = DiagnosticResult(check="storage", status="ok", message="磁盘空间充足")
        handler = DiskCleanupHandler()
        assert not await handler.can_heal(issue)

    @pytest.mark.asyncio
    async def test_proxy_failover_cannot_heal(self):
        issue = DiagnosticResult(check="network", status="ok", message="正常")
        handler = ProxyFailoverHandler()
        assert not await handler.can_heal(issue)

    @pytest.mark.asyncio
    async def test_memory_pressure_handler(self):
        issue = DiagnosticResult(check="memory", status="warning", message="memory pressure")
        handler = MemoryPressureHandler()
        assert await handler.can_heal(issue)
        result = await handler.heal(issue)
        assert result.action == "memory_cleanup"

    @pytest.mark.asyncio
    async def test_config_recovery_handler(self):
        issue = DiagnosticResult(check="config_consistency", status="warning", message="配置异常")
        handler = ConfigRecoveryHandler()
        assert await handler.can_heal(issue)
        result = await handler.heal(issue)
        assert result.action == "config_reload"

    def test_history_clear(self):
        auto_healer.clear_history()
        stats = auto_healer.get_stats()
        assert stats["total_attempts"] == 0
        assert stats["success_count"] == 0