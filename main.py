from __future__ import annotations

import uvicorn
from api import create_app
from services.config import config

app = create_app()

if __name__ == "__main__":
    w = config.workers
    if w > 1 and config.storage_backend_type == "json":
        print(f"⚠️  WARNING: workers={w} 但存储后端为 JSON。多进程下各进程持有独立账号副本，")
        print("   会导致账号重复分配和数据丢失。请设置 STORAGE_BACKEND=sqlite 或 postgres。")
        print("   自动回退到 workers=1 以保证数据安全。")
        w = 1
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=23456,
        access_log=False,
        log_level="info",
        workers=w,
    )
