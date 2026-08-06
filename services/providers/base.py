"""多提供商元信息（地基）。

为后续接入 grok 等提供商搭框架：账号按 provider 归属、调度按 provider 分池、
前端按 provider 切换。本阶段仅注册元信息，上游调用仍走现有 chatgpt 链路，
不改变任何现有行为（默认 provider = chatgpt）。
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
