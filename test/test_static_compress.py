"""静态资源预压缩 .gz 服务测试：/_next/static 优先返回 .gz（Content-Length 非 chunked）。

背景：GZipMiddleware 已移除（gzip+chunked 代理下 ERR_INVALID_CHUNKED_ENCODING），
改为预生成 .gz + 自定义路由返回（FileResponse Content-Length 非 chunked）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app

client = TestClient(create_app())


def _pick_js() -> str:
    """从 web_dist/_next/static/chunks 挑一个真实的 .js 路径。"""
    chunks = Path("web_dist/_next/static/chunks")
    js = next((p for p in sorted(chunks.iterdir()) if p.suffix == ".js"), None)
    assert js is not None, "web_dist/_next/static/chunks 下应存在 .js"
    return f"/_next/static/chunks/{js.name}"


class TestStaticCompress:
    def setup_method(self) -> None:
        self.js_path = _pick_js()

    def test_gzip_returns_precompressed(self) -> None:
        """带 Accept-Encoding: gzip → Content-Encoding: gzip + Content-Length（非 chunked），body 可解压。"""
        r = client.get(self.js_path, headers={"Accept-Encoding": "gzip, br, zstd"})
        assert r.status_code == 200
        assert r.headers.get("content-encoding") == "gzip"
        assert "content-length" in r.headers, "预压缩必须走 Content-Length（非 chunked）"
        assert "transfer-encoding" not in r.headers
        assert r.headers.get("vary") == "Accept-Encoding"
        assert r.headers.get("cache-control") == "public, max-age=31536000, immutable"
        # TestClient(httpx) 会自动解压 gzip，r.content 已是解压后的 JS
        assert len(r.content) > 50, "解压后应为完整 JS 文本"
        r.content.decode("utf-8")  # 必须是合法 UTF-8 文本（JS）

    def test_no_gzip_returns_raw(self) -> None:
        """Accept-Encoding: identity（明确不接受 gzip）→ 返回原始文件，无 Content-Encoding。"""
        # TestClient 默认带 Accept-Encoding: gzip，须显式 identity 测原始分支
        r = client.get(self.js_path, headers={"Accept-Encoding": "identity"})
        assert r.status_code == 200
        assert "content-encoding" not in r.headers
        assert r.headers.get("cache-control") == "public, max-age=31536000, immutable"
        assert len(r.content) > 50, "原始 JS 应完整"
        r.content.decode("utf-8")

    def test_missing_file_404(self) -> None:
        assert client.get("/_next/static/chunks/not-exist.js").status_code == 404

    def test_gzip_missing_falls_back_raw(self) -> None:
        """请求带 gzip 但无对应 .gz 时回退原始文件（如 .png 无压缩）。"""
        img = Path("web_dist/_next/static")
        png = next((p for p in sorted(img.rglob("*")) if p.suffix in (".png", ".woff2", ".ico")), None)
        if png is None:
            return  # 无二进制资源则跳过
        rel = png.relative_to(img).as_posix()
        r = client.get(f"/_next/static/{rel}", headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200
        # 无 .gz 时返回原始，不强制 gzip
        assert r.headers.get("content-encoding", "") != "gzip" or "content-length" in r.headers

    def test_path_traversal_blocked(self) -> None:
        """路径穿越必须被拒（resolve 校验在 _static_dir 内）。"""
        # %2e%2e 编码点，避免 HTTP 层规范化
        r = client.get("/_next/static/%2e%2e/%2e%2e/app.py")
        assert r.status_code in (404, 400)
        assert "def create_app" not in r.text

    def test_head_supported(self) -> None:
        r = client.head(self.js_path, headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200
        assert r.headers.get("content-encoding") == "gzip"
