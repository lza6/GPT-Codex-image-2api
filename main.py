from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

import uvicorn

from api import create_app
from services.config import DATA_DIR, config


def _check_data_dir_writable() -> None:
    """D-B2：检查 data/ 目录是否可写（Docker 非 root 与 bind mount 权限冲突常见）。
    不可写时打印明确告警，让运维可在宿主机 `chown -R 10001:10001 data/` 修复。
    """
    try:
        probe = Path(DATA_DIR) / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except (OSError, PermissionError) as exc:
        print(f"⚠️  data/ 目录不可写（{exc}）。如果是 Docker 非 root 用户权限问题，")
        print("   请在宿主机执行：chown -R 10001:10001 data/")
        print("   或使用 named volume 替代 bind mount：volumes: data:/app/data")
        print("   当前进程将继续运行，但图片/日志/配置写入将失败。")
        # 继续运行不抛异常（用户可先修复，日志写入失败有降级兜底）


def _init_file_logging() -> None:
    """把 chatgpt2api 主 logger + 根 logger 同步落盘到 data/logs/server.log。

    - bat 黑匣子看不清时的备用排查通道：DEBUG 事件（codex 请求/响应、账号状态）都会进文件。
    - chatgpt2api logger 的 propagate=False，必须单独挂 handler 才能收到。
    - RotatingFileHandler 5MB × 3 备份，避免磁盘爆量。
    - 幂等：重复启动不会重复挂 handler。
    """
    try:
        log_dir = Path(DATA_DIR) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        for logger_name in ("chatgpt2api", ""):
            target = logging.getLogger(logger_name)
            if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in target.handlers):
                continue
            handler = logging.handlers.RotatingFileHandler(
                log_dir / "server.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(formatter)
            target.addHandler(handler)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  日志文件初始化失败: {exc}")


_init_file_logging()
_check_data_dir_writable()


def resolve_workers() -> int:
    """Worker 数解析（模块级——uvicorn CLI 与 python main.py 两条启动路径都经过）。

    JSON 存储下 workers>1 必须回退为 1（多进程各持独立账号副本 = 数据损坏），
    回退必须打警告而非静默（第七轮 audit-deploy：bat/Docker 走 uvicorn CLI
    绕过 __main__ 守卫，workers 配置曾静默无效）。
    """
    w = config.workers
    if w > 1 and config.storage_backend_type == "json":
        print(f"⚠️  WARNING: workers={w} 但存储后端为 JSON。多进程下各进程持有独立账号副本，")
        print("   会导致账号重复分配和数据丢失。请设置 STORAGE_BACKEND=sqlite 或 postgres。")
        print("   自动回退到 workers=1 以保证数据安全。")
        return 1
    return w


RESOLVED_WORKERS = resolve_workers()


def _init_prometheus_multiproc_dir(workers: int) -> None:
    """多 Worker 时初始化 prometheus_client 的共享指标目录。

    prometheus_client 的 multiprocess 模式需要 PROMETHEUS_MULTIPROC_DIR
    指向一个空目录，各 worker 把指标写入，/metrics 端点从该目录聚合。
    """
    if workers <= 1:
        return
    try:
        from services.config import DATA_DIR

        multiproc_dir = DATA_DIR / "prometheus_multiproc"
        multiproc_dir.mkdir(parents=True, exist_ok=True)
        # 清空旧文件（prometheus_client 要求目录为空）
        for f in multiproc_dir.glob("*.db"):
            try:
                f.unlink()
            except OSError:
                pass
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = str(multiproc_dir)
    except Exception as exc:
        print(f"⚠️  prometheus multiprocess 目录初始化失败: {exc}")


_init_prometheus_multiproc_dir(RESOLVED_WORKERS)

app = create_app()


if __name__ == "__main__":
    # 免费代理池抓取守护线程（仅主进程；free_proxy.enabled 默认 false 时无副作用）
    try:
        from services.free_proxy_fetcher import free_proxy_fetcher

        free_proxy_fetcher.start()
    except Exception as exc:
        print(f"⚠️  免费代理池抓取线程启动失败: {exc}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("CHATGPT2API_PORT", "23456")),
        access_log=False,
        log_level="info",
        limit_concurrency=512,
        backlog=1024,
        workers=RESOLVED_WORKERS,
    )
