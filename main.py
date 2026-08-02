from __future__ import annotations

import os

import uvicorn

from api import create_app
from services.config import config

app = create_app()


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


if __name__ == "__main__":
    w = config.workers
    if w > 1 and config.storage_backend_type == "json":
        print(f"⚠️  WARNING: workers={w} 但存储后端为 JSON。多进程下各进程持有独立账号副本，")
        print("   会导致账号重复分配和数据丢失。请设置 STORAGE_BACKEND=sqlite 或 postgres。")
        print("   自动回退到 workers=1 以保证数据安全。")
        w = 1
    _init_prometheus_multiproc_dir(w)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=23456,
        access_log=False,
        log_level="info",
        workers=w,
    )
