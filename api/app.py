from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from threading import Event

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api import accounts, ai, dashboard, image_tasks, keys, kookeey, providers, proxy_pool, system
from api.errors import install_exception_handlers
from api.rate_limit import RateLimitMiddleware
from api.support import resolve_web_asset, start_limited_account_watcher, start_proactive_probe
from services.backup_service import backup_service
from services.config import config
from services.image_service import start_image_cleanup_scheduler
from services.metrics_service import set_request_id
from utils.log import logger


def create_app() -> FastAPI:
    app_version = config.app_version

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # 初始化事件总线（在后台线程启动之前注册所有订阅）
        try:
            from services.event_bus_init import register_subscribers
            register_subscribers()
        except Exception:  # noqa: BLE001 - 事件总线初始化失败不阻断启动
            pass

        # 初始化任务队列处理器（在后台线程启动之前注册所有处理器）
        try:
            from services.task_queue_init import register_task_handlers
            register_task_handlers()
        except Exception:  # noqa: BLE001 - 任务队列初始化失败不阻断启动
            pass

        stop_event = Event()
        # 配置追踪器（从 config 读取慢请求阈值和缓冲区大小）
        try:
            tracer.slow_threshold_ms = config.trace_slow_threshold_ms
            buffer_size = config.trace_buffer_size
            import collections
            tracer._buffer = collections.deque(maxlen=buffer_size)
        except Exception:  # noqa: BLE001
            pass
        thread = start_limited_account_watcher(stop_event)
        cleanup_thread = start_image_cleanup_scheduler(stop_event)
        probe_thread = start_proactive_probe(stop_event)
        # 4.1：启动即迁移旧 logs.jsonl 到天文件，确保 usage_agg watcher 读的是切分后日志
        from services.log_service import log_service
        log_service.migrate_legacy()
        from services.usage_agg import start_usage_agg_watcher
        # v2.9.0：启动即从 config.json 加载 kookeey 配置（支持 KOOKEEY_DEVELOPER_TOKEN 环境变量覆盖）
        try:
            kookeey_cfg = config.get_kookeey_settings()
            if isinstance(kookeey_cfg, dict):
                from services.kookeey_service import kookeey_service
                kookeey_service.update_config(kookeey_cfg)
        except Exception:  # noqa: BLE001 - kookeey 配置加载失败不阻断启动
            pass

        # v2.9.0：定时批量探测所有账号出口 IP（默认每 2 小时，KOOKEEY_IP_PROBE_INTERVAL_SEC 可调）
        ip_probe_thread = None
        try:
            from services.kookeey_service import kookeey_service
            ip_probe_thread = kookeey_service.start_ip_probe_watcher(stop_event)
        except Exception:  # noqa: BLE001 - IP 探测线程启动失败不阻断
            ip_probe_thread = None

        agg_thread = start_usage_agg_watcher(stop_event)
        backup_service.start()
        config.cleanup_old_images()
        # P2：启动时预热模型缓存，避免首次请求 /v1/models 时等待 0.7s+ 上游调用
        try:
            from services.model_service import model_catalog_service
            from threading import Thread
            Thread(target=model_catalog_service.list_models, daemon=True).start()
        except Exception:  # noqa: BLE001 - 预热失败不阻断启动
            pass
        # S6：启动即补一次审计清理（服务长期无管理操作时，过期天文件也能按期整删）
        try:
            from services.audit_service import audit_service
            audit_service.maybe_cleanup()
        except Exception:  # noqa: BLE001 - 审计清理失败不阻断启动
            pass
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=5)
            cleanup_thread.join(timeout=5)
            if probe_thread is not None:
                probe_thread.join(timeout=5)
            agg_thread.join(timeout=5)
            backup_service.stop()
            # 停止任务队列消费者
            try:
                from services.task_queue import task_queue
                task_queue.stop_consumer()
            except Exception:  # noqa: BLE001
                pass
            # D15：优雅停机——归还并关闭所有池化 TLS 连接，防资源泄漏
            from services.session_pool import session_pool

            session_pool.close_all()

    app = FastAPI(title="chatgpt2api", version=app_version, lifespan=lifespan)
    install_exception_handlers(app)

    @app.middleware("http")
    async def access_log_middleware(request, call_next):
        """记录所有 HTTP 请求到控制台，包括 /v1/models、鉴权失败等黑匣子。

        LoggedCall 只覆盖 AI 端点（chat/completions/images/messages/responses），
        GET /v1/models、鉴权失败、管理 API 等请求完全不可见。此中间件保证
        每个请求都有日志，便于开发者调试对接。
        """
        req_id = uuid.uuid4().hex[:16]
        set_request_id(req_id)
        try:
            from services.request_context import set_request_context

            client = request.client
            set_request_context(
                path=request.url.path,
                method=request.method,
                ip=str(getattr(client, "host", "") or ""),
            )
        except Exception:  # noqa: BLE001
            pass
        start = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            status = response.status_code if response is not None else 0
            ip = str(getattr(request.client, "host", "") if request.client else "")
            logger.info({
                "event": "access",
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "duration_ms": elapsed_ms,
                "request_id": req_id,
                "ip": ip,
            })
            if response is not None:
                response.headers["X-Request-ID"] = req_id
                response.headers["X-Response-Time-Ms"] = str(elapsed_ms)

    # S-R15：注册限流中间件（此前 RateLimitMiddleware 定义了但从未接线，
    # rate_limit_rpm 配置形同虚设）。0 表示关闭；基于 BaseHTTPMiddleware，
    # 需在 CORS 之前注册成最外层。
    # 注意：多 worker 下进程内限流不共享，如需全局精确限流应配 Redis（shared_state）。
    app.add_middleware(
        RateLimitMiddleware,
        global_rpm=config.rate_limit_rpm,
        per_ip_rpm=config.rate_limit_per_ip_rpm,
    )
    # CORS：配置驱动
    cors_origins = config.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 注册请求追踪中间件（6.1 TracedMiddleware）
    try:
        from services.tracing import TracedMiddleware
        app.add_middleware(
            TracedMiddleware,
            sample_rate=config.traces_sample_rate,
            slow_threshold_ms=config.traces_slow_threshold_ms,
        )
    except Exception:
        pass
    app.include_router(ai.create_router())
    app.include_router(accounts.create_router())
    app.include_router(keys.create_router())
    app.include_router(image_tasks.create_router())
    app.include_router(system.create_router(app_version))
    app.include_router(dashboard.create_router())
    app.include_router(proxy_pool.create_router())
    app.include_router(kookeey.create_router())
    app.include_router(providers.create_router())
    

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_web(full_path: str):
        # 修复：浏览器缓存的旧 RSC 数据可能引用已不存在的旧 chunk URL，
        # 导致 _next//_next/static/chunks/xxx.js 双斜杠 404 路径阻塞页面。
        # 剥离多余 _next/ 前缀，回源到正确路径。
        # 注意：_next/ 与其他路径之间是单斜杠 /，但 URL 中双斜杠 // 被 FastAPI
        # 路由保留，所以 full_path 可以包含 _next//_next/
        if full_path.startswith("_next//_next/"):
            full_path = "_next/" + full_path[len("_next//_next/"):]
            asset = resolve_web_asset(full_path)
            if asset is not None:
                return FileResponse(asset, headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                })
        asset = resolve_web_asset(full_path)
        if asset is not None:
            headers: dict[str, str] = {}
            # _next/static 文件是内容哈希文件名，可永久缓存
            if full_path.startswith("_next/static/"):
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            # RSC 负载（__next.*.txt）禁止浏览器缓存，否则旧 RSC 数据
            # 会引用已不存在的旧 chunk URL，导致 404 阻塞页面切换
            elif "__next." in full_path.split("/")[-1] and full_path.endswith(".txt"):
                headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return FileResponse(asset, headers=headers)
        # 缺失的 _next/static 文件直接 404，不返回 index.html
        # 否则浏览器会收到 HTML 却当作 JS 执行，产生语法错误
        if full_path.strip("/").startswith("_next/"):
            raise HTTPException(status_code=404, detail="Not Found")
        # SPA fallback：非 _next/* 路径返回 index.html
        fallback = resolve_web_asset("")
        if fallback is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(fallback)

    return app
