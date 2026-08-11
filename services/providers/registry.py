"""多提供商注册表（地基 — 进度：Phase 4/4）。

当前状态（Phase 4，已完成）：
  - chatgpt 已接入（默认，enabled=True）
  - grok 已接入元数据 + 调度/路由（enabled=True）
  - grok 真实出图需要独立上游（xAI API 或 grok 官方账号逆向），当前未接——
    生图选 grok 模型会在 protocol 层按 IMAGE_MODELS 白名单拦截并给出明确错误，
    调度/路由层已就绪，外部凭据到位后仅需实现上游客户端即可出图

阶段进度：
  - Phase 1 — 地基：ProviderMeta 元信息 + 注册表 + 账号入库自动 provider 字段
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
        capabilities=("chat", "image", "edit"),
    ),
    "grok": ProviderMeta(
        name="grok",
        display_name="Grok",
        enabled=True,  # Phase 4：元数据/调度/路由已启用；出图需外部上游凭据
        models=(
            # xAI 官方 API 模型命名（对话/推理/图片），供前端展示与调度参考
            "grok-4",
            "grok-4-mini",
            "grok-4-fast",
            "grok-3",
            "grok-3-mini",
            "grok-3-fast",
            "grok-3-mini-fast",
            "grok-3-image",
            "grok-vision",
            "grok-2",
            "grok-2-image",
        ),
        description="Grok（xAI）— 调度/路由已接入，出图需外部上游凭据",
        capabilities=("chat", "image", "reasoning"),
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
