from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.prometheus_metrics import storage_operation_timer
from services.storage.base import StorageBackend


def _atomic_write_text(file_path: Path, content: str, *, retries: int = 5) -> None:
    """原子写文本文件：唯一 tmp + replace，Windows 瞬态锁重试。

    - tmp 名带 pid+uuid，并发写者互不干扰；
    - replace 为同文件系统原子操作，读者只见完整旧版或完整新版；
    - Windows 上读者持句柄时 replace 偶发 WinError 5/32（瞬态），短暂退避重试；
      重试耗尽抛错（调用方感知失败），tmp 残留不破坏原文件；
    - 注意：并发写者之间不保证顺序语义（最后 replace 者赢），与整文件覆写模型一致。
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f".{file_path.name}.{os.getpid()}.{uuid4().hex[:8]}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    try:
        for attempt in range(retries):
            try:
                tmp_path.replace(file_path)
                return
            except PermissionError:
                if attempt == retries - 1:
                    raise
                time.sleep(0.05 * (2 ** attempt))
    finally:
        tmp_path.unlink(missing_ok=True)


class JSONStorageBackend(StorageBackend):
    """本地 JSON 文件存储后端"""

    def __init__(self, file_path: Path, auth_keys_path: Path | None = None):
        self.file_path = file_path
        self.auth_keys_path = auth_keys_path or file_path.with_name("auth_keys.json")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _load_json_list(file_path: Path) -> list[dict[str, Any]]:
        """加载 JSON 数组文件。

        安全语义：文件存在但损坏时**抛错**而非静默返回空——否则会出现
        "监控全绿但账号池被清空"的事故（第七轮 B7：health_check 报 healthy、
        服务照常运行、账号静默为空）。文件不存在属正常首启，返回空。
        """
        if not file_path.exists():
            return []
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"存储文件损坏: {file_path}（第 {exc.lineno} 行: {exc.msg}）。"
                "请从备份恢复或手工修复后重启——为避免静默丢数据，服务拒绝继续。"
            ) from exc
        except OSError as exc:
            raise ValueError(f"存储文件读取失败: {file_path} - {exc}") from exc
        if not isinstance(data, list):
            raise ValueError(f"存储文件格式错误: {file_path} 顶层必须是 JSON 数组")
        return data

    @staticmethod
    def _save_json_list(file_path: Path, items: list[dict[str, Any]]) -> None:
        """原子写（第七轮 B6）：防半写损坏 + Windows 瞬态锁重试。"""
        _atomic_write_text(
            file_path,
            json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        )

    @staticmethod
    def _save_content_if_changed(file_path: Path, content: str) -> None:
        """内容去重写（III-04）：磁盘内容与新内容一致时跳过原子写。

        账号状态周期刷新（健康检查/心跳）若数据未变，直接读比对后跳过，
        避免无谓的整文件覆写（慢查询猎杀热点「账号存储整文件覆写」）。
        读失败（OSError）回退正常原子写——不允许因比较失败而丢写。
        """
        try:
            if file_path.exists() and file_path.read_text(encoding="utf-8") == content:
                return
        except OSError:
            pass
        _atomic_write_text(file_path, content)

    def load_accounts(self) -> list[dict[str, Any]]:
        """从 JSON 文件加载账号数据"""
        with storage_operation_timer("json", "load_accounts"):
            return self._load_json_list(self.file_path)

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存账号数据到 JSON 文件（内容未变时跳过写盘）"""
        content = json.dumps(accounts, ensure_ascii=False, indent=2) + "\n"
        with storage_operation_timer("json", "save_accounts"):
            self._save_content_if_changed(self.file_path, content)

    def load_auth_keys(self) -> list[dict[str, Any]]:
        """从 JSON 文件加载鉴权密钥数据（损坏时抛错，同 _load_json_list 语义）"""
        with storage_operation_timer("json", "load_auth_keys"):
            if not self.auth_keys_path.exists():
                return []
            try:
                data = json.loads(self.auth_keys_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"密钥存储文件损坏: {self.auth_keys_path}（第 {exc.lineno} 行: {exc.msg}）。"
                    "请从备份恢复或手工修复后重启——为避免静默丢密钥，服务拒绝继续。"
                ) from exc
            except OSError as exc:
                raise ValueError(f"密钥存储文件读取失败: {self.auth_keys_path} - {exc}") from exc
            if isinstance(data, dict):
                data = data.get("items")
            if not isinstance(data, list):
                raise ValueError(f"密钥存储文件格式错误: {self.auth_keys_path}")
            return data

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存鉴权密钥数据到 JSON 文件（原子写，内容未变时跳过写盘）"""
        content = json.dumps({"items": auth_keys}, ensure_ascii=False, indent=2) + "\n"
        with storage_operation_timer("json", "save_auth_keys"):
            self._save_content_if_changed(self.auth_keys_path, content)

    def health_check(self) -> dict[str, Any]:
        """健康检查：可读+可解析才算 healthy（损坏必须报 unhealthy，第七轮 B7）"""
        with storage_operation_timer("json", "health_check"):
            try:
                if self.file_path.exists():
                    json.loads(self.file_path.read_text(encoding="utf-8"))
                if self.auth_keys_path.exists():
                    json.loads(self.auth_keys_path.read_text(encoding="utf-8"))
                return {
                    "status": "healthy",
                    "backend": "json",
                    "file_exists": self.file_path.exists(),
                    "file_path": str(self.file_path),
                    "auth_keys_file_exists": self.auth_keys_path.exists(),
                    "auth_keys_file_path": str(self.auth_keys_path),
                }
            except Exception as e:
                return {
                    "status": "unhealthy",
                    "backend": "json",
                    "error": str(e),
                }

    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        return {
            "type": "json",
            "description": "本地 JSON 文件存储",
            "file_path": str(self.file_path),
            "file_exists": self.file_path.exists(),
            "auth_keys_file_path": str(self.auth_keys_path),
            "auth_keys_file_exists": self.auth_keys_path.exists(),
        }
