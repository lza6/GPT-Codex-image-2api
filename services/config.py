from __future__ import annotations

import copy
import functools
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)  # type: ignore[misc]

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
    # Cloudflare R2（S3 兼容，SigV4 签名）
    "r2_account_id": "",
    "r2_access_key_id": "",
    "r2_secret_access_key": "",
    "r2_bucket": "",
    "r2_prefix": "images",
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

# 免费代理池（kookeey 付费住宅代理的低成本替代）。默认关闭，运维显式开启。
# 凭据走免费代理有泄露风险——登录/OTP 路径默认优先 kookeey（若开启）。
DEFAULT_FREE_PROXY = {
    "enabled": False,
    "refresh_interval_min": 30,
    "max_pool_size": 200,
    "min_healthy": 5,
    "sticky_by_account": True,
    "precheck_url": "https://api.ipify.org",
    "timeout_sec": 10,
    "sources": [
        {
            "name": "proxyscrape",
            "enabled": True,
            "format": "ipport",
            "protocols": ["http"],
            "url": "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&proxy_format=ipport&format=text",
        },
        {
            "name": "geonode",
            "enabled": True,
            "format": "json",
            "protocols": ["http"],
            "url": "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc",
        },
        {
            "name": "proxy-list.download",
            "enabled": True,
            "format": "ipport",
            "protocols": ["http"],
            "url": "https://www.proxy-list.download/api/v1/get?type=http",
        },
        {
            "name": "github-list",
            "enabled": True,
            "format": "ipport",
            "protocols": ["http"],
            "url": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        },
    ],
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
        "last_sha256": str(source.get("last_sha256") or "").strip() or None,
        "last_verify_status": str(source.get("last_verify_status") or "").strip() or None,
        "last_verify_error": str(source.get("last_verify_error") or "").strip() or None,
    }


def _normalize_image_storage_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    mode = str(source.get("mode") or "local").strip().lower()
    if mode not in {"local", "webdav", "r2", "both", "r2_local", "r2local"}:
        mode = "local"
    enabled = _normalize_bool(source.get("enabled"), False)
    if not enabled:
        mode = "local"
    root_path = str(source.get("webdav_root_path") or DEFAULT_IMAGE_STORAGE["webdav_root_path"]).strip().strip("/")
    # 归一化 r2_local / r2local → r2_local（本地兜底 + R2 主存）
    if mode in {"r2_local", "r2local"}:
        mode = "r2_local"
    return {
        "enabled": enabled,
        "mode": mode,
        "webdav_url": str(source.get("webdav_url") or "").strip().rstrip("/"),
        "webdav_username": str(source.get("webdav_username") or "").strip(),
        "webdav_password": str(source.get("webdav_password") or "").strip(),
        "webdav_root_path": root_path or str(DEFAULT_IMAGE_STORAGE["webdav_root_path"]),
        # R2 对象存储（Cloudflare R2，S3 兼容，SigV4 签名，无需 boto3）
        "r2_account_id": str(source.get("r2_account_id") or "").strip(),
        "r2_access_key_id": str(source.get("r2_access_key_id") or "").strip(),
        "r2_secret_access_key": str(source.get("r2_secret_access_key") or "").strip(),
        "r2_bucket": str(source.get("r2_bucket") or "").strip(),
        "r2_prefix": str(source.get("r2_prefix") or "images").strip().strip("/"),
        # 公开访问域名：R2 自定义域 / r2.dev 子域，用于拼接永久直链
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


def _mask_token(token: str) -> str:
    """脱敏敏感 token：只显示末 4 位，其余替换为 ****。"""
    if not token:
        return ""
    if len(token) <= 4:
        return "****"
    return "****" + token[-4:]


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


def _normalize_free_proxy_sources(value: object) -> list[dict[str, object]]:
    """归一化免费代理源列表；非法条目丢弃，空则视为不抓取。"""
    raw = value if isinstance(value, list) else []
    result: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        fmt = str(item.get("format") or "").strip().lower()
        if not (name and url and fmt in {"ipport", "json"}):
            continue
        protocols = item.get("protocols")
        normalized_protocols = (
            [str(p).strip().lower() for p in protocols if str(p).strip()]
            if isinstance(protocols, list)
            else ["http"]
        )
        result.append({
            "name": name,
            "url": url,
            "format": fmt,
            "protocols": normalized_protocols or ["http"],
            "enabled": _normalize_bool(item.get("enabled"), True),
        })
    return result


def _normalize_free_proxy_settings(value: object) -> dict[str, object]:
    """归一化免费代理池配置（kookeey 低成本替代，默认关闭）。

    - enabled 兼容布尔字符串
    - refresh_interval_min ≥5；max_pool_size ≥10；min_healthy ≥1
    - sources 非法条目丢弃，空则视为不抓取
    """
    source = value if isinstance(value, dict) else {}
    return {
        "enabled": _normalize_bool(source.get("enabled"), bool(DEFAULT_FREE_PROXY["enabled"])),
        "refresh_interval_min": _normalize_positive_int(
            source.get("refresh_interval_min"),
            int(DEFAULT_FREE_PROXY["refresh_interval_min"]),
            5,
        ),
        "max_pool_size": _normalize_positive_int(
            source.get("max_pool_size"),
            int(DEFAULT_FREE_PROXY["max_pool_size"]),
            10,
        ),
        "min_healthy": _normalize_positive_int(
            source.get("min_healthy"),
            int(DEFAULT_FREE_PROXY["min_healthy"]),
            1,
        ),
        "sticky_by_account": _normalize_bool(
            source.get("sticky_by_account"),
            bool(DEFAULT_FREE_PROXY["sticky_by_account"]),
        ),
        "precheck_url": str(source.get("precheck_url") or DEFAULT_FREE_PROXY["precheck_url"]).strip(),
        "timeout_sec": _normalize_positive_int(
            source.get("timeout_sec"),
            int(DEFAULT_FREE_PROXY["timeout_sec"]),
            1,
        ),
        "sources": _normalize_free_proxy_sources(source.get("sources")),
    }


def _validate_image_storage_settings(settings: dict[str, object]) -> None:
    if not _normalize_bool(settings.get("enabled"), False):
        return
    if not str(settings.get("webdav_url") or "").strip():
        raise ValueError("启用 WebDAV 图片存储后必须填写 WebDAV URL")
    if not str(settings.get("webdav_password") or "").strip():
        raise ValueError("启用 WebDAV 图片存储后必须填写 WebDAV 密码")


def _normalize_alert_channels(value: object) -> dict[str, dict[str, object]]:
    """归一化告警多通道配置：{通道名: {type, enabled, ...}}。

    - 保留所有通道（含用户自定义类型），按 type 归一化字段
    - enabled 缺省视为 True（向后兼容：旧配置无 enabled 字段默认启用）
    - 环境变量覆盖在 alert_channels property 中叠加
    """
    source = value if isinstance(value, dict) else {}
    normalized: dict[str, dict[str, object]] = {}
    for name, raw_cfg in source.items():
        if not isinstance(raw_cfg, dict):
            continue
        cfg = dict(raw_cfg)
        channel_type = str(cfg.get("type", name)).strip().lower()
        entry: dict[str, object] = {
            "type": channel_type,
            "enabled": _normalize_bool(cfg.get("enabled"), True),
        }
        if channel_type == "telegram":
            entry["bot_token"] = str(cfg.get("bot_token") or "").strip()
            entry["chat_id"] = str(cfg.get("chat_id") or "").strip()
        elif channel_type == "email":
            smtp_user = str(cfg.get("smtp_user") or "").strip()
            raw_to = cfg.get("to_addrs")
            if isinstance(raw_to, str):
                to_addrs = [addr.strip() for addr in raw_to.split(",") if addr.strip()]
            elif isinstance(raw_to, list):
                to_addrs = [str(addr).strip() for addr in raw_to if str(addr).strip()]
            else:
                to_addrs = []
            entry["smtp_host"] = str(cfg.get("smtp_host") or "").strip()
            entry["smtp_port"] = _normalize_positive_int(cfg.get("smtp_port"), 465, 1)
            entry["smtp_user"] = smtp_user
            entry["smtp_password"] = str(cfg.get("smtp_password") or "").strip()
            entry["use_tls"] = _normalize_bool(cfg.get("use_tls"), True)
            entry["from_addr"] = str(cfg.get("from_addr") or "").strip() or smtp_user
            entry["to_addrs"] = to_addrs
        else:
            # wecom / dingtalk / generic / 自定义 webhook 类通道
            entry["webhook_url"] = str(cfg.get("webhook_url") or "").strip()
        normalized[str(name)] = entry
    return normalized


def _validate_alert_channels(channels: dict[str, dict[str, object]]) -> None:
    """校验启用状态的告警通道参数完整性（fail-fast）。"""
    for name, cfg in channels.items():
        if not _normalize_bool(cfg.get("enabled"), True):
            continue
        channel_type = str(cfg.get("type") or name).strip().lower()
        if channel_type == "telegram":
            if not str(cfg.get("bot_token") or "").strip() or not str(cfg.get("chat_id") or "").strip():
                raise ValueError(f"告警通道 {name} 启用 Telegram 后必须填写 bot_token 与 chat_id")
        elif channel_type == "email":
            if not str(cfg.get("smtp_host") or "").strip():
                raise ValueError(f"告警通道 {name} 启用邮件后必须填写 smtp_host")
            if not str(cfg.get("from_addr") or "").strip():
                raise ValueError(f"告警通道 {name} 启用邮件后必须填写 from_addr（或 smtp_user）")
            if not cfg.get("to_addrs"):
                raise ValueError(f"告警通道 {name} 启用邮件后必须至少填写一个收件人 to_addrs")
        else:
            if not str(cfg.get("webhook_url") or "").strip():
                raise ValueError(f"告警通道 {name} 启用后必须填写 webhook_url")


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


_WEAK_SMTP_PASSWORDS = {"admin", "password", "secret", "123456", "test", "changeme", "smtp_password", "your_password"}


def _validate_weak_channel_credentials(channels: dict[str, dict[str, object]], env: str) -> None:
    """G6-S3：告警通道弱口令检测——启用的 email 通道 smtp_password 为常见占位符时告警/拒绝。

    与 auth-key 弱口令同策略：production 拒绝启动，development 仅 WARNING（不阻断）。
    """
    for name, cfg in channels.items():
        if not _normalize_bool(cfg.get("enabled"), True):
            continue
        channel_type = str(cfg.get("type") or name).strip().lower()
        if channel_type != "email":
            continue
        smtp_password = str(cfg.get("smtp_password") or "").strip().lower()
        if not smtp_password or smtp_password in _WEAK_SMTP_PASSWORDS:
            msg = (
                f"❌ 告警通道 {name}（email）smtp_password 为空白或常见占位符，存在泄露风险！\n"
                "   请设置真实的 SMTP 密码（或用 CHATGPT2API_ALERT_EMAIL_SMTP_PASSWORD 环境变量注入）。"
            )
            if env == "production":
                raise ValueError(f"❌ 生产环境拒绝使用弱 SMTP 密码启动！\n{msg}")
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
        self._config_mtime: float = 0.0
        self.data = self._load()
        self._config_mtime = self._get_file_mtime()
        # 延迟求值类型注解（防 storage 层循环 import）
        self._storage_backend: object | None = None  # 惰性初始化，见 get_storage_backend（避免循环 import）
        if _is_invalid_auth_key(self.auth_key):
            raise ValueError(
                "❌ auth-key 未设置！\n"
                "请按以下任意一种方式解决：\n"
                "1. 在 Render 的 Environment 变量中添加：\n"
                "   CHATGPT2API_AUTH_KEY = your_real_auth_key\n"
                "2. 或者在 config.json 中填写：\n"
                '   "auth-key": "your_real_auth_key"'
            )
        # G6-S3：告警通道弱口令检测（production 拒绝 / development WARNING）
        try:
            _validate_weak_channel_credentials(self.alert_channels, self.env)
        except ValueError:
            raise
        except Exception:  # noqa: BLE001 - 弱口令检测自身失败不阻断启动
            pass

    def _get_file_mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return 0.0

    def _try_reload(self) -> None:
        try:
            mtime = self._get_file_mtime()
            if mtime > self._config_mtime:
                new_data = _read_json_object(self.path, name="config.json")
                self._validate_schema(new_data)
                self.data = new_data
                self._config_mtime = mtime
                logger.info("config.json 已自动热加载（mtime 变更）")
        except Exception as exc:
            logger.warning("config.json 热加载失败，保留旧配置: %s", exc)

    def _load(self) -> dict[str, object]:
        data = _read_json_object(self.path, name="config.json")
        self._validate_schema(data)
        return data

    # E4/P: 配置校验表驱动化——新增数值/布尔配置项只需在此登记，类型+范围 fail-fast 自动覆盖
    _INT_FIELDS: tuple[tuple[str, tuple[int, int] | None], ...] = (
        ("workers", (1, 64)),
        ("rate_limit_rpm", (0, 1_000_000)),
        ("rate_limit_per_ip_rpm", (0, 100_000)),
        ("refresh_account_interval_minute", (1, 1440)),
        ("image_retention_days", (1, 3650)),
        ("image_account_concurrency", (1, 1024)),
        ("sqlite_busy_timeout_ms", (0, 300_000)),
        ("progress_ttl_seconds", (1, 86400)),
        ("alert_webhook_timeout", (1, 300)),
        ("proactive_probe_interval_minute", (5, 1440)),
        ("audit_retention_days", (1, 3650)),
        ("self_heal_retry_initial_secs", (1, 86400)),
        ("self_heal_retry_max_secs", (1, 86400)),
        ("self_heal_retry_max_attempts", (1, 100)),
        ("account_warmup_timeout_secs", (5, 3600)),
        ("auto_diagnose_interval_minutes", (1, 1440)),
    )
    _BOOL_FIELDS: tuple[str, ...] = (
        "sqlite_wal_mode",
        "ssrf_allow_private_ips",
        "proactive_probe_enabled",
        "upstream_failover_enabled",
        "session_pool_health_check_enabled",
        "self_heal_auto_replace_enabled",
        "account_warmup_enabled",
        "auto_heal_enabled",
        "openapi_enabled",
        "config_watch_enabled",
        "scheduler_adaptive_enabled",
    )
    _FLOAT_FIELDS: tuple[str, ...] = (
        "metrics_sample_rate",
        "scheduler_adaptive_interval_seconds",
        "traces_sample_rate",
        "traces_slow_threshold_ms",
    )
    _DICT_FIELDS: tuple[str, ...] = (
        "provider_weights",
        "provider_rate_limit_rpm",
        "model_upstream_map",
        "alert_channels",
        "account_aging",
    )
    _ENUM_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("scheduler_mode", ("round_robin", "remaining_quota", "weighted_random", "least_load", "least_used", "predictive", "affinity")),
    )

    @staticmethod
    def _check_int_field(field: str, bounds: tuple[int, int] | None, data: dict[str, object], errors: list[str]) -> None:
        value = data.get(field)
        if value is None:
            return
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{field} 必须是整数，当前为 {value!r} ({type(value).__name__})")
            return
        if value < 0:
            errors.append(f"{field} 不能为负数，当前为 {value}")
            return
        if bounds is not None and not (bounds[0] <= value <= bounds[1]):
            errors.append(f"{field} 超出允许范围 [{bounds[0]}, {bounds[1]}]，当前为 {value}")

    @classmethod
    def _validate_schema(cls, data: dict[str, object]) -> None:
        """启动时校验关键配置项类型与范围（表驱动，fail-fast）。"""
        errors: list[str] = []
        for field, bounds in cls._INT_FIELDS:
            cls._check_int_field(field, bounds, data, errors)
        for field, allowed in cls._ENUM_FIELDS:
            mode = data.get(field)
            if mode is not None and mode not in allowed:
                errors.append(f"{field} 必须是 {'、'.join(allowed)} 之一，当前为 {mode!r}")
        for field in cls._BOOL_FIELDS:
            bval = data.get(field)
            if bval is not None and not isinstance(bval, bool):
                errors.append(f"{field} 必须是布尔值，当前为 {bval!r} ({type(bval).__name__})")
        # float 字段校验（只校验类型，不校验范围——范围在 property 中 clamp）
        for field in cls._FLOAT_FIELDS:
            fval = data.get(field)
            if fval is not None:
                if not isinstance(fval, (int, float)) or isinstance(fval, bool):
                    errors.append(f"{field} 必须是浮点数，当前为 {fval!r} ({type(fval).__name__})")
        # trusted_proxies 类型校验（list[str] 或逗号分隔 str）
        tp = data.get("trusted_proxies")
        if tp is not None and not isinstance(tp, (list, str)):
            errors.append(f"trusted_proxies 必须是数组或逗号分隔字符串，当前为 {tp!r} ({type(tp).__name__})")
        # scheduler_priority 必须为 dict[str, int]
        sp = data.get("scheduler_priority")
        if sp is not None and not isinstance(sp, dict):
            errors.append(f"scheduler_priority 必须是对象 {{}}，当前为 {type(sp).__name__}")
        # dict 字段校验（类型为 dict 即可）
        for field in cls._DICT_FIELDS:
            df = data.get(field)
            if df is not None and not isinstance(df, dict):
                errors.append(f"{field} 必须是对象 {{}}，当前为 {type(df).__name__}")
        # proxy_groups / account_groups 必须为数组
        for field in ("proxy_groups", "account_groups"):
            lv = data.get(field)
            if lv is not None and not isinstance(lv, list):
                errors.append(f"{field} 必须是数组，当前为 {type(lv).__name__}")
        # free_proxy 必须为 dict；sources 非空时逐条校验 name/url/format
        fp = data.get("free_proxy")
        if fp is not None and not isinstance(fp, dict):
            errors.append(f"free_proxy 必须是对象 {{}}，当前为 {type(fp).__name__}")
        elif isinstance(fp, dict):
            fsrc = fp.get("sources")
            if fsrc is not None and not isinstance(fsrc, list):
                errors.append(f"free_proxy.sources 必须是数组，当前为 {type(fsrc).__name__}")
            elif isinstance(fsrc, list):
                for idx, src in enumerate(fsrc):
                    if not isinstance(src, dict):
                        errors.append(f"free_proxy.sources[{idx}] 必须是对象")
                        continue
                    name = src.get("name")
                    url = src.get("url")
                    fmt = src.get("format")
                    if not name or not isinstance(name, str):
                        errors.append(f"free_proxy.sources[{idx}].name 必须为非空字符串")
                    if not url or not isinstance(url, str):
                        errors.append(f"free_proxy.sources[{idx}].url 必须为非空字符串")
                    if fmt is not None and fmt not in {"ipport", "json"}:
                        errors.append(f"free_proxy.sources[{idx}].format 必须为 ipport 或 json")
        if errors:
            raise ValueError("❌ config.json 配置校验失败：\n" + "\n".join(f"   - {e}" for e in errors))

    def _save(self) -> None:
        # 原子写（第七轮 B9）：复用 json_storage 的 _atomic_write_text，
        # 防写入中途断电/杀进程导致 config.json 截断损坏
        from services.storage.json_storage import _atomic_write_text
        payload = json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"
        try:
            _atomic_write_text(self.path, payload)
        except PermissionError:
            # 单文件挂载（docker compose `- ./config.json:/app/config.json`）场景：
            # 原子替换需对父目录建 tmp + rename，但挂载点只给了文件写权限、目录不可写，
            # 原子写必 PermissionError。回退为直接写（非原子），保证 UI 运行时改配置可用。
            # 挂载点是只给文件写权限的 bind mount，父目录不可写，tmp + rename 通不过。
            # 风险：直接写过程中断（断电/杀进程）可能导致 config.json 截断损坏。
            # 建议：生产环境改配 named volume 挂载 config.json 目录，恢复原子写能力。
            logger.warning(
                "config.json 原子写回退为直接写（非原子），bind mount 场景下写入中断有截断风险。"
                " 建议改用 named volume 挂载 config.json：`docker volume create cfg` 后挂载到 /app/config/。"
            )
            self.path.write_text(payload, encoding="utf-8")
        self._config_mtime = self._get_file_mtime()

    @functools.cached_property
    def auth_key(self) -> str:
        """高频读取（每个请求鉴权），用 cached_property 缓存。"""
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
            return max(1, int(self.data.get("image_poll_timeout_secs", 600)))
        except (TypeError, ValueError):
            return 120

    @property
    def image_min_free_mb(self) -> int:
        """图片磁盘最小剩余空间阈值（MB），低于此值自动清理最旧图片。"""
        try:
            return max(50, int(self.data.get("image_min_free_mb", 500)))
        except (TypeError, ValueError):
            return 500

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
        return value if value in {"round_robin", "remaining_quota", "weighted_random", "least_load", "least_used", "predictive", "affinity"} else "round_robin"

    @property
    def scheduler_affinity_ttl_seconds(self) -> float:
        """Affinity 调度模式：同一模型路由到同一账号的亲和超时（秒，默认 300）。"""
        try:
            return max(60.0, float(
                os.getenv("CHATGPT2API_SCHEDULER_AFFINITY_TTL")
                or self.data.get("scheduler_affinity_ttl_seconds", 300)
            ))
        except (TypeError, ValueError):
            return 300.0

    @property
    def scheduler_adaptive_enabled(self) -> bool:
        """自适应调度器开关（默认 false）。"""
        value = os.getenv("CHATGPT2API_SCHEDULER_ADAPTIVE_ENABLED") or self.data.get("scheduler_adaptive_enabled")
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def scheduler_adaptive_interval_seconds(self) -> float:
        """自适应调度器检查间隔（秒，默认 30，最小 5）。"""
        try:
            return max(5.0, float(
                os.getenv("CHATGPT2API_SCHEDULER_ADAPTIVE_INTERVAL")
                or self.data.get("scheduler_adaptive_interval_seconds", 30)
            ))
        except (TypeError, ValueError):
            return 30.0

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
    def storage_backend_type(self) -> str:
        return str(os.getenv("STORAGE_BACKEND") or self.data.get("storage_backend") or "json").strip().lower()

    @property
    def storage_async_enabled(self) -> bool:
        """异步存储后端开关（默认关闭，启用后数据库操作使用 sqlalchemy.ext.asyncio）。"""
        value = os.getenv("STORAGE_ASYNC_ENABLED")
        if value is not None:
            return _normalize_bool(value, False)
        return _normalize_bool(self.data.get("storage_async_enabled"), False)

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
    def redis_url(self) -> str:
        """Redis 共享状态连接串（默认空 = Local 进程内，多 worker 状态分裂可接受时）。"""
        return str(os.getenv("CHATGPT2API_REDIS_URL") or self.data.get("redis_url") or "").strip()

    @property
    def metrics_token(self) -> str:
        """Prometheus 指标独立抓取 token（G6-S1，默认空 = 回退 auth-key 鉴权）。

        配置后 /metrics 只认该 token，auth-key 不再放行——防 auth-key 泄漏后指标裸奔。
        """
        return str(os.getenv("CHATGPT2API_METRICS_TOKEN") or "").strip()

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
        default = ["circuit_breaker_open", "circuit_breaker_closed", "backup_failure", "backup_checksum_mismatch", "account_invalid", "account_recovered", "quota_exhausted", "quota_forecast_depletion"]
        raw = os.getenv("CHATGPT2API_ALERT_EVENTS")
        if raw is not None:
            return [e.strip() for e in str(raw).split(",") if e.strip()]
        value = self.data.get("alert_events")
        if isinstance(value, list):
            return [str(e).strip() for e in value if str(e).strip()]
        return default

    @property
    def alert_channels(self) -> dict[str, dict[str, object]]:
        """告警多通道配置（telegram / wecom / dingtalk / email / 自定义 webhook）。

        环境变量覆盖约定（CHATGPT2API_*，设置即启用对应通道）：
        - CHATGPT2API_ALERT_TELEGRAM_BOT_TOKEN / CHATGPT2API_ALERT_TELEGRAM_CHAT_ID
        - CHATGPT2API_ALERT_EMAIL_SMTP_HOST / _SMTP_PORT / _SMTP_USER / _SMTP_PASSWORD / _FROM / _TO / _USE_TLS
        """
        channels = _normalize_alert_channels(self.data.get("alert_channels"))

        tg_token = os.getenv("CHATGPT2API_ALERT_TELEGRAM_BOT_TOKEN")
        tg_chat = os.getenv("CHATGPT2API_ALERT_TELEGRAM_CHAT_ID")
        if tg_token or tg_chat:
            entry = channels.get("telegram_ops")
            if entry is None:
                entry = {"type": "telegram", "enabled": True}
                channels["telegram_ops"] = entry
            if tg_token:
                entry["bot_token"] = tg_token.strip()
            if tg_chat:
                entry["chat_id"] = tg_chat.strip()
            entry["enabled"] = True
            entry["type"] = "telegram"

        email_host = os.getenv("CHATGPT2API_ALERT_EMAIL_SMTP_HOST")
        if email_host:
            entry = channels.get("email_ops")
            if entry is None:
                entry = {"type": "email", "enabled": True}
                channels["email_ops"] = entry
            entry["smtp_host"] = email_host.strip()
            port_raw = os.getenv("CHATGPT2API_ALERT_EMAIL_SMTP_PORT")
            if port_raw:
                try:
                    entry["smtp_port"] = max(1, int(port_raw))
                except ValueError:
                    pass
            user_raw = os.getenv("CHATGPT2API_ALERT_EMAIL_SMTP_USER")
            if user_raw:
                entry["smtp_user"] = user_raw.strip()
            pass_raw = os.getenv("CHATGPT2API_ALERT_EMAIL_SMTP_PASSWORD")
            if pass_raw:
                entry["smtp_password"] = pass_raw.strip()
            from_raw = os.getenv("CHATGPT2API_ALERT_EMAIL_FROM")
            if from_raw:
                entry["from_addr"] = from_raw.strip()
            else:
                entry["from_addr"] = str(entry.get("from_addr") or entry.get("smtp_user") or "").strip()
            to_raw = os.getenv("CHATGPT2API_ALERT_EMAIL_TO")
            if to_raw:
                entry["to_addrs"] = [addr.strip() for addr in to_raw.split(",") if addr.strip()]
            tls_raw = os.getenv("CHATGPT2API_ALERT_EMAIL_USE_TLS")
            if tls_raw is not None:
                entry["use_tls"] = _normalize_bool(tls_raw, True)
            entry["enabled"] = True
            entry["type"] = "email"

        return channels

    @property
    def proactive_probe_enabled(self) -> bool:
        """低频主动探活开关（F4/B6，默认关）：周期性 fetch_remote_info 探活全部账号，
        把哑死账号（限流/失效）提前剔除，避免首次请求才踩坑。"""
        raw = os.getenv("CHATGPT2API_PROACTIVE_PROBE_ENABLED")
        if raw is not None:
            return _normalize_bool(raw, False)
        return _normalize_bool(self.data.get("proactive_probe_enabled"), False)

    @property
    def proactive_probe_interval_minute(self) -> int:
        """主动探活周期分钟数（默认 30，最小 5，防过度消耗配额）。"""
        try:
            return max(5, int(
                os.getenv("CHATGPT2API_PROACTIVE_PROBE_INTERVAL_MINUTE")
                or self.data.get("proactive_probe_interval_minute", 30)
            ))
        except (TypeError, ValueError):
            return 30

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
    def image_passthrough_enabled(self) -> bool:
        """出图直接返回上游签名 URL（服务器不下载/重托管，省服务器上下行流量与带宽压力）。

        开启后生图响应 data[].url 为上游签名直链（带 TTL，约 1-24h 过期，过期 410），
        客户端应即时下载。默认开启（省上下行流量；UI 可实时切换回服务端下载重托管）。
        """
        return _normalize_bool(self.data.get("image_passthrough_enabled"), True)

    @property
    def image_passthrough_ttl_secs(self) -> int:
        """透传直链标注的有效期（秒），过期后直链 410 不可用。"""
        try:
            return max(60, int(self.data.get("image_passthrough_ttl_secs", 3600)))
        except (TypeError, ValueError):
            return 3600

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
    def abnormal_auto_recover_enabled(self) -> bool:
        """v2.9.0：异常账号自动恢复开关（watcher 第二职责）。"""
        value = self.data.get("abnormal_auto_recover_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def abnormal_auto_recover_interval_minutes(self) -> int:
        """v2.9.0：异常账号自动恢复扫描间隔（分钟）。"""
        try:
            value = int(self.data.get("abnormal_auto_recover_interval_minutes", 5))
        except (TypeError, ValueError):
            value = 5
        return max(1, min(1440, value))

    @property
    def cf_solver_url(self) -> str:
        """OTP 登录 CF 清除服务地址（默认 http://127.0.0.1:8001）。
        环境变量 OTP_CF_SOLVER_URL 优先于 config.json 的 otp_cf_solver_url。"""
        return str(
            os.getenv("OTP_CF_SOLVER_URL")
            or self.data.get("otp_cf_solver_url")
            or "http://127.0.0.1:8001"
        ).strip().rstrip("/")

    @property
    def upstream_failover_enabled(self) -> bool:
        """上游 5xx/连接错误时自动切换账号（默认开启）。"""
        value = self.data.get("upstream_failover_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def session_pool_health_check_enabled(self) -> bool:
        """连接池健康预检开关（默认开启）。"""
        value = self.data.get("session_pool_health_check_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def provider_weights(self) -> dict[str, int]:
        """Provider 权重调度配置（如 {"chatgpt": 3, "grok": 1}）。"""
        raw = self.data.get("provider_weights")
        if not isinstance(raw, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in raw.items():
            try:
                w = int(value)
                if w >= 0:
                    result[str(key).strip()] = w
            except (TypeError, ValueError):
                pass
        return result

    @property
    def provider_rate_limit_rpm(self) -> dict[str, int]:
        """Provider 独立 rate limit（如 {"chatgpt": 60, "grok": 30}，0=不限）。"""
        raw = self.data.get("provider_rate_limit_rpm")
        if not isinstance(raw, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in raw.items():
            try:
                w = int(value)
                if w >= 0:
                    result[str(key).strip()] = w
            except (TypeError, ValueError):
                pass
        return result

    @property
    def self_heal_retry_initial_secs(self) -> int:
        """自愈指数退避初始延迟（秒，默认 60）。"""
        try:
            return max(1, int(self.data.get("self_heal_retry_initial_secs", 60)))
        except (TypeError, ValueError):
            return 60

    @property
    def self_heal_retry_max_secs(self) -> int:
        """自愈指数退避最大延迟（秒，默认 3600）。"""
        try:
            return max(1, int(self.data.get("self_heal_retry_max_secs", 3600)))
        except (TypeError, ValueError):
            return 3600

    @property
    def self_heal_retry_max_attempts(self) -> int:
        """自愈指数退避最大重试次数（默认 5）。"""
        try:
            return max(1, int(self.data.get("self_heal_retry_max_attempts", 5)))
        except (TypeError, ValueError):
            return 5

    @property
    def self_heal_auto_replace_enabled(self) -> bool:
        """自动替换不健康账号开关（默认关闭）。"""
        value = self.data.get("self_heal_auto_replace_enabled", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def account_warmup_enabled(self) -> bool:
        """新账号预热开关（默认开启）。"""
        value = self.data.get("account_warmup_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def account_warmup_timeout_secs(self) -> float:
        """账号预热超时秒数（默认 60）。"""
        try:
            return max(5.0, float(self.data.get("account_warmup_timeout_secs", 60.0)))
        except (TypeError, ValueError):
            return 60.0

    @property
    def abnormal_auto_recover_max_workers(self) -> int:
        """v2.9.0：异常账号自动恢复并发数上限。"""
        try:
            value = int(self.data.get("abnormal_auto_recover_max_workers", 5))
        except (TypeError, ValueError):
            value = 5
        return max(1, min(20, value))

    @property
    def auto_heal_enabled(self) -> bool:
        """自动修复引擎开关（默认开启）。"""
        value = self.data.get("auto_heal_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def auto_diagnose_interval_minutes(self) -> int:
        """自动诊断间隔分钟数（默认 60）。"""
        try:
            return max(1, int(self.data.get("auto_diagnose_interval_minutes", 60)))
        except (TypeError, ValueError):
            return 60

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
    def model_upstream_map(self) -> dict[str, str]:
        raw = self.data.get("model_upstream_map")
        if isinstance(raw, dict):
            return {str(k).strip(): str(v).strip() for k, v in raw.items() if k and v}
        return {}

    @property
    def default_thinking_effort(self) -> str:
        value = str(self.data.get("default_thinking_effort") or "auto").strip().lower()
        return value if value in {"auto", "standard", "extended", "max"} else "auto"

    @property
    def audit_retention_days(self) -> int:
        return int(self.data.get("audit_retention_days", 90))

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
    def metrics_sample_rate(self) -> float:
        """Prometheus 指标采样率（0.0 关闭，1.0 全量采集，默认 1.0）。"""
        try:
            return max(0.0, min(1.0, float(
                os.getenv("CHATGPT2API_METRICS_SAMPLE_RATE")
                or self.data.get("metrics_sample_rate", 1.0)
            )))
        except (TypeError, ValueError):
            return 1.0

    @property
    def trace_slow_threshold_ms(self) -> float:
        try:
            return max(0.0, float(
                os.getenv("CHATGPT2API_TRACE_SLOW_THRESHOLD_MS")
                or self.data.get("trace_slow_threshold_ms", 5000.0)
            ))
        except (TypeError, ValueError):
            return 5000.0

    @property
    def trace_buffer_size(self) -> int:
        try:
            return max(10, int(
                os.getenv("CHATGPT2API_TRACE_BUFFER_SIZE")
                or self.data.get("trace_buffer_size", 10000)
            ))
        except (TypeError, ValueError):
            return 10000

    @property
    def openapi_enabled(self) -> bool:
        return bool(self.data.get("openapi_enabled", True))

    @property
    def openapi_docs_url(self) -> str:
        return str(self.data.get("openapi_docs_url", "/docs") or "").strip()

    @property
    def openapi_redoc_url(self) -> str:
        return str(self.data.get("openapi_redoc_url", "/redoc") or "").strip()

    @property
    def openapi_openapi_url(self) -> str:
        return str(self.data.get("openapi_openapi_url", "/openapi.json") or "").strip()

    @property
    def config_watch_enabled(self) -> bool:
        """配置热加载开关（默认开启）。"""
        value = os.getenv("CHATGPT2API_CONFIG_WATCH_ENABLED")
        if value is not None:
            return _normalize_bool(value, True)
        return _normalize_bool(self.data.get("config_watch_enabled"), True)

    @property
    def app_version(self) -> str:
        try:
            value = VERSION_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return "0.0.0"
        return value or "0.0.0"

    def get(self) -> dict[str, object]:
        self._try_reload()
        data = dict(self.data)
        data["refresh_account_interval_minute"] = self.refresh_account_interval_minute
        data["image_retention_days"] = self.image_retention_days
        data["image_poll_timeout_secs"] = self.image_poll_timeout_secs
        data["image_min_free_mb"] = self.image_min_free_mb
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
        data["alert_channels"] = self.alert_channels
        data["proactive_probe_enabled"] = self.proactive_probe_enabled
        data["proactive_probe_interval_minute"] = self.proactive_probe_interval_minute
        data["self_heal_retry_initial_secs"] = self.self_heal_retry_initial_secs
        data["self_heal_retry_max_secs"] = self.self_heal_retry_max_secs
        data["self_heal_retry_max_attempts"] = self.self_heal_retry_max_attempts
        data["self_heal_auto_replace_enabled"] = self.self_heal_auto_replace_enabled
        data["account_warmup_enabled"] = self.account_warmup_enabled
        data["account_warmup_timeout_secs"] = self.account_warmup_timeout_secs
        data["auto_heal_enabled"] = self.auto_heal_enabled
        data["auto_diagnose_interval_minutes"] = self.auto_diagnose_interval_minutes
        data["redis_url"] = self.redis_url
        data["upstream_failover_enabled"] = self.upstream_failover_enabled
        data["session_pool_health_check_enabled"] = self.session_pool_health_check_enabled
        data["metrics_sample_rate"] = self.metrics_sample_rate
        data["trace_slow_threshold_ms"] = self.trace_slow_threshold_ms
        data["trace_buffer_size"] = self.trace_buffer_size
        data["provider_weights"] = self.provider_weights
        data["provider_rate_limit_rpm"] = self.provider_rate_limit_rpm
        data["model_upstream_map"] = self.model_upstream_map
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
        data["model_upstream_map"] = self.model_upstream_map
        data["default_thinking_effort"] = self.default_thinking_effort
        data["backup"] = self.get_backup_settings()
        data["image_storage"] = self.get_image_storage_settings()
        data["chat_completion_cache"] = self.get_chat_completion_cache_settings()
        data["proxy_runtime"] = self.get_public_proxy_runtime_settings()
        data["proxy_groups"] = self.get_proxy_groups()
        data["account_groups"] = self.get_account_groups()
        data["account_aging"] = self.get_account_aging()
        data["openapi_enabled"] = self.openapi_enabled
        data["openapi_docs_url"] = self.openapi_docs_url
        data["openapi_redoc_url"] = self.openapi_redoc_url
        data["openapi_openapi_url"] = self.openapi_openapi_url
        data["config_watch_enabled"] = self.config_watch_enabled
        data.pop("auth-key", None)
        return data

    def get_proxy_settings(self) -> str:
        return str(self.data.get("proxy") or "").strip()

    def get_proxy_groups(self) -> list[dict]:
        """代理分组配置（账号分组 → 代理组 → 节点池，供 AccountProxyPool 读取）。

        结构示例：
        [{"id": "kookeey-pool", "enabled": true, "nodes": [
            {"id": "node-1", "provider": "kookeey", "url": "http://...", "image_concurrency_limit": 30}]}]
        未配置返回 []（代理池默认关闭，走原直连逻辑）。
        """
        raw = self.data.get("proxy_groups")
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def get_account_groups(self) -> list[dict]:
        """账号分组配置（账号 group_id → 代理组绑定，供 AccountProxyPool 读取）。

        结构示例：
        [{"id": "group-a", "enabled": true, "proxy_group_id": "kookeey-pool"}]
        未配置返回 []。
        """
        raw = self.data.get("account_groups")
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def get_account_aging(self) -> dict[str, object]:
        """养号池配置：{enabled, days(默认7), auto_apply_to_new, behaviors}。

        养号期账号（status=养号中）不进入图片调度，超过 days 天自动转正。
        """
        raw = self.data.get("account_aging")
        if not isinstance(raw, dict):
            return {"enabled": False, "days": 7, "auto_apply_to_new": True, "behaviors": []}
        behaviors = raw.get("behaviors")
        return {
            "enabled": _normalize_bool(raw.get("enabled"), False),
            "days": _normalize_positive_int(raw.get("days"), 7, 1),
            "auto_apply_to_new": _normalize_bool(raw.get("auto_apply_to_new"), True),
            "behaviors": (
                [str(b).strip() for b in behaviors if str(b).strip()]
                if isinstance(behaviors, list) else []
            ),
        }

    def get_kookeey_settings(self) -> dict[str, object]:
        """kookeey 动态住宅代理配置（密码登录 / OTP 取件的每号独立出口）。

        结构：{enabled, scheme, gate_host, gate_port, user_id, security_username,
              security_password, country, developer_token, access_id}。
        支持 KOOKEEY_DEVELOPER_TOKEN 环境变量覆盖 developer_token（避免明文 base64 存 config.json）。
        未配置返回 {}。
        """
        raw = self.data.get("kookeey")
        result = dict(raw) if isinstance(raw, dict) else {}
        env_token = os.getenv("KOOKEEY_DEVELOPER_TOKEN")
        if env_token:
            result["developer_token"] = env_token.strip()
        return result

    def get_free_proxy_settings(self) -> dict[str, object]:
        """免费代理池配置（kookeey 付费住宅代理的低成本替代）。

        实时读取 + 归一化：改 free_proxy.enabled 无需重启生效（热加载）。
        默认关闭；sources 非法条目丢弃，空则视为不抓取。
        """
        self._try_reload()
        return _normalize_free_proxy_settings(self.data.get("free_proxy"))

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

    def update(self, data: dict[str, object]) -> dict[str, object]:
        self._try_reload()
        next_data = dict(self.data)
        next_data.update(dict(data or {}))
        if "backup" in next_data:
            next_data["backup"] = _normalize_backup_settings(next_data.get("backup"))
        if "image_storage" in next_data:
            next_data["image_storage"] = _normalize_image_storage_settings(next_data.get("image_storage"))
            _validate_image_storage_settings(next_data["image_storage"])
        if "alert_channels" in next_data:
            next_data["alert_channels"] = _normalize_alert_channels(next_data.get("alert_channels"))
            _validate_alert_channels(next_data["alert_channels"])
        if "chat_completion_cache" in next_data:
            next_data["chat_completion_cache"] = _normalize_chat_completion_cache_settings(
                next_data.get("chat_completion_cache")
            )
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

    def get_quota_management(self) -> dict[str, object]:
        self._try_reload()
        raw = self.data.get("quota_management")
        if not isinstance(raw, dict):
            return {"enabled": False, "default_quota": {}, "overage_action": "reject"}
        return {
            "enabled": bool(raw.get("enabled", False)),
            "default_quota": raw.get("default_quota") if isinstance(raw.get("default_quota"), dict) else {},
            "overage_action": str(raw.get("overage_action") or "reject"),
        }

    def get_storage_backend(self) -> Any:  # 返回 StorageBackend（惰性 import 防循环）
        """获取存储后端实例（单例）"""
        if self._storage_backend is None:
            from services.storage.factory import create_storage_backend
            self._storage_backend = create_storage_backend(DATA_DIR)
        return self._storage_backend


def load_backup_state() -> dict[str, object]:
    return _normalize_backup_state(_read_json_object(BACKUP_STATE_FILE, name="backup_state.json"))


def save_backup_state(state: dict[str, object]) -> dict[str, object]:
    normalized = _normalize_backup_state(state)
    from services.storage.json_storage import _atomic_write_text

    _atomic_write_text(BACKUP_STATE_FILE, json.dumps(normalized, ensure_ascii=False, indent=2) + "\n")
    return normalized


config = ConfigStore(CONFIG_FILE)
