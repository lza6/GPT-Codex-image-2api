from __future__ import annotations

import os

import uvicorn

from api import create_app
from services.config import config


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
