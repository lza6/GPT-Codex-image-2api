"""多提供商支持（地基）。

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
