from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

from fastapi import HTTPException, Request

from services.account_service import account_service
from services.auth_service import auth_service
from services.config import config
from utils.log import logger

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST_DIR = BASE_DIR / "web_dist"


def extract_bearer_token(authorization: str | None) -> str:
    scheme, _, value = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return ""
    return value.strip()


def _legacy_admin_identity(token: str) -> dict[str, object] | None:
    auth_key = str(config.auth_key or "").strip()
    if auth_key and token == auth_key:
        return {"id": "admin", "name": "管理员", "role": "admin"}
    return None


def require_identity(authorization: str | None) -> dict[str, object]:
    token = extract_bearer_token(authorization)
    identity = _legacy_admin_identity(token) or auth_service.authenticate(token)
    if identity is None:
        raise HTTPException(status_code=401, detail={"error": "密钥无效或已失效，请重新登录"})
    return identity


def _audit_admin_access(action: str, *, result: str, identity: dict[str, object] | None = None) -> None:
    """require_admin 审计埋点辅助（失败不阻断主流程）。"""
    try:
        from services.audit_service import record_admin_access

        record_admin_access(action=action, result=result, identity=identity)
    except Exception:  # noqa: BLE001 - 审计失败绝不阻断鉴权
        pass


def require_admin(authorization: str | None) -> dict[str, object]:
    """管理操作鉴权（3.2 起统一埋点审计：成功 + 失败都留痕）。

    降噪策略（防看板轮询刷爆审计）：
    - 失败（401/403）总是记录；
    - 成功仅记录「写操作」（POST/PUT/DELETE/PATCH）与非轮询 GET；
    - `/api/dashboard/*` 与 `/metrics` 的轮询 GET 成功跳过（SSE 每 3s 推送，
      全部记录会让审计文件失真）。
    """
    try:
        identity = require_identity(authorization)
    except HTTPException:
        try:
            from services.request_context import get_request_path
            action = get_request_path() or "/api"
        except Exception:  # noqa: BLE001
            action = "/api"
        _audit_admin_access(action, result="unauthorized", identity=None)
        raise
    if identity.get("role") != "admin":
        try:
            from services.request_context import get_request_path
            denied_path = get_request_path() or "/api"
        except Exception:  # noqa: BLE001
            denied_path = "/api"
        _audit_admin_access(denied_path, result="denied", identity=identity)
        raise HTTPException(status_code=403, detail={"error": "需要管理员权限才能执行这个操作"})
    # 成功埋点（降噪：轮询 GET 跳过）
    try:
        from services.request_context import get_request_method, get_request_path

        path = get_request_path()
        method = get_request_method().upper()
        is_write = method in {"POST", "PUT", "DELETE", "PATCH"}
        # 降噪：dashboard/metrics 是轮询热点（SSE 每 3s / 抓取周期），成功不记防刷爆审计。
        # 注意：/health 不经过 require_admin（公开端点），无需在此豁免。
        is_polling_get = method == "GET" and (
            path.startswith("/api/dashboard/") or path == "/metrics"
        )
        if is_write or (method == "GET" and not is_polling_get):
            _audit_admin_access(path or "/api", result="success", identity=identity)
    except Exception:  # noqa: BLE001 - 审计失败绝不阻断鉴权
        pass
    return identity


def resolve_image_base_url(request: Request) -> str:
    return config.base_url or f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"


# 图片错误的透传出口在 services/log_service.py:_image_error_response——
# LoggedCall.run 捕获异常后走那里构造 OpenAI 兼容 error body + debug 字段。
# 之前这里的 raise_image_quota_error 无调用方（死代码），已删除避免误导。


def sanitize_cpa_pool(pool: dict | None) -> dict | None:
    if not isinstance(pool, dict):
        return None
    return {key: value for key, value in pool.items() if key != "secret_key"}


def sanitize_cpa_pools(pools: list[dict]) -> list[dict]:
    return [sanitized for pool in pools if (sanitized := sanitize_cpa_pool(pool)) is not None]


def sanitize_sub2api_server(server: dict | None) -> dict | None:
    if not isinstance(server, dict):
        return None
    sanitized = {key: value for key, value in server.items() if key not in {"password", "api_key"}}
    sanitized["has_api_key"] = bool(str(server.get("api_key") or "").strip())
    return sanitized


def sanitize_sub2api_servers(servers: list[dict]) -> list[dict]:
    return [sanitized for server in servers if (sanitized := sanitize_sub2api_server(server)) is not None]


def start_limited_account_watcher(stop_event: Event) -> Thread:
    interval_seconds = config.refresh_account_interval_minute * 60
    # v2.9.0：异常账号自动恢复是 watcher 第二职责，独立更长间隔
    abnormal_recover_seconds = config.abnormal_auto_recover_interval_minutes * 60
    last_abnormal_recover_ts: float = 0.0

    def worker() -> None:
        nonlocal last_abnormal_recover_ts
        while not stop_event.is_set():
            try:
                limited_tokens = account_service.list_limited_tokens()
                # v2.9.0：限流账号若 quota=0 且 restore_at 在未来（未到期），跳过刷新避免浪费上游额度
                # 只刷限流但 quota>0（说明限流但还有额度，可能刚解限）或 restore_at 已过期的账号
                import time as _time_mod
                from datetime import datetime, UTC
                now_dt = datetime.now(UTC)
                skip_count = 0
                filtered_limited = []
                for token in limited_tokens:
                    acct = account_service.get_account(token)
                    if not acct:
                        continue
                    quota = int(acct.get("quota") or 0)
                    restore_at = str(acct.get("restore_at") or "").strip()
                    if quota == 0 and restore_at:
                        try:
                            from datetime import datetime as _dt
                            restore_ts = _dt.fromisoformat(restore_at.replace("Z", "+00:00")).timestamp()
                            if restore_ts > _time_mod.time():
                                skip_count += 1
                                continue
                        except Exception:
                            pass
                    filtered_limited.append(token)
                limited_tokens = filtered_limited
                if skip_count:
                    print(f"[account-watcher] skip {skip_count} limited accounts (quota=0, restore_at future)")
                normal_tokens = account_service.list_normal_tokens()
                expiring_tokens = account_service.list_expiring_access_tokens()
                keepalive_tokens = account_service.list_refresh_token_keepalive_tokens()
                tokens = list(dict.fromkeys([*limited_tokens, *normal_tokens, *expiring_tokens]))
                expiring_token_set = set(expiring_tokens)
                keepalive_tokens = [token for token in keepalive_tokens if token not in expiring_token_set]
                if tokens:
                    print(
                        "[account-watcher] checking "
                        f"{len(limited_tokens)} limited accounts, "
                        f"{len(normal_tokens)} normal accounts, "
                        f"{len(expiring_tokens)} expiring access tokens"
                    )
                    account_service.refresh_accounts(tokens)
                if keepalive_tokens:
                    print(f"[account-watcher] keepalive {len(keepalive_tokens)} refresh tokens")
                    result = account_service.keepalive_refresh_tokens(keepalive_tokens)
                    if result.get("errors"):
                        print(f"[account-watcher] keepalive errors: {result['errors']}")

                # v2.9.0：异常账号自动恢复（到间隔才跑，避免雪崩）
                import time as _time
                now_ts = _time.time()
                if (
                    config.abnormal_auto_recover_enabled
                    and now_ts - last_abnormal_recover_ts >= abnormal_recover_seconds
                ):
                    last_abnormal_recover_ts = now_ts
                    abnormal_tokens = account_service.list_abnormal_tokens_for_recover()
                    if abnormal_tokens:
                        print(
                            f"[account-watcher] auto-recover {len(abnormal_tokens)} abnormal accounts "
                            f"(max_workers={config.abnormal_auto_recover_max_workers})"
                        )
                        try:
                            recover_result = account_service.recover_abnormal_accounts(abnormal_tokens)
                            if recover_result.get("recovered") or recover_result.get("failed"):
                                print(
                                    f"[account-watcher] auto-recover done: "
                                    f"recovered={recover_result.get('recovered', 0)}, "
                                    f"failed={recover_result.get('failed', 0)}"
                                )
                        except Exception as recover_exc:  # noqa: BLE001
                            logger.warning(
                                {"event": "account_watcher_recover_failed", "error": str(recover_exc)}
                            )
            except Exception as exc:  # noqa: BLE001
                # S-R7：后台线程异常改走 logger（原 print 不进 server.log，bat 下无迹可寻）
                logger.warning({"event": "account_watcher_failed", "error": str(exc)})
            stop_event.wait(interval_seconds)

    thread = Thread(target=worker, name="account-watcher", daemon=True)
    thread.start()
    return thread


def start_proactive_probe(stop_event: Event) -> Thread | None:
    """F4/B6：低频主动探活线程（默认关）。

    周期性对全部账号 fetch_remote_info，把哑死账号（限流/失效）在调度前提前
    标记/剔除，避免首次真实请求才踩坑。复用 refresh_accounts 的远程探活能力。
    周期由 config.proactive_probe_interval_minute 控制（默认 30min，最小 5min）。
    """
    if not config.proactive_probe_enabled:
        return None
    interval_seconds = config.proactive_probe_interval_minute * 60

    def worker() -> None:
        while not stop_event.is_set():
            try:
                tokens = account_service.list_all_access_tokens()
                if tokens:
                    print(f"[proactive-probe] probing {len(tokens)} accounts")
                    account_service.refresh_accounts(tokens)
            except Exception as exc:  # noqa: BLE001 - 探活异常不阻塞主服务
                logger.warning({"event": "proactive_probe_failed", "error": str(exc)})
            # F1：探活后顺带做一次配额耗尽预测，临近耗尽发 webhook 告警（含去重）
            try:
                from services.usage_forecast import forecast_quota_depletion

                forecast = forecast_quota_depletion()
                if forecast.get("should_alert"):
                    from services.alert_service import send_alert

                    send_alert("quota_forecast_depletion", {
                        "days_until_depletion": forecast.get("days_until_depletion"),
                        "estimated_depletion_date": forecast.get("estimated_depletion_date") or "",
                        "total_remaining_quota": forecast.get("total_remaining_quota"),
                        "daily_avg_consumption": forecast.get("daily_avg_consumption"),
                    })
            except Exception as exc:  # noqa: BLE001 - 告警绝不阻塞探活
                logger.warning({"event": "proactive_probe_forecast_alert_failed", "error": str(exc)})
            stop_event.wait(interval_seconds)

    thread = Thread(target=worker, name="proactive-probe", daemon=True)
    thread.start()
    return thread


def resolve_web_asset(requested_path: str) -> Path | None:
    if not WEB_DIST_DIR.exists():
        return None
    clean_path = requested_path.strip("/")
    base_dir = WEB_DIST_DIR.resolve()
    candidates = [base_dir / "index.html"] if not clean_path else [
        base_dir / Path(clean_path),
        base_dir / clean_path / "index.html",
        base_dir / f"{clean_path}.html",
    ]
    for candidate in candidates:
        try:
            candidate.resolve().relative_to(base_dir)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None
