"""Grok 注册编排器：手动触发单次注册 + 自动补号定时器 + 状态查询。

内部闭环：注册成功 → `account_service.add_account_items` 直接写入号池（provider=grok），
无外部推送。自动补号：后台线程按 `check_interval_minutes` 检查号池中 provider=grok
的可用号数，低于 `min_accounts` 时触发注册 `register_batch` 个。

线程模型：
- `_reg_lock` 保证同一时刻只有一个注册任务在跑（手动/自动互斥）。
- 注册在调用线程内同步执行（FastAPI 端点经 `run_in_threadpool` 跑，不阻塞事件循环）。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from services.registration.config import GrokRegistrationConfig, get_registration_config
from services.registration.email_pool import EmailPool
from services.registration.grok.email_service import EmailService
from services.registration.grok.engine import GrokRegisterEngine, resolve_proxy_for_group

logger = logging.getLogger("chatgpt2api.registration")

# 号池中视为"不可用"的状态（与 chatgpt2api 既有语义对齐）
_UNAVAILABLE_STATUS = {"异常", "禁用", "待登录", "已删除", "失效", "回收"}


def count_grok_accounts() -> int:
    """统计号池中 provider=grok 的可用号数（有 token 且状态正常）。"""
    try:
        from services.account_service import account_service

        accounts = account_service.list_accounts()
    except Exception:
        return 0
    count = 0
    for account in accounts:
        if not isinstance(account, dict):
            continue
        if str(account.get("provider") or "").strip().lower() != "grok":
            continue
        if not str(account.get("access_token") or "").strip():
            continue
        if str(account.get("status") or "") in _UNAVAILABLE_STATUS:
            continue
        count += 1
    return count


def _push_to_pool(items: list[dict[str, Any]]) -> int:
    """把注册成功的账号写入号池。返回实际新增数（按 token 去重，重复跳过）。"""
    if not items:
        return 0
    try:
        from services.account_service import account_service

        result = account_service.add_account_items(items)
        return int(result.get("added") or 0)
    except Exception as exc:  # noqa: BLE001 - 入库失败记录日志，不阻断注册结果返回
        logger.error("grok 账号写入号池失败: %s", exc)
        return 0


class RegistrationCoordinator:
    """grok 注册编排器单例。"""

    def __init__(self) -> None:
        self._reg_lock = threading.Lock()
        self._email_pool = EmailPool()
        self._stats: dict[str, Any] = {
            "last_run_at": None,
            "last_run_result": None,
            "total_registered": 0,
            "total_failed": 0,
        }
        self._thread: Optional[threading.Thread] = None

    # ── 注册触发 ───────────────────────────────────────────────────

    def register(self, count: Optional[int] = None) -> dict[str, Any]:
        """手动触发注册 N 个（默认取配置 register_batch）。返回本次执行结果。"""
        if not self._reg_lock.acquire(blocking=False):
            return {"ok": False, "error": "已有注册任务在运行，请稍后再试"}
        try:
            return self._register_inner(count)
        finally:
            self._reg_lock.release()

    def _register_inner(self, count: Optional[int] = None) -> dict[str, Any]:
        cfg = get_registration_config()
        if not cfg.enabled:
            return {"ok": False, "error": "grok 注册未启用（registration.grok.enabled=false）"}

        n = max(1, int(count or cfg.register_batch))
        # 每次注册前从 config 重载邮箱池（支持热更新）
        self._email_pool.reload(cfg.email_pool, cfg.email_pool_file)
        email_service = EmailService(cfg, self._email_pool)
        proxy = resolve_proxy_for_group(cfg.proxy_group_id)

        engine = GrokRegisterEngine(cfg)
        result = engine.register(email_service, n, proxy=proxy)

        # 可选：SSO → OAuth Device Flow 铸造（patchright + 有头 Chrome，默认关）。
        # 先铸造再入池，铸造出的 refresh_token/AT 一并写进号池记录。
        minted = 0
        items = result.get("items") or []
        if cfg.device_mint_enabled and items:
            minted = self._try_mint(items, proxy)

        # 写入号池
        pool_items: list[dict[str, Any]] = []
        for item in items:
            sso = str(item.get("sso") or "").strip()
            if not sso:
                continue
            record: dict[str, Any] = {
                "access_token": sso,
                "provider": "grok",
                "email": str(item.get("email") or "").strip(),
                "password": str(item.get("password") or "").strip(),
                "source_type": "grok_registration",
                "type": "free",
                "label": "grok-auto",
                "status": "正常",
                "note": "grok 自动注册",
            }
            if item.get("grok_refresh_token"):
                record["grok_refresh_token"] = str(item["grok_refresh_token"])
            if item.get("grok_oauth_access_token"):
                record["grok_oauth_access_token"] = str(item["grok_oauth_access_token"])
            pool_items.append(record)
        added = _push_to_pool(pool_items)

        result["pool_added"] = added
        result["minted"] = minted
        self._stats["last_run_at"] = time.time()
        self._stats["last_run_result"] = {
            "success": result.get("success", 0),
            "failed": result.get("failed", 0),
            "pool_added": added,
            "minted": minted,
        }
        self._stats["total_registered"] += result.get("success", 0)
        self._stats["total_failed"] += result.get("failed", 0)
        logger.info(
            "grok 注册批次完成: 注册 %s 成功 %s 失败, 入池 %s",
            n, result.get("success", 0), added,
        )
        return {"ok": True, **result}

    def _try_mint(self, items: list[dict[str, Any]], proxy: str) -> int:
        """对注册成功的 SSO 尝试 Device Flow 铸造（失败不影响入池）。"""
        from services.registration.grok.device_mint import sso_to_device

        minted = 0
        for item in items:
            try:
                oauth = sso_to_device(str(item.get("sso") or ""), str(item.get("email") or ""), proxy)
                if oauth:
                    item["grok_refresh_token"] = oauth.get("refresh_token", "")
                    item["grok_oauth_access_token"] = oauth.get("access_token", "")
                    minted += 1
            except Exception:  # noqa: BLE001 - 铸造失败不阻断
                continue
        return minted

    # ── 自动补号 ───────────────────────────────────────────────────

    def start_watcher(self, stop_event: Optional[threading.Event] = None) -> None:
        """启动自动补号定时器（后台线程，幂等）。enabled=false 时线程空转不注册。"""
        if self._thread is not None and self._thread.is_alive():
            return
        event = stop_event or threading.Event()
        self._thread = threading.Thread(
            target=self._watch_loop,
            args=(event,),
            daemon=True,
            name="grok-registration-replenish",
        )
        self._thread.start()

    def _watch_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            time.sleep(30)  # 首次检查等 30s（服务完全启动后再动）
            if stop_event.is_set():
                break
            try:
                cfg = get_registration_config()
                if not cfg.enabled:
                    continue
                interval = max(60, cfg.check_interval_minutes * 60)
                self._watch_check(cfg, stop_event, interval)
            except Exception:  # noqa: BLE001 - 补号线程异常不崩服务
                logger.exception("grok 自动补号循环异常")

    def _watch_check(self, cfg: GrokRegistrationConfig, stop_event: threading.Event, interval: int) -> None:
        """等待 interval 后检查一次；期间 stop_event 置位立即退出。"""
        waited = 0
        step = 10
        while waited < interval and not stop_event.is_set():
            time.sleep(step)
            waited += step
        if stop_event.is_set():
            return
        available = count_grok_accounts()
        if available >= cfg.min_accounts:
            return
        logger.info("grok 号池可用 %s < 阈值 %s，触发自动补号 %s 个", available, cfg.min_accounts, cfg.register_batch)
        if self._reg_lock.acquire(blocking=False):
            try:
                self._register_inner(cfg.register_batch)
            except Exception:  # noqa: BLE001
                logger.exception("grok 自动补号失败")
            finally:
                self._reg_lock.release()

    # ── 状态 ───────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """注册状态/号池健康快照（API 用）。"""
        cfg = get_registration_config()
        available = count_grok_accounts()
        return {
            "enabled": cfg.enabled,
            "config": cfg.to_dict(),
            "grok_pool": {
                "available": available,
                "min_accounts": cfg.min_accounts,
                "need_replenish": bool(cfg.enabled and available < cfg.min_accounts),
            },
            "email_pool": {
                "total": self._email_pool.count(),
                "available": self._email_pool.available(),
            },
            "stats": self._stats,
            "watcher_running": bool(self._thread is not None and self._thread.is_alive()),
            "registration_busy": self._reg_lock.locked(),
        }


# 模块级单例（供 API / app lifespan 使用）
registration_coordinator = RegistrationCoordinator()
