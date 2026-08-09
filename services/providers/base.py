"""多提供商元信息（地基 — 进度：Phase 1/4）。

为后续接入 grok 等提供商搭框架：账号按 provider 归属、调度按 provider 分池（Phase 2）、
路由按 provider 分发（Phase 3）、前端按 provider 切换（Phase 4）。

当前 Phase 1 仅注册元信息，上游调用仍走现有 chatgpt 链路，
不改变任何现有行为（默认 provider = chatgpt）。

Phase 1 已完成项：
  - ProviderMeta 元信息模型（本文件）
  - 注册表 + 归一化/校验/列表（registry.py）
  - 账号入库自动附加 provider 字段（account_service._normalize_account）
  - 调度层 provider 过滤参数透传（_account_matches_provider）
  - GET /api/providers 端点 + 账号列表 ?provider= 过滤
  - 单元测试覆盖（test_providers_api.py + test_kookeey_providers.py）
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderMeta:
    """提供商元信息。

    Attributes:
        name: 唯一标识，如 "chatgpt" / "grok"。存入账号的 provider 字段。
        display_name: 前端展示名，如 "ChatGPT"。
        enabled: 是否已接入可用。地基阶段 grok 为 False（占位，UI 灰显"即将支持"）。
        models: 该提供商支持的模型名列表（供前端展示与调度参考）。
        description: 简短描述。
    """

    name: str
    display_name: str
    enabled: bool = True
    models: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
