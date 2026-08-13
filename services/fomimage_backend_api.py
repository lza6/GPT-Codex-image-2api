"""fomimage（FromImage AI）上游客户端（v2.36.0）。

职责：图片生成/编辑全链路上游调用——参考图上传、创建生成任务、轮询结果、查余额。
与 chatgpt2api 既有 OpenAIBackendAPI 并列，由 protocol 层按 account.provider=="fomimage" 分派。

认证：注册/登录时 fromimage 服务端下发会话 cookie（_session 持有），业务接口凭 cookie 即可。
每账号独立出口 IP：构造时传入 proxy（注册引擎按邮箱 resolve_account_proxy 分配，生成时读账号 proxy）。

真实契约（2026-08-13 实测）：
    POST /api/storage/upload-image  multipart files[] -> {urls[], results[]}
    POST /api/ai/image-tasks/        {modelId,prompt,images[],options:{...}} -> {id,status,costCredits}
    GET  /api/ai/image-tasks/{id}    -> {status:pending|processing|success|failed, images[], costCredits}
    GET  /api/credits/balance        -> {code:0,data:{balance}}
响应统一包裹 {code,message,data}；code!=0 抛 FomimageApiError。
"""
from __future__ import annotations

import time
from typing import Any

from curl_cffi import requests as cffi_requests

from services.fomimage_pricing import upstream_model_id

BASE_URL = "https://fromimage.ai"
IMAGES_BASE_URL = "https://images.fromimage.ai"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

# 任务轮询：无数据/<30s 2.5s，30-90s 5s，>90s 10s（对齐前端 alert-C8vENeqy.js v 函数）
POLL_FRESH_SEC = 30
POLL_WARM_SEC = 90
POLL_FRESH_INTERVAL = 2.5
POLL_WARM_INTERVAL = 5.0
POLL_COLD_INTERVAL = 10.0
DEFAULT_POLL_TIMEOUT = 240


class FomimageApiError(RuntimeError):
    """fomimage 上游业务错误（code!=0 或 HTTP 错误）。"""

    def __init__(self, message: str = "", code: int = -1, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class FomimageTaskError(FomimageApiError):
    """图片任务失败（status=failed 携带上游错误信息）。"""


def _proxies(proxy: str = "") -> dict[str, str] | None:
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


class FomimageBackendAPI:
    """fomimage 上游客户端。每个实例绑定一个账号（cookie 会话）+ 可选独立出口 IP。"""

    def __init__(
        self,
        access_token: str = "",
        email: str = "",
        proxy: str = "",
        cookies: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        # access_token 为 sign-in 返回的会话 token（仅用于关联号池记录，请求凭 cookie）
        self.access_token = access_token
        self.email = email
        self.proxy = proxy
        self.timeout = timeout
        self._session = cffi_requests.Session(impersonate="chrome131")
        if proxy:
            self._session.proxies.update(_proxies(proxy) or {})
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
            "Origin": BASE_URL,
            "Referer": BASE_URL + "/",
        })
        # 恢复注册时的 fromimage 会话 cookie（业务接口凭 cookie 认证，缺失则上游 401）
        if cookies:
            for name, value in cookies.items():
                if name and value:
                    self._session.cookies.set(name, str(value), domain=".fromimage.ai")
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._session.close()
        except Exception:
            pass

    def __enter__(self) -> FomimageBackendAPI:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── 内部请求 ──────────────────────────────────────────────────

    def _request_json(self, method: str, path: str, *, json_body: Any = None, timeout: float | None = None) -> Any:
        url = BASE_URL + path
        try:
            response = self._session.request(
                method,
                url,
                json=json_body,
                timeout=timeout or self.timeout,
            )
        except Exception as exc:
            raise FomimageApiError(f"fomimage 请求失败: {exc}", code=-2) from exc
        try:
            payload = response.json()
        except Exception:
            raise FomimageApiError(f"fomimage 响应非 JSON: {response.status_code} {response.text[:200]}", code=-3) from None
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise FomimageApiError(
                str(payload.get("message") or "fomimage 业务错误"),
                code=int(payload.get("code") or -1),
                data=payload.get("data"),
            )
        # 非 {code,...} 包裹（如 auth 接口直接返回业务对象）
        return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

    # ── 认证态（登录后调用，cookie 已在 session）──────────────────

    def get_balance(self) -> int:
        """当前账号积分余额（注册送 50；用完为 0）。失败抛错。"""
        data = self._request_json("GET", "/api/credits/balance")
        try:
            return int((data or {}).get("balance") or 0)
        except (TypeError, ValueError):
            return 0

    def get_user(self) -> dict[str, Any]:
        """当前账号资料（含 emailVerified 等）。"""
        data = self._request_json("GET", "/api/auth/get-session")
        return data if isinstance(data, dict) else {}

    # ── 参考图上传 ────────────────────────────────────────────────

    def upload_images(self, files: list[tuple[bytes, str, str]]) -> list[str]:
        """上传参考图（multipart files[]），返回上游 URL 列表（顺序对应）。"""
        if not files:
            return []
        try:
            from curl_cffi import CurlMime

            mime = CurlMime()
            for data, name, mime_type in files:
                mime.addpart(name="files", filename=name, content_type=mime_type, data=data)
            response = self._session.post(
                BASE_URL + "/api/storage/upload-image",
                multipart=mime,
                timeout=max(60.0, self.timeout * 2),
            )
        except Exception as exc:
            raise FomimageApiError(f"fomimage 上传失败: {exc}", code=-4) from exc
        try:
            payload = response.json()
        except Exception:
            raise FomimageApiError(f"fomimage 上传响应非 JSON: {response.status_code} {response.text[:200]}", code=-5) from None
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise FomimageApiError(
                str(payload.get("message") or "fomimage 上传失败"),
                code=int(payload.get("code") or -1),
            )
        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        urls = []
        if isinstance(data, dict):
            urls = [str(u) for u in (data.get("urls") or []) if str(u)]
        return urls

    # ── 生成任务 ──────────────────────────────────────────────────

    def create_task(
        self,
        model: str,
        prompt: str,
        image_urls: list[str] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """创建生成/编辑任务。返回 {id, status, costCredits, ...}。"""
        upstream_model = upstream_model_id(model)
        body = {
            "modelId": upstream_model,
            "prompt": prompt,
            "images": image_urls or [],
            "options": options or {},
        }
        data = self._request_json("POST", "/api/ai/image-tasks/", json_body=body, timeout=60.0)
        if not isinstance(data, dict):
            raise FomimageApiError("fomimage 创建任务返回异常", code=-6, data=data)
        return data

    def get_task(self, task_id: str) -> dict[str, Any]:
        """查询任务状态（pending/processing/success/failed）。"""
        data = self._request_json("GET", f"/api/ai/image-tasks/{task_id}")
        if not isinstance(data, dict):
            raise FomimageApiError("fomimage 任务查询返回异常", code=-7, data=data)
        return data

    def poll_task(self, task_id: str, timeout: float = DEFAULT_POLL_TIMEOUT) -> dict[str, Any]:
        """轮询任务到终态。返回终态 dict；超时抛 FomimageTaskError。
        间隔对齐前端：<30s 2.5s，30-90s 5s，>90s 10s。
        """
        created_at = time.time()
        while True:
            task = self.get_task(task_id)
            status = str(task.get("status") or "pending")
            if status in {"success", "failed", "canceled"}:
                if status != "success":
                    raise FomimageTaskError(
                        str(task.get("error") or f"fomimage 任务 {status}"),
                        code=-8,
                        data=task,
                    )
                return task
            if time.time() - created_at > timeout:
                raise FomimageTaskError(
                    f"fomimage 任务轮询超时（{int(timeout)}s）",
                    code=-9,
                    data={"id": task_id, "status": status},
                )
            elapsed = time.time() - created_at
            if elapsed < POLL_FRESH_SEC:
                interval = POLL_FRESH_INTERVAL
            elif elapsed < POLL_WARM_SEC:
                interval = POLL_WARM_INTERVAL
            else:
                interval = POLL_COLD_INTERVAL
            time.sleep(interval)

    # ── 结果图片处理 ──────────────────────────────────────────────

    @staticmethod
    def download_image(url: str, proxy: str = "", timeout: float = 60.0) -> bytes:
        """下载上游结果图（images.fromimage.ai 直链，跨域需带 UA）。返回字节。"""
        import requests as std_requests

        proxies = _proxies(proxy)
        response = std_requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Referer": BASE_URL + "/"},
            proxies=proxies,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.content
