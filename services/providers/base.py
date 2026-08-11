"""多提供商元信息（地基 — 进度：Phase 4/4）。

为多提供商提供元信息框架：账号按 provider 归属、调度按 provider 分池（Phase 2）、
路由按 provider 分发（Phase 3）、前端按 provider 切换（Phase 4）。

已完成项：
  - ProviderMeta 元信息模型（本文件，含 capabilities）
  - 注册表 + 归一化/校验/列表（registry.py，chatgpt/grok 均已启用）
  - 账号入库自动附加 provider 字段（account_service._normalize_account）
  - 调度层 provider 过滤参数透传（_account_matches_provider）
  - GET /api/providers 端点 + 账号列表 ?provider= 过滤
  - 生图任务 provider 透传（api/image_tasks.py → protocol 层取号过滤）
  - 前端切换器（账号列表/设置页/图片工作台）
  - 单元测试覆盖（test_providers_api.py + test_kookeey_providers.py + test_router_service.py + test_provider_scheduler.py）
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderMeta:
    """提供商元信息。

    Attributes:
        name: 唯一标识，如 "chatgpt" / "grok"。存入账号的 provider 字段。
        display_name: 前端展示名，如 "ChatGPT"。
        enabled: 是否已接入可用。true 表示调度/路由/前端均已启用该 provider。
        models: 该提供商支持的模型名列表（供前端展示与调度参考）。
        description: 简短描述。
        capabilities: 该提供商的能力标签，如 ("chat", "image", "reasoning")。
    """

    name: str
    display_name: str
    enabled: bool = True
    models: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    capabilities: tuple[str, ...] = field(default_factory=tuple)
