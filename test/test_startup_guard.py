"""启动路径守卫回归（第七轮 audit-deploy #4 修复的看护测试）。

main.py 的 workers 解析已模块级化：uvicorn CLI（bat/Docker）与 python main.py
两条启动路径共享同一 resolve_workers()。本测试守住：
- 属性存在性（曾误报"属性不存在"，此测试防真实回归）
- JSON 存储下 workers>1 回退为 1
- 非 JSON 存储下 workers 保持配置值
"""

from __future__ import annotations


class TestStartupGuard:
    def test_resolve_workers_exists_and_json_fallback(self):
        from main import resolve_workers
        from services.config import config

        assert config.storage_backend_type in ("json", "sqlite", "postgres", "git")
        resolved = resolve_workers()
        if config.storage_backend_type == "json":
            assert resolved == 1, f"JSON 存储下 workers 必须回退为 1，实际 {resolved}"
        else:
            assert resolved == config.workers

    def test_workers_guard_logic_unit(self, monkeypatch):
        """脱离真实 config，验证守卫分支逻辑本身。"""
        import main

        class FakeConfig:
            workers = 8
            storage_backend_type = "json"

        monkeypatch.setattr(main, "config", FakeConfig())
        assert main.resolve_workers() == 1, "JSON + workers=8 必须回退为 1"

        class FakeConfig2:
            workers = 8
            storage_backend_type = "sqlite"

        monkeypatch.setattr(main, "config", FakeConfig2())
        assert main.resolve_workers() == 8, "sqlite + workers=8 必须保持 8"
