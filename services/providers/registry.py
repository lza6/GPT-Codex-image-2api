"""多提供商注册表（地基 — 进度：Phase 1/4）。

当前状态（Phase 1）：
  - chatgpt 为唯一已接入提供商（默认，enabled=True）
  - grok 占位 enabled=False（UI 灰显"即将支持"）
  - 后续接入 grok 时，实现对应上游客户端后把 enabled 置 True 即可

后续阶段：
  - Phase 2 — 调度分池：各 provider 独立调度池
  - Phase 3 — 路由分发：按模型/请求类型自动路由
  - Phase 4 — 前端切换器：账号列表/设置页/图片工作台支持切换
"""
from __future__ import annotations

from services.providers.base import ProviderMeta

DEFAULT_PROVIDER = "chatgpt"

_PROVIDERS: dict[str, ProviderMeta] = {
    "chatgpt": ProviderMeta(
        name="chatgpt",
        display_name="ChatGPT",
        enabled=True,
        models=(),  # 模型列表由 /v1/models 动态返回，地基不写死
        description="ChatGPT 官网逆向封装（默认提供商）",
    ),
    "grok": ProviderMeta(
        name="grok",
        display_name="Grok",
        enabled=False,  # 地基阶段未接入
        models=(),
        description="Grok（X.AI），即将支持",
    ),
}


def list_providers(enabled_only: bool = False) -> list[ProviderMeta]:
    """列出所有提供商；enabled_only=True 只返回已接入可用的。"""
    providers = list(_PROVIDERS.values())
    if enabled_only:
        providers = [p for p in providers if p.enabled]
    return providers


def get_provider(name: str | None) -> ProviderMeta | None:
    """按名取提供商元信息，不存在返回 None。"""
    return _PROVIDERS.get(str(name or "").strip().lower())


def is_valid_provider(name: str | None) -> bool:
    """是否为已注册且已接入可用的提供商。"""
    meta = get_provider(name)
    return bool(meta and meta.enabled)


def normalize_provider(name: str | None) -> str:
    """归一化 provider 名：空或未知一律回退到默认 chatgpt。"""
    value = str(name or "").strip().lower()
    return value if get_provider(value) else DEFAULT_PROVIDER
