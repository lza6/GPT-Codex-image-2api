"""fomimage 自动注册协调器（v2.36.0）。

内部闭环：注册成功 → account_service.add_account_items 写入号池（provider=fomimage，
quota=注册送 50 积分）。自动补号：后台线程按 check_interval_minutes 检查 provider=fomimage
可用号数，低于 min_accounts 触发注册 register_batch 个。

线程模型：_reg_lock 保证同一时刻只有一个注册任务在跑；注册在调用线程内同步执行。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from services.registration.config import FomimageRegistrationConfig, get_fomimage_registration_config
from services.registration.fomimage.engine import FomimageRegisterEngine

logger = logging.getLogger("chatgpt2api.registration")

_UNAVAILABLE_STATUS = {"异常", "禁用", "待登录", "已删除", "失效", "回收"}


def count_fomimage_accounts() -> int:
    """统计号池中 provider=fomimage 的可用号数（有 token 且状态正常）。"""
    try:
        from services.account_service import account_service

        accounts = account_service.list_accounts()
    except Exception:
        return 0
    count = 0
    for account in accounts:
        if not isinstance(account, dict):
            continue
        if str(account.get("provider") or "").strip().lower() != "fomimage":
            continue
        if not str(account.get("access_token") or "").strip():
            continue
        if str(account.get("status") or "") in _UNAVAILABLE_STATUS:
            continue
        count += 1
    return count


def _push_to_pool(items: list[dict[str, Any]], pool_quota: int) -> int:
    """把注册成功的账号写入号池（按 token 去重，重复跳过）。返回实际新增数。"""
    if not items:
        return 0
    try:
        from services.account_service import account_service

        records: list[dict[str, Any]] = []
        for item in items:
            token = str(item.get("access_token") or "").strip()
            email = str(item.get("email") or "").strip()
            if not token:
                continue
            records.append({
                "access_token": token,
                "provider": "fomimage",
                "email": email,
                "password": str(item.get("password") or "").strip(),
                "source_type": "fomimage_registration",
                "type": "free",
                "label": "fomimage-auto",
                "status": "正常",
                "quota": max(0, int(item.get("balance") or pool_quota)),
                "proxy": str(item.get("proxy") or "").strip(),
                "note": "fomimage 自动注册（注册送积分，用完即弃）",
            })
        result = account_service.add_account_items(records)
        return int(result.get("added") or 0)
    except Exception as exc:  # noqa: BLE001 - 入库失败记录日志，不阻断
        logger.error("fomimage 账号写入号池失败: %s", exc)
        return 0


class FomimageRegistrationCoordinator:
    """fomimage 注册编排器单例。"""

    def __init__(self) -> None:
        self._reg_lock = threading.Lock()
        self._stats: dict[str, Any] = {
            "last_run_at": None,
            "last_run_result": None,
            "total_registered": 0,
            "total_failed": 0,
        }
        self._thread: threading.Thread | None = None

    def register(self, count: int | None = None) -> dict[str, Any]:
        """手动触发注册 N 个（默认取配置 register_batch）。返回本次执行结果。"""
        if not self._reg_lock.acquire(blocking=False):
            return {"ok": False, "error": "已有注册任务在运行，请稍后再试"}
        try:
            return self._register_inner(count)
        finally:
            self._reg_lock.release()

    def _register_inner(self, count: int | None = None) -> dict[str, Any]:
        cfg = get_fomimage_registration_config()
        if not cfg.enabled:
            return {"ok": False, "error": "fomimage 注册未启用（registration.fomimage.enabled=false）"}

        n = max(1, int(count or cfg.register_batch))
        engine = FomimageRegisterEngine(cfg)
        result = engine.register(n)
        items = result.get("items") or []
        added = _push_to_pool(items, cfg.pool_quota)

        result["pool_added"] = added
        self._stats["last_run_at"] = time.time()
        self._stats["last_run_result"] = {
            "success": result.get("success", 0),
            "failed": result.get("failed", 0),
            "pool_added": added,
        }
        self._stats["total_registered"] += result.get("success", 0)
        self._stats["total_failed"] += result.get("failed", 0)
        logger.info(
            "fomimage 注册批次完成: 注册 %s 成功 %s 失败, 入池 %s",
            n, result.get("success", 0), added,
        )
        return {"ok": True, **result}

    def start_watcher(self, stop_event: threading.Event | None = None) -> None:
        """启动自动补号定时器（后台线程，幂等）。enabled=false 时线程空转不注册。"""
        if self._thread is not None and self._thread.is_alive():
            return
        event = stop_event or threading.Event()
        self._thread = threading.Thread(
            target=self._watch_loop,
            args=(event,),
            daemon=True,
            name="fomimage-registration-replenish",
        )
        self._thread.start()

    def _watch_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            time.sleep(30)
            if stop_event.is_set():
                break
            try:
                cfg = get_fomimage_registration_config()
                if not cfg.enabled:
                    continue
                interval = max(60, cfg.check_interval_minutes * 60)
                self._watch_check(cfg, stop_event, interval)
            except Exception:  # noqa: BLE001 - 补号线程异常不崩服务
                logger.exception("fomimage 自动补号循环异常")

    def _watch_check(self, cfg: FomimageRegistrationConfig, stop_event: threading.Event, interval: int) -> None:
        waited = 0
        step = 10
        while waited < interval and not stop_event.is_set():
            time.sleep(step)
            waited += step
        if stop_event.is_set():
            return
        available = count_fomimage_accounts()
        if available >= cfg.min_accounts:
            return
        logger.info("fomimage 号池可用 %s < 阈值 %s，触发自动补号 %s 个", available, cfg.min_accounts, cfg.register_batch)
        if self._reg_lock.acquire(blocking=False):
            try:
                self._register_inner(cfg.register_batch)
            except Exception:  # noqa: BLE001
                logger.exception("fomimage 自动补号失败")
            finally:
                self._reg_lock.release()

    def status(self) -> dict[str, Any]:
        """注册状态/号池健康快照（API 用）。"""
        cfg = get_fomimage_registration_config()
        available = count_fomimage_accounts()
        return {
            "enabled": cfg.enabled,
            "config": cfg.to_dict(),
            "fomimage_pool": {
                "available": available,
                "min_accounts": cfg.min_accounts,
                "need_replenish": bool(cfg.enabled and available < cfg.min_accounts),
            },
            "stats": self._stats,
            "watcher_running": bool(self._thread is not None and self._thread.is_alive()),
            "registration_busy": self._reg_lock.locked(),
        }


# 模块级单例（供 API / app lifespan 使用）
fomimage_registration_coordinator = FomimageRegistrationCoordinator()
