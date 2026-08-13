"""Grok 号自动注册子模块（chatgpt2api 子模块，不独立端口/服务）。

职责边界：
- 仅当 `config.json` 的 `registration.grok.enabled=true` 时才加载 grok 注册依赖（YesCaptcha / curl_cffi 等）。
- 注册成功的账号直接写入 chatgpt2api 号池（`account_service.add_account_items`，provider=grok），内部闭环，无外部推送。
- 对外暴露的编排器单例：`registration_coordinator`。

典型用法：
    from services.registration.coordinator import registration_coordinator
    result = registration_coordinator.register(count=3)   # 手动触发
    registration_coordinator.start_watcher()               # 自动补号定时器（配合 app lifespan）
"""
from __future__ import annotations

from services.registration.coordinator import RegistrationCoordinator, registration_coordinator

__all__ = ["RegistrationCoordinator", "registration_coordinator"]
