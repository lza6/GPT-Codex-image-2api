from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from services.image_storage_service import ImageStorageService


def png_bytes() -> bytes:
    path = Path(tempfile.gettempdir()) / "chatgpt2api-test-image.png"
    Image.new("RGB", (2, 2), color=(255, 0, 0)).save(path, format="PNG")
    return path.read_bytes()


class FakeWebDAVClient:
    uploaded: dict[str, bytes] = {}
    deleted: list[str] = []

    def __init__(self, _settings):
        pass

    def put(self, rel: str, payload: bytes) -> str:
        self.uploaded[rel] = payload
        return f"https://dav.example.test/{rel}"

    def get(self, rel: str) -> bytes:
        return self.uploaded[rel]

    def delete(self, rel: str) -> bool:
        self.deleted.append(rel)
        self.uploaded.pop(rel, None)
        return True

    def test(self) -> dict[str, object]:
        self.put(".chatgpt2api_webdav_test.txt", b"chatgpt2api webdav test\n")
        self.delete(".chatgpt2api_webdav_test.txt")
        return {"ok": True, "status": 200, "error": None}


class ImageStorageServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.images_dir = self.data_dir / "images"
        self.settings = {
            "enabled": False,
            "mode": "local",
            "webdav_url": "",
            "webdav_username": "",
            "webdav_password": "",
            "webdav_root_path": "chatgpt2api/images",
            "public_base_url": "",
        }
        self.config_patcher = mock.patch("services.image_storage_service.config")
        self.mock_config = self.config_patcher.start()
        self.addCleanup(self.config_patcher.stop)
        self.mock_config.images_dir = self.images_dir
        self.mock_config.base_url = "http://app.test"
        self.mock_config.cleanup_old_images.return_value = 0
        self.mock_config.get_image_storage_settings.side_effect = lambda: dict(self.settings)
        FakeWebDAVClient.uploaded = {}
        FakeWebDAVClient.deleted = []

    def service(self) -> ImageStorageService:
        return ImageStorageService(self.data_dir / "image_index.json")

    def test_local_mode_saves_to_local_directory(self):
        stored = self.service().save(png_bytes(), "http://app.test")

        self.assertEqual(stored.storage, "local")
        self.assertTrue((self.images_dir / stored.rel).is_file())
        self.assertEqual(stored.url, f"http://app.test/images/{stored.rel}")

    def test_webdav_mode_uploads_without_local_file(self):
        self.settings.update({
            "enabled": True,
            "mode": "webdav",
            "webdav_url": "https://dav.example.test",
            "webdav_password": "secret",
        })
        with mock.patch("services.image_storage_service.WebDAVClient", FakeWebDAVClient):
            stored = self.service().save(png_bytes(), "http://app.test")
            payload = self.service().get_bytes(stored.rel)

        self.assertEqual(stored.storage, "webdav")
        self.assertFalse((self.images_dir / stored.rel).exists())
        self.assertIn(stored.rel, FakeWebDAVClient.uploaded)
        self.assertEqual(payload, FakeWebDAVClient.uploaded[stored.rel])

    def test_list_items_ignores_non_image_files(self):
        image = png_bytes()
        image_path = self.images_dir / "2026" / "05" / "07" / "sample.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image)
        (self.images_dir / ".DS_Store").write_text("not an image", encoding="utf-8")
        (self.images_dir / "2026" / ".DS_Store").write_text("not an image", encoding="utf-8")

        items = self.service().list_items("http://app.test")

        self.assertEqual([item["rel"] for item in items], ["2026/05/07/sample.png"])
        self.assertEqual(items[0]["storage"], "local")

    def test_both_mode_saves_to_local_and_webdav(self):
        self.settings.update({
            "enabled": True,
            "mode": "both",
            "webdav_url": "https://dav.example.test",
            "webdav_password": "secret",
            "public_base_url": "https://cdn.example.test/images",
        })
        with mock.patch("services.image_storage_service.WebDAVClient", FakeWebDAVClient):
            stored = self.service().save(png_bytes(), "http://app.test")

        self.assertEqual(stored.storage, "both")
        self.assertTrue((self.images_dir / stored.rel).is_file())
        self.assertIn(stored.rel, FakeWebDAVClient.uploaded)
        self.assertEqual(stored.url, f"https://cdn.example.test/images/{stored.rel}")

    def test_test_webdav_writes_and_deletes_probe_file(self):
        self.settings.update({
            "enabled": True,
            "mode": "webdav",
            "webdav_url": "https://dav.example.test",
            "webdav_password": "secret",
        })
        with mock.patch("services.image_storage_service.WebDAVClient", FakeWebDAVClient):
            result = self.service().test_webdav()

        self.assertTrue(result["ok"])
        self.assertIn(".chatgpt2api_webdav_test.txt", FakeWebDAVClient.deleted)


class FakeR2Client:
    uploaded: dict[str, bytes] = {}
    deleted: list[str] = []

    def __init__(self, _settings):
        pass

    def put(self, rel: str, payload: bytes) -> dict[str, object]:
        self.uploaded[rel] = payload
        return {"key": f"images/{rel}", "etag": "abc"}

    def get(self, rel: str) -> bytes:
        return self.uploaded[rel]

    def exists(self, rel: str) -> bool:
        return rel in self.uploaded

    def delete(self, rel: str) -> bool:
        self.deleted.append(rel)
        self.uploaded.pop(rel, None)
        return True

    def test_connection(self) -> dict[str, object]:
        return {"ok": True, "status": 200}


class R2StorageTests(unittest.TestCase):
    """R2 模式（Cloudflare 对象存储）行为验证。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.images_dir = self.data_dir / "images"
        self.settings = {
            "enabled": True,
            "mode": "r2",
            "webdav_url": "",
            "webdav_username": "",
            "webdav_password": "",
            "webdav_root_path": "chatgpt2api/images",
            "r2_account_id": "test-acct",
            "r2_access_key_id": "test-access",
            "r2_secret_access_key": "test-secret",
            "r2_bucket": "test-bucket",
            "r2_prefix": "images",
            "public_base_url": "https://cdn.example.test",
        }
        self.config_patcher = mock.patch("services.image_storage_service.config")
        self.mock_config = self.config_patcher.start()
        self.addCleanup(self.config_patcher.stop)
        self.mock_config.images_dir = self.images_dir
        self.mock_config.base_url = "http://app.test"
        self.mock_config.cleanup_old_images.return_value = 0
        self.mock_config.get_image_storage_settings.side_effect = lambda: dict(self.settings)
        FakeR2Client.uploaded = {}
        FakeR2Client.deleted = []

    def service(self) -> ImageStorageService:
        return ImageStorageService(self.data_dir / "image_index.json")

    def test_r2_mode_uploads_and_returns_cdn_url(self):
        with mock.patch("services.image_storage_service.R2Client", FakeR2Client):
            stored = self.service().save(png_bytes(), "http://app.test")

        self.assertEqual(stored.storage, "r2")
        self.assertFalse((self.images_dir / stored.rel).exists())
        self.assertIn(stored.rel, FakeR2Client.uploaded)
        # public_base_url + r2_prefix + rel = 永久直链
        self.assertEqual(stored.url, f"https://cdn.example.test/images/{stored.rel}")

    def test_r2_get_bytes_fetches_from_r2(self):
        with mock.patch("services.image_storage_service.R2Client", FakeR2Client):
            stored = self.service().save(png_bytes(), "http://app.test")
            payload = self.service().get_bytes(stored.rel)

        self.assertEqual(payload, FakeR2Client.uploaded[stored.rel])

    def test_r2_local_mode_falls_back_to_local_on_upload_failure(self):
        self.settings.update({"mode": "r2_local"})

        def boom(_rel, _payload):
            raise RuntimeError("r2 down")

        with mock.patch("services.image_storage_service.R2Client") as mock_cls:
            mock_cls.return_value.put = boom
            stored = self.service().save(png_bytes(), "http://app.test")

        # R2 上传失败降级本地：storage 如实标 local（与 both 模式 WebDAV 失败降级约定一致），
        # 但 URL 仍指向 CDN 直链，请求不因 R2 故障而失败。
        self.assertEqual(stored.storage, "local")
        self.assertTrue((self.images_dir / stored.rel).is_file())
        self.assertEqual(stored.url, f"https://cdn.example.test/images/{stored.rel}")

    def test_pure_r2_mode_raises_on_upload_failure(self):
        def boom(_rel, _payload):
            raise RuntimeError("r2 down")

        with mock.patch("services.image_storage_service.R2Client") as mock_cls:
            mock_cls.return_value.put = boom
            with self.assertRaises(RuntimeError):
                self.service().save(png_bytes(), "http://app.test")

    def test_r2_delete_removes_object(self):
        with mock.patch("services.image_storage_service.R2Client", FakeR2Client):
            stored = self.service().save(png_bytes(), "http://app.test")
            removed = self.service().delete(stored.rel)

        self.assertTrue(removed)
        self.assertIn(stored.rel, FakeR2Client.deleted)
        self.assertNotIn(stored.rel, FakeR2Client.uploaded)

    def test_test_r2_reports_ok(self):
        with mock.patch("services.image_storage_service.R2Client", FakeR2Client):
            result = self.service().test_r2()

        self.assertTrue(result["ok"])

    def test_r2_disabled_reports_not_enabled(self):
        self.settings.update({"mode": "local"})
        result = self.service().test_r2()

        self.assertFalse(result["ok"])
        self.assertIn("R2 未启用", str(result["error"]))


if __name__ == "__main__":
    unittest.main()
