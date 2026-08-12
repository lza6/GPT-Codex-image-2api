from __future__ import annotations

import mimetypes
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer

from api import accounts, ai, dashboard, image_tasks, keys, kookeey, logs, providers, proxy_pool, system, tracing
from api.errors import install_exception_handlers
from api.rate_limit import RateLimitMiddleware
from api.response_cache import response_cache
from api.support import WEB_DIST_DIR, resolve_web_asset, start_limited_account_watcher, start_proactive_probe
from services.backup_service import backup_service
from services.config import config
from services.image_service import start_image_cleanup_scheduler
from services.metrics_service import set_request_id
from utils.log import logger


def _trim_events_file(path: Path, max_lines: int = 2000) -> None:
    """裁剪 events.jsonl 行数，防止无限增长。"""
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                with path.open("w", encoding="utf-8") as f:
                    f.writelines(lines[-max_lines:])
    except OSError:
        pass


def _append_event_jsonl(event, events_path: Path) -> None:
    """把事件序列化追加到 events.jsonl，并失效 /api/dashboard/events 响应缓存。

    V-02：事件列表缓存写侧失效点——事件持久化订阅写入后立即清缓存，
    保证轮询方读不到脏数据。提取为模块级函数便于测试直接验证失效行为
    （无需启动完整 lifespan）。
    """
    import json as _json

    with events_path.open("a", encoding="utf-8") as f:
        f.write(_json.dumps({
            "id": event.id,
            "type": event.type,
            "data": event.data,
            "timestamp": int(event.timestamp) if hasattr(event, "timestamp") else int(time.time()),
        }, ensure_ascii=False) + "\n")
    response_cache.invalidate("/api/dashboard/events")


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

        # 注册事件总线持久化订阅（写入 events.jsonl 供 SSE 事件流消费）
        try:
            from services.config import DATA_DIR
            from services.event_bus import event_bus

            _events_path = Path(str(DATA_DIR)) / "events.jsonl"
            _last_events_cleanup = 0

            def _persist_event(event):
                nonlocal _last_events_cleanup
                try:
                    _append_event_jsonl(event, _events_path)
                    # 每天清理一次
                    now = int(time.time())
                    if now - _last_events_cleanup > 86400:
                        _last_events_cleanup = now
                        _trim_events_file(_events_path, 2000)
                except Exception:
                    pass

            for evt in ["account.invalid", "account.recovered", "account.quota_exhausted",
                        "circuit.open", "circuit.half_open", "circuit.closed",
                        "backup.failure", "provider.health_changed",
                        "session_pool.leak"]:
                event_bus.subscribe(evt, sync_handler=_persist_event)
            _trim_events_file(_events_path, 2000)
        except Exception:
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
        # III-05：连接池泄漏检测守护线程（空闲超阈值告警 + 健康检查清理）
        leak_thread = None
        try:
            from services.session_pool import start_leak_watcher
            leak_thread = start_leak_watcher(stop_event)
        except Exception:  # noqa: BLE001 - 泄漏检测线程启动失败不阻断
            leak_thread = None
        backup_service.start()
        config.cleanup_old_images()
        # P2：启动时预热模型缓存，避免首次请求 /v1/models 时等待 0.7s+ 上游调用
        try:
            from threading import Thread

            from services.model_service import model_catalog_service
            Thread(target=model_catalog_service.list_models, daemon=True).start()
        except Exception:  # noqa: BLE001 - 预热失败不阻断启动
            pass
        # S6：启动即补一次审计清理（服务长期无管理操作时，过期天文件也能按期整删）
        try:
            from services.audit_service import audit_service
            audit_service.maybe_cleanup()
        except Exception:  # noqa: BLE001 - 审计清理失败不阻断启动
            pass

        # 3.2.3：配置热加载（config_watch_enabled 控制开关，默认开启）
        config_watcher_thread = None
        try:
            if config.config_watch_enabled:
                from services.config_watcher import ConfigWatcher
                config_watcher = ConfigWatcher(config, poll_interval=5.0)
                config_watcher.start(stop_event)
                config_watcher_thread = config_watcher
        except Exception:  # noqa: BLE001 - 配置热加载启动失败不阻断
            pass

        try:
            yield
        finally:
            stop_event.set()
            if config_watcher_thread is not None:
                config_watcher_thread.stop()
            thread.join(timeout=5)
            cleanup_thread.join(timeout=5)
            if probe_thread is not None:
                probe_thread.join(timeout=5)
            agg_thread.join(timeout=5)
            if leak_thread is not None:
                leak_thread.join(timeout=5)
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

    bearer_scheme = HTTPBearer(auto_error=False)
    app = FastAPI(
        title="chatgpt2api",
        description="ChatGPT 官网能力的逆向封装服务。提供 OpenAI 兼容的图片生成/编辑 API + 号池管理 + 智能调度 + 运维看板。\n\n"
        "## 鉴权方式\n\n"
        "所有管理 API 和 AI API 均使用 Bearer Token 鉴权：\n"
        "```\n"
        "Authorization: Bearer <auth-key>\n"
        "```\n\n"
        "## 特性\n\n"
        "- OpenAI 兼容的 `/v1/*` 端点（chat/completions、images/generations、images/edits、responses、messages）\n"
        "- 账号池管理（CRUD、刷新、批量操作、分组）\n"
        "- 智能调度（轮询/剩余配额/加权随机/最少负载/预测/亲和性）\n"
        "- 上游熔断器（状态机 + 分级重试）\n"
        "- 代理池管理（HTTP/SOCKS5 代理调度）\n"
        "- 运维看板（调度/熔断/用量/延迟/寿命预测/容量规划）\n"
        "- 图片异步生成（任务提交 + 轮询 + 续轮询）\n"
        "- kookeey 住宅代理集成（每号独立出口 IP）\n"
        "- 审计日志 + Prometheus 指标 + 事件追踪",
        version=app_version,
        lifespan=lifespan,
        contact={
            "name": "chatgpt2api",
            "url": "https://github.com/your-org/chatgpt2api",
        },
        license_info={
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT",
        },
        servers=[
            {"url": "/", "description": "当前服务"},
        ],
        openapi_tags=[
            {"name": "AI", "description": "OpenAI 兼容 AI 接口 (chat/completions, images, responses, messages, models)"},
            {"name": "Accounts", "description": "账号池管理 (CRUD, 刷新, 批量操作, 分组)"},
            {"name": "Dashboard", "description": "运维看板 (调度/熔断/用量/延迟/寿命预测/容量/Provider)"},
            {"name": "Image Tasks", "description": "图片异步任务 (提交/轮询/编辑)"},
            {"name": "System", "description": "系统管理 (设置, 日志, 图片, 备份, 健康检查)"},
            {"name": "Auth Keys", "description": "API Key 管理 (CRUD, 撤销, 用量查询)"},
            {"name": "Proxy Pool", "description": "代理池管理 (HTTP/SOCKS5 代理)"},
            {"name": "Kookeey", "description": "kookeey 住宅代理集成 (流量/出口 IP)"},
            {"name": "Providers", "description": "提供商管理 (注册列表/状态)"},
            {"name": "Audit", "description": "审计日志查询与导出"},
            {"name": "logs", "description": "日志查询与下载"},
            {"name": "tracing", "description": "请求追踪 (慢查询分析)"},
        ],
        docs_url=(config.openapi_docs_url if hasattr(config, "openapi_enabled") and config.openapi_enabled else None),
        redoc_url=(config.openapi_redoc_url if hasattr(config, "openapi_enabled") and config.openapi_enabled else None),
        openapi_url=(config.openapi_openapi_url if hasattr(config, "openapi_enabled") and config.openapi_enabled else None),
    )
    # 注入 OpenAPI security scheme（bearer token 全局认证）
    from fastapi.openapi.utils import get_openapi

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            terms_of_service=app.terms_of_service,
            contact=app.contact,
            license_info=app.license_info,
            routes=app.routes,
            tags=app.openapi_tags,
            servers=app.servers,
        )
        openapi_schema["components"]["securitySchemes"] = {
            "BearerAuth": {"type": "http", "scheme": "bearer"}
        }
        openapi_schema["security"] = [{"BearerAuth": []}]
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
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

    # 注意：有意不使用 GZipMiddleware。gzip + Transfer-Encoding: chunked 组合在部分
    # 代理链路上会导致浏览器 ERR_INVALID_CHUNKED_ENCODING（curl 宽容、Chrome 严格）。
    # 自托管多走代理访问，稳定性优先，静态/JSON 响应均走 identity + Content-Length。
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
    app.include_router(logs.create_router())
    app.include_router(tracing.create_router())

    # _next/static 静态服务：优先返回预压缩 .gz（FileResponse 带 Content-Length，
    # 非 chunked，不触发 ERR_INVALID_CHUNKED_ENCODING）；客户端不接受 gzip 时返回
    # 原始文件。防路径穿越（resolve 后校验在 _static_dir 内）。
    _static_dir = WEB_DIST_DIR / "_next" / "static"

    @app.api_route("/_next/static/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_next_static(path: str, accept_encoding: str = Header(default="")):
        base = (_static_dir / path).resolve()
        if not str(base).startswith(str(_static_dir.resolve())) or not base.is_file():
            raise HTTPException(status_code=404, detail="Not Found")
        content_type = mimetypes.guess_type(str(base))[0] or "application/octet-stream"
        # Next.js 产物带内容 hash，可 immutable 缓存（避免慢链路上刷新重复下载）
        cache_hdr = {"Cache-Control": "public, max-age=31536000, immutable"}
        if "gzip" in accept_encoding.lower():
            gz = Path(str(base) + ".gz")
            if gz.is_file():
                return FileResponse(
                    gz,
                    media_type=content_type,
                    headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding", **cache_hdr},
                )
        return FileResponse(base, media_type=content_type, headers=cache_hdr)

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_web(full_path: str):
        asset = resolve_web_asset(full_path)
        if asset is not None:
            headers: dict[str, str] = {}
            if "__next." in full_path.split("/")[-1] and full_path.endswith(".txt"):
                headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return FileResponse(asset, headers=headers)
        if full_path.strip("/").startswith("_next/"):
            raise HTTPException(status_code=404, detail="Not Found")
        fallback = resolve_web_asset("")
        if fallback is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(fallback)

    return app
