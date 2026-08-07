from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from threading import Event

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api import accounts, ai, dashboard, image_tasks, kookeey, proxy_pool, system
from api.errors import install_exception_handlers
from api.rate_limit import RateLimitMiddleware
from api.support import resolve_web_asset, start_limited_account_watcher, start_proactive_probe
from services.backup_service import backup_service
from services.config import config
from services.image_service import start_image_cleanup_scheduler
from services.metrics_service import set_request_id


def create_app() -> FastAPI:
    app_version = config.app_version

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_event = Event()
        thread = start_limited_account_watcher(stop_event)
        cleanup_thread = start_image_cleanup_scheduler(stop_event)
        probe_thread = start_proactive_probe(stop_event)
        # 4.1：启动即迁移旧 logs.jsonl 到天文件，确保 usage_agg watcher 读的是切分后日志
        from services.log_service import log_service
        log_service.migrate_legacy()
        from services.usage_agg import start_usage_agg_watcher
        # v2.9.0：启动即从 config.json 加载 kookeey 配置
        try:
            kookeey_cfg = config.data.get("kookeey")
            if isinstance(kookeey_cfg, dict):
                from services.kookeey_service import kookeey_service
                kookeey_service.update_config(kookeey_cfg)
        except Exception:  # noqa: BLE001 - kookeey 配置加载失败不阻断启动
            pass

        # v2.9.0：定时批量探测所有账号出口 IP（默认每 2 小时，KOOKEEY_IP_PROBE_INTERVAL_SEC 可调）
        ip_probe_thread = None
        try:
            from services.kookeey_service import start_ip_probe_watcher
            ip_probe_thread = start_ip_probe_watcher(stop_event)
        except Exception:  # noqa: BLE001 - IP 探测线程启动失败不阻断
            ip_probe_thread = None

        agg_thread = start_usage_agg_watcher(stop_event)
        backup_service.start()
        config.cleanup_old_images()
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
            # D15：优雅停机——归还并关闭所有池化 TLS 连接，防资源泄漏
            from services.session_pool import session_pool

            session_pool.close_all()

    app = FastAPI(title="chatgpt2api", version=app_version, lifespan=lifespan)
    install_exception_handlers(app)

    @app.middleware("http")
    async def inject_request_headers(request, call_next):
        """D-R2：注入 X-Request-ID + X-Response-Time-Ms 响应头。

        此前 metrics_service 有 request_id 基础设施但从未写响应头，而
        docs 与前端 request.ts 都依赖 X-Request-ID（5xx 排障定位）。
        3.2：同时注入请求上下文（path/method/ip），供 require_admin 审计埋点读取。
        """
        request_id = uuid.uuid4().hex[:16]
        set_request_id(request_id)
        try:
            from services.request_context import set_request_context

            client = request.client
            set_request_context(
                path=request.url.path,
                method=request.method,
                ip=str(getattr(client, "host", "") or ""),
            )
        except Exception:  # noqa: BLE001 - 审计上下文失败不影响主流程
            pass
        start = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            if response is not None:
                response.headers["X-Request-ID"] = request_id
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
    app.include_router(ai.create_router())
    app.include_router(accounts.create_router())
    app.include_router(image_tasks.create_router())
    app.include_router(system.create_router(app_version))
    app.include_router(dashboard.create_router())
    app.include_router(proxy_pool.create_router())
    app.include_router(kookeey.create_router())

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_web(full_path: str):
        asset = resolve_web_asset(full_path)
        if asset is not None:
            return FileResponse(asset)
        if full_path.strip("/").startswith("_next/"):
            raise HTTPException(status_code=404, detail="Not Found")
        fallback = resolve_web_asset("")
        if fallback is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(fallback)

    return app
