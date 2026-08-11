"""调度看板 + 运维概览 API（参考 codex2api SchedulerBoard / ops.go）。"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Header, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, StreamingResponse

from api.response_cache import apply_cache_headers, response_cache
from api.support import require_admin
from services.account_service import AccountService, account_service
from services.circuit_breaker import circuit_breaker_registry
from services.config import DATA_DIR, config
from services.image_service import storage_stats
from services.metrics_service import metrics_service


def _collect_account_health(accounts: list[dict]) -> dict[str, object]:
    """按健康档位统计账号分布。"""
    tiers = {"healthy": 0, "warm": 0, "risky": 0, "banned": 0}
    statuses: dict[str, int] = {}
    total_quota = 0
    total_inflight = 0
    for account in accounts:
        status = str(account.get("status") or "未知")
        statuses[status] = statuses.get(status, 0) + 1
        total_quota += max(0, int(account.get("quota") or 0))
        total_inflight += int(account.get("image_inflight") or 0)
        if status in {"禁用", "异常"}:
            tiers["banned"] += 1
        else:
            tier = AccountService._account_health_tier(account)
            tiers[tier] = tiers.get(tier, 0) + 1
    return {
        "tiers": tiers,
        "statuses": statuses,
        "total": len(accounts),
        "total_quota": total_quota,
        "total_inflight": total_inflight,
    }


def _collect_log_stats() -> dict[str, object]:
    """基于日志聚合缓存统计用量（近 24h 成功/失败/总量）。

    3.5.1：改读 usage_agg 增量缓存，不再每次全量扫 logs.jsonl（慢查询热点根治）。
    字段结构与旧全量扫描口径一致（由 test_usage_agg 双算对比保证不漂移）。
    """
    from services.usage_agg import usage_agg

    return usage_agg.stats_24h()


def _build_metrics_summary() -> dict[str, object]:
    """看板聚合指标：请求速率/错误率/P95 延迟。供 metrics_summary 端点与 SSE 复用。"""
    summary = metrics_service.get_summary()
    total = summary["total_requests"]
    errors = summary["total_errors"]
    uptime = max(1, summary["uptime_seconds"])
    # P95 延迟估算（基于平均延迟 + 错误率加权的简单估算，真实 P95 需 histogram 分位数）
    avg = summary["avg_latency_ms"]
    p95 = round(avg * 1.8, 1) if avg else 0.0  # 简化估算
    return {
        "request_rate": round(total / uptime, 2),
        "error_rate": summary["error_rate"],
        "p95_latency_ms": p95,
        "avg_latency_ms": avg,
        "total_requests": total,
        "total_errors": errors,
    }


def _build_stream_payload() -> dict[str, object]:
    """构建 SSE 每帧推送的完整看板数据。

    包含 ops/usage/metrics_summary，使看板顶部资源、用量、指标卡片
    都能经 SSE 实时更新，而非依赖 30s 兜底轮询。
    """
    accounts = account_service.list_accounts()
    return {
        "type": "dashboard",
        "ts": int(time.time()),
        "health": _collect_account_health(accounts),
        "latency": metrics_service.get_summary(),
        "ops": _collect_ops_overview(),
        "usage": _collect_log_stats(),
        "metrics_summary": _build_metrics_summary(),
        # III-02：调度模式 A/B 统计随 SSE 实时推送
        "effective_mode": account_service._effective_scheduler_mode(),
        "mode_stats": account_service.get_scheduler_mode_stats(),
    }


def _collect_ops_overview() -> dict[str, object]:
    """运维概览：CPU/内存/磁盘/进程/存储统计。"""
    # CPU 使用率（Windows 上取不到精确值，用 loadavg 兜底）
    cpu_percent: float | None = None
    try:
        import psutil  # type: ignore

        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        memory_used = memory.used
        memory_total = memory.total
    except ImportError:
        memory_used = memory_total = 0
    if cpu_percent is None:
        try:
            cpu_percent = os.getloadavg()[0] / max(1, os.cpu_count() or 1) * 100
        except (OSError, AttributeError):
            cpu_percent = 0.0
    disk = shutil.disk_usage(str(DATA_DIR))
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "pid": os.getpid(),
        "uptime_seconds": int(time.time() - _PROCESS_START_TIME),
        "cpu_percent": round(cpu_percent, 1),
        "memory_used_mb": round(memory_used / 1024 / 1024, 1) if memory_used else None,
        "memory_total_mb": round(memory_total / 1024 / 1024, 1) if memory_total else None,
        "disk_free_mb": round(disk.free / 1024 / 1024, 1),
        "disk_total_mb": round(disk.total / 1024 / 1024, 1),
        "storage": storage_stats(),
        "scheduler_mode": config.scheduler_mode,
        "scheduler_adaptive_enabled": config.scheduler_adaptive_enabled,
        "refresh_account_interval_minute": config.refresh_account_interval_minute,
        "image_account_concurrency": config.image_account_concurrency,
        # D9：备份状态接看板（最近备份时间/状态/错误），SSE 实时可见
        "backup": _collect_backup_overview(),
    }


def _collect_backup_overview() -> dict[str, object]:
    """备份状态概览：最近备份时间/状态/错误/是否配置。"""
    try:
        from services.backup_service import backup_service

        status = backup_service.get_status()
        return {
            "configured": backup_service.is_configured(),
            "running": bool(status.get("running")),
            "last_status": status.get("last_status") or "idle",
            "last_finished_at": status.get("last_finished_at"),
            "last_error": status.get("last_error"),
        }
    except Exception:
        return {"configured": False, "running": False, "last_status": "idle", "last_finished_at": None, "last_error": None}


def _collect_circuit_breaker_status() -> dict[str, object]:
    """按 token 末 8 位聚合熔断器状态（不泄露完整 token）。

    返回 {token_suffix: {state, recover_in_seconds}}，仅含非 closed 的账号
    （closed 为正常态无需上报，减少负载）。
    """
    status = circuit_breaker_registry.all_status()
    result: dict[str, dict[str, object]] = {}
    for token, info in status.items():
        if info.get("state") == "closed":
            continue
        suffix = str(token)[-8:]
        result[suffix] = {
            "state": info.get("state"),
            "recover_in_seconds": info.get("recover_in_seconds", 0),
        }
    return {"breakers": result, "total_open": sum(1 for i in status.values() if i.get("state") == "open")}


_PROCESS_START_TIME = time.time()


def _collect_capacity(windows_days: int = 7) -> dict[str, object]:
    """5.2：容量规划——日均请求 / 活跃账号 / 单账号日均消耗 / 外推需新号数。

    数据源为 usage_agg 聚合缓存（禁止全量扫 logs.jsonl），口径与用量统计一致。
    边界：空数据 / 单账号 / 零增长率不除零崩溃（日均与账号数为 0 时给占位值）。
    """
    from services.usage_agg import usage_agg

    series = usage_agg.daily_success_series(windows_days)
    if not series:
        return {"days": windows_days, "avg_daily_requests": 0, "active_accounts": 0, "per_account_daily": 0, "growth_rate": 0.0, "suggested_new_accounts": 0, "series": series}

    today = datetime.now().strftime("%Y-%m-%d")
    active_series = [s for s in series if s["date"] < today]  # 不含今天（不完整），避免拉低日均
    if not active_series:
        active_series = series
    total = sum(int(s["calls"]) for s in active_series)
    avg_daily = total / max(1, len(active_series))

    # 活跃账号：近 windows_days 天有 success 或最近使用过的账号
    accounts = account_service.list_accounts()
    active_accounts = 0
    for account in accounts:
        if int(account.get("success") or 0) > 0:
            active_accounts += 1
            continue
        last_used = account.get("last_used_at") or ""
        if last_used[:10] >= (datetime.now() - timedelta(days=windows_days)).strftime("%Y-%m-%d"):
            active_accounts += 1

    per_account_daily = round(avg_daily / active_accounts, 1) if active_accounts else 0.0

    # 增长率：最近一半窗口 vs 前一半窗口（线性外推日均），零/负增长按 0 处理
    half = len(active_series) // 2
    if half >= 1:
        recent = sum(int(s["calls"]) for s in active_series[half:])
        earlier = sum(int(s["calls"]) for s in active_series[:half])
        growth_rate = round((recent - earlier) / max(1.0, earlier), 3) if earlier > 0 else 0.0
    else:
        growth_rate = 0.0

    # 外推：按当前日均 + 增长率，若要扛 target 张/天，缺多少新号（每人按 per_account_daily）
    suggested_new_accounts = 0
    if active_accounts and per_account_daily > 0 and avg_daily > 0:
        # 假设目标为当前日均的 2 倍（可解释为"翻倍容量"），需新增账号数 = (目标-当前)/单号日均
        target_daily = avg_daily * 2
        gap = target_daily - avg_daily
        if gap > 0:
            suggested_new_accounts = int(gap / per_account_daily) + (1 if gap % per_account_daily else 0)

    return {
        "days": windows_days,
        "avg_daily_requests": round(avg_daily, 1),
        "active_accounts": active_accounts,
        "per_account_daily": per_account_daily,
        "growth_rate": growth_rate,
        "suggested_new_accounts": suggested_new_accounts,
        "series": series,
    }


def _fetch_recent_events(limit: int = 50) -> list[dict]:
    """从 events.jsonl 读取最近事件。

    事件总线持久化订阅的 handler 每收到事件写入 data/events.jsonl，
    然后由本函数读取最近 N 条返回（JSON 容错，跳过坏行）。
    """
    events: list[dict] = []
    events_path = Path(str(DATA_DIR)) / "events.jsonl"
    if events_path.exists():
        try:
            with events_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass
    return events


def create_router() -> APIRouter:
    router = APIRouter(tags=["Dashboard"])

    @router.get("/api/dashboard/scheduler")
    async def scheduler_dashboard(
        authorization: str | None = Header(default=None),
        refresh: bool = False,
        response: Response = None,
    ):
        """调度看板：账号健康分布 + 实时并发 + 调度分排名。"""
        require_admin(authorization)
        if not refresh:
            cached = response_cache.get("/api/dashboard/scheduler")
            if cached is not None:
                if response is not None:
                    apply_cache_headers("/api/dashboard/scheduler", response)
                return cached
        accounts = account_service.list_accounts()
        health = _collect_account_health(accounts)
        # 更新 prometheus 账号池指标
        try:
            from services.prometheus_metrics import (
                update_account_pool_size,
                update_image_tasks_inflight,
                update_lifetime_risk,
            )
            update_account_pool_size(health["tiers"])
            update_image_tasks_inflight(health["total_inflight"])
            # v2.10.0：寿命预测档位分布指标
            risk_dist: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
            for acc in accounts:
                risk = acc.get("lifetime_risk") or ""
                if risk in risk_dist:
                    risk_dist[risk] += 1
            update_lifetime_risk(risk_dist)
        except Exception:
            import logging
            logging.getLogger("chatgpt2api").warning("Prometheus 指标更新失败")
        # 带调度分的账号排名（供前端展示）
        ranked = []
        quota_warning_accounts = 0
        for account in accounts:
            if account.get("status") in {"禁用", "异常"}:
                continue
            token = str(account.get("access_token") or "")
            tier = AccountService._account_health_tier(account)
            score = AccountService._account_dispatch_score(account, tier)
            # 5.1：寿命预测（含风险档位 + 预估剩余天数）
            # III-03：配额预警第三信号（quota_warning / 剩余天数）一并透出
            lifetime = {}
            try:
                from services.account_lifetime import compute_lifetime_risk
                lifetime = compute_lifetime_risk(account)
            except Exception:  # pragma: no cover - 预测失败不影响排名
                lifetime = {"level": "low", "eta_days": None}
            if bool(lifetime.get("quota_warning")):
                quota_warning_accounts += 1
            ranked.append(
                {
                    "email": account.get("email"),
                    "type": account.get("type"),
                    "status": account.get("status"),
                    "quota": max(0, int(account.get("quota") or 0)),
                    "success": int(account.get("success") or 0),
                    "fail": int(account.get("fail") or 0),
                    "image_inflight": int(account.get("image_inflight") or 0),
                    "tier": tier,
                    "score": score,
                    "priority": account_service._priority_for_token(token),
                    "lifetime_risk": lifetime.get("level", "low"),
                    "lifetime_eta_days": lifetime.get("eta_days"),
                    "lifetime_score": lifetime.get("score", 0.0),
                    "quota_warning": bool(lifetime.get("quota_warning")),
                    "quota_remaining_days": lifetime.get("quota_remaining_days"),
                }
            )
        ranked.sort(key=lambda item: (item["tier"] != "healthy", -item["score"]))
        # Phase 2：各 provider 调度统计
        provider_stats = []
        try:
            from services.provider_scheduler import provider_scheduler
            provider_stats = provider_scheduler.get_provider_stats(accounts)
        except Exception:
            pass
        # III-02：按调度模式 A/B 统计（命中数/失败率/平均延迟）
        result = {
            "health": health,
            "accounts": ranked,
            "provider_stats": provider_stats,
            "effective_mode": account_service._effective_scheduler_mode(),
            "mode_stats": account_service.get_scheduler_mode_stats(),
            "quota_warning_accounts": quota_warning_accounts,
        }
        response_cache.set("/api/dashboard/scheduler", result)
        if response is not None:
            apply_cache_headers("/api/dashboard/scheduler", response)
        return result

    @router.get("/api/dashboard/circuit_breakers")
    async def circuit_breakers(authorization: str | None = Header(default=None)):
        """熔断状态：token 末 8 位 -> 熔断器状态（供账号页标注当前被熔断账号）。"""
        require_admin(authorization)
        return await run_in_threadpool(_collect_circuit_breaker_status)

    @router.get("/api/dashboard/ops")
    async def ops_overview(
        authorization: str | None = Header(default=None),
        refresh: bool = False,
        response: Response = None,
    ):
        """运维概览：CPU/内存/磁盘/账号池/日志统计。"""
        require_admin(authorization)
        if not refresh:
            cached = response_cache.get("/api/dashboard/ops")
            if cached is not None:
                if response is not None:
                    apply_cache_headers("/api/dashboard/ops", response)
                return cached
        result = await run_in_threadpool(_collect_ops_overview)
        response_cache.set("/api/dashboard/ops", result)
        if response is not None:
            apply_cache_headers("/api/dashboard/ops", response)
        return result

    @router.get("/api/dashboard/usage")
    async def usage_stats(authorization: str | None = Header(default=None), hours: int = 24):
        """用量统计：指定小时窗口内调用量 + 按类型分布 + 最近记录。

        支持 hours 参数控制窗口：1/6/24/168(7d)/720(30d)，默认 24。
        """
        require_admin(authorization)
        from services.usage_agg import usage_agg

        window = max(1, min(int(hours), 720))
        data = await run_in_threadpool(usage_agg.stats_for_window, window)
        return data

    @router.get("/api/dashboard/usage-totals")
    async def usage_totals(authorization: str | None = Header(default=None)):
        """累计用量：总请求/成功/失败/成功率 + 图片累计 + 按类型分布（全时段）。"""
        require_admin(authorization)
        from services.usage_agg import usage_agg

        return await run_in_threadpool(usage_agg.totals)

    @router.get("/api/dashboard/usage-forecast")
    async def usage_forecast_stats(authorization: str | None = Header(default=None)):
        """F2/A2：用量预测——按近 7 天趋势线性外推号池配额耗尽时间 + 提前告警。"""
        require_admin(authorization)
        from services.usage_forecast import forecast_quota_depletion

        return await run_in_threadpool(forecast_quota_depletion)

    @router.get("/api/dashboard/quota")
    async def quota_detail(authorization: str | None = Header(default=None)):
        """逐账号额度明细：总额度 + 每号 quota/restore_at + 临近刷新(24h内)列表。"""
        require_admin(authorization)
        from services.usage_forecast import per_account_quota

        return await run_in_threadpool(per_account_quota)

    @router.get("/api/dashboard/capacity")
    async def capacity_stats(authorization: str | None = Header(default=None), days: int = 7):
        """5.2：容量规划——日均请求/活跃账号/单账号日均消耗/外推需新号数（基于聚合缓存）。"""
        require_admin(authorization)
        window = max(1, min(int(days), 90))
        return await run_in_threadpool(_collect_capacity, window)

    @router.get("/api/dashboard/cost")
    async def cost_overview(authorization: str | None = Header(default=None)):
        """5.1.2：成本优化概览——全链路成本追踪（调用量/Provider 分布/代理流量）。"""
        require_admin(authorization)
        from services.cost_service import cost_service

        return await run_in_threadpool(cost_service.get_cost_overview)

    @router.get("/api/dashboard/latency")
    async def latency_stats(authorization: str | None = Header(default=None)):
        """请求延迟统计：总请求/错误率/平均延迟/按路径分布/在途。"""
        require_admin(authorization)
        return metrics_service.get_summary()

    @router.get("/api/dashboard/metrics_summary")
    async def metrics_summary(authorization: str | None = Header(default=None)):
        """看板聚合指标：请求速率/错误率/P95 延迟。"""
        require_admin(authorization)
        return _build_metrics_summary()

    @router.get("/metrics", include_in_schema=False)
    async def prometheus_metrics(authorization: str | None = Header(default=None), token: str = ""):
        """Prometheus 指标端点（prometheus-client 库，供监控系统抓取）。

        指标含账号规模等敏感信息，需鉴权（Authorization header 或 ?token= 查询参数，
        与 /api/* 一致），防止公网暴露内部状态。Prometheus 抓取方配置 Bearer <auth-key>。
        """
        if not authorization and token:
            authorization = f"Bearer {token}"
        require_admin(authorization)
        from services.prometheus_metrics import generate_metrics

        content, content_type = generate_metrics()
        return PlainTextResponse(content, media_type=content_type)

    @router.get("/api/dashboard/stream", include_in_schema=False)
    async def dashboard_stream(authorization: str | None = Header(default=None), token: str = ""):
        """SSE 实时推送：看板数据每 3 秒推送一次。

        EventSource 无法传 Authorization header，支持 ?token= 查询参数鉴权。
        """
        if not authorization and token:
            authorization = f"Bearer {token}"
        require_admin(authorization)

        async def event_generator():
            try:
                while True:
                    try:
                        # 收集逻辑（含磁盘/账号 IO）放线程池，避免阻塞事件循环
                        payload = await run_in_threadpool(_build_stream_payload)
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    except Exception:
                        # 单次数据构建失败，跳过本次，等待下一周期
                        pass
                    await asyncio.sleep(3)
            except asyncio.CancelledError:
                # 客户端断开连接，正常退出协程
                return

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/api/dashboard/events")
    async def dashboard_events(authorization: str | None = Header(default=None), limit: int = 50):
        """看板事件流：最近系统事件（从 events.jsonl 读取，SSE 事件频道同源）。"""
        require_admin(authorization)
        events = await run_in_threadpool(_fetch_recent_events, limit)
        return {"events": events}

    @router.get("/api/events/stream", include_in_schema=False)
    async def events_stream(authorization: str | None = Header(default=None), token: str = ""):
        """SSE 事件流：实时推送系统事件（事件总线事件，1s 级）。

        EventSource 无法传 Authorization header，支持 ?token= 查询参数鉴权。
        """
        if not authorization and token:
            authorization = f"Bearer {token}"
        require_admin(authorization)

        async def event_generator():
            sent_ids: set[str] = set()
            try:
                while True:
                    try:
                        events_data = await run_in_threadpool(_fetch_recent_events, 20)
                        for event in events_data:
                            if event["id"] not in sent_ids:
                                sent_ids.add(event["id"])
                                payload = {
                                    "type": "dashboard",
                                    "channel": "events",
                                    "data": event,
                                }
                                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        if len(sent_ids) > 1000:
                            sent_ids = set(list(sent_ids)[-500:])
                    except Exception:
                        pass
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                return

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/api/dashboard/adaptive_scheduler")
    async def adaptive_scheduler_status(authorization: str | None = Header(default=None)):
        """自适应调度器状态：当前模式/运行指标/切换历史。"""
        require_admin(authorization)
        try:
            from services.adaptive_scheduler import adaptive_scheduler
            return {
                "enabled": config.scheduler_adaptive_enabled,
                "status": adaptive_scheduler.get_status(),
                "history": adaptive_scheduler.get_history(limit=10),
            }
        except Exception:
            return {"enabled": False, "status": {}, "history": []}

    return router
