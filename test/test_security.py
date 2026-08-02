"""安全审查测试：密码管理、输入校验、注入风险、凭证处理。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT_DIR / "config.json"


class SecurityTests(unittest.TestCase):
    """安全审查测试套件。"""

    def setUp(self):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            self.config = json.load(f)

    def test_no_hardcoded_secrets(self):
        """检查代码中是否有硬编码密钥。

        仅检查已知模式，不保证完全覆盖。
        """
        import re
        patterns = [
            r'sk-[a-zA-Z0-9]{20,}',
            r'ghp_[a-zA-Z0-9]{36}',
            r'gho_[a-zA-Z0-9]{36}',
            r'AKIA[0-9A-Z]{16}',
        ]
        for py_file in Path(ROOT_DIR).rglob("*.py"):
            if ".venv" in str(py_file) or "graft" in str(py_file):
                continue
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for pattern in patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    # 跳过测试文件中的示例密钥
                    if "example" in content.lower() or "test" in str(py_file).lower():
                        continue
                    self.fail(f"发现硬编码密钥: {py_file} 匹配 {match[:20]}...")

    def test_no_bare_except(self):
        """裸露的 except: 必须为零——发现即 fail（原为只 print 不 fail 的假测试）。"""
        offenders: list[str] = []
        for py_file in Path(ROOT_DIR).rglob("*.py"):
            path_str = str(py_file)
            if ".venv" in path_str or "graft" in path_str or "node_modules" in path_str:
                continue
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped == "except:" or stripped == "except :":
                    # 排除 __init__.py 和明确注释
                    if "pragma: no cover" in line:
                        continue
                    offenders.append(f"{py_file}:{i}")
        self.assertEqual(offenders, [],
                         f"发现 {len(offenders)} 处裸露 except: 吞错——必须改为具体异常类型：\n" + "\n".join(offenders[:10]))

    def test_rate_limit_middleware_coverage(self):
        """限流中间件真实注册且行为生效：超限返回 429。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from api.rate_limit import SlidingWindowLimiter
        # 行为断言：窗口内 max_requests+1 个请求必须被拒绝
        limiter = SlidingWindowLimiter(window_seconds=60.0, max_requests=3)
        for _ in range(3):
            self.assertTrue(limiter.check("k"))
        self.assertFalse(limiter.check("k"), "超限请求未被拒绝——限流失效")
        # 中间件确实挂载在 app 上
        from api.app import create_app
        app = create_app()
        middleware_names = [getattr(m.cls, "__name__", "") for m in app.user_middleware]
        self.assertIn("RateLimitMiddleware", middleware_names,
                      f"限流中间件未注册到 app：{middleware_names}")

    def test_auth_required_on_api(self):
        """关键管理端点无鉴权必须 401（真实行为断言，非结构检查）。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from fastapi.testclient import TestClient

        from api.app import create_app
        client = TestClient(create_app())
        protected = [
            "/api/settings",
            "/api/accounts",
            "/api/dashboard/scheduler",
            "/api/proxies",
            "/api/backups",
        ]
        for path in protected:
            resp = client.get(path)
            self.assertEqual(resp.status_code, 401,
                             f"{path} 无鉴权访问返回 {resp.status_code} 而非 401——鉴权失守")
        # 错误密钥也必须 401
        resp = client.get("/api/settings", headers={"Authorization": "Bearer definitely-wrong-key-xyz"})
        self.assertEqual(resp.status_code, 401, "错误密钥未返回 401——鉴权可被绕过")


class SecurityHardeningTests(unittest.TestCase):
    """S3 安全加固行为测试：CORS/请求体限制/安全头/metrics鉴权/弱口令。"""

    def _client(self):
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from fastapi.testclient import TestClient

        from api.app import create_app
        return TestClient(create_app())

    def test_request_body_limit_returns_413(self):
        """超限 chat 请求体（>10MB）返回 413。"""
        client = self._client()
        big = "x" * (11 * 1024 * 1024)  # 11MB 超 chat 10MB 上限
        resp = client.post(
            "/v1/chat/completions",
            content=big,
            headers={"Content-Type": "application/json", "Authorization": "Bearer chatgpt2api"},
        )
        self.assertEqual(resp.status_code, 413, f"超限应 413，实际 {resp.status_code}")

    def test_security_headers_present(self):
        """响应含安全头（nosniff/DENY/Referrer-Policy）。"""
        client = self._client()
        resp = client.get("/api/dashboard/scheduler", headers={"Authorization": "Bearer chatgpt2api"})
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(resp.headers.get("x-frame-options"), "DENY")
        self.assertEqual(resp.headers.get("referrer-policy"), "strict-origin-when-cross-origin")

    def test_metrics_requires_auth(self):
        """/metrics 未授权访问被拒（401/403）。"""
        client = self._client()
        resp = client.get("/metrics")
        self.assertIn(resp.status_code, (401, 403), f"/metrics 无鉴权应拒，实际 {resp.status_code}")

    def test_metrics_with_token_ok(self):
        """/metrics 带 ?token= 可访问。"""
        client = self._client()
        resp = client.get("/metrics?token=chatgpt2api")
        self.assertEqual(resp.status_code, 200)

    def test_weak_auth_key_detected(self):
        """弱口令检测函数正确识别。"""
        import sys
        sys.path.insert(0, str(ROOT_DIR))
        from services.config import _is_weak_auth_key
        self.assertTrue(_is_weak_auth_key("chatgpt2api"))
        self.assertTrue(_is_weak_auth_key("admin"))
        self.assertTrue(_is_weak_auth_key("short"))
        self.assertFalse(_is_weak_auth_key("a" * 24))


if __name__ == "__main__":
    unittest.main()