"""连接池自愈与泄漏检测测试（III-05）：stats 正确性 + 泄漏阈值告警触发 + 健康检查清理。

覆盖：
- stats() 扩展字段：空闲连接数 / 在用数 / 复用率 / 总配置数 / idle_stale
- leak_report()：空闲超 TTL×multiplier 未回收 + 借用超阈值未归还
- check_leaks()：泄漏超阈值触发 session_pool.leak 事件 + alert_service 告警（mock）
- cleanup_stale()：健康检查接管——不健康空闲连接主动清理，健康连接保留
- 事件总线接入：SESSION_POOL_LEAK 在 ALL_EVENTS + event_bus_init 告警映射
- metrics_service.prometheus() 导出连接池 gauge
"""

from __future__ import annotations

import time
from unittest.mock import patch

from services.session_pool import SessionPool


def _pool(ttl: float = 300.0, multiplier: float = 3.0, alert_min: int = 1) -> SessionPool:
    return SessionPool(
        ttl_seconds=ttl,
        max_entries=10,
        min_size=1,
        health_check_enabled=False,
        leak_threshold_multiplier=multiplier,
        leak_alert_min=alert_min,
    )


def _get(pool: SessionPool, token: str = "tok-aaa") -> object:
    """从池中取出一个 Session（patch proxy_settings，不触网）。"""
    with patch("services.session_pool.proxy_settings") as ps:
        ps.get_profile.return_value = type("P", (), {"proxy_url": ""})()
        ps.build_session_kwargs.return_value = {}
        return pool.get(account={"access_token": token}, fp_key="f")


# ── stats 正确性 ───────────────────────────────────────────────────


def test_stats_idle_in_use_hit_rate_configured():
    """stats：第一次 get 为 miss（在用），第二次同 key 为 hit，复用率递增。"""
    pool = _pool()
    _get(pool, "tok-a")
    s = pool.stats()
    assert s["pooled_sessions"] == 1
    assert s["in_use"] == 1, "get 后未 release 的连接应计为在用"
    assert s["idle_sessions"] == 0
    assert s["get_total"] == 1
    assert s["get_hits"] == 0
    assert s["hit_rate"] == 0.0
    assert s["configured_count"] == 1

    _get(pool, "tok-a")  # 同 key 第二次：命中缓存
    s = pool.stats()
    assert s["get_total"] == 2
    assert s["get_hits"] == 1
    assert s["hit_rate"] == 0.5
    assert s["in_use"] == 1


def test_stats_release_marks_idle():
    """release 归还后连接回到空闲，在用数归零。"""
    pool = _pool()
    s = _get(pool, "tok-a")
    pool.release(s)
    st = pool.stats()
    assert st["in_use"] == 0
    assert st["idle_sessions"] == 1
    assert st["pooled_sessions"] == 1, "release 不得拆掉池化连接"


def test_stats_configured_count_tracks_distinct_keys():
    """总配置数：不同 token 累加，同 token 不重复。"""
    pool = _pool()
    _get(pool, "tok-a")
    _get(pool, "tok-b")
    _get(pool, "tok-a")  # 复用已有配置，不新增
    assert pool.stats()["configured_count"] == 2
    assert pool.stats()["pooled_sessions"] == 2


def test_stats_exposes_leak_threshold_and_idle_stale():
    pool = _pool(ttl=0.05, multiplier=3.0)
    s = _get(pool, "tok-a")
    pool.release(s)
    time.sleep(0.2)  # 超过 ttl*3=0.15s
    st = pool.stats()
    assert st["leak_threshold_seconds"] >= 0.15
    assert st["idle_stale"] == 1


# ── 泄漏检测（leak_report） ────────────────────────────────────────


def test_leak_report_idle_stale():
    """池内空闲超阈值连接被标记为 idle_stale（空闲长时间未回收）。"""
    pool = _pool(ttl=0.05, multiplier=3.0)
    s = _get(pool, "tok-a")
    pool.release(s)  # 归还后空闲
    time.sleep(0.2)
    report = pool.leak_report()
    assert report["idle_stale_count"] == 1
    assert report["borrowed_stale_count"] == 0
    assert report["leak_count"] == 1
    assert report["leak_threshold_seconds"] >= 0.15


def test_leak_report_borrowed_stale():
    """get 借出后长期未 release（借用泄漏）被标记为 borrowed_stale。"""
    pool = _pool(ttl=0.05, multiplier=3.0)
    _get(pool, "tok-a")  # 借用后不归还
    time.sleep(0.2)
    report = pool.leak_report()
    assert report["borrowed_stale_count"] == 1
    assert report["leak_count"] == 1


def test_leak_report_no_leak_when_fresh():
    """新连接未超阈值：无泄漏。"""
    pool = _pool(ttl=300.0, multiplier=3.0)
    s = _get(pool, "tok-a")
    pool.release(s)
    report = pool.leak_report()
    assert report["leak_count"] == 0


# ── 泄漏阈值告警触发（check_leaks） ────────────────────────────────


def test_check_leaks_triggers_alert_when_over_threshold():
    """泄漏超阈值：发布 session_pool.leak 事件 + 调用 alert_service.send_alert。"""
    pool = _pool(ttl=0.05, multiplier=3.0, alert_min=1)
    s = _get(pool, "tok-a")
    pool.release(s)
    time.sleep(0.2)

    with patch("services.alert_service.send_alert") as mock_send, \
         patch("services.event_bus.event_bus.publish") as mock_publish:
        report = pool.check_leaks()

    assert report["leak_count"] >= 1
    assert mock_send.called, "泄漏超阈值必须触发 alert_service.send_alert"
    args, kwargs = mock_send.call_args
    assert args[0] == "session_pool_leak"
    assert args[1]["leak_count"] >= 1
    assert args[1]["trigger"] == "session_pool_leak"

    assert mock_publish.called, "泄漏超阈值必须发布 session_pool.leak 事件"
    event = mock_publish.call_args[0][0]
    assert event.type == "session_pool.leak"
    assert event.data["leak_count"] >= 1


def test_check_leaks_no_alert_below_threshold():
    """未超阈值：不触发告警。"""
    pool = _pool(ttl=300.0, multiplier=3.0, alert_min=1)
    s = _get(pool, "tok-a")
    pool.release(s)
    with patch("services.alert_service.send_alert") as mock_send, \
         patch("services.event_bus.event_bus.publish") as mock_publish:
        pool.check_leaks()
    assert not mock_send.called
    assert not mock_publish.called


def test_check_leaks_alert_uses_dedupe_payload_fields():
    """告警载荷包含指纹可去重字段（trigger 等），复用现有多通道去重。"""
    pool = _pool(ttl=0.05, multiplier=3.0, alert_min=1)
    s = _get(pool, "tok-a")
    pool.release(s)
    time.sleep(0.2)
    with patch("services.alert_service.send_alert") as mock_send:
        pool.check_leaks()
    payload = mock_send.call_args[0][1]
    assert "trigger" in payload
    assert "leak_count" in payload
    assert "idle_stale_count" in payload
    assert "borrowed_stale_count" in payload
    assert "pool_size" in payload
    assert "leak_threshold_seconds" in payload


def test_check_leaks_event_duplicate_alert_deduplicated_by_service():
    """连续两次 check_leaks：告警载荷一致（去重由 alert_service 内部去重窗口保证，不刷屏）。"""
    pool = _pool(ttl=0.05, multiplier=3.0, alert_min=1)
    s = _get(pool, "tok-a")
    pool.release(s)
    time.sleep(0.2)
    with patch("services.alert_service.send_alert") as mock_send:
        pool.check_leaks()
        pool.check_leaks()
    assert mock_send.call_count == 2  # session_pool 每次检测都通知，去重由 alert_service 窗口承担


# ── 健康检查清理（cleanup_stale） ──────────────────────────────────


def test_cleanup_stale_removes_dead_connections():
    """健康检查失败的空闲连接被主动清理。"""
    pool = _pool(ttl=0.05, multiplier=3.0)
    s = _get(pool, "tok-a")
    pool.release(s)
    time.sleep(0.2)
    with patch("services.session_pool.SessionPool._health_check", return_value=False):
        removed = pool.cleanup_stale()
    assert removed == 1
    assert pool.stats()["pooled_sessions"] == 0


def test_cleanup_stale_keeps_healthy_connections():
    """健康检查通过的空闲连接保留（由下一次 get 的 TTL 自然重建）。"""
    pool = _pool(ttl=0.05, multiplier=3.0)
    s = _get(pool, "tok-a")
    pool.release(s)
    time.sleep(0.2)
    with patch("services.session_pool.SessionPool._health_check", return_value=True):
        removed = pool.cleanup_stale()
    assert removed == 0
    assert pool.stats()["pooled_sessions"] == 1


def test_cleanup_stale_does_not_remove_borrowed():
    """借用中的连接（在用）不被 cleanup 误清理。"""
    pool = _pool(ttl=0.05, multiplier=3.0)
    _get(pool, "tok-a")  # 借用中，不归还
    time.sleep(0.2)
    with patch("services.session_pool.SessionPool._health_check", return_value=False):
        removed = pool.cleanup_stale()
    assert removed == 0
    assert pool.stats()["in_use"] == 1


# ── 事件总线接入 ───────────────────────────────────────────────────


def test_session_pool_leak_event_registered():
    """SESSION_POOL_LEAK 已进 ALL_EVENTS + event_bus_init 告警映射。"""
    from services.event_bus import ALL_EVENTS, SESSION_POOL_LEAK
    from services.event_bus_init import _ALERT_EVENT_MAP

    assert SESSION_POOL_LEAK in ALL_EVENTS
    assert _ALERT_EVENT_MAP[SESSION_POOL_LEAK] == "session_pool_leak"


def test_check_session_pool_leaks_global_entry():
    """模块级便捷入口作用于全局 session_pool，返回报告字典。"""
    from services.session_pool import check_session_pool_leaks

    report = check_session_pool_leaks()
    assert "leak_count" in report
    assert "removed_count" in report


# ── metrics_service 导出 ───────────────────────────────────────────


def test_metrics_prometheus_exports_session_pool_gauge():
    """metrics_service.prometheus() 导出连接池 gauge（空闲/在用/复用率/泄漏）。"""
    from services.metrics_service import metrics_service

    text = metrics_service.prometheus()
    assert "chatgpt2api_session_pool_pooled" in text
    assert "chatgpt2api_session_pool_idle" in text
    assert "chatgpt2api_session_pool_in_use" in text
    assert "chatgpt2api_session_pool_hit_rate" in text
    assert "chatgpt2api_session_pool_configured_total" in text
    assert "chatgpt2api_session_pool_idle_stale" in text


def test_metrics_gauge_reflects_pool_state():
    """gauge 值随全局连接池状态变化（prometheus() 读取全局 session_pool）。"""
    from services.metrics_service import metrics_service
    from services.session_pool import session_pool

    session_pool.close_all()  # 清空避免遗留状态
    with patch("services.session_pool.proxy_settings") as ps:
        ps.get_profile.return_value = type("P", (), {"proxy_url": ""})()
        ps.build_session_kwargs.return_value = {}
        session_pool.get(account={"access_token": "tok-metrics"}, fp_key="f")
    text = metrics_service.prometheus()
    try:
        assert "chatgpt2api_session_pool_in_use 1" in text
        assert "chatgpt2api_session_pool_pooled 1" in text
    finally:
        session_pool.close_all()
