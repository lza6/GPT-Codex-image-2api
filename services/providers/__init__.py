"""多提供商支持（地基 — 进度：Phase 4/4）。

已完成：
  - ProviderMeta 元信息模型 + 注册表（chatgpt/grok 均已启用）
  - 账号入库自动附加 provider 字段（默认 chatgpt）
  - 调度层接受 provider 过滤参数（_account_matches_provider + 各调度入口透传）
  - 账号列表支持 ?provider= 过滤
  - GET /api/providers 端点返回注册列表（含 models/capabilities）
  - 生图任务 provider 透传（按所选 provider 过滤生图账号选取）
  - 前端切换器：账号列表/设置页/图片工作台支持 provider 切换与筛选

grok 说明：调度/路由已就绪（enabled=True）；真实出图需独立上游
（xAI API 或 grok 官方账号逆向），当前未接，需外部凭据。

用法：
    from services.providers import normalize_provider, list_providers, is_valid_provider
"""
from services.providers.base import ProviderMeta
from services.providers.registry import (
    DEFAULT_PROVIDER,
    get_provider,
    is_valid_provider,
    list_providers,
    normalize_provider,
)

__all__ = [
    "DEFAULT_PROVIDER",
    "ProviderMeta",
    "get_provider",
    "is_valid_provider",
    "list_providers",
    "normalize_provider",
]
