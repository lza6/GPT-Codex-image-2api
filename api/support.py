from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

from fastapi import HTTPException, Request

from services.account_service import account_service
from services.auth_service import auth_service
from services.config import config

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


def require_admin(authorization: str | None) -> dict[str, object]:
    identity = require_identity(authorization)
    if identity.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"error": "需要管理员权限才能执行这个操作"})
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

    def worker() -> None:
        while not stop_event.is_set():
            try:
                limited_tokens = account_service.list_limited_tokens()
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
            except Exception as exc:
                print(f"[account-watcher] fail {exc}")
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
                print(f"[proactive-probe] fail {exc}")
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
                print(f"[proactive-probe] forecast alert fail {exc}")
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
