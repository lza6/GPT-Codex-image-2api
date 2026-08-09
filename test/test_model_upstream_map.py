"""测试 model_upstream_map 模型映射表。"""
from __future__ import annotations

from unittest.mock import patch

from services.openai_backend_api import OpenAIBackendAPI


class TestModelUpstreamMap:
    def test_resolve_returns_mapped_value(self):
        """映射表中的模型返回映射值。"""
        with patch("services.openai_backend_api.config") as mock_config:
            mock_config.model_upstream_map = {"gpt-4o": "gpt-5-5"}
            mock_config.default_upstream_model_name = "gpt-5-5"
            result = OpenAIBackendAPI._resolve_upstream_model("gpt-4o")
            assert result == "gpt-5-5"

    def test_resolve_passthrough_unmapped(self):
        """不在映射表中的模型直接透传。"""
        with patch("services.openai_backend_api.config") as mock_config:
            mock_config.model_upstream_map = {"gpt-4o": "gpt-5-5"}
            result = OpenAIBackendAPI._resolve_upstream_model("gpt-5-5")
            assert result == "gpt-5-5"

    def test_resolve_auto_returns_default(self):
        """model=auto 时返回 default_upstream_model_name。"""
        with patch("services.openai_backend_api.config") as mock_config:
            mock_config.model_upstream_map = {}
            mock_config.default_upstream_model_name = "gpt-5-5"
            result = OpenAIBackendAPI._resolve_upstream_model("auto")
            assert result == "gpt-5-5"

    def test_resolve_empty_map(self):
        """空映射表时所有模型透传。"""
        with patch("services.openai_backend_api.config") as mock_config:
            mock_config.model_upstream_map = {}
            mock_config.default_upstream_model_name = "gpt-5-5"
            assert OpenAIBackendAPI._resolve_upstream_model("gpt-4o") == "gpt-4o"
            assert OpenAIBackendAPI._resolve_upstream_model("gpt-5-5") == "gpt-5-5"

    def test_resolve_empty_model(self):
        """空模型名返回默认值。"""
        with patch("services.openai_backend_api.config") as mock_config:
            mock_config.model_upstream_map = {}
            mock_config.default_upstream_model_name = "gpt-5-5"
            assert OpenAIBackendAPI._resolve_upstream_model("") == "gpt-5-5"

    def test_conversation_payload_uses_mapped_model(self):
        """_conversation_payload 使用映射后的模型名。"""
        with patch("services.openai_backend_api.config") as mock_config:
            mock_config.model_upstream_map = {"gpt-4o": "gpt-5-5"}
            mock_config.default_upstream_model_name = "gpt-5-5"
            mock_config.default_thinking_effort = "auto"
            api = OpenAIBackendAPI(access_token="test")
            payload = api._conversation_payload(
                messages=[{"role": "user", "content": "hello"}],
                model="gpt-4o",
                timezone="UTC",
            )
            assert payload["model"] == "gpt-5-5"

    def test_list_models_includes_mapped(self, monkeypatch):
        """list_models 含映射模型。"""
        from services.protocol.openai_v1_models import list_models
        from services.config import config

        monkeypatch.setitem(config.data, "model_upstream_map", {"gpt-4-5": "gpt-5-5", "o3": "o3-pro"})
        monkeypatch.setattr(
            "services.protocol.openai_v1_models.model_catalog_service.list_models",
            lambda: {"object": "list", "data": [{"id": "gpt-5-5", "object": "model"}]},
        )
        result = list_models()
        model_ids = {m["id"] for m in result["data"]}
        assert "gpt-4-5" in model_ids
        assert "o3" in model_ids
        assert "gpt-5-5" in model_ids
