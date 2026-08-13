"""邮箱池管理：解析并持有预置邮箱凭据，线程安全地 acquire/release。

条目格式（一行一条，与 chatgpt2api 既有 `mail_credential` 语义对齐）：

    邮箱----密码----client_id----refresh_token

- `email`：收件邮箱地址（如 outlook.com 微软邮箱）
- `password`：该邮箱的密码（取件时备用）
- `client_id` + `refresh_token`：微软 MSAL 取件凭证（复用 otp_login_service 的
  Graph 直连取件链路，`client_id` 换 Graph access_token → Mail.Read 读收件箱）

三种来源：
1. `registration.grok.email_pool`：config.json 数组
2. `registration.grok.email_pool_file`：外部文本文件（每行一条，支持热重载）
3. 两者均空 → 池为空，注册改走 luckmail/gptmail 购买或生成邮箱
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

_SEPARATOR = "----"


def parse_pool_line(line: str) -> Optional[dict[str, str]]:
    """解析一行 `邮箱----密码----client_id----refresh_token`，非法行返回 None。"""
    if not line or not isinstance(line, str):
        return None
    parts = [p.strip() for p in line.split(_SEPARATOR)]
    email = parts[0] if parts else ""
    if not email or "@" not in email:
        return None
    return {
        "email": email,
        "password": parts[1] if len(parts) > 1 else "",
        "client_id": parts[2] if len(parts) > 2 else "",
        "refresh_token": parts[3] if len(parts) > 3 else "",
    }


def _normalize_entry(item: Any) -> Optional[dict[str, str]]:
    """把数组里的 dict 或字符串统一成标准条目。"""
    if isinstance(item, dict):
        email = str(item.get("email") or "").strip()
        if not email or "@" not in email:
            return None
        return {
            "email": email,
            "password": str(item.get("password") or "").strip(),
            "client_id": str(item.get("client_id") or "").strip(),
            "refresh_token": str(item.get("refresh_token") or "").strip(),
        }
    return parse_pool_line(str(item))


class EmailPool:
    """预置邮箱凭据池（进程内，acquire/release 加锁）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, str]] = []
        self._busy: set[str] = set()
        self._consumed: set[str] = set()

    def reload(self, entries: list[Any], pool_file: str = "") -> None:
        """从 config 数组 + 可选文件重载池（调用方每次注册前调用一次）。"""
        parsed: list[dict[str, str]] = []
        for item in entries or []:
            entry = _normalize_entry(item)
            if entry:
                parsed.append(entry)
        if pool_file:
            try:
                path = Path(pool_file)
                for line in path.read_text(encoding="utf-8").splitlines():
                    entry = parse_pool_line(line)
                    if entry:
                        parsed.append(entry)
            except OSError:
                pass
        with self._lock:
            # 去重 + 过滤已消耗
            seen: set[str] = set()
            fresh: list[dict[str, str]] = []
            for entry in parsed:
                key = entry["email"].lower()
                if key in seen or key in self._consumed:
                    continue
                seen.add(key)
                fresh.append(entry)
            self._entries = fresh
            self._busy = {k for k in self._busy if k in seen}
        return None

    def acquire(self) -> Optional[dict[str, str]]:
        """取一个空闲条目（标 busy），无空闲返回 None。"""
        with self._lock:
            for entry in self._entries:
                key = entry["email"].lower()
                if key not in self._busy and key not in self._consumed:
                    self._busy.add(key)
                    return dict(entry)
        return None

    def release(self, email: str) -> None:
        """失败归还（取消 busy 标记，允许下次再用）。"""
        with self._lock:
            self._busy.discard(str(email or "").strip().lower())

    def consume(self, email: str) -> None:
        """注册成功后消耗（永久移除，后续批次不再用该邮箱）。"""
        with self._lock:
            key = str(email or "").strip().lower()
            self._busy.discard(key)
            self._consumed.add(key)
            self._entries = [e for e in self._entries if e["email"].lower() != key]

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def available(self) -> int:
        with self._lock:
            return len(self._entries) - len(self._busy)

    def snapshot(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(e) for e in self._entries]
