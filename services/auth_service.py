from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime
from threading import Lock
from typing import Literal

from services.config import config
from services.storage.base import StorageBackend

AuthRole = Literal["admin", "user"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, storage: StorageBackend):
        self.storage = storage
        self._lock = Lock()
        self._items = self._load()
        self._last_used_flush_at: dict[str, datetime] = {}

    @staticmethod
    def _clean(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _default_name(role: object) -> str:
        return "管理员密钥" if str(role or "").strip().lower() == "admin" else "普通用户"

    def _normalize_item(self, raw: object) -> dict[str, object] | None:
        if not isinstance(raw, dict):
            return None
        role = self._clean(raw.get("role")).lower()
        if role not in {"admin", "user"}:
            return None
        key_hash = self._clean(raw.get("key_hash"))
        if not key_hash:
            return None
        item_id = self._clean(raw.get("id")) or uuid.uuid4().hex[:12]
        name = self._clean(raw.get("name")) or self._default_name(role)
        created_at = self._clean(raw.get("created_at")) or _now_iso()
        last_used_at = self._clean(raw.get("last_used_at")) or None
        usage_count = int(raw.get("usage_count") or 0)
        # 新增字段
        expires_at = self._clean(raw.get("expires_at")) or None
        permissions = raw.get("permissions")
        if not isinstance(permissions, list) or not permissions:
            permissions = ["*"]
        quota_raw = raw.get("quota")
        if isinstance(quota_raw, dict):
            quota = {
                "daily_requests": quota_raw.get("daily_requests"),
                "daily_images": quota_raw.get("daily_images"),
                "monthly_requests": quota_raw.get("monthly_requests"),
                "monthly_images": quota_raw.get("monthly_images"),
                "reset_cycle": str(quota_raw.get("reset_cycle") or "none").strip().lower(),
            }
            if quota["reset_cycle"] not in {"none", "daily", "monthly"}:
                quota["reset_cycle"] = "none"
            for k in ("daily_requests", "daily_images", "monthly_requests", "monthly_images"):
                v = quota[k]
                if v is not None:
                    try:
                        quota[k] = int(v)
                    except (TypeError, ValueError):
                        quota[k] = None
        else:
            quota = None
        quota_used_raw = raw.get("quota_used")
        if isinstance(quota_used_raw, dict):
            quota_used = {
                "daily_requests": int(quota_used_raw.get("daily_requests") or 0),
                "daily_images": int(quota_used_raw.get("daily_images") or 0),
                "monthly_requests": int(quota_used_raw.get("monthly_requests") or 0),
                "monthly_images": int(quota_used_raw.get("monthly_images") or 0),
                "daily_reset_date": str(quota_used_raw.get("daily_reset_date") or "") or None,
                "monthly_reset_date": str(quota_used_raw.get("monthly_reset_date") or "") or None,
            }
        else:
            quota_used = None
        return {
            "id": item_id,
            "name": name,
            "role": role,
            "key_hash": key_hash,
            "enabled": bool(raw.get("enabled", True)),
            "created_at": created_at,
            "last_used_at": last_used_at,
            "usage_count": usage_count,
            "expires_at": expires_at,
            "permissions": permissions,
            "quota": quota,
            "quota_used": quota_used,
        }

    def _load(self) -> list[dict[str, object]]:
        try:
            items = self.storage.load_auth_keys()
        except Exception as exc:  # noqa: BLE001
            # S-R1：原实现损坏时静默返回 [] → 所有用户密钥"消失"且无法定位根因。
            # 改为显式失败（与 json_storage 损坏抛错拒启语义一致），
            # 避免"所有登录失败但列表为空"的诡异状态。
            raise ValueError(f"auth_keys.json 读取失败：{exc}。请检查文件是否损坏。") from exc
        if not isinstance(items, list):
            raise ValueError("auth_keys.json 结构错误：应为列表")
        return [normalized for item in items if (normalized := self._normalize_item(item)) is not None]

    def _save(self) -> None:
        self.storage.save_auth_keys(self._items)

    def _reload_locked(self) -> None:
        self._items = self._load()

    @staticmethod
    def _public_item(item: dict[str, object]) -> dict[str, object]:
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "role": item.get("role"),
            "enabled": bool(item.get("enabled", True)),
            "created_at": item.get("created_at"),
            "last_used_at": item.get("last_used_at"),
            "usage_count": int(item.get("usage_count") or 0),
            "expires_at": item.get("expires_at"),
            "permissions": item.get("permissions", ["*"]),
            "quota": item.get("quota"),
            "quota_used": item.get("quota_used"),
        }

    def list_keys(self, role: AuthRole | None = None) -> list[dict[str, object]]:
        with self._lock:
            self._reload_locked()
            items = [item for item in self._items if role is None or item.get("role") == role]
            return [self._public_item(item) for item in items]

    def _has_key_hash_locked(self, key_hash: str, *, exclude_id: str = "") -> bool:
        for item in self._items:
            item_id = self._clean(item.get("id"))
            if exclude_id and item_id == exclude_id:
                continue
            stored_hash = self._clean(item.get("key_hash"))
            if stored_hash and hmac.compare_digest(stored_hash, key_hash):
                return True
        return False

    def _build_key_hash_locked(self, raw_key: str, *, exclude_id: str = "") -> str:
        candidate = self._clean(raw_key)
        if not candidate:
            raise ValueError("请输入新的专用密钥")
        admin_key = self._clean(config.auth_key)
        if admin_key and hmac.compare_digest(candidate, admin_key):
            raise ValueError("这个密钥和管理员密钥冲突了，请换一个新的密钥")
        key_hash = _hash_key(candidate)
        if self._has_key_hash_locked(key_hash, exclude_id=exclude_id):
            raise ValueError("这个专用密钥已经存在，请换一个新的密钥")
        return key_hash

    def _has_name_locked(self, name: str, *, role: AuthRole | None = None, exclude_id: str = "") -> bool:
        candidate = self._clean(name)
        if not candidate:
            return False
        for item in self._items:
            item_id = self._clean(item.get("id"))
            if exclude_id and item_id == exclude_id:
                continue
            if role is not None and item.get("role") != role:
                continue
            if self._clean(item.get("name")) == candidate:
                return True
        return False

    def _build_default_name_locked(self, role: AuthRole, *, exclude_id: str = "") -> str:
        base_name = self._default_name(role)
        if not self._has_name_locked(base_name, role=role, exclude_id=exclude_id):
            return base_name
        suffix = 2
        while True:
            candidate = f"{base_name} {suffix}"
            if not self._has_name_locked(candidate, role=role, exclude_id=exclude_id):
                return candidate
            suffix += 1

    def _build_name_locked(self, name: str, *, role: AuthRole, exclude_id: str = "") -> str:
        candidate = self._clean(name)
        if not candidate:
            return self._build_default_name_locked(role, exclude_id=exclude_id)
        if self._has_name_locked(candidate, role=role, exclude_id=exclude_id):
            raise ValueError("这个名称已经在使用中了，换一个更容易区分的名称吧")
        return candidate

    def create_key(
        self, *, role: AuthRole, name: str = "",
        expires_at: str | None = None,
        permissions: list[str] | None = None,
        quota: dict | None = None,
    ) -> tuple[dict[str, object], str]:
        with self._lock:
            self._reload_locked()
            normalized_name = self._build_name_locked(name, role=role)
            while True:
                raw_key = f"sk-{secrets.token_urlsafe(24)}"
                try:
                    key_hash = self._build_key_hash_locked(raw_key)
                    break
                except ValueError:
                    continue
            item = {
                "id": uuid.uuid4().hex[:12],
                "name": normalized_name,
                "role": role,
                "key_hash": key_hash,
                "enabled": True,
                "created_at": _now_iso(),
                "last_used_at": None,
                "usage_count": 0,
                "expires_at": expires_at,
                "permissions": permissions if isinstance(permissions, list) and permissions else ["*"],
                "quota": None,
                "quota_used": None,
            }
            if isinstance(quota, dict):
                normalized_quota = {
                    "daily_requests": quota.get("daily_requests"),
                    "daily_images": quota.get("daily_images"),
                    "monthly_requests": quota.get("monthly_requests"),
                    "monthly_images": quota.get("monthly_images"),
                    "reset_cycle": str(quota.get("reset_cycle") or "none").strip().lower(),
                }
                if normalized_quota["reset_cycle"] not in {"none", "daily", "monthly"}:
                    normalized_quota["reset_cycle"] = "none"
                for k in ("daily_requests", "daily_images", "monthly_requests", "monthly_images"):
                    v = normalized_quota[k]
                    if v is not None:
                        try:
                            normalized_quota[k] = int(v)
                        except (TypeError, ValueError):
                            normalized_quota[k] = None
                item["quota"] = normalized_quota
                item["quota_used"] = {"daily_requests": 0, "daily_images": 0, "monthly_requests": 0, "monthly_images": 0, "daily_reset_date": None, "monthly_reset_date": None}
            self._items.append(item)
            self._save()
            return self._public_item(item), raw_key

    def update_key(
        self,
        key_id: str,
        updates: dict[str, object],
        *,
        role: AuthRole | None = None,
    ) -> dict[str, object] | None:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                if role is not None and item.get("role") != role:
                    return None
                next_item = dict(item)
                next_role = "admin" if str(next_item.get("role") or "").strip().lower() == "admin" else "user"
                if "name" in updates and updates.get("name") is not None:
                    next_item["name"] = self._build_name_locked(
                        str(updates.get("name") or ""),
                        role=next_role,
                        exclude_id=normalized_id,
                    )
                if "enabled" in updates and updates.get("enabled") is not None:
                    next_item["enabled"] = bool(updates.get("enabled"))
                if "key" in updates and updates.get("key") is not None:
                    next_item["key_hash"] = self._build_key_hash_locked(str(updates.get("key") or ""), exclude_id=normalized_id)
                if "expires_at" in updates:
                    next_item["expires_at"] = self._clean(updates.get("expires_at")) or None
                if "permissions" in updates:
                    perms = updates.get("permissions")
                    next_item["permissions"] = perms if isinstance(perms, list) and perms else ["*"]
                if "quota" in updates:
                    q = updates.get("quota")
                    if isinstance(q, dict):
                        nq = {
                            "daily_requests": q.get("daily_requests"),
                            "daily_images": q.get("daily_images"),
                            "monthly_requests": q.get("monthly_requests"),
                            "monthly_images": q.get("monthly_images"),
                            "reset_cycle": str(q.get("reset_cycle") or "none").strip().lower(),
                        }
                        if nq["reset_cycle"] not in {"none", "daily", "monthly"}:
                            nq["reset_cycle"] = "none"
                        for k in ("daily_requests", "daily_images", "monthly_requests", "monthly_images"):
                            v = nq[k]
                            if v is not None:
                                try:
                                    nq[k] = int(v)
                                except (TypeError, ValueError):
                                    nq[k] = None
                        next_item["quota"] = nq
                        # 重置用量统计
                        next_item["quota_used"] = {"daily_requests": 0, "daily_images": 0, "monthly_requests": 0, "monthly_images": 0, "daily_reset_date": None, "monthly_reset_date": None}
                    else:
                        next_item["quota"] = None
                        next_item["quota_used"] = None
                self._items[index] = next_item
                self._save()
                return self._public_item(next_item)
        return None

    def delete_key(self, key_id: str, *, role: AuthRole | None = None) -> bool:
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return False
        with self._lock:
            self._reload_locked()
            before = len(self._items)
            self._items = [
                item
                for item in self._items
                if not (item.get("id") == normalized_id and (role is None or item.get("role") == role))
            ]
            if len(self._items) == before:
                return False
            self._save()
            return True

    def authenticate(self, raw_key: str) -> dict[str, object] | None:
        candidate = self._clean(raw_key)
        if not candidate:
            return None
        candidate_hash = _hash_key(candidate)
        with self._lock:
            for index, item in enumerate(self._items):
                if not bool(item.get("enabled", True)):
                    continue
                stored_hash = self._clean(item.get("key_hash"))
                if not stored_hash or not hmac.compare_digest(stored_hash, candidate_hash):
                    continue
                next_item = dict(item)
                now = datetime.now(UTC)
                next_item["last_used_at"] = now.isoformat()
                self._items[index] = next_item
                item_id = self._clean(next_item.get("id"))
                last_flush_at = self._last_used_flush_at.get(item_id)
                if last_flush_at is None or (now - last_flush_at).total_seconds() >= 60:
                    try:
                        self._save()
                        self._last_used_flush_at[item_id] = now
                    except Exception:
                        pass
                return self._public_item(next_item)
        return None

    def update_quota_used(self, key_id: str, api_type: str = "request", count: int = 1) -> None:
        """更新 Key 用量计数（原子操作，失败不冒泡）。"""
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return
        with self._lock:
            self._reload_locked()
            for index, item in enumerate(self._items):
                if item.get("id") != normalized_id:
                    continue
                next_item = dict(item)
                q = next_item.get("quota_used")
                if not isinstance(q, dict):
                    q = {"daily_requests": 0, "daily_images": 0, "monthly_requests": 0, "monthly_images": 0, "daily_reset_date": None, "monthly_reset_date": None}
                # 周期重置检测
                quota = next_item.get("quota")
                reset_cycle = "none"
                if isinstance(quota, dict):
                    reset_cycle = str(quota.get("reset_cycle") or "none")
                new_q = dict(q)
                if reset_cycle == "daily" and new_q.get("daily_reset_date") != today:
                    new_q["daily_requests"] = 0
                    new_q["daily_images"] = 0
                    new_q["daily_reset_date"] = today
                if reset_cycle == "monthly" and new_q.get("monthly_reset_date") != month:
                    new_q["monthly_requests"] = 0
                    new_q["monthly_images"] = 0
                    new_q["monthly_reset_date"] = month
                if api_type == "image":
                    new_q["daily_images"] = new_q.get("daily_images", 0) + count
                    new_q["monthly_images"] = new_q.get("monthly_images", 0) + count
                else:
                    new_q["daily_requests"] = new_q.get("daily_requests", 0) + count
                    new_q["monthly_requests"] = new_q.get("monthly_requests", 0) + count
                next_item["quota_used"] = new_q
                self._items[index] = next_item
                self._save()
                return

    def get_quota_used(self, key_id: str) -> dict | None:
        """获取 Key 用量统计。"""
        normalized_id = self._clean(key_id)
        if not normalized_id:
            return None
        with self._lock:
            for item in self._items:
                if item.get("id") == normalized_id:
                    q = item.get("quota_used")
                    if isinstance(q, dict):
                        return dict(q)
                    return None
        return None


auth_service = AuthService(config.get_storage_backend())