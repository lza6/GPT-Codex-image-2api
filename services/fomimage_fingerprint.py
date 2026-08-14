"""fomimage 一号一指纹（v2.36.0）。

为规避风控，每账号注册/调用使用**独立随机指纹**（TLS JA3 指纹 + UA + 设备特征）：
- impersonate：curl_cffi 支持的浏览器指纹随机选（实测 chrome110/116/120/124/131/edge101）
- user-agent：与该 impersonate 匹配的真实 UA
- 设备特征：Sec-Ch-Ua 平台/移动端随机

`random_fingerprint()` 返回 {impersonate, user_agent, headers_extra}，注册引擎与上游
客户端构造 Session 时按账号绑定（粘性：同一邮箱固定指纹，不随请求漂移）。
"""
from __future__ import annotations

import random
from typing import Any

# curl_cffi 实测支持的 impersonate（0.15.0）——均通过 api.ipify.org 连通性验证
_IMPRESONATE_OPTIONS: tuple[str, ...] = (
    "chrome110",
    "chrome116",
    "chrome120",
    "chrome124",
    "chrome131",
    "edge101",
)

# impersonate → 匹配的真实 UA（与 TLS 指纹一致，避免指纹不一致被识别）
_UA_MAP: dict[str, str] = {
    "chrome110": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    ),
    "chrome116": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
    ),
    "chrome120": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "chrome124": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "chrome131": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "edge101": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    ),
}

# 平台特征（UA 与 Sec-Ch-Ua-Platform 需一致）
_PLATFORMS: tuple[tuple[str, str], ...] = (
    ("Windows", '"Windows"'),
    ("Macintosh", '"macOS"'),
    ("X11; Linux x86_64", '"Linux"'),
)

# 可注入的 UA 微变体（数字/版本尾巴随机，降低整批 UA 完全相同概率）
_UA_TAILS: tuple[str, ...] = (
    "",
    " Chrome/131.0.0.0 Safari/537.36",
    " Chrome/130.0.0.0 Safari/537.36",
    " Chrome/129.0.0.0 Safari/537.36",
    " Edg/131.0.0.0",
    " Edg/130.0.0.0",
)


def available_impersonates() -> tuple[str, ...]:
    """可用指纹清单（前端展示/健康探测用）。"""
    return _IMPRESONATE_OPTIONS


def pick_impersonate() -> str:
    """随机挑一个浏览器指纹。"""
    return random.choice(_IMPRESONATE_OPTIONS)


def random_fingerprint(seed_key: str = "") -> dict[str, Any]:
    """生成一个随机指纹。seed_key 非空时按 key 稳定（同 key 同指纹——粘性）。

    返回 {impersonate, user_agent, platform, platform_ua}。
    """
    impersonate = pick_impersonate() if not seed_key else _stable_pick(seed_key)
    base_ua = _UA_MAP.get(impersonate, _UA_MAP["chrome131"])
    platform, platform_ua = _PLATFORMS[random.randrange(len(_PLATFORMS))]
    # 平台与 UA 保持一致（Linux/Mac 的 UA 前缀）
    if platform == "Macintosh":
        base_ua = base_ua.replace("Windows NT 10.0; Win64; x64", "Macintosh; Intel Mac OS X 10_15_7")
    elif platform == "X11; Linux x86_64":
        base_ua = base_ua.replace("Windows NT 10.0; Win64; x64", "X11; Linux x86_64")
    # 微变体：随机加版本尾巴（同一 impersonate 下 UA 也不完全相同）
    tail = _UA_TAILS[random.randrange(len(_UA_TAILS))]
    user_agent = base_ua + tail
    return {
        "impersonate": impersonate,
        "user_agent": user_agent,
        "platform": platform,
        "platform_ua": platform_ua,
    }


def _stable_pick(seed_key: str) -> str:
    """按 seed_key 稳定选指纹（同一账号/邮箱固定，跨请求不漂移）。"""
    idx = 0
    for ch in str(seed_key):
        idx = (idx * 31 + ord(ch)) % len(_IMPRESONATE_OPTIONS)
    return _IMPRESONATE_OPTIONS[idx % len(_IMPRESONATE_OPTIONS)]


def fingerprint_headers(fp: dict[str, Any]) -> dict[str, str]:
    """把指纹转成请求头（UA + Sec-Ch-Ua 平台）。"""
    platform_ua = str(fp.get("platform_ua") or '"Windows"')
    major = str(fp.get("impersonate") or "chrome131").replace("chrome", "").replace("edge", "")
    try:
        major = major[:3]
    except Exception:
        major = "131"
    return {
        "User-Agent": str(fp.get("user_agent") or _UA_MAP["chrome131"]),
        "Sec-Ch-Ua-Platform": platform_ua,
        "Sec-Ch-Ua-Platform-Version": '"0.0.0"',
        "Sec-Ch-Ua": f'"Chromium";v="{major}", "Not A(Brand";v="24", "Google Chrome";v="{major}"',
        "Sec-Ch-Ua-Mobile": "?0",
    }
