"""统一重试预算：收敛散落的上游重试逻辑为显式规则。

规则（仅两类允许重试）：
1. 幂等 GET（_get_me/_get_conversation/_query_backend_tasks 等）：指数退避最多 N 次；
2. 流式首字节前连接失败：换账号重试最多 1 次。

流式开始（已收到首个事件/字节）后绝不重试——重复请求会重复扣费/重复出图，
只断流报错。调用方据此决定是否安全重试。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

# 幂等 GET 默认最多重试 2 次（共 3 次尝试）
IDEMPOTENT_GET_MAX_RETRIES = 2
# 流式首字节前连接失败换账号最多重试 1 次
PRE_STREAM_SWITCH_MAX_RETRIES = 1


def retry_idempotent_get(
    fn: Callable[[], T],
    *,
    max_retries: int = IDEMPOTENT_GET_MAX_RETRIES,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
    retryable: Callable[[Exception], bool] | None = None,
) -> T:
    """对幂等 GET 做指数退避重试。

    参数：
    - `fn`：执行一次请求的零参可调用。
    - `max_retries`：最多重试次数（不含首次尝试）。
    - `base_delay`：首次重试等待秒数，之后按 2 倍指数退避。
    - `max_delay`：单次等待上限。
    - `retryable`：判定异常是否可重试；缺省全部异常可重试。

    重试耗尽后抛出最后一次异常。
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            if attempt >= max_retries:
                raise
            if retryable is not None and not retryable(exc):
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            time.sleep(delay)
            attempt += 1


def can_retry_stream(emitted: bool, *, pre_stream_retries_used: int = 0) -> bool:
    """流式请求是否还允许重试。

    - 已发出任何内容（emitted=True）→ 绝不重试（防重复扣费/出图）。
    - 首字节前连接失败 → 仅当换账号重试次数未达上限时才允许。
    """
    if emitted:
        return False
    return pre_stream_retries_used < PRE_STREAM_SWITCH_MAX_RETRIES
