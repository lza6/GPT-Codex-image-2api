"""YesCaptcha Turnstile 求解服务（移植 grok-register/YesCaptcha_service.py，配置驱动）。

仅 grok 注册启用时实例化（coordinator 惰性 import），默认关闭时不加载。
"""
from __future__ import annotations

import time

import requests

YESCAPTCHA_API = "https://api.yescaptcha.com"
YESCAPTCHA_SOFT_ID = 102154


class TurnstileService:
    """YesCaptcha 创建/轮询 Turnstile 任务（Proxyless 模式，走本机出口）。"""

    def __init__(self, client_key: str) -> None:
        if not client_key:
            raise ValueError("缺少 yescaptcha_key，无法创建 Turnstile 任务")
        self.client_key = client_key

    def create_task(self, siteurl: str, sitekey: str) -> str:
        url = f"{YESCAPTCHA_API}/createTask"
        payload = {
            "clientKey": self.client_key,
            "task": {
                "type": "TurnstileTaskProxyless",
                "websiteURL": siteurl,
                "websiteKey": sitekey,
            },
            "softID": YESCAPTCHA_SOFT_ID,
        }
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("errorId") != 0:
            raise RuntimeError(f"YesCaptcha创建任务失败: {data.get('errorDescription')}")
        return str(data["taskId"])

    def get_response(self, task_id: str, max_retries: int = 30, initial_delay: float = 5.0, retry_delay: float = 2.0):
        """轮询任务结果，返回 token 或 None（失败/超时）。"""
        time.sleep(initial_delay)
        for _ in range(max_retries):
            try:
                url = f"{YESCAPTCHA_API}/getTaskResult"
                payload = {"clientKey": self.client_key, "taskId": task_id}
                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()
                data = response.json()
                if data.get("errorId") != 0:
                    return None
                status = data.get("status")
                if status == "ready":
                    token = data.get("solution", {}).get("token")
                    return token if token else None
                if status == "processing":
                    time.sleep(retry_delay)
                else:
                    time.sleep(retry_delay)
            except Exception:
                time.sleep(retry_delay)
        return None
