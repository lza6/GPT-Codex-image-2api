# 智能诊断引擎 + 自动修复 2.0 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现自动诊断引擎（7 个检查器）+ 自动修复引擎（6 个修复器），添加 API 端点 + 前端页面 + 定时自动诊断 + 修复成功率统计。

**架构：**
- `services/diagnostic_engine.py` — DiagnosticCheck 基类 + 7 检查器 + DiagnosticEngine
- `services/auto_healer.py` — HealingHandler 基类 + 6 修复器 + AutoHealer
- `api/system.py` — 新增 `/api/system/diagnose` 和 `/api/system/healing/history` 端点
- 新配置项 `auto_heal_enabled` + `auto_diagnose_interval_minutes`
- 前端新增系统诊断页面 + 导航

**技术栈：** Python 3.13 · FastAPI · Next.js 16 · React 19

---

## 文件结构

### 创建
- `services/diagnostic_engine.py` — 诊断引擎（DiagnosticCheck ABC + 7 检查器 + DiagnosticEngine + DiagnosticReport/Result）
- `services/auto_healer.py` — 自动修复引擎（HealingHandler ABC + 6 修复器 + AutoHealer + HealingResult）
- `web/src/app/system/diagnose/page.tsx` — 诊断报告页面
- `web/src/app/system/healing/page.tsx` — 自动修复历史页面
- `test/test_diagnostic_engine.py` — 诊断引擎测试
- `test/test_auto_healer.py` — 自动修复引擎测试

### 修改
- `api/system.py` — 新增 diagnose/healing/history 端点
- `services/config.py` — 新增 auto_heal_enabled/auto_diagnose_interval_minutes 配置
- `services/event_bus_init.py` — 注册自动修复事件订阅
- `web/src/components/top-nav.tsx` — 导航加系统诊断/修复历史项
- `web/src/lib/api.ts` — 加诊断/修复类型和请求函数
- `scripts/contract_guard.py` — DYNAMIC_KEY_ENDPOINTS 加新端点
- `config.json` — 加默认配置项
- `VERSION` — 升版本
- `CHANGELOG.md` — 加变更日志

---

### 任务 1：诊断引擎基类 + 数据模型

**文件：** 创建 `services/diagnostic_engine.py`

- [ ] **步骤 1：编写 DiagnosticResult、DiagnosticReport、DiagnosticCheck ABC**

```python
"""自动诊断引擎：常见问题自动识别 + 修复建议。"""

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
```

- [ ] **步骤 2：运行测试验证导入成功**

运行：`uv run python -c "from services.diagnostic_engine import DiagnosticCheck, DiagnosticResult, DiagnosticReport; print('OK')"`
预期：OK

- [ ] **步骤 3：Commit**

```bash
git add services/diagnostic_engine.py
git commit -m "feat: diagnostic engine base classes and data models"
```

---

### 任务 2：7 个诊断检查器

**文件：** 修改 `services/diagnostic_engine.py`（追加检查器实现）

- [ ] **步骤 1：编写 CircuitBreakerCheck + AccountHealthCheck + NetworkCheck**

```python
class CircuitBreakerCheck(DiagnosticCheck):
    """检查熔断器状态，识别异常上游。"""

    @property
    def name(self) -> str:
        return "circuit_breaker"

    async def run(self) -> DiagnosticResult:
        from services.circuit_breaker import circuit_breaker_registry
        try:
            open_breakers = circuit_breaker_registry.list_open()
            total = circuit_breaker_registry.size()
            if open_breakers is None:
                open_breakers = []
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
        from services.account_service import account_service
        try:
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
            if active / max(total, 1) < 0.3:
                return DiagnosticResult(
                    check=self.name, status="error",
                    message=f"账号可用率过低: {active}/{total} ({active*100//max(total,1)}%)",
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
        from services.proxy_pool import proxy_pool
        try:
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
```

- [ ] **步骤 2：编写 StorageCheck + RateLimitCheck + SessionPoolCheck + ConfigConsistencyCheck**

```python
class StorageCheck(DiagnosticCheck):
    """检查存储空间。"""

    @property
    def name(self) -> str:
        return "storage"

    async def run(self) -> DiagnosticResult:
        import shutil
        from services.config import DATA_DIR
        try:
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
        from services.config import config
        try:
            rpm = config.rate_limit_rpm
            per_ip = config.rate_limit_per_ip_rpm
            if rpm == 0 and per_ip == 0:
                return DiagnosticResult(
                    check=self.name, status="ok",
                    message="限流未启用（rpm=0）", severity="info",
                    details={"global_rpm": rpm, "per_ip_rpm": per_ip},
                )
            # 尝试从 metrics 获取限流命中数
            try:
                from services.metrics_service import get_rate_limit_hits
                hits = get_rate_limit_hits()
            except Exception:
                hits = -1
            return DiagnosticResult(
                check=self.name, status="ok",
                message=f"限流已启用（全局 {rpm}/min, 每IP {per_ip}/min）",
                severity="info",
                details={"global_rpm": rpm, "per_ip_rpm": per_ip, "recent_hits": hits},
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
        from services.session_pool import session_pool
        try:
            size = session_pool.size()
            if size > 100:
                return DiagnosticResult(
                    check=self.name, status="warning",
                    message=f"连接池过大: {size} 个连接", severity="info",
                    details={"size": size},
                )
            return DiagnosticResult(
                check=self.name, status="ok",
                message=f"连接池正常: {size} 个连接", severity="info",
                details={"size": size},
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
        from services.config import config
        try:
            issues: list[str] = []
            # 检查 auth-key
            if not config.auth_key or len(config.auth_key) < 12:
                issues.append("auth-key 过短或为空")
            # 检查 workers 与存储后端
            if config.workers > 1:
                from services.storage.factory import create_storage_backend
                from services.config import DATA_DIR
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
```

- [ ] **步骤 3：编写 DiagnosticEngine 类**

```python
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
```

- [ ] **步骤 4：运行测试验证导入**

运行：`uv run python -c "from services.diagnostic_engine import diagnostic_engine, CircuitBreakerCheck, AccountHealthCheck; print('OK')"`
预期：OK

- [ ] **步骤 5：Commit**

```bash
git add services/diagnostic_engine.py
git commit -m "feat: 7 diagnostic checkers and DiagnosticEngine"
```

---

### 任务 3：自动修复引擎基类 + 6 个修复器

**文件：** 创建 `services/auto_healer.py`

- [ ] **步骤 1：编写 HealingResult + HealingHandler ABC + 6 个修复器**

```python
"""自动修复引擎（Auto-Healing 2.0）：扩展自动修复能力，覆盖更多故障场景。"""

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
        from services.session_pool import session_pool
        started = time.perf_counter()
        session_key = issue.details.get("session_key", "")
        if session_key:
            try:
                session_pool.release(session_key)
                await session_pool.get_or_create(session_key)
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
        import shutil
        from services.config import DATA_DIR
        from services.image_service import delete_to_target
        started = time.perf_counter()
        try:
            usage = shutil.disk_usage(str(DATA_DIR))
            free_gb = usage.free / (1024**3)
            if free_gb >= 0.5:
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                return HealingResult(
                    healed=True, action="noop",
                    detail="磁盘空间已自动恢复，无需清理",
                    duration_ms=elapsed,
                )
            # 清理到 1GB 可用
            result = await delete_to_target(target_free_mb=1024, dry_run=False)
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
        from services.proxy_pool import proxy_pool
        started = time.perf_counter()
        try:
            isolated = proxy_pool.get_stats().get("isolated", 0)
            if isolated > 0:
                # 尝试恢复隔离代理
                count = proxy_pool.recover_isolated()
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                return HealingResult(
                    healed=count > 0, action="proxy_recover",
                    detail=f"尝试恢复 {count} 个隔离代理" if count > 0 else "无隔离代理可恢复",
                    duration_ms=elapsed,
                )
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return HealingResult(
                healed=True, action="noop",
                detail="代理池状态正常", duration_ms=elapsed,
            )
        except Exception as e:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return HealingResult(
                healed=False, action="proxy_recover",
                reason=f"代理恢复失败: {e}", duration_ms=elapsed,
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
        started = time.perf_counter()
        try:
            gc.collect()
            from services.session_pool import session_pool
            session_pool.shrink()
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
        from services.config import config
        started = time.perf_counter()
        try:
            # 尝试重新加载配置
            config._try_reload()
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
        from services.circuit_breaker import circuit_breaker_registry
        from services.account_service import account_service
        started = time.perf_counter()
        try:
            open_breakers = circuit_breaker_registry.list_open()
            if not open_breakers:
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                return HealingResult(
                    healed=True, action="noop",
                    detail="无开启熔断器", duration_ms=elapsed,
                )
            # 对每个开启熔断器触发一次探测
            probed = 0
            for key in open_breakers[:5]:
                breaker = circuit_breaker_registry.get(key)
                if breaker.state.name == "OPEN":
                    # 获取半开状态触发探测
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
```

- [ ] **步骤 2：编写 AutoHealer 类**

```python
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
```

- [ ] **步骤 3：运行测试验证导入**

运行：`uv run python -c "from services.auto_healer import auto_healer, StaleSessionHandler, DiskCleanupHandler; print('OK')"`
预期：OK

- [ ] **步骤 4：Commit**

```bash
git add services/auto_healer.py
git commit -m "feat: auto-healing engine with 6 handlers"
```

---

### 任务 4：配置项 + 事件总线订阅

**文件：** 修改 `services/config.py`、`services/event_bus_init.py`、`config.json`

- [ ] **步骤 1：config.py 加 auto_heal_enabled + auto_diagnose_interval_minutes**

```python
# 在 _BOOL_FIELDS 中加 "auto_heal_enabled"
# 在 _INT_FIELDS 中加 ("auto_diagnose_interval_minutes", (1, 1440))

# 加 property:
@property
def auto_heal_enabled(self) -> bool:
    value = self.data.get("auto_heal_enabled", True)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)

@property
def auto_diagnose_interval_minutes(self) -> int:
    try:
        return max(1, int(self.data.get("auto_diagnose_interval_minutes", 60)))
    except (TypeError, ValueError):
        return 60

# 在 get() 中加：
data["auto_heal_enabled"] = self.auto_heal_enabled
data["auto_diagnose_interval_minutes"] = self.auto_diagnose_interval_minutes
```

- [ ] **步骤 2：config.json 加默认值**

```json
"auto_heal_enabled": true,
"auto_diagnose_interval_minutes": 60,
```

- [ ] **步骤 3：event_bus_init.py 注册自动修复订阅**

```python
# 在 register_subscribers 中添加：
def _auto_diagnose_handler(event):
    """诊断事件触发自动修复。"""
    try:
        # 异步执行诊断 + 修复
        import asyncio
        from services.diagnostic_engine import diagnostic_engine
        from services.auto_healer import auto_healer
        from services.config import config
        if not config.auto_heal_enabled:
            return
        report = asyncio.run(diagnostic_engine.diagnose())
        if any(r.status in ("warning", "error") for r in report.results):
            asyncio.run(auto_healer.heal_all(report))
    except Exception:
        pass
```

- [ ] **步骤 4：Commit**

```bash
git add services/config.py services/event_bus_init.py config.json
git commit -m "feat: auto_heal config and event bus subscription"
```

---

### 任务 5：API 端点

**文件：** 修改 `api/system.py`

- [ ] **步骤 1：添加 /api/system/diagnose 端点**

```python
@router.post("/api/system/diagnose")
async def run_diagnose(authorization: str | None = Header(default=None)):
    require_admin(authorization)
    from services.diagnostic_engine import diagnostic_engine
    from services.audit_service import record_admin_access
    try:
        report = await diagnostic_engine.diagnose()
        result = report.to_dict()
        record_admin_access(action="/api/system/diagnose", result="success", identity=require_admin(authorization))
        return result
    except Exception as e:
        record_admin_access(action="/api/system/diagnose", result="error", identity=require_admin(authorization))
        raise HTTPException(status_code=500, detail={"error": str(e)}) from e

@router.get("/api/system/diagnose")
async def get_last_diagnose(authorization: str | None = Header(default=None)):
    require_admin(authorization)
    from services.diagnostic_engine import diagnostic_engine
    report = diagnostic_engine.get_last_report()
    return {"report": report, "last_time": diagnostic_engine.get_last_report_time()}
```

- [ ] **步骤 2：添加 /api/system/healing/history 端点**

```python
@router.get("/api/system/healing/history")
async def get_healing_history(limit: int = Query(default=100, ge=1, le=500), authorization: str | None = Header(default=None)):
    require_admin(authorization)
    from services.auto_healer import auto_healer
    return {
        "items": auto_healer.get_history(limit),
        "stats": auto_healer.get_stats(),
    }

@router.post("/api/system/healing/run")
async def run_healing(authorization: str | None = Header(default=None)):
    require_admin(authorization)
    from services.diagnostic_engine import diagnostic_engine
    from services.auto_healer import auto_healer
    from services.audit_service import record_admin_access
    try:
        report = await diagnostic_engine.diagnose()
        results = await auto_healer.heal_all(report)
        record_admin_access(action="/api/system/healing/run", result="success", identity=require_admin(authorization))
        return {
            "diagnose": report.to_dict(),
            "healing": [r.to_dict() for r in results],
        }
    except Exception as e:
        record_admin_access(action="/api/system/healing/run", result="error", identity=require_admin(authorization))
        raise HTTPException(status_code=500, detail={"error": str(e)}) from e

@router.post("/api/system/healing/clear-history")
async def clear_healing_history(authorization: str | None = Header(default=None)):
    require_admin(authorization)
    from services.auto_healer import auto_healer
    auto_healer.clear_history()
    from services.audit_service import record_admin_access
    record_admin_access(action="/api/system/healing/clear-history", result="success", identity=require_admin(authorization))
    return {"ok": True}
```

- [ ] **步骤 3：导入路由**（确保已在 app.py 中 `system.create_router(app_version)`）

`api/app.py` 已 include `system.create_router()`，无需改。

- [ ] **步骤 4：Commit**

```bash
git add api/system.py
git commit -m "feat: diagnose and healing API endpoints"
```

---

### 任务 6：前端类型 + API 请求函数

**文件：** 修改 `web/src/lib/api.ts`

- [ ] **步骤 1：添加诊断和修复类型**

```typescript
// Diagnostic types
export type DiagnosticResult = {
  check: string;
  status: "ok" | "warning" | "error";
  message: string;
  severity: "info" | "warning" | "error" | "critical";
  details: Record<string, unknown>;
};

export type DiagnosticReport = {
  results: DiagnosticResult[];
  summary: Record<string, number>;
  duration_ms: number;
  started_at: number;
  completed_at: number;
};

export type HealingResult = {
  healed: boolean;
  detail: string;
  reason: string;
  action: string;
  duration_ms: number;
};

export type HealingHistoryItem = {
  ts: number;
  check: string;
  issue_message: string;
  healed: boolean;
  action: string;
  detail: string;
  duration_ms: number;
};

export type HealingStats = {
  total_attempts: number;
  success_count: number;
  success_rate: number;
  history_size: number;
};
```

- [ ] **步骤 2：添加请求函数**

```typescript
export async function runDiagnose(): Promise<DiagnosticReport> {
  const resp = await httpRequest("/api/system/diagnose", { method: "POST" });
  return resp.json();
}

export async function getLastDiagnose(): Promise<{ report: DiagnosticReport | null; last_time: number }> {
  const resp = await httpRequest("/api/system/diagnose");
  return resp.json();
}

export async function getHealingHistory(limit = 100): Promise<{ items: HealingHistoryItem[]; stats: HealingStats }> {
  const resp = await httpRequest(`/api/system/healing/history?limit=${limit}`);
  return resp.json();
}

export async function runHealing(): Promise<{ diagnose: DiagnosticReport; healing: HealingResult[] }> {
  const resp = await httpRequest("/api/system/healing/run", { method: "POST" });
  return resp.json();
}

export async function clearHealingHistory(): Promise<void> {
  await httpRequest("/api/system/healing/clear-history", { method: "POST" });
}
```

- [ ] **步骤 3：Commit**

```bash
git add web/src/lib/api.ts
git commit -m "feat: frontend diagnose/healing types and API functions"
```

---

### 任务 7：前端诊断页面

**文件：** 创建 `web/src/app/system/diagnose/page.tsx`

- [ ] **步骤 1：编写诊断报告页面**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { runDiagnose, getLastDiagnose, type DiagnosticReport } from "@/lib/api";

export default function DiagnosePage() {
  const [report, setReport] = useState<DiagnosticReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await getLastDiagnose();
      if (data.report) setReport(data.report);
    } catch { /* 首次加载无报告 */ }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleDiagnose = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await runDiagnose();
      setReport(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const statusColor = (s: string) => {
    if (s === "ok") return "text-green-600 dark:text-green-400";
    if (s === "warning") return "text-yellow-600 dark:text-yellow-400";
    return "text-red-600 dark:text-red-400";
  };

  const severityIcon = (sev: string) => {
    if (sev === "critical") return "🔴";
    if (sev === "error") return "❌";
    if (sev === "warning") return "⚠️";
    return "✅";
  };

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold">系统诊断</h1>
        <button
          onClick={handleDiagnose}
          disabled={loading}
          className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-50 dark:bg-white dark:text-stone-900 dark:hover:bg-stone-200"
        >
          {loading ? "诊断中..." : "运行诊断"}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}

      {report && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg border p-3 dark:border-white/10">
              <div className="text-xs text-stone-500">总检查项</div>
              <div className="text-2xl font-bold">{report.results.length}</div>
            </div>
            <div className="rounded-lg border p-3 dark:border-white/10">
              <div className="text-xs text-green-600">通过</div>
              <div className="text-2xl font-bold text-green-600">{report.summary.ok ?? 0}</div>
            </div>
            <div className="rounded-lg border p-3 dark:border-white/10">
              <div className="text-xs text-yellow-600">警告</div>
              <div className="text-2xl font-bold text-yellow-600">{report.summary.warning ?? 0}</div>
            </div>
            <div className="rounded-lg border p-3 dark:border-white/10">
              <div className="text-xs text-red-600">错误</div>
              <div className="text-2xl font-bold text-red-600">{report.summary.error ?? 0}</div>
            </div>
          </div>

          <div className="mb-4 text-xs text-stone-400">
            耗时: {report.duration_ms}ms
          </div>

          <div className="space-y-2">
            {report.results.map((r, i) => (
              <div key={i} className="rounded-lg border p-3 dark:border-white/10">
                <div className="flex items-center gap-2">
                  <span>{severityIcon(r.severity)}</span>
                  <span className="font-mono text-xs font-medium uppercase text-stone-500">{r.check}</span>
                  <span className={`text-sm font-medium ${statusColor(r.status)}`}>{r.status}</span>
                </div>
                <div className="mt-1 text-sm">{r.message}</div>
                {r.details && Object.keys(r.details).length > 0 && (
                  <pre className="mt-2 overflow-x-auto rounded bg-stone-50 p-2 text-xs dark:bg-stone-900">
                    {JSON.stringify(r.details, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {!report && !loading && (
        <div className="rounded-lg border border-dashed p-8 text-center text-stone-400 dark:border-white/10">
          点击"运行诊断"开始检查系统状态
        </div>
      )}
    </div>
  );
}
```

- [ ] **步骤 2：Commit**

```bash
git add web/src/app/system/diagnose/page.tsx
git commit -m "feat: system diagnose page"
```

---

### 任务 8：前端修复历史页面

**文件：** 创建 `web/src/app/system/healing/page.tsx`

- [ ] **步骤 1：编写修复历史页面**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { getHealingHistory, runHealing, clearHealingHistory, type HealingHistoryItem, type HealingStats } from "@/lib/api";

export default function HealingPage() {
  const [items, setItems] = useState<HealingHistoryItem[]>([]);
  const [stats, setStats] = useState<HealingStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [healing, setHealing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await getHealingHistory(100);
      setItems(data.items);
      setStats(data.stats);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleHeal = async () => {
    setHealing(true);
    try {
      await runHealing();
      await load();
    } finally {
      setHealing(false);
    }
  };

  const handleClear = async () => {
    if (!confirm("确定清除修复历史？")) return;
    await clearHealingHistory();
    setItems([]);
    setStats(null);
  };

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold">自动修复</h1>
        <div className="flex gap-2">
          <button
            onClick={handleHeal}
            disabled={healing}
            className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-50 dark:bg-white dark:text-stone-900 dark:hover:bg-stone-200"
          >
            {healing ? "修复中..." : "运行修复"}
          </button>
          <button
            onClick={handleClear}
            className="rounded-lg border px-4 py-2 text-sm text-stone-600 transition hover:bg-stone-50 dark:border-white/10 dark:text-stone-400 dark:hover:bg-white/10"
          >
            清除历史
          </button>
        </div>
      </div>

      {stats && (
        <div className="mb-4 grid grid-cols-3 gap-3">
          <div className="rounded-lg border p-3 dark:border-white/10">
            <div className="text-xs text-stone-500">总尝试</div>
            <div className="text-2xl font-bold">{stats.total_attempts}</div>
          </div>
          <div className="rounded-lg border p-3 dark:border-white/10">
            <div className="text-xs text-green-600">成功</div>
            <div className="text-2xl font-bold text-green-600">{stats.success_count}</div>
          </div>
          <div className="rounded-lg border p-3 dark:border-white/10">
            <div className="text-xs text-stone-500">成功率</div>
            <div className="text-2xl font-bold">{stats.success_rate}%</div>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {items.length === 0 && (
          <div className="rounded-lg border border-dashed p-8 text-center text-stone-400 dark:border-white/10">
            暂无修复记录
          </div>
        )}
        {items.map((item, i) => (
          <div key={i} className="rounded-lg border p-3 dark:border-white/10">
            <div className="flex items-center gap-2">
              <span>{item.healed ? "✅" : "❌"}</span>
              <span className="font-mono text-xs text-stone-500">{item.check}</span>
              <span className="text-xs text-stone-400">{new Date(item.ts * 1000).toLocaleString()}</span>
              {item.duration_ms > 0 && (
                <span className="text-xs text-stone-400">{item.duration_ms}ms</span>
              )}
            </div>
            <div className="mt-1 text-sm">{item.issue_message}</div>
            <div className="mt-0.5 text-xs text-stone-500">{item.detail}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **步骤 2：Commit**

```bash
git add web/src/app/system/healing/page.tsx
git commit -m "feat: auto-healing history page"
```

---

### 任务 9：前端导航 + 主页面

**文件：** 修改 `web/src/components/top-nav.tsx`，创建 `web/src/app/system/page.tsx`

- [ ] **步骤 1：导航加系统诊断/修复历史项**

```typescript
// 在 adminNavItems 末尾加：
{ href: "/system", label: "系统诊断" },
```

- [ ] **步骤 2：创建系统主页面（重定向到诊断）**

```tsx
// web/src/app/system/page.tsx
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function SystemPage() {
  const router = useRouter();
  useEffect(() => { router.replace("/system/diagnose"); }, [router]);
  return null;
}
```

- [ ] **步骤 3：Commit**

```bash
git add web/src/components/top-nav.tsx web/src/app/system/page.tsx
git commit -m "feat: system navigation and main page"
```

---

### 任务 10：测试

**文件：** 创建 `test/test_diagnostic_engine.py`、`test/test_auto_healer.py`

- [ ] **步骤 1：诊断引擎测试**

```python
"""诊断引擎单元测试。"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from services.diagnostic_engine import (
    DiagnosticResult, DiagnosticReport, DiagnosticCheck,
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
```

- [ ] **步骤 2：自动修复引擎测试**

```python
"""自动修复引擎单元测试。"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from services.diagnostic_engine import DiagnosticResult
from services.auto_healer import (
    HealingResult, HealingHandler,
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
        # 即使没有实际压力，GC + shrink 也不应抛异常
        assert result.action == "memory_cleanup"

    @pytest.mark.asyncio
    async def test_config_recovery_handler(self):
        issue = DiagnosticResult(check="config_consistency", status="warning", message="配置异常")
        handler = ConfigRecoveryHandler()
        assert await handler.can_heal(issue)
        result = await handler.heal(issue)
        assert result.action == "config_reload"

    @pytest.mark.asyncio
    async def test_history_clear(self):
        auto_healer.clear_history()
        stats = auto_healer.get_stats()
        assert stats["total_attempts"] == 0
        assert stats["success_count"] == 0
```

- [ ] **步骤 3：运行测试**

```bash
uv run pytest test/test_diagnostic_engine.py test/test_auto_healer.py -v
```
预期：PASS

- [ ] **步骤 4：Commit**

```bash
git add test/test_diagnostic_engine.py test/test_auto_healer.py
git commit -m "test: diagnostic engine and auto-healer tests"
```

---

### 任务 11：契约守卫 + 版本号 + CHANGELOG

- [ ] **步骤 1：contract_guard.py 加新端点**

```python
# 在 DYNAMIC_KEY_ENDPOINTS 中加：
"/api/system/diagnose",
"/api/system/healing/history",
"/api/system/healing/run",
```

- [ ] **步骤 2：升版本号**

```bash
echo "2.24.0" > VERSION
```

- [ ] **步骤 3：CHANGELOG.md 更新**

- [ ] **步骤 4：Commit**

```bash
git add VERSION CHANGELOG.md scripts/contract_guard.py
git commit -m "chore: bump to v2.24.0, update contract guard"
```

---

### 任务 12：全面验证

- [ ] **步骤 1：pytest 全量**

```bash
uv run pytest test/test_diagnostic_engine.py test/test_auto_healer.py -v
```

- [ ] **步骤 2：启动验证**

```bash
uv run python -c "from api.app import create_app; app=create_app()"
```

- [ ] **步骤 3：前端构建**

```bash
cd web && npm run build
```

- [ ] **步骤 4：契约守卫**

```bash
uv run python scripts/contract_guard.py
```

- [ ] **步骤 5：E2E 冒烟**

```bash
cd web && NODE_PATH=./node_modules E2E_AUTH_KEY=test_key node ../scripts/e2e_smoke.cjs
```

- [ ] **步骤 6：git push + tag + Release**

---

### 任务 13：部署到服务器

- [ ] **步骤 1：本地 push + tag**

```bash
git push
git tag v2.24.0
git push origin v2.24.0
```

- [ ] **步骤 2：创建 GitHub Release**

```bash
gh release create v2.24.0 --generate-notes
```

- [ ] **步骤 3：部署到服务器**

```bash
ssh -i key -o ProxyCommand="" user@server "cd /path/to/chatgpt2api && git pull && ./启动chatgpt2api.bat"
```