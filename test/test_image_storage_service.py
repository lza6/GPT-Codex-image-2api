from __future__ import annotations

import hashlib
import hmac
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from services.image_storage_service import ImageStorageError, ImageStorageService, R2Client


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


def _reference_sigv4_signature(secret: str, now: datetime, method: str, path: str, query: dict[str, str], body: bytes) -> str:
    """独立参考实现：用与被测 `_aws_v4_headers` 相同步骤重算签名，验证被测无步骤漂移。"""
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {
        "host": "test-acct.r2.cloudflarestorage.com",
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    sorted_items = sorted((key.lower(), " ".join(str(value).strip().split())) for key, value in headers.items())
    canonical_headers = "".join(f"{key}:{value}\n" for key, value in sorted_items)
    signed_headers = ";".join(key for key, _ in sorted_items)
    encoded_query = urlencode(sorted((query or {}).items()))
    canonical_request = "\n".join([method.upper(), path, encoded_query, canonical_headers, signed_headers, payload_hash])
    scope = f"{date_stamp}/auto/s3/aws4_request"
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])
    k_date = hmac.new(("AWS4" + secret).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    k_region = hmac.new(k_date, b"auto", hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    return hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


class FakeResponse:
    def __init__(self, status_code: int = 200, content: bytes = b"", text: str = "", headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.content = content
        self.text = text
        self.headers = headers or {}


class FakeR2Session:
    """可编程 R2 HTTP 会话替身：响应队列按调用顺序消费（含分页 continuation）。"""

    responses: list[tuple[str, FakeResponse]] = []

    def __init__(self, **kwargs):
        self.calls = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append({
            "method": method.upper(),
            "url": url,
            "headers": kwargs.get("headers", {}),
            "data": kwargs.get("data", b""),
            "timeout": kwargs.get("timeout"),
        })
        for i, (exp_method, resp) in enumerate(FakeR2Session.responses):
            if exp_method == method.upper():
                return FakeR2Session.responses.pop(i)[1]
        return FakeResponse(status_code=404, text="<Error>no response programmed</Error>")

    def close(self) -> None:
        pass


class R2ClientTests(unittest.TestCase):
    """R2Client 层直接验证：SigV4 签名 / object_key / HTTP 语义 / ListObjectsV2 解析。"""

    def setUp(self):
        self.settings = {
            "r2_account_id": "test-acct",
            "r2_access_key_id": "test-access",
            "r2_secret_access_key": "test-secret",
            "r2_bucket": "test-bucket",
            "r2_prefix": "images",
        }
        self.session_patcher = mock.patch("services.image_storage_service.requests.Session", FakeR2Session)
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)
        FakeR2Session.responses = []

    def client(self) -> R2Client:
        return R2Client(self.settings)

    def test_validate_raises_on_missing_r2_fields(self):
        self.settings = {**self.settings, "r2_access_key_id": "", "r2_bucket": ""}
        with self.assertRaises(ImageStorageError) as ctx:
            self.client().validate()
        message = str(ctx.exception)
        self.assertIn("r2_access_key_id", message)
        self.assertIn("r2_bucket", message)

    def test_object_key_prefixes_rel(self):
        self.assertEqual(self.client().object_key("2026/08/12/a.png"), "images/2026/08/12/a.png")
        self.assertEqual(self.client().object_key("a.png"), "images/a.png")

    def test_object_key_sanitizes_traversal(self):
        # `..` 段会被 _safe_relative_path 直接拒绝（HTTPException 404），防路径穿越而非清理
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):
            self.client().object_key("../escape.png")

    def test_aws_v4_headers_contain_expected_components(self):
        fixed = datetime(2026, 8, 12, 3, 4, 5, tzinfo=UTC)
        with mock.patch("services.image_storage_service._utc_now", return_value=fixed):
            _, headers = self.client()._aws_v4_headers(
                "PUT", "/test-bucket/images/a.png", body=b"hello", extra_headers={"content-type": "image/png"}
            )
        self.assertEqual(headers["x-amz-date"], "20260812T030405Z")
        self.assertEqual(headers["x-amz-content-sha256"], hashlib.sha256(b"hello").hexdigest())
        auth = headers["authorization"]
        self.assertTrue(auth.startswith("AWS4-HMAC-SHA256 "))
        self.assertIn("Credential=test-access/20260812/auto/s3/aws4_request", auth)
        self.assertIn("SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date", auth)

    def test_aws_v4_signature_matches_independent_reference(self):
        fixed = datetime(2026, 8, 12, 3, 4, 5, tzinfo=UTC)
        with mock.patch("services.image_storage_service._utc_now", return_value=fixed):
            _, headers = self.client()._aws_v4_headers("GET", "/test-bucket", query={"list-type": "2", "max-keys": "1"})
        expected = _reference_sigv4_signature("test-secret", fixed, "GET", "/test-bucket", {"list-type": "2", "max-keys": "1"}, b"")
        self.assertEqual(headers["authorization"].split("Signature=")[1], expected)

    def test_put_returns_key_and_etag(self):
        FakeR2Session.responses = [("PUT", FakeResponse(status_code=200, headers={"etag": '"abc123"'}))]
        result = self.client().put("a.png", b"data", content_type="image/png")
        self.assertEqual(result["key"], "images/a.png")
        self.assertEqual(result["etag"], "abc123")

    def test_put_raises_on_error_status(self):
        FakeR2Session.responses = [("PUT", FakeResponse(status_code=500, text="<Error/>"))]
        with self.assertRaises(ImageStorageError):
            self.client().put("a.png", b"data")

    def test_get_returns_content(self):
        FakeR2Session.responses = [("GET", FakeResponse(status_code=200, content=b"\x89PNG\r\n"))]
        self.assertEqual(self.client().get("a.png"), b"\x89PNG\r\n")

    def test_get_404_raises_not_found(self):
        FakeR2Session.responses = [("GET", FakeResponse(status_code=404))]
        with self.assertRaises(ImageStorageError) as ctx:
            self.client().get("missing.png")
        self.assertIn("不存在", str(ctx.exception))

    def test_delete_404_returns_false(self):
        FakeR2Session.responses = [("DELETE", FakeResponse(status_code=404))]
        self.assertFalse(self.client().delete("gone.png"))

    def test_delete_success_returns_true(self):
        FakeR2Session.responses = [("DELETE", FakeResponse(status_code=204))]
        self.assertTrue(self.client().delete("a.png"))

    def test_list_objects_parses_list_v2(self):
        xml = (
            "<ListBucketResult><IsTruncated>false</IsTruncated>"
            "<Contents><Key>images/2026/08/12/a.png</Key><Size>1024</Size>"
            "<LastModified>2026-08-12T03:04:05.000Z</LastModified></Contents>"
            "<Contents><Key>images/b.png</Key><Size>2048</Size>"
            "<LastModified>2026-08-11T00:00:00.000Z</LastModified></Contents>"
            "</ListBucketResult>"
        )
        FakeR2Session.responses = [("GET", FakeResponse(status_code=200, text=xml))]
        items = self.client().list_objects()
        self.assertEqual([item["rel"] for item in items], ["2026/08/12/a.png", "b.png"])
        self.assertEqual(items[0]["size"], 1024)
        self.assertEqual(items[1]["size"], 2048)
        # 按 updated_at 倒序
        self.assertGreater(items[0]["updated_at"], items[1]["updated_at"])

    def test_list_objects_follows_continuation(self):
        page1 = (
            "<ListBucketResult><IsTruncated>true</IsTruncated><NextContinuationToken>tok-2</NextContinuationToken>"
            "<Contents><Key>images/a.png</Key><Size>1</Size></Contents></ListBucketResult>"
        )
        page2 = (
            "<ListBucketResult><IsTruncated>false</IsTruncated>"
            "<Contents><Key>images/b.png</Key><Size>2</Size></Contents></ListBucketResult>"
        )
        FakeR2Session.responses = [("GET", FakeResponse(status_code=200, text=page1)), ("GET", FakeResponse(status_code=200, text=page2))]
        items = self.client().list_objects()
        self.assertEqual([item["rel"] for item in items], ["a.png", "b.png"])

    def test_connection_requires_valid_session(self):
        FakeR2Session.responses = [("GET", FakeResponse(status_code=200, text="<ListBucketResult/>"))]
        result = self.client().test_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], 200)


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


def test_sync_endpoint_maps_image_storage_error_to_400():
    """api/system.py 同步端点把 ImageStorageError 映射为 HTTPException 400（错误映射约定）。"""
    with mock.patch(
        "services.image_storage_service.image_storage_service.sync_all",
        side_effect=ImageStorageError("R2 配置不完整：缺少 r2_secret_access_key"),
    ):
        with TestClient(create_app()) as client:
            resp = client.post("/api/image-storage/sync", headers={"Authorization": "Bearer chatgpt2api"})
    assert resp.status_code == 400
    assert "R2 配置不完整" in resp.json()["detail"]["error"]


def test_test_endpoint_uses_r2_when_mode_is_r2():
    """测试端点按模式分流：r2/r2_local 时调用 test_r2 而非 test_webdav。"""
    with mock.patch("services.image_storage_service.image_storage_service.mode", return_value="r2"), \
         mock.patch("services.image_storage_service.image_storage_service.test_r2", return_value={"ok": True, "status": 200}), \
         mock.patch("services.image_storage_service.image_storage_service.test_webdav", side_effect=AssertionError("不应调用 test_webdav")):
        with TestClient(create_app()) as client:
            resp = client.post("/api/image-storage/test", headers={"Authorization": "Bearer chatgpt2api"})
    assert resp.status_code == 200
    assert resp.json()["result"]["ok"] is True


def test_test_endpoint_uses_webdav_when_mode_is_local():
    """测试端点按模式分流：非 r2 模式调用 test_webdav。"""
    with mock.patch("services.image_storage_service.image_storage_service.mode", return_value="webdav"), \
         mock.patch("services.image_storage_service.image_storage_service.test_webdav", return_value={"ok": False, "status": 0, "error": "n/a"}), \
         mock.patch("services.image_storage_service.image_storage_service.test_r2", side_effect=AssertionError("不应调用 test_r2")):
        with TestClient(create_app()) as client:
            resp = client.post("/api/image-storage/test", headers={"Authorization": "Bearer chatgpt2api"})
    assert resp.status_code == 200
    assert resp.json()["result"]["ok"] is False


if __name__ == "__main__":
    unittest.main()
