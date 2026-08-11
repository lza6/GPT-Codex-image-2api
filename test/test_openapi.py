"""测试：OpenAPI 规范生成 + SDK 生成 + Swagger UI 端点。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from services.config import config


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


class TestOpenAPI:
    """OpenAPI 规范生成与端点验证"""

    def test_swagger_ui_accessible(self, client: TestClient) -> None:
        """Swagger UI 页面可访问"""
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_redoc_ui_accessible(self, client: TestClient) -> None:
        """Redoc 页面可访问"""
        resp = client.get("/redoc")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_openapi_json_accessible(self, client: TestClient) -> None:
        """OpenAPI JSON 端点返回有效规范"""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        assert spec["openapi"].startswith("3.")
        assert spec["info"]["title"] == "chatgpt2api"
        assert len(spec["info"]["version"]) > 0
        assert "openapi" in spec
        assert "paths" in spec
        assert len(spec["paths"]) > 0

    def test_openapi_has_metadata(self, client: TestClient) -> None:
        """OpenAPI 规范包含元信息"""
        spec = client.get("/openapi.json").json()
        info = spec["info"]
        assert info["description"] is not None
        assert len(info["description"]) > 50
        assert info["contact"] is not None
        assert info["license"] is not None
        assert spec.get("servers") is not None

    def test_openapi_has_tags(self, client: TestClient) -> None:
        """OpenAPI 规范包含分组标签"""
        spec = client.get("/openapi.json").json()
        tags = spec.get("tags", [])
        tag_names = [t["name"] for t in tags]
        assert "AI" in tag_names
        assert "Accounts" in tag_names
        assert "Dashboard" in tag_names
        assert "System" in tag_names
        assert "logs" in tag_names

    def test_openapi_has_security_schemes(self, client: TestClient) -> None:
        """OpenAPI 规范包含 Bearer 鉴权方案"""
        spec = client.get("/openapi.json").json()
        schemes = spec.get("components", {}).get("securitySchemes", {})
        assert "BearerAuth" in schemes
        assert schemes["BearerAuth"]["scheme"] == "bearer"
        assert spec.get("security") is not None

    def test_openapi_disabled_when_config_false(self) -> None:
        """openapi_enabled=False 时所有端点返回 None"""
        config.data["openapi_enabled"] = False
        try:
            app = create_app()
            assert app.openapi_url is None
            assert app.docs_url is None
            assert app.redoc_url is None
        finally:
            config.data.pop("openapi_enabled", None)

    def test_openapi_v1_paths_present(self, client: TestClient) -> None:
        """OpenAI 兼容的 /v1/* 路径在规范中"""
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/v1/chat/completions" in paths
        assert "/v1/images/generations" in paths
        assert "/v1/images/edits" in paths
        assert "/v1/models" in paths
        assert "/v1/responses" in paths

    def test_openapi_management_paths_present(self, client: TestClient) -> None:
        """管理 API 路径在规范中"""
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/api/accounts" in paths
        assert "/api/system/healthz" not in paths  # include_in_schema=False
        assert "/api/dashboard/stream" not in paths  # include_in_schema=False


class TestOpenAPISpecFile:
    """openapi.json 文件生成验证"""

    def test_spec_file_exists(self) -> None:
        """docs/openapi.json 文件存在"""
        spec_file = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
        assert spec_file.exists(), "请先运行 scripts/generate_openapi_spec.py"
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
        assert "openapi" in spec
        assert len(spec.get("paths", {})) > 0

    def test_spec_file_matches_live(self, client: TestClient) -> None:
        """docs/openapi.json 与当前应用生成的规范一致"""
        spec_file = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
        live_spec = client.get("/openapi.json").json()
        file_spec = json.loads(spec_file.read_text(encoding="utf-8"))
        # 比较路径数量
        assert len(file_spec["paths"]) == len(live_spec["paths"])
        # 比较版本
        assert file_spec["info"]["version"] == live_spec["info"]["version"]


class TestSDKGeneration:
    """多语言 SDK 生成验证"""

    SDK_DIR = Path(__file__).resolve().parents[1] / "docs" / "sdks"

    def test_python_sdk_exists(self) -> None:
        """Python SDK 文件存在且语法有效"""
        py_file = self.SDK_DIR / "python" / "chatgpt2api_client.py"
        assert py_file.exists()
        code = py_file.read_text(encoding="utf-8")
        exec(compile(code, str(py_file), "exec"))
        assert "Chatgpt2apiClient" in code

    def test_javascript_sdk_exists(self) -> None:
        """JavaScript SDK 文件存在"""
        js_file = self.SDK_DIR / "javascript" / "chatgpt2api-client.js"
        assert js_file.exists()
        content = js_file.read_text(encoding="utf-8")
        assert "export class" in content

    def test_go_sdk_exists(self) -> None:
        """Go SDK 文件存在"""
        go_file = self.SDK_DIR / "go" / "chatgpt2api.go"
        assert go_file.exists()
        content = go_file.read_text(encoding="utf-8")
        assert "package chatgpt2api" in content

    def test_sdk_client_init(self) -> None:
        """Python SDK 客户端能初始化"""
        from docs.sdks.python.chatgpt2api_client import Chatgpt2apiClient

        c = Chatgpt2apiClient(base_url="http://test", api_key="test-key")
        assert c is not None
        c.close()