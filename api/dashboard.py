"""调度看板 + 运维概览 API（参考 codex2api SchedulerBoard / ops.go）。"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import platform
import shutil
import time

from fastapi import APIRouter, Header
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, StreamingResponse

from api.support import require_admin
from services.account_service import AccountService, account_service
from services.circuit_breaker import circuit_breaker_registry
from services.config import DATA_DIR, config
from services.image_service import storage_stats
from services.log_service import log_service
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
    """基于系统日志统计用量（近 24h 成功/失败/总量）。"""
    logs = log_service.list(limit=1000)
    now = time.time()
    day_ago = now - 86400
    success = 0
    failed = 0
    calls: dict[str, int] = {}
    recent: list[dict[str, object]] = []
    for item in logs:
        # 兼容日志三种时间键：text 格式写 'time'，json 格式写 'ts'，历史可能写 'created_at'
        created = str(item.get("time") or item.get("ts") or item.get("created_at") or "")
        try:
            # 'ts' 为 ISO 格式（含 T 与毫秒），统一截断前 19 字符并替换 T 为空格
            normalized = created[:19].replace("T", " ")
            ts = time.mktime(datetime.datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S").timetuple())
        except (ValueError, TypeError):
            ts = 0
        if ts < day_ago:
            continue
        # 成败状态在 detail 子对象（detail['status']），顶层无 status 键，需兜底读取
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        status = str(item.get("status") or detail.get("status") or "success")
        summary = str(item.get("summary") or "调用")
        calls[summary] = calls.get(summary, 0) + 1
        if status == "failed":
            failed += 1
        else:
            success += 1
        recent.append({"time": created, "summary": summary, "status": status})
    return {
        "success_24h": success,
        "failed_24h": failed,
        "total_24h": success + failed,
        "by_summary": calls,
        "recent": recent[-20:],
    }


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


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/dashboard/scheduler")
    async def scheduler_dashboard(authorization: str | None = Header(default=None)):
        """调度看板：账号健康分布 + 实时并发 + 调度分排名。"""
        require_admin(authorization)
        accounts = account_service.list_accounts()
        health = _collect_account_health(accounts)
        # 更新 prometheus 账号池指标
        try:
            from services.prometheus_metrics import update_account_pool_size, update_image_tasks_inflight
            update_account_pool_size(health["tiers"])
            update_image_tasks_inflight(health["total_inflight"])
        except Exception:
            import logging
            logging.getLogger("chatgpt2api").warning("Prometheus 指标更新失败")
        # 带调度分的账号排名（供前端展示）
        ranked = []
        for account in accounts:
            if account.get("status") in {"禁用", "异常"}:
                continue
            token = str(account.get("access_token") or "")
            tier = AccountService._account_health_tier(account)
            score = AccountService._account_dispatch_score(account, tier)
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
                }
            )
        ranked.sort(key=lambda item: (item["tier"] != "healthy", -item["score"]))
        return {"health": health, "accounts": ranked}

    @router.get("/api/dashboard/circuit_breakers")
    async def circuit_breakers(authorization: str | None = Header(default=None)):
        """熔断状态：token 末 8 位 -> 熔断器状态（供账号页标注当前被熔断账号）。"""
        require_admin(authorization)
        return await run_in_threadpool(_collect_circuit_breaker_status)

    @router.get("/api/dashboard/ops")
    async def ops_overview(authorization: str | None = Header(default=None)):
        """运维概览：CPU/内存/磁盘/账号池/日志统计。"""
        require_admin(authorization)
        return await run_in_threadpool(_collect_ops_overview)

    @router.get("/api/dashboard/usage")
    async def usage_stats(authorization: str | None = Header(default=None)):
        """用量统计：近 24h 调用量 + 按类型分布 + 最近记录。"""
        require_admin(authorization)
        return await run_in_threadpool(_collect_log_stats)

    @router.get("/api/dashboard/usage-forecast")
    async def usage_forecast_stats(authorization: str | None = Header(default=None)):
        """F2/A2：用量预测——按近 7 天趋势线性外推号池配额耗尽时间 + 提前告警。"""
        require_admin(authorization)
        from services.usage_forecast import forecast_quota_depletion

        return await run_in_threadpool(forecast_quota_depletion)

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

    return router
