#!/usr/bin/env python3
"""3.3.2：多 Worker 共享状态（Redis）一键接线引导。

幂等：连接 redis_url 校验可用 → 把 redis_url 写入 config.json（已存在同值则不重复写）。

多 worker 部署时，进程内限流计数/聊天缓存/熔断器状态各自独立（状态分裂），
Redis 共享状态让限流计数跨进程一致。本脚本做"一键接线"，之后重启服务生效。

用法：
    python scripts/init_redis_state.py                 # 默认 redis://127.0.0.1:6379/0
    python scripts/init_redis_state.py redis://host:6379/0

环境变量覆盖：CHATGPT2API_CONFIG_FILE（默认 ./config.json）、CHATGPT2API_REDIS_URL
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"


def _mask_url(value: str) -> str:
    """打码 URL 中的密码段，避免日志泄漏。"""
    if "://" not in value:
        return value
    scheme, _, rest = value.partition("://")
    if "@" not in rest:
        return value
    creds, _, host = rest.rpartition("@")
    if ":" in creds:
        user, _, _pw = creds.partition(":")
        return f"{scheme}://{user}:[REDACTED]@{host}"
    return f"{scheme}://[REDACTED]@{host}"


def _check_redis(url: str) -> tuple[bool, str]:
    """校验 Redis 连通性。redis 包不可用 / 连接失败时返回 (False, 原因)。"""
    try:
        import redis  # type: ignore
    except ImportError:
        return False, "redis 包未安装（pip install redis 后本脚本可校验连通性）"
    try:
        client = redis.Redis.from_url(url, socket_timeout=3)
        client.ping()
        client.close()
        return True, "OK"
    except Exception as exc:  # noqa: BLE001 - 连接失败原因统一包装
        return False, str(exc)


def main() -> int:
    config_path = Path(os.getenv("CHATGPT2API_CONFIG_FILE", "config.json"))
    redis_url = (os.getenv("CHATGPT2API_REDIS_URL") or sys.argv[1] if len(sys.argv) > 1 else "") or DEFAULT_REDIS_URL
    redis_url = redis_url.strip()

    # 1) 连通性校验（redis 包不可用不阻断，仅提示）
    ok, reason = _check_redis(redis_url)
    if ok:
        print(f"[ok] Redis 连通性校验通过: {_mask_url(redis_url)}")
    else:
        print(f"[warn] Redis 校验跳过: {reason}（仍会写入 config.json，启动时不可用自动降级 Local）")

    # 2) 幂等写入 config.json
    if not config_path.exists():
        print(f"Config file not found, creating {config_path}")
        data: dict[str, object] = {}
    else:
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON in {config_path}: {exc}", file=sys.stderr)
            return 1
        if not isinstance(data, dict):
            print(f"Config root must be an object: {config_path}", file=sys.stderr)
            return 1

    existing = str(data.get("redis_url") or "").strip()
    if existing == redis_url:
        print(f"[idempotent] redis_url 已配置且一致，无需改动: {_mask_url(redis_url)}")
    else:
        data["redis_url"] = redis_url
        config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
        try:
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(config_path)
        except OSError as exc:
            # Docker bind-mounted single files can reject atomic rename with EBUSY.
            if getattr(exc, "errno", None) != 16:
                raise
            config_path.write_text(payload, encoding="utf-8")
            tmp_path.unlink(missing_ok=True)
        print(f"[wrote] config.json redis_url = {_mask_url(redis_url)}（重启服务后生效）")

    print("多 worker 精确限流已接线指引：重启服务 → services/shared_state 自动走 Redis 实现 →")
    print("  `uv run pytest test/test_shared_state.py` 验证两实现（Local/Redis 工厂降级）全过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
