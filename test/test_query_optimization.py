"""查询优化测试：配置缓存、采样率、路径归一化。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class ConfigCacheTests(unittest.TestCase):
    """ConfigStore auth_key/app_version 缓存测试。"""

    @classmethod
    def setUpClass(cls) -> None:
        from services import config as config_module
        cls.config_module = config_module

    def test_metrics_sample_rate_default(self) -> None:
        """未设置时 metrics_sample_rate 默认为 1.0。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            config_file = Path(tmp) / "config.json"
            config_file.write_text(json.dumps({"auth-key": "test-auth-key-12345678"}), encoding="utf-8")
            module = self.config_module
            old_base = module.BASE_DIR
            old_data = module.DATA_DIR
            old_config = module.CONFIG_FILE
            try:
                module.BASE_DIR = Path(tmp)
                module.DATA_DIR = data_dir
                module.CONFIG_FILE = config_file
                from services.config import ConfigStore
                cfg = ConfigStore(config_file)
                self.assertEqual(cfg.metrics_sample_rate, 1.0)
            finally:
                module.BASE_DIR = old_base
                module.DATA_DIR = old_data
                module.CONFIG_FILE = old_config

    def test_metrics_sample_rate_env_override(self) -> None:
        """环境变量 CHATGPT2API_METRICS_SAMPLE_RATE 覆盖配置值。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            config_file = Path(tmp) / "config.json"
            config_file.write_text(json.dumps({
                "auth-key": "test-auth-key-12345678",
                "metrics_sample_rate": 0.5,
            }), encoding="utf-8")
            os.environ["CHATGPT2API_METRICS_SAMPLE_RATE"] = "0.3"
            try:
                from services.config import ConfigStore
                cfg = ConfigStore(config_file)
                self.assertEqual(cfg.metrics_sample_rate, 0.3)
            finally:
                os.environ.pop("CHATGPT2API_METRICS_SAMPLE_RATE", None)

    def test_metrics_sample_rate_clamp(self) -> None:
        """metrics_sample_rate 超出 [0, 1] 范围被 clamp 到边界。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            config_file = Path(tmp) / "config.json"
            config_file.write_text(json.dumps({
                "auth-key": "test-auth-key-12345678",
                "metrics_sample_rate": 2.5,
            }), encoding="utf-8")
            from services.config import ConfigStore
            cfg = ConfigStore(config_file)
            self.assertEqual(cfg.metrics_sample_rate, 1.0)

    def test_metrics_sample_rate_negative(self) -> None:
        """负数 metrics_sample_rate 被 clamp 到 0.0。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            config_file = Path(tmp) / "config.json"
            config_file.write_text(json.dumps({
                "auth-key": "test-auth-key-12345678",
                "metrics_sample_rate": -0.5,
            }), encoding="utf-8")
            from services.config import ConfigStore
            cfg = ConfigStore(config_file)
            self.assertEqual(cfg.metrics_sample_rate, 0.0)

    def test_metrics_sample_rate_invalid_fallback(self) -> None:
        """非法 metrics_sample_rate 值在 schema 层面被拒绝（类型校验优先于 property fallback）。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            config_file = Path(tmp) / "config.json"
            config_file.write_text(json.dumps({
                "auth-key": "test-auth-key-12345678",
                "metrics_sample_rate": "not-a-number",
            }), encoding="utf-8")
            from services.config import ConfigStore
            with self.assertRaises(ValueError):
                ConfigStore(config_file)

    def test_metrics_sample_rate_zero(self) -> None:
        """metrics_sample_rate 为 0.0 时关闭采集。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            config_file = Path(tmp) / "config.json"
            config_file.write_text(json.dumps({
                "auth-key": "test-auth-key-12345678",
                "metrics_sample_rate": 0.0,
            }), encoding="utf-8")
            from services.config import ConfigStore
            cfg = ConfigStore(config_file)
            self.assertEqual(cfg.metrics_sample_rate, 0.0)


class PrometheusMetricsTests(unittest.TestCase):
    """Prometheus 指标路径归一化+采样测试。"""

    @classmethod
    def setUpClass(cls) -> None:
        from services import prometheus_metrics as pm
        cls.pm = pm

    def test_normalize_path_digits(self) -> None:
        """数字路径段归一化为 {id}。"""
        result = self.pm._normalize_path("/api/accounts/refresh/progress/12345")
        self.assertEqual(result, "/api/accounts/refresh/progress/{id}")

    def test_normalize_path_hex(self) -> None:
        """hex 路径段归一化为 {id}。"""
        result = self.pm._normalize_path("/api/accounts/refresh/progress/abc123def4567890")
        self.assertEqual(result, "/api/accounts/refresh/progress/{id}")

    def test_normalize_path_uuid(self) -> None:
        """UUID 路径段归一化为 {id}。"""
        result = self.pm._normalize_path("/api/images/download/550e8400-e29b-41d4-a4b4-123456789abc")
        self.assertEqual(result, "/api/images/download/{id}")

    def test_normalize_path_short(self) -> None:
        """短路径不变。"""
        result = self.pm._normalize_path("/api/metrics")
        self.assertEqual(result, "/api/metrics")

    def test_normalize_path_static(self) -> None:
        """静态 API 路径不变。"""
        result = self.pm._normalize_path("/v1/chat/completions")
        self.assertEqual(result, "/v1/chat/completions")

    def test_record_http_request_normalizes_path(self) -> None:
        """record_http_request 自动归一化 path。"""
        # 记录后检查指标是否包含归一化路径
        self.pm.record_http_request("/api/accounts/refresh/progress/12345", "GET", 200, 0.1)
        self.pm.record_http_request("/api/accounts/refresh/progress/67890", "GET", 200, 0.1)
        # 生成指标文本
        content, _ = self.pm.generate_metrics()
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        # 归一化路径应出现，原始路径不应出现
        self.assertIn("/api/accounts/refresh/progress/{id}", text)
        self.assertNotIn("12345", text)
        self.assertNotIn("67890", text)


if __name__ == "__main__":
    unittest.main()
