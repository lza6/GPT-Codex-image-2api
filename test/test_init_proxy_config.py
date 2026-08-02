import errno
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "init_proxy_config.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("init_proxy_config_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class InitProxyConfigTests(unittest.TestCase):
    def test_creates_warp_defaults_when_proxy_runtime_missing(self) -> None:
        module = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"auth-key": "secret", "proxy": ""}), encoding="utf-8")
            with patch.dict(os.environ, {"CHATGPT2API_CONFIG_FILE": str(path)}, clear=False):
                self.assertEqual(module.main(), 0)

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["auth-key"], "secret")
            runtime = data["proxy_runtime"]
            self.assertTrue(runtime["enabled"])
            self.assertEqual(runtime["egress_mode"], "single_proxy")
            self.assertEqual(runtime["proxy_url"], "http://privoxy:8118")
            self.assertTrue(runtime["clearance"]["enabled"])
            self.assertEqual(runtime["clearance"]["mode"], "flaresolverr")
            self.assertEqual(runtime["clearance"]["flaresolverr_url"], "http://flaresolverr:8191")

    def test_existing_custom_runtime_is_not_overwritten(self) -> None:
        module = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "auth-key": "secret",
                        "proxy_runtime": {
                            "enabled": False,
                            "egress_mode": "single_proxy",
                            "proxy_url": "http://custom.proxy:8080",
                            "clearance": {
                                "enabled": True,
                                "mode": "manual",
                                "cf_clearance": "manual-token",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CHATGPT2API_CONFIG_FILE": str(path)}, clear=False):
                self.assertEqual(module.main(), 0)

            runtime = json.loads(path.read_text(encoding="utf-8"))["proxy_runtime"]
            self.assertFalse(runtime["enabled"])
            self.assertEqual(runtime["proxy_url"], "http://custom.proxy:8080")
            self.assertEqual(runtime["clearance"]["mode"], "manual")
            self.assertEqual(runtime["clearance"]["cf_clearance"], "manual-token")
            self.assertIn("timeout_sec", runtime["clearance"])
            self.assertIn("reset_session_status_codes", runtime)

    def test_env_can_disable_runtime_defaults_for_warp_compose(self) -> None:
        module = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"auth-key": "secret"}), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "CHATGPT2API_CONFIG_FILE": str(path),
                    "CHATGPT2API_PROXY_RUNTIME_ENABLED": "false",
                    "CHATGPT2API_PROXY_RUNTIME_CLEARANCE_ENABLED": "false",
                },
                clear=False,
            ):
                self.assertEqual(module.main(), 0)

            runtime = json.loads(path.read_text(encoding="utf-8"))["proxy_runtime"]
            self.assertFalse(runtime["enabled"])
            self.assertFalse(runtime["clearance"]["enabled"])
            self.assertEqual(runtime["clearance"]["mode"], "none")

    def test_bind_mounted_config_file_falls_back_when_atomic_replace_is_busy(self) -> None:
        module = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"auth-key": "secret", "proxy": ""}), encoding="utf-8")
            original_replace = Path.replace

            def replace_with_ebusy(self: Path, target: Path) -> Path:
                if self.name == "config.json.tmp":
                    raise OSError(errno.EBUSY, "Device or resource busy")
                return original_replace(self, target)

            with patch.dict(os.environ, {"CHATGPT2API_CONFIG_FILE": str(path)}, clear=False):
                with patch.object(Path, "replace", replace_with_ebusy):
                    self.assertEqual(module.main(), 0)

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["proxy_runtime"]["enabled"])
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
