from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

MAX_INDEX_ENTRIES = 100_000
PERSIST_INTERVAL_SECONDS = 60


class InvertedIndex:
    """日志倒排索引：按 request_id 和 account_email 快速定位日志行。"""

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = Path(log_dir)
        self._index_file = self._log_dir / "log_index.json"
        self._lock = threading.Lock()
        self._by_request_id: dict[str, list[tuple[str, int, int]]] = {}
        self._by_account_email: dict[str, list[tuple[str, int, int]]] = {}
        self._insert_order: OrderedDict[str, None] = OrderedDict()
        self._last_persist_ts: float = 0.0
        self._total_entries = 0
        self._load()

    def add_entry(self, request_id: str, file_path: str, byte_offset: int, length: int, account_email: str = "") -> None:
        if not request_id:
            return
        loc = (file_path, byte_offset, length)
        with self._lock:
            if request_id not in self._by_request_id:
                self._by_request_id[request_id] = []
                self._insert_order[request_id] = None
                self._total_entries += 1
            self._by_request_id[request_id].append(loc)
            if account_email:
                self._by_account_email.setdefault(account_email, []).append(loc)
            while self._total_entries > MAX_INDEX_ENTRIES:
                self._evict_one()

    def lookup(self, request_id: str) -> list[tuple[str, int, int]]:
        with self._lock:
            return list(self._by_request_id.get(request_id, []))

    def lookup_by_email(self, email: str) -> list[tuple[str, int, int]]:
        with self._lock:
            return list(self._by_account_email.get(email, []))

    def read_entry(self, file_path: str, byte_offset: int, length: int) -> str | None:
        try:
            with open(file_path, "rb") as f:
                f.seek(byte_offset)
                raw = f.read(length)
                return raw.decode("utf-8", errors="replace")
        except OSError:
            return None

    def read_entries(self, locations: list[tuple[str, int, int]]) -> list[str]:
        results: list[str] = []
        for fp, bo, ln in locations:
            line = self.read_entry(fp, bo, ln)
            if line is not None:
                results.append(line)
        return results

    def maybe_persist(self) -> None:
        now = time.time()
        if now - self._last_persist_ts >= PERSIST_INTERVAL_SECONDS:
            self.persist()

    def persist(self) -> None:
        with self._lock:
            data = {
                "by_request_id": {k: v for k, v in self._by_request_id.items()},
                "by_account_email": {k: v for k, v in self._by_account_email.items()},
                "insert_order": list(self._insert_order.keys()),
            }
            self._last_persist_ts = time.time()
        try:
            from services.storage.json_storage import _atomic_write_text
            _atomic_write_text(self._index_file, json.dumps(data, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _evict_one(self) -> None:
        if not self._insert_order:
            return
        oldest_key, _ = self._insert_order.popitem(last=False)
        locations = self._by_request_id.pop(oldest_key, [])
        self._total_entries -= 1
        if locations:
            loc_set = set(locations)
            for email in list(self._by_account_email.keys()):
                remaining = [loc for loc in self._by_account_email[email] if loc not in loc_set]
                if remaining:
                    self._by_account_email[email] = remaining
                else:
                    del self._by_account_email[email]

    def _load(self) -> None:
        if not self._index_file.exists():
            return
        try:
            raw = self._index_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            with self._lock:
                self._by_request_id = {k: [tuple(v) for v in val] for k, val in data.get("by_request_id", {}).items()}
                self._by_account_email = {k: [tuple(v) for v in val] for k, val in data.get("by_account_email", {}).items()}
                self._insert_order = OrderedDict.fromkeys(data.get("insert_order", []))
                self._total_entries = len(self._by_request_id)
        except Exception:
            self._by_request_id = {}
            self._by_account_email = {}
            self._insert_order = OrderedDict()
            self._total_entries = 0

    def clear(self) -> None:
        with self._lock:
            self._by_request_id.clear()
            self._by_account_email.clear()
            self._insert_order.clear()
            self._total_entries = 0
            self._last_persist_ts = 0.0