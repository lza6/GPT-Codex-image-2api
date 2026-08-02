"""熔断器生命周期管理测试（D4）：账号删除/轮换清理熔断器，孤儿熔断器 TTL 淘汰。"""

from __future__ import annotations

import time

from services.account_service import AccountService
from services.circuit_breaker import CircuitBreakerRegistry
from services.storage.json_storage import JSONStorageBackend


def _service(tmp_path) -> AccountService:
    return AccountService(JSONStorageBackend(tmp_path / "accounts.json"))


def _account(token: str) -> dict:
    return {"access_token": token, "email": f"{token[:4]}@example.com", "status": "正常", "quota": 10}


def test_delete_accounts_removes_circuit_breaker(tmp_path):
    svc = _service(tmp_path)
    registry = CircuitBreakerRegistry()
    svc.set_circuit_breaker_registry(registry)
    svc.add_accounts(["token-aaa"])
    registry.get("token-aaa").record_failure()  # 让熔断器存在
    assert "token-aaa" in registry.all_status()
    svc.delete_accounts(["token-aaa"])
    assert "token-aaa" not in registry.all_status()


def test_token_rotation_removes_old_breaker(tmp_path):
    svc = _service(tmp_path)
    registry = CircuitBreakerRegistry()
    svc.set_circuit_breaker_registry(registry)
    svc.add_accounts(["old-token"])
    registry.get("old-token").record_failure()
    # 模拟 token 轮换（refresh_token 换新 access_token 的路径）
    svc._apply_refreshed_tokens("old-token", {"access_token": "new-token"}, "test")
    assert "old-token" not in registry.all_status()
    # 新 token 的熔断器惰性创建（get 时）
    assert registry.get("new-token") is not None


def test_orphan_breaker_ttl_eviction(tmp_path):
    registry = CircuitBreakerRegistry(orphan_ttl_seconds=0.05)
    registry.get("ghost-token").record_failure()
    assert "ghost-token" in registry.all_status()
    time.sleep(0.08)
    # get 时惰性淘汰过期熔断器
    registry.prune_orphans()
    assert "ghost-token" not in registry.all_status()
