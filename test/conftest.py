"""pytest 全局夹具：隔离 CHATGPT2API_AUTH_KEY 环境变量污染。

问题（红队审查 Blocking）：test_account_image_capabilities.py 在模块导入时
`os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")`，改写全局环境变量，
导致按字母序排在其后的测试中 `Bearer chatgpt2api` 全部 401（CI 9 failed）。

修复：每个测试函数前后强制固定 auth-key 为 "chatgpt2api"（与多数测试的 Bearer
一致），测试后复原，消除模块导入顺序导致的污染。
"""

from __future__ import annotations

import os

import pytest

_TEST_AUTH_KEY = "chatgpt2api"


@pytest.fixture(autouse=True)
def _isolate_auth_key(monkeypatch):
    """每个测试固定 auth-key，避免模块级 setdefault 污染其他测试。"""
    monkeypatch.setenv("CHATGPT2API_AUTH_KEY", _TEST_AUTH_KEY)
    yield
    # monkeypatch 自动复原原值
