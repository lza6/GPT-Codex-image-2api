from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from services.config import config

if TYPE_CHECKING:
    from services.account_service import AccountService

logger = logging.getLogger(__name__)


class AccountWarmup:
    """新账号加入后自动执行预热验证。

    预热步骤：
    1. 调用 fetch_remote_info 验证 token 有效性
    在预热完成前，账号不会被主调度选取。
    """

    def __init__(self, account_service: AccountService | None = None) -> None:
        self._account_service = account_service
        self._warmup_inflight: dict[str, float] = {}  # token -> start_time
        self._lock = threading.RLock()  # RLock 支持同一线程重入

    def set_account_service(self, account_service: AccountService) -> None:
        """设置 account_service 引用（延迟注入，避免循环导入）。"""
        self._account_service = account_service

    def warmup_account(self, token: str, timeout_secs: float | None = None) -> bool:
        """预热单个账号：fetch_remote_info + 验证。

        返回 True 表示预热成功，False 表示失败或超时。
        """
        if not token:
            return False
        if not config.account_warmup_enabled:
            return True
        if self._account_service is None:
            return True
        timeout = timeout_secs if timeout_secs is not None else config.account_warmup_timeout_secs

        with self._lock:
            if token in self._warmup_inflight:
                return True  # 已在预热中
            self._warmup_inflight[token] = time.time()

        try:
            # 步骤 1：fetch_remote_info 验证 token 有效性
            account = self._account_service.fetch_remote_info(token, "account_warmup")
            if account is None:
                self.mark_warmup_failed(token)
                return False
            status = str(account.get("status") or "")
            if status in ("禁用", "异常", "限流"):
                self.mark_warmup_failed(token)
                return False
            # 验证通过
            with self._lock:
                if token in self._warmup_inflight:
                    elapsed = time.time() - self._warmup_inflight[token]
                    if elapsed > timeout:
                        self.mark_warmup_failed(token)
                        return False
            self.mark_warmup_success(token)
            return True
        except Exception as exc:
            logger.warning("账号预热失败 token=%s error=%s", token[-8:], exc)
            self.mark_warmup_failed(token)
            return False

    def is_warming_up(self, token: str) -> bool:
        """检查是否正在预热中。"""
        with self._lock:
            if token not in self._warmup_inflight:
                return False
            elapsed = time.time() - self._warmup_inflight[token]
            if elapsed > config.account_warmup_timeout_secs:
                self._warmup_inflight.pop(token, None)
                return False
            return True

    def mark_warmup_failed(self, token: str) -> None:
        """标记预热失败。"""
        with self._lock:
            self._warmup_inflight.pop(token, None)
        if self._account_service is not None:
            self._account_service.update_account(token, {"status": "异常"}, quiet=True)

    def mark_warmup_success(self, token: str) -> None:
        """标记预热成功。"""
        with self._lock:
            self._warmup_inflight.pop(token, None)

    def warmup_new_accounts(self) -> int:
        """预热所有未预热的新账号。

        查找没有 health_score 或 health_score=0 且 status=正常的账号进行预热。
        返回已启动预热的账号数。
        """
        if not config.account_warmup_enabled or self._account_service is None:
            return 0
        accounts = self._account_service.list_accounts()
        warmed = 0
        for account in accounts:
            token = account.get("access_token") or ""
            if not token:
                continue
            if self.is_warming_up(token):
                continue
            hs = account.get("health_score")
            if hs is not None and float(hs) > 0:
                continue
            if account.get("status") not in ("正常",):
                continue
            threading.Thread(
                target=self.warmup_account,
                args=(token,),
                daemon=True,
            ).start()
            warmed += 1
        return warmed


# 模块级单例——延迟注入 account_service
account_warmup: AccountWarmup = AccountWarmup()  # type: ignore[arg-type]