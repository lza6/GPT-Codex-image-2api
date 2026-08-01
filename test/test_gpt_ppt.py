from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import uuid4

BASE_URL = "http://127.0.0.1:23456"
PROMPT = "生成一份 2026 年 Q2 电商运营复盘 PPT，8 页以内，商务科技风，包含销售、用户、渠道、广告、618 活动和 Q3 规划。"
BASE64_IMAGES: list[str] = []
TIMEOUT_SECS = 600
POLL_INTERVAL_SECS = 5


def request_json(method: str, path: str, payload: dict | None = None) -> dict:
    api_key = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))["auth-key"]
    if not api_key.strip():
        raise ValueError("API_KEY is empty")
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(
        BASE_URL.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8", "replace")) from exc


def main() -> None:
    task = request_json("POST", "/v1/ppt/generations", {
        "client_task_id": str(uuid4()),
        "prompt": PROMPT,
        "base64_images": BASE64_IMAGES,
    })
    task_id = str(task.get("taskId") or task.get("id") or "")
    if not task_id:
        raise RuntimeError(f"missing taskId: {task}")
    print(json.dumps(task, ensure_ascii=False, indent=2))
    deadline = time.time() + TIMEOUT_SECS
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_SECS)
        status = request_json("GET", "/v1/editable-file-tasks?ids=" + urllib.parse.quote(task_id))
        print(json.dumps(status, ensure_ascii=False, indent=2))
        item = (status.get("items") or [{}])[0]
        if item.get("status") in {"success", "error"}:
            return
    raise TimeoutError(f"task timeout: {task_id}")


if __name__ == "__main__":
    main()
