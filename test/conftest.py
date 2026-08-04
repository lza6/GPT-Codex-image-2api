"""pytest 全局夹具：隔离环境变量污染，防测试误触真实外部资源。

历史问题（红队审查 Blocking）：test_account_image_capabilities.py 在模块导入时
`os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")`，改写全局环境变量，
导致按字母序排在其后的测试中 `Bearer chatgpt2api` 全部 401（CI 9 failed）。

E3 扩大隔离面：除 auth-key 外，把 DATABASE_URL / STORAGE_BACKEND / REDIS_URL /
webhook 等会改变存储后端或触发外部告警的变量全部钉死为本地安全值，
防止任何模块级 setdefault 把测试带进真实库/真实推送。
"""

from __future__ import annotations

import pytest

_TEST_AUTH_KEY = "chatgpt2api"

# E3：隔离面扩大——任何测试不得意外连接真实存储/Redis/告警通道
_ISOLATED_ENV = {
    "CHATGPT2API_AUTH_KEY": _TEST_AUTH_KEY,
    "CHATGPT2API_STORAGE_BACKEND": "json",          # 默认 JSON 存储，防连真实库
    "CHATGPT2API_DATABASE_URL": "",                 # 防模块级 setdefault 连 PostgreSQL
    "CHATGPT2API_REDIS_URL": "",                    # 防 Redis 共享状态误连
    "CHATGPT2API_ALERT_WEBHOOK_URL": "",            # 防测试触发真实 webhook 告警
}


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """每个测试固定关键环境变量，避免模块级 setdefault 污染其他测试。"""
    for key, value in _ISOLATED_ENV.items():
        monkeypatch.setenv(key, value)
    yield
    # monkeypatch 自动复原原值
