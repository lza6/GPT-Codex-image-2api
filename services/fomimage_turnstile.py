"""fomimage Turnstile 求解器（v2.36.0）：cf_solver（camoufox 真实浏览器）优先 + YesCaptcha 兜底。

学习 imagefree-2ai 过 CF 方案：cf_solver 是 FastAPI + camoufox 反检测浏览器子服务，
真实浏览器加载 Turnstile widget 自动完成挑战，读取 cf-turnstile-response 值即 token。
（数据中心 IP 也能过——靠浏览器指纹/行为，不依赖 IP 信誉。）

cf_solver 契约（http://<host>:8001）：
  GET /turnstile?url=&sitekey=  → 202 {task_id, status:"accepted"}
  GET /result?id=<task_id>      → 200 {status:"success", value:<token>}
                                → 202 处理中 / 404 过期 / 408 超时 / 422 失败

返回的 token 与 cf_solver 出口 IP 绑定；若提交端 IP 与之一致成功率更高。
"""
from __future__ import annotations

import time

import requests

# fromimage 的 Cloudflare Turnstile sitekey（首页 HTML turnstile_site_key，2026-08-15）
FROMIMAGE_TURNSTILE_SITEKEY = "0x4AAAAAAEP4Cgtdy3L61Coz"
FROMIMAGE_URL = "https://fromimage.ai"

# cf_solver 默认地址（与 chatgpt2api 同机/同网时容器名；可配置覆盖）
DEFAULT_CF_SOLVER_URL = "http://imagefree-cfsolver:8001"

_POLL_INTERVAL = 2.0
_MAX_WAIT = 90.0


class TurnstileSolveError(RuntimeError):
    pass


def solve_with_cf_solver(cf_solver_url: str, url: str, sitekey: str, timeout: float = 90.0) -> str:
    """用 cf_solver（camoufox 真实浏览器）解 Turnstile token。失败抛 TurnstileSolveError。"""
    base = str(cf_solver_url or "").strip().rstrip("/")
    if not base:
        raise TurnstileSolveError("cf_solver_url 未配置")
    try:
        resp = requests.get(
            f"{base}/turnstile",
            params={"url": url, "sitekey": sitekey},
            timeout=15,
        )
    except Exception as exc:
        raise TurnstileSolveError(f"cf_solver 创建任务失败: {exc}") from exc
    if resp.status_code != 202:
        raise TurnstileSolveError(f"cf_solver 创建任务 HTTP {resp.status_code}: {resp.text[:160]}")
    task_id = str((resp.json() or {}).get("task_id") or "")
    if not task_id:
        raise TurnstileSolveError("cf_solver 响应缺 task_id")

    deadline = time.monotonic() + min(timeout, _MAX_WAIT)
    while time.monotonic() < deadline:
        try:
            result = requests.get(f"{base}/result", params={"id": task_id}, timeout=30)
        except Exception:
            time.sleep(_POLL_INTERVAL)
            continue
        data = result.json() if result.text else {}
        if result.status_code == 200:
            value = str((data or {}).get("value") or "")
            if value and value != "captcha_fail":
                return value
            raise TurnstileSolveError(f"cf_solver 求解失败: {data}")
        if result.status_code in (404, 408, 422):
            raise TurnstileSolveError(f"cf_solver 求解失败 HTTP {result.status_code}: {data}")
        time.sleep(_POLL_INTERVAL)
    raise TurnstileSolveError("cf_solver 求解超时")


def solve_with_yescaptcha(yescaptcha_key: str, url: str, sitekey: str, max_attempts: int = 2) -> str | None:
    """YesCaptcha 打码平台兜底（无 key 返回 None）。"""
    if not yescaptcha_key:
        return None
    try:
        from services.registration.grok.captcha import TurnstileService

        service = TurnstileService(yescaptcha_key)
        for _ in range(max_attempts):
            try:
                task_id = service.create_task(url, sitekey)
                token = service.get_response(task_id)
                if token and token != "CAPTCHA_FAIL":
                    return token
            except Exception:
                continue
    except Exception:
        return None
    return None


def solve_turnstile(
    cf_solver_url: str,
    yescaptcha_key: str,
    url: str = FROMIMAGE_URL,
    sitekey: str = FROMIMAGE_TURNSTILE_SITEKEY,
) -> str | None:
    """综合求解：cf_solver（真实浏览器）优先，YesCaptcha 兜底。全失败返回 None。"""
    if cf_solver_url:
        try:
            return solve_with_cf_solver(cf_solver_url, url, sitekey)
        except TurnstileSolveError:
            pass
    if yescaptcha_key:
        token = solve_with_yescaptcha(yescaptcha_key, url, sitekey)
        if token:
            return token
    return None
