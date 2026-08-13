"""模型→Provider 路由分发（Phase 3）。

按模型名自动路由到对应 provider 的调度池。
规则表可配置（config.json 的 router_rules），
默认规则基于模型名前缀匹配。
"""

from __future__ import annotations

import logging
from typing import Any

from services.providers import is_valid_provider

logger = logging.getLogger(__name__)

# 默认路由规则：模型名前缀 → provider
_DEFAULT_RULES: dict[str, str] = {
    "gpt-": "chatgpt",
    "claude-": "chatgpt",
    "grok-": "grok",
    "dall-e-": "chatgpt",
    # v2.36.0：fomimage 提供商模型前缀
    "fomimage-": "fomimage",
}


class RouterService:
    """模型→Provider 路由分发。

    根据模型名自动匹配目标 provider，支持精确匹配和前缀匹配两级策略。
    """

    def __init__(self, rules: dict[str, str] | None = None) -> None:
        self._rules: dict[str, str] = dict(rules or {})

    def route_for_model(self, model: str) -> str:
        """根据模型名返回目标 provider。

        匹配顺序：
        1. 精确匹配（用户自定义规则）
        2. 前缀匹配（默认规则 + 用户自定义规则）
        3. 回退默认 "chatgpt"
        """
        cleaned = str(model or "").strip()
        if not cleaned or cleaned == "auto":
            return "chatgpt"

        # 1. 精确匹配
        if cleaned in self._rules:
            provider = self._rules[cleaned]
            if is_valid_provider(provider):
                return provider

        # 2. 前缀匹配
        merged = {**_DEFAULT_RULES, **self._rules}
        for prefix, provider in merged.items():
            if cleaned.startswith(prefix):
                if is_valid_provider(provider):
                    return provider

        # 3. 回退默认
        return "chatgpt"

    def update_rules(self, rules: dict[str, str]) -> None:
        """热更新路由规则。

        从 config.json 加载后调用，替换现有规则表。
        """
        self._rules = dict(rules or {})

    def list_routes(self) -> list[dict[str, str]]:
        """返回当前路由表（供前端展示）。"""
        merged = {**_DEFAULT_RULES, **self._rules}
        return [
            {"model_prefix": prefix, "provider": provider}
            for prefix, provider in sorted(merged.items())
        ]

    def load_from_config(self, config_data: dict[str, Any]) -> None:
        """从配置数据加载 router_rules。

        从 config.json 的 ConfigStore.data 中提取 router_rules 字段。
        """
        rules = config_data.get("router_rules", {})
        if isinstance(rules, dict):
            self.update_rules({str(k): str(v) for k, v in rules.items()})
        else:
            logger.warning("router_rules 格式无效，跳过: %s", type(rules).__name__)


# 模块级单例
router_service = RouterService()