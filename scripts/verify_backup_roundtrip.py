#!/usr/bin/env python3
"""C1/P0-4：备份恢复演练自动化（verify_backup_roundtrip）。

不触网、不调 R2：直接调用 BackupService._build_backup_archive 在内存中打包，
再 tarfile 解包逐项校验 manifest 与各启用项内容齐全、可解析、sha256 一致。
证明"备份产物可恢复"——打包/解包往返零丢失。

用法：
    .venv/Scripts/python.exe scripts/verify_backup_roundtrip.py
退出码：0 = 演练通过；1 = 演练失败（输出缺失项）。
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

# 项目根目录入 path（scripts/ 下直接跑）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.backup_service import backup_service  # noqa: E402
from services.config import config  # noqa: E402


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_roundtrip() -> dict[str, object]:
    settings = dict(config.get_backup_settings())
    # 演练全开所有 include 项，验证最完整打包路径
    include = settings.get("include") if isinstance(settings.get("include"), dict) else {}
    full_include = {k: True for k in ("config", "cpa", "sub2api", "logs", "image_tasks", "accounts_snapshot", "auth_keys_snapshot", "images")}
    settings["include"] = {**include, **full_include}

    archive_bytes = backup_service._build_backup_archive(settings, trigger="verify_roundtrip")
    assert archive_bytes[:2] == b"\x1f\x8b", "备份包必须是 gzip（tar.gz）"

    entries: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile():
                extracted = tar.extractfile(member)
                entries[member.name] = extracted.read() if extracted else b""

    # 1. manifest 必须存在且可解析
    assert "backup-metadata.json" in entries, "缺 backup-metadata.json"
    manifest = json.loads(entries["backup-metadata.json"].decode("utf-8"))
    assert manifest.get("version") == 2, f"manifest version 应为 2，实际 {manifest.get('version')}"
    assert manifest.get("trigger") == "verify_roundtrip"

    # 2. 源文件 vs 包内 sha256 一致性（存在的源文件必须无损打包）
    checks: list[dict[str, object]] = []

    def _check_file(arcname: str, source: Path) -> None:
        if not source.exists():
            checks.append({"item": arcname, "status": "skip", "reason": "源文件不存在"})
            return
        assert arcname in entries, f"包内缺 {arcname}（源文件存在）"
        src_bytes = source.read_bytes()
        ok = _sha256(src_bytes) == _sha256(entries[arcname])
        checks.append({
            "item": arcname,
            "status": "pass" if ok else "FAIL",
            "source_bytes": len(src_bytes),
            "archived_bytes": len(entries[arcname]),
            "sha256_match": ok,
        })
        assert ok, f"{arcname} sha256 不一致（打包损坏）"

    from services.config import CONFIG_FILE, DATA_DIR
    _check_file("config.json", CONFIG_FILE)
    # 4.1：日志按天切分，校验全部天文件（logs-*.jsonl）；无天文件时跳过（不强制）
    daily_logs = sorted(DATA_DIR.glob("logs-*.jsonl"))
    if daily_logs:
        for log_path in daily_logs:
            _check_file(f"data/{log_path.name}", log_path)
    else:
        checks.append({"item": "data/logs-*.jsonl", "status": "skip", "reason": "当前无天文件"})
    _check_file("data/image_tasks.json", DATA_DIR / "image_tasks.json")

    # 3. 快照项：JSON 可解析
    for snap in ("snapshots/accounts.json", "snapshots/auth_keys.json"):
        assert snap in entries, f"缺快照 {snap}"
        json.loads(entries[snap].decode("utf-8"))
        checks.append({"item": snap, "status": "pass", "parse": "json ok"})

    return {
        "status": "pass",
        "archive_bytes": len(archive_bytes),
        "archive_sha256": _sha256(archive_bytes),
        "entries": sorted(entries.keys()),
        "checks": checks,
        "manifest": manifest,
    }


def main() -> int:
    try:
        result = run_roundtrip()
    except AssertionError as exc:
        print(f"[FAIL] 备份恢复演练失败: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 备份恢复演练异常: {type(exc).__name__}: {exc}")
        return 1

    print("[PASS] 备份恢复演练通过")
    print(f"  包大小: {result['archive_bytes']} bytes, sha256: {result['archive_sha256'][:16]}...")
    print(f"  打包条目: {len(result['entries'])}")
    for check in result["checks"]:  # type: ignore[union-attr]
        print(f"  - {check['item']}: {check['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
