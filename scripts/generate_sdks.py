#!/usr/bin/env python
"""基于 OpenAPI 规范生成多语言 SDK 客户端代码。

用法：
    .venv/Scripts/python.exe scripts/generate_sdks.py

输出：
    docs/sdks/python/chatgpt2api_client.py — Python 客户端
    docs/sdks/javascript/chatgpt2api-client.js — JavaScript 客户端
    docs/sdks/go/chatgpt2api.go — Go 客户端
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
SPEC_PATH = BASE_DIR / "docs" / "openapi.json"
OUTPUT_DIR = BASE_DIR / "docs" / "sdks"


def load_spec() -> dict[str, Any]:
    with open(str(SPEC_PATH), encoding="utf-8") as f:
        return json.load(f)


def _get_security_scheme(spec: dict[str, Any]) -> str:
    schemes = spec.get("components", {}).get("securitySchemes", {})
    for name, scheme in schemes.items():
        if scheme.get("scheme") == "bearer":
            return name
    return "BearerAuth"


def _get_servers(spec: dict[str, Any]) -> list[str]:
    return [s.get("url", "/") for s in spec.get("servers", [{"url": "/"}])]


def _get_paths(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """返回 [(method, path, operation), ...]"""
    result: list[tuple[str, str, dict[str, Any]]] = []
    for path, methods in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "delete", "patch", "options", "head"):
            op = methods.get(method)
            if op:
                result.append((method.upper(), path, op))
    return result


def _get_method_name(method: str, path: str, op: dict[str, Any]) -> str:
    """从 operationId 生成方法名"""
    oid = op.get("operationId", "")
    if oid:
        # camelCase → snake_case for Python
        parts = []
        current = ""
        for ch in oid:
            if ch.isupper() and current:
                parts.append(current.lower())
                current = ch
            else:
                current += ch
        if current:
            parts.append(current.lower())
        return "_".join(parts)
    # fallback
    path_part = path.replace("/", "_").replace("{", "").replace("}", "").strip("_")
    return f"{method.lower()}{path_part}"


def _get_return_type(schema: dict[str, Any] | None, spec: dict[str, Any]) -> str:
    if not schema:
        return "dict"
    ref = schema.get("$ref", "")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        return name
    if schema.get("type") == "array":
        items = schema.get("items", {})
        return f"list[{_get_return_type(items, spec)}]"
    return "dict"


def _get_parameters(op: dict[str, Any]) -> list[dict[str, Any]]:
    return op.get("parameters", [])


def _get_request_body(op: dict[str, Any]) -> dict[str, Any] | None:
    rb = op.get("requestBody")
    if not rb:
        return None
    content = rb.get("content", {})
    for media_type, body in content.items():
        return body.get("schema")
    return None


def _get_schema_name(schema: dict[str, Any] | None, spec: dict[str, Any]) -> str | None:
    if not schema:
        return None
    ref = schema.get("$ref", "")
    if ref:
        return ref.rsplit("/", 1)[-1]
    return None


def _get_schema_properties(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    schemas = spec.get("components", {}).get("schemas", {})
    result: dict[str, dict[str, Any]] = {}
    for name, schema in schemas.items():
        props = schema.get("properties", {})
        result[name] = {k: _simplify_type(v) for k, v in props.items()}
    return result


def _simplify_type(schema: dict[str, Any]) -> str:
    ref = schema.get("$ref", "")
    if ref:
        return ref.rsplit("/", 1)[-1]
    s_type = schema.get("type", "object")
    if s_type == "array":
        items = schema.get("items", {})
        return f"list[{_simplify_type(items)}]"
    if s_type == "string":
        enum = schema.get("enum")
        if enum:
            return " | ".join(f'"{e}"' for e in enum)
        return "str"
    if s_type == "integer":
        return "int"
    if s_type == "number":
        return "float"
    if s_type == "boolean":
        return "bool"
    return "dict"


# ──────────────────────────────────────────────
# Python SDK
# ──────────────────────────────────────────────

def generate_python(spec: dict[str, Any]) -> str:
    title = spec.get("info", {}).get("title", "API")
    version = spec.get("info", {}).get("version", "0.0.0")
    servers = _get_servers(spec)
    base_url = servers[0] if servers else "/"
    paths = _get_paths(spec)
    schemas = _get_schema_properties(spec)

    lines = [
        '"""',
        f"{title} SDK — 自动生成 (v{version})",
        "",
        "用法：",
        f"    client = Chatgpt2apiClient(base_url='{base_url}', api_key='your-key')",
        "    models = client.list_models()",
        '"""',
        "from __future__ import annotations",
        "",
        "import json",
        "from typing import Any",
        "",
        "import httpx",
        "",
        "",
        f"VERSION = \"{version}\"",
        "",
        "",
        "class Chatgpt2apiClient:",
        f'    """{title} API 客户端"""',
        "",
        "    def __init__(",
        "        self,",
        f"        base_url: str = \"{base_url}\",",
        "        api_key: str | None = None,",
        "        timeout: float = 60.0,",
        "    ):",
        '        self.base_url = base_url.rstrip("/")',
        '        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}',
        "        self._client = httpx.Client(timeout=timeout, headers=self._headers)",
        "",
        "    def close(self) -> None:",
        "        self._client.close()",
        "",
        "    def __enter__(self) -> Chatgpt2apiClient:",
        "        return self",
        "",
        "    def __exit__(self, *args: Any) -> None:",
        "        self.close()",
        "",
    ]

    # schema 类型
    if schemas:
        lines.extend(["    # --- 数据模型 ---", ""])
        for name, props in schemas.items():
            fields = []
            for pname, ptype in props.items():
                fields.append(f"        {pname}: {ptype}")
            lines.append(f"    class {name}:")
            if fields:
                lines.append("        def __init__(self, **kwargs: Any):")
                lines.append("            for k, v in kwargs.items():")
                lines.append("                setattr(self, k, v)")
            else:
                lines.append("        pass")
            lines.append("")

    lines.append("    # --- API 方法 ---")
    lines.append("")

    # 路径分组
    tag_groups: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for method, path, op in paths:
        tags = op.get("tags", ["default"])
        tag = tags[0] if tags else "default"
        tag_groups.setdefault(tag, []).append((method, path, op))

    for tag, tag_paths in sorted(tag_groups.items()):
        lines.append(f"    # --- {tag} ---")
        lines.append("")
        for method, path, op in tag_paths:
            summary = op.get("summary", op.get("operationId", ""))
            name = _get_method_name(method, path, op)
            params = _get_parameters(op)
            rb = _get_request_body(op)

            # 构造参数列表
            func_params = ["self"]
            query_params = []
            path_params = []

            for p in params:
                pname = p.get("name", "param")
                pin = p.get("in", "query")
                required = p.get("required", False)
                if pin == "path":
                    path_params.append(pname)
                    func_params.append(f"{pname}: str")
                elif pin == "query":
                    query_params.append(pname)
                    func_params.append(f"{pname}: Any = None")

            if rb:
                schema_name = _get_schema_name(rb, spec)
                if schema_name:
                    func_params.append(f"body: dict | None = None")
                else:
                    func_params.append("body: dict | None = None")

            lines.append(f"    def {name}({', '.join(func_params)}):")
            lines.append(f'        """{summary}"""')

            # 构建 URL
            url_template = path
            for p in path_params:
                url_template = url_template.replace(f"{{{p}}}", "{" + p + "}")
            lines.append(f"        url = self.base_url + {json.dumps(url_template)}")
            if query_params:
                lines.append("        params = {k: v for k, v in locals().items() if k in " + str(query_params) + " and v is not None}")
                lines.append("        if params:")
                lines.append("            from urllib.parse import urlencode")
                lines.append("            url += '?' + urlencode(params)")

            if method == "GET":
                lines.append("        resp = self._client.get(url)")
            elif method == "DELETE":
                lines.append("        resp = self._client.delete(url)")
            elif method == "POST":
                lines.append("        resp = self._client.post(url, json=body)")
            elif method == "PUT":
                lines.append("        resp = self._client.put(url, json=body)")
            elif method == "PATCH":
                lines.append("        resp = self._client.patch(url, json=body)")
            else:
                lines.append("        resp = self._client.request('" + method + "', url, json=body)")

            lines.append("        resp.raise_for_status()")
            lines.append("        return resp.json()")
            lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# JavaScript SDK
# ──────────────────────────────────────────────

def generate_javascript(spec: dict[str, Any]) -> str:
    title = spec.get("info", {}).get("title", "API")
    version = spec.get("info", {}).get("version", "0.0.0")
    servers = _get_servers(spec)
    base_url = servers[0] if servers else "/"
    paths = _get_paths(spec)

    lines = [
        "/**",
        f" * {title} SDK — 自动生成 (v{version})",
        " *",
        " * 用法：",
        f" *   const client = new Chatgpt2apiClient('{base_url}', 'your-api-key');",
        " *   const models = await client.listModels();",
        " */",
        "",
        "export class Chatgpt2apiClient {",
        f'  VERSION = "{version}";',
        "",
        "  constructor(baseUrl = " + json.dumps(base_url) + ", apiKey = null) {",
        '    this.baseUrl = baseUrl.replace(/\\/$/, "");',
        "    this.headers = {",
        '      "Content-Type": "application/json",',
        "    };",
        "    if (apiKey) {",
        '      this.headers["Authorization"] = `Bearer ${apiKey}`;',
        "    }",
        "  }",
        "",
        "  async request(method, path, options = {}) {",
        "    const url = `${this.baseUrl}${path}`;",
        "    const opts = {",
        "      method,",
        "      headers: { ...this.headers },",
        "    };",
        "    if (options.body) {",
        "      opts.body = JSON.stringify(options.body);",
        "    }",
        "    if (options.params) {",
        "      const qs = new URLSearchParams(options.params).toString();",
        "      if (qs) path += `?${qs}`;",
        "    }",
        "    const resp = await fetch(url, opts);",
        "    if (!resp.ok) {",
        '      const err = await resp.text().catch(() => "");',
        "      throw new Error(`HTTP ${resp.status}: ${err}`);",
        "    }",
        '    const ct = resp.headers.get("content-type") || "";',
        "    if (ct.includes(\"application/json\")) {",
        "      return resp.json();",
        "    }",
        "    return resp.text();",
        "  }",
        "",
    ]

    tag_groups: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for method, path, op in paths:
        tags = op.get("tags", ["default"])
        tag = tags[0] if tags else "default"
        tag_groups.setdefault(tag, []).append((method, path, op))

    for tag, tag_paths in sorted(tag_groups.items()):
        lines.append(f"  // --- {tag} ---")
        for method, path, op in tag_paths:
            summary = op.get("summary", op.get("operationId", ""))
            name = _get_method_name(method, path, op)
            # camelCase
            parts = name.split("_")
            js_name = parts[0] + "".join(p.capitalize() for p in parts[1:])

            params = _get_parameters(op)
            query_params = [p.get("name") for p in params if p.get("in") == "query"]
            path_params = [p.get("name") for p in params if p.get("in") == "path"]
            rb = _get_request_body(op)

            js_params = []
            js_path = path
            for p in path_params:
                js_params.append(p)
                js_path = js_path.replace(f"{{{p}}}", "${" + p + "}")

            lines.append(f"")
            lines.append(f"  /** {summary} */")
            lines.append(f"  async {js_name}({', '.join(js_params)}) {{")

            url_path = f"`{js_path}`"
            lines.append(f"    const path = {url_path};")

            opts = []
            if rb:
                opts.append("body")
            if query_params:
                lines.append(f"    const params = {{ {', '.join(f'{p}' for p in query_params)} }};")
                opts.append("params: params")
            if opts:
                lines.append(f"    return this.request('{method}', path, {{ {', '.join(opts)} }});")
            else:
                lines.append(f"    return this.request('{method}', path);")

            lines.append("  }")

        lines.append("")

    lines.append("}")
    lines.append("")
    lines.append("export default Chatgpt2apiClient;")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# Go SDK
# ──────────────────────────────────────────────

def generate_go(spec: dict[str, Any]) -> str:
    title = spec.get("info", {}).get("title", "API")
    version = spec.get("info", {}).get("version", "0.0.0")
    servers = _get_servers(spec)
    base_url = servers[0] if servers else "/"
    paths = _get_paths(spec)

    lines = [
        "package chatgpt2api",
        "",
        "// Code generated by scripts/generate_sdks.py. DO NOT EDIT.",
        "//",
        f"// {title} Go SDK — 自动生成 (v{version})",
        "//",
        "// 用法：",
        "//     client := chatgpt2api.NewClient(\"" + base_url + "\", \"your-api-key\")",
        "//     models, err := client.ListModels()",
        "//",
        "",
        "import (",
        '    "bytes"',
        '    "encoding/json"',
        '    "fmt"',
        '    "io"',
        '    "net/http"',
        '    "net/url"',
        ")",
        "",
        "const Version = \"" + version + "\"",
        "",
        "// Client 是 " + title + " 的 API 客户端",
        "type Client struct {",
        "    baseURL string",
        "    apiKey  string",
        "    http    *http.Client",
        "}",
        "",
        "// NewClient 创建一个新的 API 客户端",
        f"func NewClient(baseURL, apiKey string) *Client {{",
        "    return &Client{",
        "        baseURL: baseURL,",
        "        apiKey:  apiKey,",
        "        http:    &http.Client{},",
        "    }",
        "}",
        "",
        "func (c *Client) do(method, path string, body interface{}) ([]byte, error) {",
        "    u, err := url.JoinPath(c.baseURL, path)",
        "    if err != nil {",
        "        return nil, fmt.Errorf(\"invalid URL: %w\", err)",
        "    }",
        "    var reqBody io.Reader",
        "    if body != nil {",
        "        b, err := json.Marshal(body)",
        "        if err != nil {",
        "            return nil, fmt.Errorf(\"marshal body: %w\", err)",
        "        }",
        "        reqBody = bytes.NewReader(b)",
        "    }",
        "    req, err := http.NewRequest(method, u, reqBody)",
        "    if err != nil {",
        "        return nil, fmt.Errorf(\"new request: %w\", err)",
        "    }",
        '    req.Header.Set("Content-Type", "application/json")',
        "    if c.apiKey != \"\" {",
        '        req.Header.Set("Authorization", "Bearer "+c.apiKey)',
        "    }",
        "    resp, err := c.http.Do(req)",
        "    if err != nil {",
        "        return nil, fmt.Errorf(\"do request: %w\", err)",
        "    }",
        "    defer resp.Body.Close()",
        "    if resp.StatusCode >= 400 {",
        "        bodyBytes, _ := io.ReadAll(resp.Body)",
        "        return nil, fmt.Errorf(\"HTTP %d: %s\", resp.StatusCode, string(bodyBytes))",
        "    }",
        "    return io.ReadAll(resp.Body)",
        "}",
        "",
        "func (c *Client) doJSON(method, path string, body, result interface{}) error {",
        "    b, err := c.do(method, path, body)",
        "    if err != nil {",
        "        return err",
        "    }",
        "    if result != nil {",
        "        if err := json.Unmarshal(b, result); err != nil {",
        "            return fmt.Errorf(\"unmarshal response: %w\", err)",
        "        }",
        "    }",
        "    return nil",
        "}",
        "",
    ]

    # Schema 类型 (Go structs)
    schemas = _get_schema_properties(spec)
    if schemas:
        lines.append("// --- 数据模型 ---")
        lines.append("")
        for name, props in schemas.items():
            lines.append(f"type {name} struct {{")
            for pname, ptype in props.items():
                go_type = _go_type(ptype)
                json_tag = f'`json:"{pname}"`'
                lines.append(f"    {_go_field_name(pname)} {go_type} {json_tag}")
            lines.append("}")
            lines.append("")

    lines.append("// --- API 方法 ---")
    lines.append("")

    tag_groups: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for method, path, op in paths:
        tags = op.get("tags", ["default"])
        tag = tags[0] if tags else "default"
        tag_groups.setdefault(tag, []).append((method, path, op))

    for tag, tag_paths in sorted(tag_groups.items()):
        lines.append(f"// {tag}")
        for method, path, op in tag_paths:
            summary = op.get("summary", op.get("operationId", ""))
            name = _get_method_name(method, path, op)
            # Go 方法名大写
            go_name = name.title().replace("_", "")
            rb = _get_request_body(op)
            params = _get_parameters(op)
            path_params = [p.get("name") for p in params if p.get("in") == "path"]
            query_params = [p.get("name") for p in params if p.get("in") == "query"]

            func_params = ["c *Client"]
            call_args = ["nil"]
            for p in path_params:
                func_params.append(f"{p} string")
            if rb:
                call_args = ["body"] if rb else call_args

            sig = f"func (c *Client) {go_name}({', '.join(func_params)}) ([]byte, error)"
            lines.append(f"// {summary}")
            lines.append(sig + " {")

            go_path = path
            for p in path_params:
                go_path = go_path.replace(f"{{{p}}}", f"\" + {p} + \"")
            lines.append(f"    return c.do(\"{method}\", \"{go_path}\", {call_args[0]})")
            lines.append("}")
            lines.append("")

    return "\n".join(lines)


def _go_type(ptype: str) -> str:
    mapping = {
        "str": "string",
        "int": "int",
        "float": "float64",
        "bool": "bool",
    }
    if ptype.startswith("list["):
        inner = ptype[5:-1]
        return f"[]{_go_type(inner)}"
    if ptype.startswith('"'):
        return "string"
    return mapping.get(ptype, "interface{}")


def _go_field_name(name: str) -> str:
    # snake_case → PascalCase
    parts = name.split("_")
    return "".join(p.capitalize() for p in parts)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    spec = load_spec()
    info = spec.get("info", {})
    title = info.get("title", "API")
    version = info.get("version", "0.0.0")

    print(f"📖 基于 OpenAPI spec 生成 SDK (v{version})...")

    packages = [
        ("Python", "python", "chatgpt2api_client.py", generate_python),
        ("JavaScript", "javascript", "chatgpt2api-client.js", generate_javascript),
        ("Go", "go", "chatgpt2api.go", generate_go),
    ]

    for lang_name, lang_dir, filename, gen_func in packages:
        lang_path = OUTPUT_DIR / lang_dir
        lang_path.mkdir(parents=True, exist_ok=True)

        # 清理旧内容
        for f in lang_path.iterdir():
            if f.is_file():
                f.unlink()

        code = gen_func(spec)
        output_file = lang_path / filename
        output_file.write_text(code, encoding="utf-8")
        line_count = len(code.splitlines())
        print(f"  ✅ {lang_name}: {output_file.relative_to(BASE_DIR)} ({line_count} lines)")

    print(f"\nSDK 生成完成！输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()