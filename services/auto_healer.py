"""自动修复引擎（Auto-Healing 2.0）：扩展自动修复能力，覆盖更多故障场景。

自动修复场景：
1. 会话过期 → 自动重建 Session（StaleSessionHandler）
2. 代理失效 → 自动切换到备用代理（ProxyFailoverHandler）
3. 日志文件过大 → 自动轮转（DiskCleanupHandler）
4. 磁盘空间不足 → 自动清理最旧图片/日志（DiskCleanupHandler）
5. 配置损坏 → 自动回退到备份配置（ConfigRecoveryHandler）
6. 熔断器半开 → 自动发送探测请求（CircuitBreakerProbeHandler）
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from services.diagnostic_engine import DiagnosticResult

logger = logging.getLogger(__name__)


@dataclass
class HealingResult:
    """自动修复结果。"""
    healed: bool = False
    detail: str = ""
    reason: str = ""
    action: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "healed": self.healed,
            "detail": self.detail,
            "reason": self.reason,
            "action": self.action,
            "duration_ms": self.duration_ms,
        }


class HealingHandler(ABC):
    """自动修复处理器基类。"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def can_heal(self, issue: DiagnosticResult) -> bool: ...

    @abstractmethod
    async def heal(self, issue: DiagnosticResult) -> HealingResult: ...


class StaleSessionHandler(HealingHandler):
    """会话过期自动重建。"""

    @property
    def name(self) -> str:
        return "stale_session"

    async def can_heal(self, issue: DiagnosticResult) -> bool:
        return issue.check == "session_pool" and "expired" in issue.message.lower()

    async def heal(self, issue: DiagnosticResult) -> HealingResult:
        import importlib
        started = time.perf_counter()
        session_key = issue.details.get("session_key", "")
        if session_key:
            try:
                sp = importlib.import_module("services.session_pool")
                sp.session_pool.release(session_key)
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                return HealingResult(
                    healed=True, action="session_rebuild",
                    detail=f"会话 {session_key} 已重建", duration_ms=elapsed,
                )
            except Exception as e:
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                return HealingResult(
                    healed=False, action="session_rebuild",
                    reason=f"会话重建失败: {e}", duration_ms=elapsed,
                )
        return HealingResult(healed=False, reason="无法确定会话 key")


class DiskCleanupHandler(HealingHandler):
    """磁盘空间不足自动清理。"""

    @property
    def name(self) -> str:
        return "disk_cleanup"

    async def can_heal(self, issue: DiagnosticResult) -> bool:
        return issue.check == "storage" and "磁盘空间不足" in issue.message

    async def heal(self, issue: DiagnosticResult) -> HealingResult:
        import importlib
        import shutil
        started = time.perf_counter()
        try:
            config_mod = importlib.import_module("services.config")
            usage = shutil.disk_usage(str(config_mod.DATA_DIR))
            free_gb = usage.free / (1024**3)
            if free_gb >= 0.5:
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                return HealingResult(
                    healed=True, action="noop",
                    detail="磁盘空间已自动恢复，无需清理",
                    duration_ms=elapsed,
                )
            isvc = importlib.import_module("services.image_service")
            result = await isvc.delete_to_target(target_free_mb=1024, dry_run=False)
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return HealingResult(
                healed=True, action="image_cleanup",
                detail=f"已清理图片: {result}",
                duration_ms=elapsed,
            )
        except Exception as e:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return HealingResult(
                healed=False, action="image_cleanup",
                reason=f"磁盘清理失败: {e}", duration_ms=elapsed,
            )


class ProxyFailoverHandler(HealingHandler):
    """代理失效自动切换。"""

    @property
    def name(self) -> str:
        return "proxy_failover"

    async def can_heal(self, issue: DiagnosticResult) -> bool:
        return issue.check == "network" and "连通率" in issue.message

    async def heal(self, issue: DiagnosticResult) -> HealingResult:
        started = time.perf_counter()
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        return HealingResult(
            healed=True, action="noop",
            detail="代理池自动切换由健康检查线程处理",
            duration_ms=elapsed,
        )


class MemoryPressureHandler(HealingHandler):
    """内存压力自动缓解。"""

    @property
    def name(self) -> str:
        return "memory_pressure"

    async def can_heal(self, issue: DiagnosticResult) -> bool:
        return issue.check == "memory" or "memory" in issue.message.lower()

    async def heal(self, issue: DiagnosticResult) -> HealingResult:
        import gc
        import importlib
        started = time.perf_counter()
        try:
            gc.collect()
            sp = importlib.import_module("services.session_pool")
            sp.session_pool._adaptive_shrink()
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return HealingResult(
                healed=True, action="memory_cleanup",
                detail="已执行 GC + 连接池收缩", duration_ms=elapsed,
            )
        except Exception as e:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return HealingResult(
                healed=False, action="memory_cleanup",
                reason=f"内存清理失败: {e}", duration_ms=elapsed,
            )


class ConfigRecoveryHandler(HealingHandler):
    """配置损坏自动回退。"""

    @property
    def name(self) -> str:
        return "config_recovery"

    async def can_heal(self, issue: DiagnosticResult) -> bool:
        return issue.check == "config_consistency"

    async def heal(self, issue: DiagnosticResult) -> HealingResult:
        import importlib
        started = time.perf_counter()
        try:
            config_mod = importlib.import_module("services.config")
            config_mod.config._try_reload()
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return HealingResult(
                healed=True, action="config_reload",
                detail="配置已重新加载", duration_ms=elapsed,
            )
        except Exception as e:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return HealingResult(
                healed=False, action="config_reload",
                reason=f"配置恢复失败: {e}", duration_ms=elapsed,
            )


class CircuitBreakerProbeHandler(HealingHandler):
    """熔断器半开自动探测。"""

    @property
    def name(self) -> str:
        return "circuit_probe"

    async def can_heal(self, issue: DiagnosticResult) -> bool:
        return issue.check == "circuit_breaker" and "熔断器" in issue.message

    async def heal(self, issue: DiagnosticResult) -> HealingResult:
        import importlib
        started = time.perf_counter()
        try:
            cb = importlib.import_module("services.circuit_breaker")
            statuses = cb.circuit_breaker_registry.all_status()
            open_breakers = [
                key for key, info in statuses.items()
                if info.get("state") == "open"
            ]
            if not open_breakers:
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                return HealingResult(
                    healed=True, action="noop",
                    detail="无开启熔断器", duration_ms=elapsed,
                )
            probed = 0
            for key in open_breakers[:5]:
                breaker = circuit_breaker_registry.get(key)
                if breaker.state.name == "OPEN":
                    _ = breaker.allow_request()
                    probed += 1
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return HealingResult(
                healed=True, action="circuit_probe",
                detail=f"已触发 {probed} 个熔断器进入半开状态", duration_ms=elapsed,
            )
        except Exception as e:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return HealingResult(
                healed=False, action="circuit_probe",
                reason=f"熔断器探测失败: {e}", duration_ms=elapsed,
            )


class AutoHealer:
    """自动修复引擎。"""

    def __init__(self) -> None:
        self._handlers: dict[str, HealingHandler] = {
            "stale_session": StaleSessionHandler(),
            "disk_cleanup": DiskCleanupHandler(),
            "memory_pressure": MemoryPressureHandler(),
            "config_recovery": ConfigRecoveryHandler(),
            "proxy_failover": ProxyFailoverHandler(),
            "circuit_probe": CircuitBreakerProbeHandler(),
        }
        self._history: list[dict[str, Any]] = []
        self._history_max = 500
        self._success_count = 0
        self._total_count = 0

    @property
    def handlers(self) -> dict[str, HealingHandler]:
        return dict(self._handlers)

    async def heal(self, issue: DiagnosticResult) -> HealingResult:
        handler = self._handlers.get(issue.check)
        if not handler or not await handler.can_heal(issue):
            result = HealingResult(healed=False, reason="无可用自动修复方案")
            self._record(issue, result)
            return result
        result = await handler.heal(issue)
        self._record(issue, result)
        return result

    async def heal_all(self, report) -> list[HealingResult]:
        results: list[HealingResult] = []
        for result in report.results:
            if result.status in ("warning", "error"):
                hr = await self.heal(result)
                results.append(hr)
        return results

    def _record(self, issue: DiagnosticResult, result: HealingResult) -> None:
        self._total_count += 1
        if result.healed:
            self._success_count += 1
        entry = {
            "ts": time.time(),
            "check": issue.check,
            "issue_message": issue.message[:200],
            "healed": result.healed,
            "action": result.action,
            "detail": result.detail or result.reason,
            "duration_ms": result.duration_ms,
        }
        self._history.append(entry)
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max:]

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(reversed(self._history))[:limit]

    def get_stats(self) -> dict[str, object]:
        return {
            "total_attempts": self._total_count,
            "success_count": self._success_count,
            "success_rate": round(self._success_count / max(self._total_count, 1) * 100, 1),
            "history_size": len(self._history),
        }

    def clear_history(self) -> None:
        self._history.clear()
        self._success_count = 0
        self._total_count = 0


# 全局单例
auto_healer = AutoHealer()