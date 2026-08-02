from __future__ import annotations

import copy
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from services.storage.base import StorageBackend

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = BASE_DIR / "config.json"
VERSION_FILE = BASE_DIR / "VERSION"
BACKUP_STATE_FILE = DATA_DIR / "backup_state.json"

DEFAULT_BACKUP_INCLUDE = {
    "config": True,
    "cpa": True,
    "sub2api": True,
    "logs": True,
    "image_tasks": True,
    "accounts_snapshot": True,
    "auth_keys_snapshot": True,
    "images": False,
}

DEFAULT_IMAGE_STORAGE = {
    "enabled": False,
    "mode": "local",
    "webdav_url": "",
    "webdav_username": "",
    "webdav_password": "",
    "webdav_root_path": "chatgpt2api/images",
    "public_base_url": "",
}

DEFAULT_CHAT_COMPLETION_CACHE = {
    "enabled": True,
    "ttl_seconds": 60,
    "max_entries": 256,
    "dedupe_inflight": True,
    "stream_cache": True,
    "normalize_messages": True,
    "drop_adjacent_duplicates": True,
    "drop_assistant_history": False,
}

DEFAULT_PROXY_RUNTIME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

DEFAULT_PROXY_RUNTIME = {
    "enabled": False,
    "egress_mode": "direct",
    "proxy_url": "",
    "resource_proxy_url": "",
    "skip_ssl_verify": False,
    "reset_session_status_codes": [403],
    "clearance": {
        "enabled": False,
        "mode": "none",
        "cf_cookies": "",
        "cf_clearance": "",
        "user_agent": DEFAULT_PROXY_RUNTIME_USER_AGENT,
        "browser": "chrome",
        "flaresolverr_url": "",
        "timeout_sec": 60,
        "refresh_interval": 3600,
        "warm_up_on_start": False,
    },
}

DEFAULT_THIRD_PARTY_APPS = {
    "infinite_canvas": {
        "enabled": False,
        "url": "https://canvas.best",
    },
}


def _normalize_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    if value is None:
        return default
    return bool(value)


def _normalize_positive_int(value: object, default: int, minimum: int = 0) -> int:
    try:
        normalized = int(value)
    except (OverflowError, TypeError, ValueError):
        normalized = default
    return max(minimum, normalized)


def _normalize_backup_include(value: object) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    normalized = dict(DEFAULT_BACKUP_INCLUDE)
    for key in normalized:
        normalized[key] = _normalize_bool(source.get(key), normalized[key])
    return normalized


def _normalize_backup_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "enabled": _normalize_bool(source.get("enabled"), False),
        "provider": "cloudflare_r2",
        "account_id": str(source.get("account_id") or "").strip(),
        "access_key_id": str(source.get("access_key_id") or "").strip(),
        "secret_access_key": str(source.get("secret_access_key") or "").strip(),
        "bucket": str(source.get("bucket") or "").strip(),
        "prefix": str(source.get("prefix") or "backups").strip().strip("/") or "backups",
        "interval_minutes": _normalize_positive_int(source.get("interval_minutes"), 360, 1),
        "rotation_keep": _normalize_positive_int(source.get("rotation_keep"), 10, 0),
        "encrypt": _normalize_bool(source.get("encrypt"), False),
        "passphrase": str(source.get("passphrase") or "").strip(),
        "include": _normalize_backup_include(source.get("include")),
    }


def _normalize_backup_state(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "last_started_at": str(source.get("last_started_at") or "").strip() or None,
        "last_finished_at": str(source.get("last_finished_at") or "").strip() or None,
        "last_status": str(source.get("last_status") or "idle").strip() or "idle",
        "last_error": str(source.get("last_error") or "").strip() or None,
        "last_object_key": str(source.get("last_object_key") or "").strip() or None,
    }


def _normalize_image_storage_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    mode = str(source.get("mode") or "local").strip().lower()
    if mode not in {"local", "webdav", "both"}:
        mode = "local"
    enabled = _normalize_bool(source.get("enabled"), False)
    if not enabled:
        mode = "local"
    root_path = str(source.get("webdav_root_path") or DEFAULT_IMAGE_STORAGE["webdav_root_path"]).strip().strip("/")
    return {
        "enabled": enabled,
        "mode": mode,
        "webdav_url": str(source.get("webdav_url") or "").strip().rstrip("/"),
        "webdav_username": str(source.get("webdav_username") or "").strip(),
        "webdav_password": str(source.get("webdav_password") or "").strip(),
        "webdav_root_path": root_path or str(DEFAULT_IMAGE_STORAGE["webdav_root_path"]),
        "public_base_url": str(source.get("public_base_url") or "").strip().rstrip("/"),
    }


def _normalize_chat_completion_cache_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "enabled": _normalize_bool(source.get("enabled"), DEFAULT_CHAT_COMPLETION_CACHE["enabled"]),
        "ttl_seconds": _normalize_positive_int(
            source.get("ttl_seconds"),
            int(DEFAULT_CHAT_COMPLETION_CACHE["ttl_seconds"]),
            0,
        ),
        "max_entries": _normalize_positive_int(
            source.get("max_entries"),
            int(DEFAULT_CHAT_COMPLETION_CACHE["max_entries"]),
            1,
        ),
        "dedupe_inflight": _normalize_bool(
            source.get("dedupe_inflight"),
            bool(DEFAULT_CHAT_COMPLETION_CACHE["dedupe_inflight"]),
        ),
        "stream_cache": _normalize_bool(
            source.get("stream_cache"),
            bool(DEFAULT_CHAT_COMPLETION_CACHE["stream_cache"]),
        ),
        "normalize_messages": _normalize_bool(
            source.get("normalize_messages"),
            bool(DEFAULT_CHAT_COMPLETION_CACHE["normalize_messages"]),
        ),
        "drop_adjacent_duplicates": _normalize_bool(
            source.get("drop_adjacent_duplicates"),
            bool(DEFAULT_CHAT_COMPLETION_CACHE["drop_adjacent_duplicates"]),
        ),
        "drop_assistant_history": _normalize_bool(
            source.get("drop_assistant_history"),
            bool(DEFAULT_CHAT_COMPLETION_CACHE["drop_assistant_history"]),
        ),
    }


def _normalize_status_codes(value: object) -> list[int]:
    items = value if isinstance(value, list) else DEFAULT_PROXY_RUNTIME["reset_session_status_codes"]
    normalized: list[int] = []
    for item in items:
        if isinstance(item, bool):
            continue
        try:
            status = int(item)
        except (OverflowError, TypeError, ValueError):
            continue
        if 100 <= status <= 599 and status not in normalized:
            normalized.append(status)
    if not normalized:
        return list(DEFAULT_PROXY_RUNTIME["reset_session_status_codes"])
    return normalized


def _normalize_proxy_runtime_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    default_clearance = DEFAULT_PROXY_RUNTIME["clearance"]
    clearance_source = source.get("clearance") if isinstance(source.get("clearance"), dict) else {}

    egress_mode = str(source.get("egress_mode") or DEFAULT_PROXY_RUNTIME["egress_mode"]).strip().lower()
    if egress_mode not in {"direct", "single_proxy"}:
        egress_mode = str(DEFAULT_PROXY_RUNTIME["egress_mode"])

    clearance_mode = str(clearance_source.get("mode") or default_clearance["mode"]).strip().lower()
    if clearance_mode not in {"none", "manual", "flaresolverr"}:
        clearance_mode = str(default_clearance["mode"])

    user_agent = str(clearance_source.get("user_agent") or default_clearance["user_agent"]).strip()
    browser = str(clearance_source.get("browser") or default_clearance["browser"]).strip()

    existing_clearance_cookies = str(source.get("_existing_cf_cookies") or "").strip()
    existing_cf_clearance = str(source.get("_existing_cf_clearance") or "").strip()
    cf_cookies = str(clearance_source.get("cf_cookies") or "").strip()
    cf_clearance = str(clearance_source.get("cf_clearance") or "").strip()
    if not cf_cookies and _normalize_bool(clearance_source.get("has_cf_cookies"), False):
        cf_cookies = existing_clearance_cookies
    if not cf_clearance and _normalize_bool(clearance_source.get("has_cf_clearance"), False):
        cf_clearance = existing_cf_clearance

    return {
        "enabled": _normalize_bool(source.get("enabled"), bool(DEFAULT_PROXY_RUNTIME["enabled"])),
        "egress_mode": egress_mode,
        "proxy_url": str(source.get("proxy_url") or "").strip(),
        "resource_proxy_url": str(source.get("resource_proxy_url") or "").strip(),
        "skip_ssl_verify": _normalize_bool(
            source.get("skip_ssl_verify"),
            bool(DEFAULT_PROXY_RUNTIME["skip_ssl_verify"]),
        ),
        "reset_session_status_codes": _normalize_status_codes(source.get("reset_session_status_codes")),
        "clearance": {
            "enabled": _normalize_bool(clearance_source.get("enabled"), bool(default_clearance["enabled"])),
            "mode": clearance_mode,
            "cf_cookies": cf_cookies,
            "cf_clearance": cf_clearance,
            "user_agent": user_agent or str(default_clearance["user_agent"]),
            "browser": browser or str(default_clearance["browser"]),
            "flaresolverr_url": str(clearance_source.get("flaresolverr_url") or "").strip(),
            "timeout_sec": _normalize_positive_int(
                clearance_source.get("timeout_sec"),
                int(default_clearance["timeout_sec"]),
                1,
            ),
            "refresh_interval": _normalize_positive_int(
                clearance_source.get("refresh_interval"),
                int(default_clearance["refresh_interval"]),
                60,
            ),
            "warm_up_on_start": _normalize_bool(
                clearance_source.get("warm_up_on_start"),
                bool(default_clearance["warm_up_on_start"]),
            ),
        },
    }


def _normalize_third_party_apps_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    canvas_source = source.get("infinite_canvas") if isinstance(source.get("infinite_canvas"), dict) else {}
    return {
        "infinite_canvas": {
            "enabled": _normalize_bool(canvas_source.get("enabled"), False),
            "url": str(canvas_source.get("url") or DEFAULT_THIRD_PARTY_APPS["infinite_canvas"]["url"]).strip(),
        },
    }


def _validate_image_storage_settings(settings: dict[str, object]) -> None:
    if not _normalize_bool(settings.get("enabled"), False):
        return
    if not str(settings.get("webdav_url") or "").strip():
        raise ValueError("启用 WebDAV 图片存储后必须填写 WebDAV URL")
    if not str(settings.get("webdav_password") or "").strip():
        raise ValueError("启用 WebDAV 图片存储后必须填写 WebDAV 密码")


@dataclass(frozen=True)
class LoadedSettings:
    auth_key: str
    refresh_account_interval_minute: int


def _normalize_auth_key(value: object) -> str:
    return str(value or "").strip()


def _is_invalid_auth_key(value: object) -> bool:
    return _normalize_auth_key(value) == ""


_WEAK_AUTH_KEYS = {"chatgpt2api", "admin", "password", "123456", "test", "changeme", "sk-xxx"}


def _is_weak_auth_key(value: object) -> bool:
    """检测常见弱口令或过短的 auth-key。"""
    v = _normalize_auth_key(value).lower()
    return v in _WEAK_AUTH_KEYS or len(v) < 12


def _warn_if_weak_auth_key(auth_key: str, env: str) -> None:
    """弱口令告警；生产环境直接拒绝启动。"""
    if not _is_weak_auth_key(auth_key):
        return
    msg = (
        "❌ auth-key 为常见弱口令或过短（<12 位），存在被打满/白嫖风险！\n"
        "   请在 CHATGPT2API_AUTH_KEY 或 config.json 的 auth-key 设置强随机值（建议 ≥24 位）。"
    )
    if env == "production":
        raise ValueError("❌ 生产环境拒绝使用弱 auth-key 启动！\n" + msg)
    print(f"⚠️  WARNING: {msg}", file=sys.stderr)


def _read_json_object(path: Path, *, name: str) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.is_dir():
        print(
            f"Warning: {name} at '{path}' is a directory, ignoring it and falling back to other configuration sources.",
            file=sys.stderr,
        )
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"❌ {name} JSON 格式错误：{path}\n"
            f"   第 {exc.lineno} 行第 {exc.colno} 列: {exc.msg}\n"
            f"   请检查 JSON 语法（多余逗号、缺少引号、括号不配对等）"
        ) from exc
    except Exception as exc:
        raise ValueError(f"❌ {name} 读取失败：{path} - {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"❌ {name} 必须是 JSON 对象（顶层 {{}}），当前为 {type(data).__name__}")
    return data


def _load_settings() -> LoadedSettings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_config = _read_json_object(CONFIG_FILE, name="config.json")
    auth_key = _normalize_auth_key(os.getenv("CHATGPT2API_AUTH_KEY") or raw_config.get("auth-key"))
    if _is_invalid_auth_key(auth_key):
        raise ValueError(
            "❌ auth-key 未设置！\n"
            "请在环境变量 CHATGPT2API_AUTH_KEY 中设置，或者在 config.json 中填写 auth-key。"
        )
    env = str(os.getenv("CHATGPT2API_ENV") or raw_config.get("env") or "development").strip().lower()
    _warn_if_weak_auth_key(auth_key, env)

    try:
        refresh_interval = int(raw_config.get("refresh_account_interval_minute", 5))
    except (TypeError, ValueError):
        refresh_interval = 5

    return LoadedSettings(
        auth_key=auth_key,
        refresh_account_interval_minute=refresh_interval,
    )


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self._storage_backend: StorageBackend | None = None
        if _is_invalid_auth_key(self.auth_key):
            raise ValueError(
                "❌ auth-key 未设置！\n"
                "请按以下任意一种方式解决：\n"
                "1. 在 Render 的 Environment 变量中添加：\n"
                "   CHATGPT2API_AUTH_KEY = your_real_auth_key\n"
                "2. 或者在 config.json 中填写：\n"
                '   "auth-key": "your_real_auth_key"'
            )

    def _load(self) -> dict[str, object]:
        data = _read_json_object(self.path, name="config.json")
        self._validate_schema(data)
        return data

    @staticmethod
    def _validate_schema(data: dict[str, object]) -> None:
        """启动时校验关键配置项类型，改配置易出错时给出清晰报错。"""
        errors: list[str] = []
        # scheduler_mode 枚举
        mode = data.get("scheduler_mode")
        if mode is not None and mode not in ("round_robin", "remaining_quota"):
            errors.append(f"scheduler_mode 必须是 round_robin 或 remaining_quota，当前为 {mode!r}")
        # 数值型配置
        int_fields = ["workers", "rate_limit_rpm", "rate_limit_per_ip_rpm", "refresh_account_interval_minute", "image_retention_days", "image_account_concurrency", "sqlite_busy_timeout_ms", "progress_ttl_seconds", "alert_webhook_timeout"]
        for field in int_fields:
            value = data.get(field)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"{field} 必须是整数，当前为 {value!r} ({type(value).__name__})")
            elif value < 0:
                errors.append(f"{field} 不能为负数，当前为 {value}")
        # trusted_proxies 类型校验（list[str] 或逗号分隔 str）
        tp = data.get("trusted_proxies")
        if tp is not None and not isinstance(tp, (list, str)):
            errors.append(f"trusted_proxies 必须是数组或逗号分隔字符串，当前为 {tp!r} ({type(tp).__name__})")
        # sqlite_wal_mode / ssrf_allow_private_ips 布尔校验
        for field in ("sqlite_wal_mode", "ssrf_allow_private_ips"):
            bval = data.get(field)
            if bval is not None and not isinstance(bval, bool):
                errors.append(f"{field} 必须是布尔值，当前为 {bval!r} ({type(bval).__name__})")
        # scheduler_priority 必须为 dict[str, int]
        sp = data.get("scheduler_priority")
        if sp is not None and not isinstance(sp, dict):
            errors.append(f"scheduler_priority 必须是对象 {{}}，当前为 {type(sp).__name__}")
        if errors:
            raise ValueError("❌ config.json 配置校验失败：\n" + "\n".join(f"   - {e}" for e in errors))

    def _save(self) -> None:
        # 原子写（第七轮 B9）：复用 json_storage 的 _atomic_write_text，
        # 防写入中途断电/杀进程导致 config.json 截断损坏
        from services.storage.json_storage import _atomic_write_text
        _atomic_write_text(self.path, json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")

    @property
    def auth_key(self) -> str:
        return _normalize_auth_key(os.getenv("CHATGPT2API_AUTH_KEY") or self.data.get("auth-key"))

    @property
    def accounts_file(self) -> Path:
        return DATA_DIR / "accounts.json"

    @property
    def refresh_account_interval_minute(self) -> int:
        try:
            return int(self.data.get("refresh_account_interval_minute", 5))
        except (TypeError, ValueError):
            return 5

    @property
    def image_retention_days(self) -> int:
        try:
            return max(1, int(self.data.get("image_retention_days", 30)))
        except (TypeError, ValueError):
            return 30

    @property
    def image_poll_timeout_secs(self) -> int:
        try:
            return max(1, int(self.data.get("image_poll_timeout_secs", 120)))
        except (TypeError, ValueError):
            return 120

    @property
    def image_poll_interval_secs(self) -> float:
        try:
            return max(0.5, float(self.data.get("image_poll_interval_secs", 10.0)))
        except (TypeError, ValueError):
            return 10.0

    @property
    def image_poll_initial_wait_secs(self) -> float:
        """Image generation upstream takes ~30s; polling immediately wastes requests
        and trips a transient 429. Default 10s gives the conversation document time
        to commit before the first poll."""
        try:
            return max(0.0, float(self.data.get("image_poll_initial_wait_secs", 10.0)))
        except (TypeError, ValueError):
            return 10.0

    @property
    def image_account_concurrency(self) -> int:
        try:
            return max(1, int(self.data.get("image_account_concurrency", 3)))
        except (TypeError, ValueError):
            return 3

    @property
    def image_parallel_generation(self) -> bool:
        value = self.data.get("image_parallel_generation", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def scheduler_mode(self) -> str:
        value = str(
            os.getenv("CHATGPT2API_SCHEDULER_MODE")
            or self.data.get("scheduler_mode")
            or "round_robin"
        ).strip().lower()
        return value if value in {"round_robin", "remaining_quota"} else "round_robin"

    @property
    def rate_limit_rpm(self) -> int:
        """全局每分钟请求数上限（0 = 不限，默认 0）。"""
        try:
            return max(0, int(
                os.getenv("CHATGPT2API_RATE_LIMIT_RPM")
                or self.data.get("rate_limit_rpm", 0)
            ))
        except (TypeError, ValueError):
            return 0

    @property
    def workers(self) -> int:
        """uvicorn worker 进程数（高并发时调大，多核利用）。

        注意：当 workers > 1 且存储后端为 JSON 时，各进程持有独立账号副本，
        会导致账号重复分配/数据丢失。请使用 SQLite 或 Postgres 存储后端。
        """
        try:
            return max(1, int(
                os.getenv("CHATGPT2API_WORKERS")
                or self.data.get("workers", 1)
            ))
        except (TypeError, ValueError):
            return 1

    @property
    def env(self) -> str:
        """运行环境（development/production），用于生产安全检查。"""
        return str(os.getenv("CHATGPT2API_ENV") or self.data.get("env") or "development").strip().lower()

    @property
    def cors_origins(self) -> list[str]:
        """CORS 允许来源。默认 ["*"]（保持向后兼容），生产环境应显式配置收紧。"""
        raw = os.getenv("CHATGPT2API_CORS_ORIGINS") or self.data.get("cors_origins") or "*"
        if isinstance(raw, str):
            return [o.strip() for o in raw.split(",") if o.strip()]
        if isinstance(raw, list):
            return [str(o).strip() for o in raw if str(o).strip()]
        return ["*"]

    @property
    def max_request_body_mb_chat(self) -> int:
        """chat/responses 类请求体上限（MB），超限返回 413。"""
        try:
            return max(1, int(
                os.getenv("CHATGPT2API_MAX_REQUEST_BODY_MB_CHAT")
                or self.data.get("max_request_body_mb_chat", 10)
            ))
        except (TypeError, ValueError):
            return 10

    @property
    def max_request_body_mb_image(self) -> int:
        """图片编辑类请求体上限（MB，base64 图占体积），超限返回 413。"""
        try:
            return max(1, int(
                os.getenv("CHATGPT2API_MAX_REQUEST_BODY_MB_IMAGE")
                or self.data.get("max_request_body_mb_image", 50)
            ))
        except (TypeError, ValueError):
            return 50

    @property
    def storage_backend_type(self) -> str:
        return str(os.getenv("STORAGE_BACKEND") or self.data.get("storage_backend") or "json").strip().lower()

    @property
    def sqlite_wal_mode(self) -> bool:
        """SQLite WAL 日志模式（多 worker 并发写安全，默认开启）。"""
        value = os.getenv("CHATGPT2API_SQLITE_WAL_MODE")
        if value is not None:
            return _normalize_bool(value, True)
        return _normalize_bool(self.data.get("sqlite_wal_mode"), True)

    @property
    def sqlite_busy_timeout_ms(self) -> int:
        """SQLite 写锁冲突时的等待毫秒数（默认 5000，0 = 立即报错）。"""
        try:
            return max(0, int(
                os.getenv("CHATGPT2API_SQLITE_BUSY_TIMEOUT_MS")
                or self.data.get("sqlite_busy_timeout_ms", 5000)
            ))
        except (TypeError, ValueError):
            return 5000

    @property
    def trusted_proxies(self) -> list[str]:
        """可信反向代理 IP 白名单（默认仅回环）；仅这些来源的 XFF 头被信任。"""
        raw = os.getenv("CHATGPT2API_TRUSTED_PROXIES")
        if raw is not None:
            return [ip.strip() for ip in str(raw).split(",") if ip.strip()]
        value = self.data.get("trusted_proxies")
        if isinstance(value, list):
            return [str(ip).strip() for ip in value if str(ip).strip()]
        if isinstance(value, str):
            return [ip.strip() for ip in value.split(",") if ip.strip()]
        return ["127.0.0.1", "::1"]

    @property
    def ssrf_allow_private_ips(self) -> bool:
        """SSRF 防护回退：true 时允许抓取内网图片（用户内网图床场景，默认 false 拒绝）。"""
        value = os.getenv("CHATGPT2API_SSRF_ALLOW_PRIVATE_IPS")
        if value is not None:
            return _normalize_bool(value, False)
        return _normalize_bool(self.data.get("ssrf_allow_private_ips"), False)

    @property
    def alert_webhook_url(self) -> str:
        """告警 webhook URL（默认空 = 关闭）。"""
        return str(os.getenv("CHATGPT2API_ALERT_WEBHOOK_URL") or self.data.get("alert_webhook_url") or "").strip()

    @property
    def alert_webhook_timeout(self) -> int:
        """告警 webhook 超时秒数（默认 10）。"""
        try:
            return max(1, int(os.getenv("CHATGPT2API_ALERT_WEBHOOK_TIMEOUT") or self.data.get("alert_webhook_timeout", 10)))
        except (TypeError, ValueError):
            return 10

    @property
    def alert_events(self) -> list[str]:
        """启用的告警事件列表。"""
        default = ["circuit_breaker_open", "backup_failure", "account_invalid", "quota_exhausted"]
        raw = os.getenv("CHATGPT2API_ALERT_EVENTS")
        if raw is not None:
            return [e.strip() for e in str(raw).split(",") if e.strip()]
        value = self.data.get("alert_events")
        if isinstance(value, list):
            return [str(e).strip() for e in value if str(e).strip()]
        return default

    @property
    def progress_ttl_seconds(self) -> int:
        """进度记录（刷新/重登）在内存中的存活秒数（默认 3600，配置层最小 1s；亚秒级仅供测试经构造参数传入）。"""
        try:
            return max(1, int(
                os.getenv("CHATGPT2API_PROGRESS_TTL_SECONDS")
                or self.data.get("progress_ttl_seconds", 3600)
            ))
        except (TypeError, ValueError):
            return 3600

    @property
    def rate_limit_per_ip_rpm(self) -> int:
        """单 IP 每分钟请求数上限（0 = 不限，默认 0）。"""
        try:
            return max(0, int(
                os.getenv("CHATGPT2API_RATE_LIMIT_PER_IP_RPM")
                or self.data.get("rate_limit_per_ip_rpm", 0)
            ))
        except (TypeError, ValueError):
            return 0

    @property
    def scheduler_priority(self) -> dict[str, int]:
        raw = self.data.get("scheduler_priority")
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): max(-100, min(100, int(value)))
            for key, value in raw.items()
            if str(value or "").lstrip("-").isdigit()
        }

    @property
    def image_settle_enabled(self) -> bool:
        """图片二次确认机制：找到 file_ids 后等待一段时间再次确认。"""
        value = self.data.get("image_settle_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def image_check_before_hit_enabled(self) -> bool:
        """先check再hit：通过轮询确认 file_ids 存在后再返回，而非仅依赖 SSE 事件。"""
        value = self.data.get("image_check_before_hit_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def image_remove_conversation_after_result(self) -> bool:
        """出图成功后异步隐藏 ChatGPT 本地对话记录。"""
        value = self.data.get("image_remove_conversation_after_result", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def image_remove_conversation_always(self) -> bool:
        """无论是否出图，画图请求结束后都异步隐藏 ChatGPT 本地对话记录。"""
        return _normalize_bool(self.data.get("image_remove_conversation_always"), False)

    @property
    def image_settle_secs(self) -> float:
        """二次确认等待时间（秒）。"""
        try:
            return max(0.5, float(self.data.get("image_settle_secs", 2.0)))
        except (TypeError, ValueError):
            return 2.0

    @property
    def auto_remove_invalid_accounts(self) -> bool:
        value = self.data.get("auto_remove_invalid_accounts", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def auto_remove_rate_limited_accounts(self) -> bool:
        value = self.data.get("auto_remove_rate_limited_accounts", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def auto_relogin_after_refresh(self) -> bool:
        value = self.data.get("auto_relogin_after_refresh", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def log_levels(self) -> list[str]:
        levels = self.data.get("log_levels")
        if not isinstance(levels, list):
            return []
        allowed = {"debug", "info", "warning", "error"}
        return [level for item in levels if (level := str(item or "").strip().lower()) in allowed]

    @property
    def sensitive_words(self) -> list[str]:
        words = self.data.get("sensitive_words")
        return [word for item in words if (word := str(item or "").strip())] if isinstance(words, list) else []

    @property
    def ai_review(self) -> dict[str, object]:
        value = self.data.get("ai_review")
        return value if isinstance(value, dict) else {}

    @property
    def global_system_prompt(self) -> str:
        return str(self.data.get("global_system_prompt") or "").strip()

    @property
    def default_upstream_model_name(self) -> str:
        return str(self.data.get("default_upstream_model_name") or "gpt-5-5").strip()

    @property
    def default_thinking_effort(self) -> str:
        value = str(self.data.get("default_thinking_effort") or "auto").strip().lower()
        return value if value in {"auto", "standard", "extended", "max"} else "auto"

    @property
    def images_dir(self) -> Path:
        path = DATA_DIR / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def image_thumbnails_dir(self) -> Path:
        path = DATA_DIR / "image_thumbnails"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup_old_images(self) -> int:
        cutoff = time.time() - self.image_retention_days * 86400
        removed = 0
        for path in self.images_dir.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        for path in sorted((p for p in self.images_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass
        return removed

    @property
    def base_url(self) -> str:
        return str(
            os.getenv("CHATGPT2API_BASE_URL")
            or self.data.get("base_url")
            or ""
        ).strip().rstrip("/")

    @property
    def app_version(self) -> str:
        try:
            value = VERSION_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return "0.0.0"
        return value or "0.0.0"

    def get(self) -> dict[str, object]:
        data = dict(self.data)
        data["refresh_account_interval_minute"] = self.refresh_account_interval_minute
        data["image_retention_days"] = self.image_retention_days
        data["image_poll_timeout_secs"] = self.image_poll_timeout_secs
        data["image_poll_interval_secs"] = self.image_poll_interval_secs
        data["image_poll_initial_wait_secs"] = self.image_poll_initial_wait_secs
        data["image_account_concurrency"] = self.image_account_concurrency
        data["image_parallel_generation"] = self.image_parallel_generation
        data["scheduler_mode"] = self.scheduler_mode
        data["scheduler_priority"] = self.scheduler_priority
        data["rate_limit_rpm"] = self.rate_limit_rpm
        data["rate_limit_per_ip_rpm"] = self.rate_limit_per_ip_rpm
        data["workers"] = self.workers
        data["sqlite_wal_mode"] = self.sqlite_wal_mode
        data["sqlite_busy_timeout_ms"] = self.sqlite_busy_timeout_ms
        data["progress_ttl_seconds"] = self.progress_ttl_seconds
        data["ssrf_allow_private_ips"] = self.ssrf_allow_private_ips
        data["trusted_proxies"] = self.trusted_proxies
        data["alert_webhook_url"] = self.alert_webhook_url
        data["alert_webhook_timeout"] = self.alert_webhook_timeout
        data["alert_events"] = self.alert_events
        data["image_remove_conversation_after_result"] = self.image_remove_conversation_after_result
        data["image_remove_conversation_always"] = self.image_remove_conversation_always
        data["auto_remove_invalid_accounts"] = self.auto_remove_invalid_accounts
        data["auto_remove_rate_limited_accounts"] = self.auto_remove_rate_limited_accounts
        data["auto_relogin_after_refresh"] = self.auto_relogin_after_refresh
        data["log_levels"] = self.log_levels
        data["sensitive_words"] = self.sensitive_words
        data["ai_review"] = self.ai_review
        data["global_system_prompt"] = self.global_system_prompt
        data["default_upstream_model_name"] = self.default_upstream_model_name
        data["default_thinking_effort"] = self.default_thinking_effort
        data["backup"] = self.get_backup_settings()
        data["image_storage"] = self.get_image_storage_settings()
        data["chat_completion_cache"] = self.get_chat_completion_cache_settings()
        data["proxy_runtime"] = self.get_public_proxy_runtime_settings()
        data["third_party_apps"] = self.get_third_party_apps_settings()
        data.pop("auth-key", None)
        return data

    def get_proxy_settings(self) -> str:
        return str(self.data.get("proxy") or "").strip()

    def get_proxy_runtime_settings(self) -> dict[str, object]:
        return _normalize_proxy_runtime_settings(self.data.get("proxy_runtime"))

    def get_public_proxy_runtime_settings(self) -> dict[str, object]:
        runtime = copy.deepcopy(self.get_proxy_runtime_settings())
        clearance = runtime.get("clearance") if isinstance(runtime.get("clearance"), dict) else {}
        if isinstance(clearance, dict):
            cf_cookies = str(clearance.get("cf_cookies") or "").strip()
            cf_clearance = str(clearance.get("cf_clearance") or "").strip()
            clearance["cf_cookies"] = ""
            clearance["cf_clearance"] = ""
            clearance["has_cf_cookies"] = bool(cf_cookies)
            clearance["has_cf_clearance"] = bool(cf_clearance)
        return runtime

    def get_third_party_apps_settings(self) -> dict[str, object]:
        return _normalize_third_party_apps_settings(self.data.get("third_party_apps"))

    def update(self, data: dict[str, object]) -> dict[str, object]:
        next_data = dict(self.data)
        next_data.update(dict(data or {}))
        if "backup" in next_data:
            next_data["backup"] = _normalize_backup_settings(next_data.get("backup"))
        if "image_storage" in next_data:
            next_data["image_storage"] = _normalize_image_storage_settings(next_data.get("image_storage"))
            _validate_image_storage_settings(next_data["image_storage"])
        if "chat_completion_cache" in next_data:
            next_data["chat_completion_cache"] = _normalize_chat_completion_cache_settings(
                next_data.get("chat_completion_cache")
            )
        if "third_party_apps" in next_data:
            next_data["third_party_apps"] = _normalize_third_party_apps_settings(next_data.get("third_party_apps"))
        if "proxy_runtime" in next_data:
            incoming_runtime = next_data.get("proxy_runtime")
            if isinstance(incoming_runtime, dict):
                previous_clearance = self.get_proxy_runtime_settings().get("clearance")
                if isinstance(previous_clearance, dict):
                    incoming_runtime = dict(incoming_runtime)
                    incoming_runtime["_existing_cf_cookies"] = previous_clearance.get("cf_cookies")
                    incoming_runtime["_existing_cf_clearance"] = previous_clearance.get("cf_clearance")
            next_data["proxy_runtime"] = _normalize_proxy_runtime_settings(incoming_runtime)
        next_data.pop("backup_state", None)
        self.data = next_data
        self._save()
        return self.get()

    def get_backup_settings(self) -> dict[str, object]:
        return _normalize_backup_settings(self.data.get("backup"))

    def get_image_storage_settings(self) -> dict[str, object]:
        return _normalize_image_storage_settings(self.data.get("image_storage"))

    def get_chat_completion_cache_settings(self) -> dict[str, object]:
        return _normalize_chat_completion_cache_settings(self.data.get("chat_completion_cache"))

    def get_storage_backend(self) -> StorageBackend:
        """获取存储后端实例（单例）"""
        if self._storage_backend is None:
            from services.storage.factory import create_storage_backend
            self._storage_backend = create_storage_backend(DATA_DIR)
        return self._storage_backend


def load_backup_state() -> dict[str, object]:
    return _normalize_backup_state(_read_json_object(BACKUP_STATE_FILE, name="backup_state.json"))


def save_backup_state(state: dict[str, object]) -> dict[str, object]:
    normalized = _normalize_backup_state(state)
    BACKUP_STATE_FILE.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


config = ConfigStore(CONFIG_FILE)
