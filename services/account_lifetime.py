"""5.1：账号寿命预测——把「已消费的同一批信号」改写成趋势形态，事前预警账号衰亡。

数据全部来自既有账号字段（无新埋点）：
- `success`/`fail`：累计成败计数（account_service 落盘，调度分直接消费）
- `invalid_count`/`last_invalid_at`：累计失效次数 + 最近失效时间（连续失败窗口）
- `last_refresh_error_at`/`last_token_refresh_error_at`：最近刷新错误时间
- `quota`/`created_at`：配额与创建时间（预估剩余可用时长）

设计（第一性原理）：
- **EWMA 失败率**：总失败率 + 最近错误时间衰减（越近越重），不引入统计回归——
  数据量小，EWMA 更稳。
- **连续失败窗口**：`invalid_count` 独立信号——累计失效次数反映"反复横跳"，
  即使最近一次成功也危险。
- **最小观测窗口守卫**：样本不足（success+fail<3）且无明确失效 → 低风险，
  防止「瞬间封禁/复活抖动」。
- **不直接封禁**：只输出风险档位 + 预估时长，调度层据此降档（warm/risky）。

本模块为纯函数 + 时钟可注入（`now`），便于单测锁定，不依赖 account_service 实例。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

# 风险档位（从低到高）
LEVEL_LOW = "low"
LEVEL_MEDIUM = "medium"
LEVEL_HIGH = "high"
LEVEL_CRITICAL = "critical"

_LEVELS = (LEVEL_LOW, LEVEL_MEDIUM, LEVEL_HIGH, LEVEL_CRITICAL)

# 最小观测窗口：成败样本 < 此值且无明确失效信号 → 不判风险
_MIN_OBSERVATION = 3
# 连续失效阈值：累计失效达此值即视为"反复失效"信号
_INVALID_WINDOW_CRITICAL = 3
_INVALID_WINDOW_HIGH = 2

# III-03：配额预警阈值（按消耗速率估算的剩余天数）
# 剩余 <= WARN 天 → 配额预警（healthy 降 warm）；剩余 <= CRITICAL 天 → 濒危（降 risky）。
# 取值避免过于激进：WARN=3 天给运维补号窗口，CRITICAL=1 天近似"当天将耗尽"。
QUOTA_WARN_DAYS = 3.0
QUOTA_CRITICAL_DAYS = 1.0
# 配额信号最小观测样本：success 至少达到此值才允许按速率外推，防刚建号误判
_QUOTA_MIN_OBSERVATION = 3


def _now() -> float:
    return time.time()


def _parse_ts(value: object) -> float | None:
    """解析账号里的时间戳字段（支持 ISO / 'YYYY-MM-DD HH:MM:SS' / epoch 秒）。"""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).timestamp()


def _time_decay_factor(ts: float, now: float, *, half_life_seconds: float = 3600.0) -> float:
    """时间衰减系数 [0,1)：事件越近越接近 1。指数衰减，避免硬阈值毛刺。"""
    age = max(0.0, now - ts)
    if age >= half_life_seconds * 8:
        return 0.0
    return 2 ** (-age / half_life_seconds)


def _quota_remaining_days(account: dict[str, Any], now: float) -> float | None:
    """按配额消耗速率估算剩余可用天数（III-03 第三信号）。

    口径与 eta_days 一致（success 近似已用量 / 创建至今时长），但作为预警信号
    有更严的观测守卫：success 样本 >= _QUOTA_MIN_OBSERVATION 且账号创建至少 1 天
    才外推，否则返回 None（样本不足不预警，防误封抖动）。
    """
    quota = int(account.get("quota") or 0)
    if quota <= 0:
        return None
    success = max(0, int(account.get("success") or 0))
    if success < _QUOTA_MIN_OBSERVATION:
        return None
    created_ts = _parse_ts(account.get("created_at"))
    if created_ts is None or now <= created_ts:
        return None
    days_elapsed = (now - created_ts) / 86400.0
    if days_elapsed < 1.0:
        return None
    daily_consumption = success / days_elapsed
    if daily_consumption <= 0:
        return None
    return quota / daily_consumption


def compute_lifetime_risk(account: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """评估单账号寿命风险。

    Args:
        account: 账号字典（account_service 的标准字段）。
        now: 可注入当前时间戳（epoch 秒），默认 time.time()，供测试锁定。

    Returns:
        {
            "level": "low|medium|high|critical",
            "score": float,            # 0-100，越接近 100 越危险
            "eta_days": int | None,    # 预估剩余可用天数（有限配额按消耗速率；无限/无数据为 None）
            "signals": {               # 各信号贡献，便于看板/调试展示
                "fail_rate": float,
                "invalid_window": int,
                "recent_error_score": float,
            },
        }
    """
    now = now if now is not None else _now()
    if not isinstance(account, dict):
        return {"level": LEVEL_LOW, "score": 0.0, "eta_days": None, "signals": {}}

    success = max(0, int(account.get("success") or 0))
    fail = max(0, int(account.get("fail") or 0))
    total = success + fail
    invalid_count = max(0, int(account.get("invalid_count") or 0))

    # ---- 信号 1：EWMA 失败率（总失败率 + 最近错误时间衰减） ----
    fail_rate = (fail / total) if total > 0 else 0.0
    recent_error_score = 0.0
    for field in ("last_invalid_at", "last_refresh_error_at", "last_token_refresh_error_at"):
        ts = _parse_ts(account.get(field))
        if ts is not None:
            # 最近错误越近，权重越高（10 分钟半衰期附近，1 小时内显著，之后快速衰减）
            recent_error_score = max(recent_error_score, _time_decay_factor(ts, now, half_life_seconds=600.0))
    # 失败率本身也随总样本量加权（样本越多越可信）；样本 >=3 时至少给 0.4 保底，
    # 避免"6 次里失败 5 次"这种绝对多数仍被样本惩罚成 low（第一性：绝对比例优先于样本量）
    if total < _MIN_OBSERVATION:
        fail_rate_confidence = 0.0
    else:
        fail_rate_confidence = min(1.0, max(0.4, total / 10.0))

    # ---- 信号 2：连续失败窗口（累计失效次数） ----
    invalid_window = 0.0
    if invalid_count >= _INVALID_WINDOW_CRITICAL:
        invalid_window = 1.0
    elif invalid_count >= _INVALID_WINDOW_HIGH:
        invalid_window = 0.6
    elif invalid_count >= 1:
        invalid_window = 0.25

    # ---- 最小观测窗口守卫 ----
    has_explicit_signal = bool(recent_error_score > 0 or invalid_count > 0)
    if total < _MIN_OBSERVATION and not has_explicit_signal:
        return {
            "level": LEVEL_LOW,
            "score": 0.0,
            "eta_days": None,
            "quota_remaining_days": None,
            "quota_warning": False,
            "signals": {"fail_rate": fail_rate, "invalid_window": invalid_count, "recent_error_score": recent_error_score},
        }

    # ---- 综合评分（各信号 0-40，封顶 100） ----
    score = 0.0
    score += 40.0 * fail_rate * fail_rate_confidence
    score += 40.0 * invalid_window
    score += 20.0 * recent_error_score

    # 濒危硬性判定：连续失效窗口 + 最近失效很近
    critical_recent_invalid = (
        invalid_count >= _INVALID_WINDOW_CRITICAL
        and (ts := _parse_ts(account.get("last_invalid_at"))) is not None
        and (now - ts) < 3600
    )
    if critical_recent_invalid:
        score = max(score, 85.0)

    if score >= 70:
        level = LEVEL_CRITICAL
    elif score >= 35:
        level = LEVEL_HIGH
    elif score >= 15:
        level = LEVEL_MEDIUM
    else:
        level = LEVEL_LOW

    # ---- 预估剩余可用时长 ----
    eta_days: int | None = None
    quota = int(account.get("quota") or 0)
    if quota > 0:
        # 有限配额：按日均消耗外推（success 为成功调用数，近似"已用"）
        created_ts = _parse_ts(account.get("created_at"))
        if created_ts is not None and success > 0 and now > created_ts:
            days_elapsed = max(1.0, (now - created_ts) / 86400.0)
            daily_consumption = success / days_elapsed
            if daily_consumption > 0:
                eta_days = max(1, int(quota / daily_consumption))
    elif quota < 0:
        # 无限配额：无精确到期；给风险等级驱动的保守上限（提示而非断言）
        if level == LEVEL_CRITICAL:
            eta_days = 1
        elif level == LEVEL_HIGH:
            eta_days = 7
        elif level == LEVEL_MEDIUM:
            eta_days = 30

    # III-03：配额预警第三信号（剩余天数按消耗速率外推）
    quota_days = _quota_remaining_days(account, now)
    quota_warning = quota_days is not None and quota_days <= QUOTA_WARN_DAYS

    return {
        "level": level,
        "score": round(min(100.0, score), 1),
        "eta_days": eta_days,
        "quota_remaining_days": round(quota_days, 1) if quota_days is not None else None,
        "quota_warning": quota_warning,
        "signals": {
            "fail_rate": round(fail_rate, 3),
            "invalid_window": invalid_count,
            "recent_error_score": round(recent_error_score, 3),
            "quota_remaining_days": round(quota_days, 1) if quota_days is not None else None,
        },
    }
