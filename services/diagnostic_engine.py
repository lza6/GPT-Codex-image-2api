"""自动诊断引擎：常见问题自动识别 + 修复建议。

诊断检查项：
1. CircuitBreakerCheck — 熔断器状态
2. AccountHealthCheck — 账号健康分布
3. NetworkCheck — 代理连通性
4. StorageCheck — 存储空间
5. RateLimitCheck — 限流命中率
6. SessionPoolCheck — 连接池健康
7. ConfigConsistencyCheck — 配置一致性
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticResult:
    """单条诊断结果。"""
    check: str = ""
    status: str = "ok"  # ok / warning / error
    message: str = ""
    severity: str = "info"  # info / warning / error / critical
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticReport:
    """完整诊断报告。"""
    results: list[DiagnosticResult] = field(default_factory=list)
    started_at: float = 0.0
    completed_at: float = 0.0

    def add(self, result: DiagnosticResult) -> None:
        self.results.append(result)

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.completed_at:
            return round((self.completed_at - self.started_at) * 1000, 1)
        return 0.0

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {"ok": 0, "warning": 0, "error": 0}
        for r in self.results:
            s = r.status if r.status in counts else "ok"
            counts[s] = counts.get(s, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [
                {"check": r.check, "status": r.status, "message": r.message,
                 "severity": r.severity, "details": r.details}
                for r in self.results
            ],
            "summary": self.summary,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class DiagnosticCheck(ABC):
    """诊断检查基类。"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def run(self) -> DiagnosticResult: ...


class CircuitBreakerCheck(DiagnosticCheck):
    """检查熔断器状态，识别异常上游。"""

    @property
    def name(self) -> str:
        return "circuit_breaker"

    async def run(self) -> DiagnosticResult:
        from services.circuit_breaker import circuit_breaker_registry
        try:
            statuses = circuit_breaker_registry.all_status()
            total = len(statuses)
            open_breakers = [
                key for key, info in statuses.items()
                if info.get("state") == "open"
            ]
            if len(open_breakers) > 5:
                return DiagnosticResult(
                    check=self.name, status="error",
                    message=f"有 {len(open_breakers)}/{total} 个熔断器处于开启状态",
                    severity="warning",
                    details={"open_count": len(open_breakers), "total": total,
                             "breakers": open_breakers[:10]},
                )
            if len(open_breakers) > 0:
                return DiagnosticResult(
                    check=self.name, status="warning",
                    message=f"有 {len(open_breakers)}/{total} 个熔断器处于开启状态",
                    severity="info",
                    details={"open_count": len(open_breakers), "total": total},
                )
            return DiagnosticResult(
                check=self.name, status="ok",
                message=f"熔断器状态正常（{total} 个，0 开启）",
                severity="info", details={"total": total, "open_count": 0},
            )
        except Exception as e:
            return DiagnosticResult(
                check=self.name, status="error",
                message=f"熔断器检查失败: {e}", severity="error",
            )


class AccountHealthCheck(DiagnosticCheck):
    """检查账号健康分布。"""

    @property
    def name(self) -> str:
        return "account_health"

    async def run(self) -> DiagnosticResult:
        try:
            from services.account_service import account_service
            stats = account_service.get_stats()
            total = stats.get("total", 0)
            active = stats.get("active", 0)
            abnormal = stats.get("abnormal", 0)
            limited = stats.get("limited", 0)
            if total == 0:
                return DiagnosticResult(
                    check=self.name, status="error",
                    message="账号池为空，无法提供服务",
                    severity="critical", details=stats,
                )
            if total > 0 and active / total < 0.3:
                return DiagnosticResult(
                    check=self.name, status="error",
                    message=f"账号可用率过低: {active}/{total} ({active * 100 // total}%)",
                    severity="warning", details=stats,
                )
            if abnormal > 5:
                return DiagnosticResult(
                    check=self.name, status="warning",
                    message=f"有 {abnormal} 个异常账号",
                    severity="info", details=stats,
                )
            return DiagnosticResult(
                check=self.name, status="ok",
                message=f"账号健康: {active}/{total} 可用",
                severity="info", details=stats,
            )
        except Exception as e:
            return DiagnosticResult(
                check=self.name, status="error",
                message=f"账号健康检查失败: {e}", severity="error",
            )


class NetworkCheck(DiagnosticCheck):
    """检查代理连通性。"""

    @property
    def name(self) -> str:
        return "network"

    async def run(self) -> DiagnosticResult:
        try:
            from services.proxy_pool import proxy_pool
            stats = proxy_pool.get_stats()
            total = stats.get("total", 0)
            healthy = stats.get("healthy", 0)
            if total > 0 and healthy / total < 0.5:
                return DiagnosticResult(
                    check=self.name, status="error",
                    message=f"代理连通率低: {healthy}/{total} 健康",
                    severity="warning", details=stats,
                )
            return DiagnosticResult(
                check=self.name, status="ok",
                message=f"代理池: {healthy}/{total} 健康",
                severity="info", details=stats,
            )
        except Exception as e:
            return DiagnosticResult(
                check=self.name, status="error",
                message=f"代理连通性检查失败: {e}", severity="error",
            )


class StorageCheck(DiagnosticCheck):
    """检查存储空间。"""

    @property
    def name(self) -> str:
        return "storage"

    async def run(self) -> DiagnosticResult:
        import shutil
        try:
            from services.config import DATA_DIR
            usage = shutil.disk_usage(str(DATA_DIR))
            free_gb = usage.free / (1024**3)
            total_gb = usage.total / (1024**3)
            if free_gb < 0.5:
                return DiagnosticResult(
                    check=self.name, status="error",
                    message=f"磁盘空间不足: {free_gb:.1f}GB 剩余",
                    severity="critical",
                    details={"free_gb": round(free_gb, 1), "total_gb": round(total_gb, 1)},
                )
            if free_gb < 2:
                return DiagnosticResult(
                    check=self.name, status="warning",
                    message=f"磁盘空间偏低: {free_gb:.1f}GB 剩余",
                    severity="warning",
                    details={"free_gb": round(free_gb, 1), "total_gb": round(total_gb, 1)},
                )
            return DiagnosticResult(
                check=self.name, status="ok",
                message=f"磁盘空间充足: {free_gb:.1f}GB 剩余",
                severity="info",
                details={"free_gb": round(free_gb, 1), "total_gb": round(total_gb, 1)},
            )
        except Exception as e:
            return DiagnosticResult(
                check=self.name, status="error",
                message=f"存储检查失败: {e}", severity="error",
            )


class RateLimitCheck(DiagnosticCheck):
    """检查限流命中率。"""

    @property
    def name(self) -> str:
        return "rate_limit"

    async def run(self) -> DiagnosticResult:
        try:
            from services.config import config
            rpm = config.rate_limit_rpm
            per_ip = config.rate_limit_per_ip_rpm
            if rpm == 0 and per_ip == 0:
                return DiagnosticResult(
                    check=self.name, status="ok",
                    message="限流未启用（rpm=0）", severity="info",
                    details={"global_rpm": rpm, "per_ip_rpm": per_ip},
                )
            return DiagnosticResult(
                check=self.name, status="ok",
                message=f"限流已启用（全局 {rpm}/min, 每IP {per_ip}/min）",
                severity="info",
                details={"global_rpm": rpm, "per_ip_rpm": per_ip},
            )
        except Exception as e:
            return DiagnosticResult(
                check=self.name, status="error",
                message=f"限流检查失败: {e}", severity="error",
            )


class SessionPoolCheck(DiagnosticCheck):
    """检查连接池健康。"""

    @property
    def name(self) -> str:
        return "session_pool"

    async def run(self) -> DiagnosticResult:
        try:
            from services.session_pool import session_pool
            s = session_pool.stats()
            size = s.get("pooled_sessions", 0)
            if size > 100:
                return DiagnosticResult(
                    check=self.name, status="warning",
                    message=f"连接池过大: {size} 个连接", severity="info",
                    details=s,
                )
            return DiagnosticResult(
                check=self.name, status="ok",
                message=f"连接池正常: {size} 个连接", severity="info",
                details=s,
            )
        except Exception as e:
            return DiagnosticResult(
                check=self.name, status="error",
                message=f"连接池检查失败: {e}", severity="error",
            )


class ConfigConsistencyCheck(DiagnosticCheck):
    """检查配置一致性。"""

    @property
    def name(self) -> str:
        return "config_consistency"

    async def run(self) -> DiagnosticResult:
        try:
            from services.config import config
            from services.storage.factory import create_storage_backend
            from services.config import DATA_DIR
            issues: list[str] = []
            if not config.auth_key or len(config.auth_key) < 12:
                issues.append("auth-key 过短或为空")
            if config.workers > 1:
                backend = create_storage_backend(DATA_DIR)
                info = backend.get_backend_info()
                if info.get("type") == "json":
                    issues.append(f"workers={config.workers} 但存储后端为 JSON，多 worker 不可用")
            if issues:
                return DiagnosticResult(
                    check=self.name, status="warning",
                    message="; ".join(issues), severity="warning",
                    details={"issues": issues},
                )
            return DiagnosticResult(
                check=self.name, status="ok",
                message="配置一致性检查通过", severity="info",
            )
        except Exception as e:
            return DiagnosticResult(
                check=self.name, status="error",
                message=f"配置一致性检查失败: {e}", severity="error",
            )


class DiagnosticEngine:
    """自动诊断引擎。"""

    def __init__(self) -> None:
        self._checks: list[DiagnosticCheck] = [
            CircuitBreakerCheck(),
            AccountHealthCheck(),
            NetworkCheck(),
            StorageCheck(),
            RateLimitCheck(),
            SessionPoolCheck(),
            ConfigConsistencyCheck(),
        ]
        self._last_report: DiagnosticReport | None = None
        self._last_report_time: float = 0.0

    @property
    def checks(self) -> list[DiagnosticCheck]:
        return list(self._checks)

    async def diagnose(self) -> DiagnosticReport:
        report = DiagnosticReport()
        report.started_at = time.time()
        for check in self._checks:
            try:
                result = await check.run()
                report.add(result)
            except Exception as e:
                report.add(DiagnosticResult(
                    check=check.name, status="error",
                    message=f"诊断检查异常: {e}", severity="error",
                ))
        report.completed_at = time.time()
        self._last_report = report
        self._last_report_time = time.time()
        return report

    def get_last_report(self) -> dict[str, object] | None:
        if self._last_report is None:
            return None
        return self._last_report.to_dict()

    def get_last_report_time(self) -> float:
        return self._last_report_time


# 全局单例
diagnostic_engine = DiagnosticEngine()