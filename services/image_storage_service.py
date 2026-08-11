from __future__ import annotations

import hashlib
import hmac
import io
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from urllib.parse import quote, urlencode, urlparse

from curl_cffi import requests
from fastapi import HTTPException
from PIL import Image

from services.config import DATA_DIR, config
from utils.log import logger

IMAGE_INDEX_FILE = DATA_DIR / "image_index.json"
IMAGE_INDEX_LOCK = Lock()
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hmac_sha256(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


class ImageStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredImage:
    rel: str
    url: str
    storage: str
    size: int


def _clean(value: object) -> str:
    return str(value or "").strip()


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_relative_path(path: str) -> str:
    value = str(path or "").strip().replace("\\", "/").lstrip("/")
    if not value:
        raise HTTPException(status_code=404, detail="image not found")
    parts = Path(value).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=404, detail="image not found")
    return Path(*parts).as_posix()


def _image_dimensions(payload: bytes) -> tuple[int, int] | None:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.size
    except Exception:
        return None


def _is_image_rel(path: str) -> bool:
    try:
        safe_rel = _safe_relative_path(path)
    except HTTPException:
        return False
    return Path(safe_rel).suffix.lower() in IMAGE_EXTENSIONS


def _local_image_path(relative_path: str) -> Path:
    rel = _safe_relative_path(relative_path)
    root = config.images_dir.resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="image not found") from exc
    return path


def _read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_object(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


class WebDAVClient:
    def __init__(self, settings: dict[str, object]):
        self.url = _clean(settings.get("webdav_url")).rstrip("/")
        self.username = _clean(settings.get("webdav_username"))
        self.password = _clean(settings.get("webdav_password"))
        self.root_path = _clean(settings.get("webdav_root_path")).strip("/")
        self.session = requests.Session()

    def _auth_kwargs(self) -> dict[str, object]:
        return {"auth": (self.username, self.password)} if self.username or self.password else {}

    def _request(self, method: str, url: str, **kwargs):
        response = self.session.request(method, url, timeout=30, **self._auth_kwargs(), **kwargs)
        if response.status_code >= 400 and not (method == "MKCOL" and response.status_code in {405}):
            raise ImageStorageError(f"WebDAV {method} failed: HTTP {response.status_code}")
        return response

    def remote_url(self, rel: str = "") -> str:
        parts = [part for part in [self.root_path, _safe_relative_path(rel) if rel else ""] if part]
        encoded = "/".join(quote(part, safe="") for item in parts for part in item.split("/") if part)
        return f"{self.url}/{encoded}" if encoded else self.url

    def ensure_dirs(self, rel: str) -> None:
        parts = [part for part in [self.root_path, Path(_safe_relative_path(rel)).parent.as_posix()] if part and part != "."]
        current = self.url
        for item in "/".join(parts).split("/"):
            if not item:
                continue
            current = f"{current}/{quote(item, safe='')}"
            response = self.session.request("MKCOL", current, timeout=30, **self._auth_kwargs())
            if response.status_code in {201, 405}:
                continue
            if response.status_code >= 400:
                raise ImageStorageError(f"WebDAV MKCOL failed: HTTP {response.status_code}")

    def put(self, rel: str, payload: bytes, content_type: str = "image/png") -> str:
        self.ensure_dirs(rel)
        url = self.remote_url(rel)
        self._request("PUT", url, data=payload, headers={"Content-Type": content_type})
        return url

    def get(self, rel: str) -> bytes:
        response = self._request("GET", self.remote_url(rel))
        return bytes(response.content)

    def delete(self, rel: str) -> bool:
        response = self.session.request("DELETE", self.remote_url(rel), timeout=30, **self._auth_kwargs())
        if response.status_code in {200, 202, 204, 404}:
            return response.status_code != 404
        raise ImageStorageError(f"WebDAV DELETE failed: HTTP {response.status_code}")

    def test(self) -> dict[str, object]:
        if not self.url:
            return {"ok": False, "status": 0, "error": "WebDAV URL is required"}
        if urlparse(self.url).scheme not in {"http", "https"}:
            return {"ok": False, "status": 0, "error": "invalid WebDAV URL"}
        test_rel = ".chatgpt2api_webdav_test.txt"
        try:
            self.put(test_rel, b"chatgpt2api webdav test\n", content_type="text/plain")
            self.delete(test_rel)
            return {"ok": True, "status": 200, "error": None}
        except ImageStorageError as exc:
            return {"ok": False, "status": 0, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "status": 0, "error": str(exc) or exc.__class__.__name__}
        finally:
            self.session.close()


class R2Client:
    """Cloudflare R2 客户端（S3 兼容 API，AWS SigV4 签名，纯 Python 无 boto3）。

    参考 chatgpt2api1/services/backup_service.py 的 CloudflareR2Client 实现。
    endpoint 固定为 https://<account_id>.r2.cloudflarestorage.com
    支持：连接测试 / 上传字节 / 读取 / 删除 / 列对象（ListObjectsV2 解析）。
    """

    def __init__(self, settings: dict[str, object]) -> None:
        self.account_id = _clean(settings.get("r2_account_id"))
        self.access_key_id = _clean(settings.get("r2_access_key_id"))
        self.secret_access_key = _clean(settings.get("r2_secret_access_key"))
        self.bucket = _clean(settings.get("r2_bucket"))
        self.prefix = _clean(settings.get("r2_prefix")) or "images"
        self.session = requests.Session(impersonate="chrome", verify=True)

    def validate(self) -> None:
        missing = []
        if not self.account_id:
            missing.append("r2_account_id")
        if not self.access_key_id:
            missing.append("r2_access_key_id")
        if not self.secret_access_key:
            missing.append("r2_secret_access_key")
        if not self.bucket:
            missing.append("r2_bucket")
        if missing:
            raise ImageStorageError(f"R2 配置不完整：缺少 {'、'.join(missing)}")

    @property
    def endpoint(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    def object_key(self, rel: str) -> str:
        safe = _safe_relative_path(rel)
        return f"{self.prefix.rstrip('/')}/{safe}"

    def _aws_v4_headers(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str]]:
        now = _utc_now()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        encoded_query = urlencode(sorted((query or {}).items()))
        payload_hash = _sha256_hex(body)
        host = f"{self.account_id}.r2.cloudflarestorage.com"
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if extra_headers:
            for key, value in extra_headers.items():
                headers[key.lower()] = value.strip()
        sorted_items = sorted((key.lower(), " ".join(str(value).strip().split())) for key, value in headers.items())
        canonical_headers = "".join(f"{key}:{value}\n" for key, value in sorted_items)
        signed_headers = ";".join(key for key, _ in sorted_items)
        canonical_request = "\n".join([
            method.upper(),
            path,
            encoded_query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ])
        credential_scope = f"{date_stamp}/auto/s3/aws4_request"
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            _sha256_hex(canonical_request.encode("utf-8")),
        ])
        k_date = _hmac_sha256(("AWS4" + self.secret_access_key).encode("utf-8"), date_stamp)
        k_region = hmac.new(k_date, b"auto", hashlib.sha256).digest()
        k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        request_headers = {key: value for key, value in headers.items()}
        request_headers["authorization"] = authorization
        return encoded_query, request_headers

    def _request(
        self,
        method: str,
        rel: str = "",
        *,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        extra_headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ):
        object_path = f"/{self.bucket}"
        if rel:
            object_path += f"/{quote(self.object_key(rel), safe='/')}"
        encoded_query, headers = self._aws_v4_headers(method, object_path, query=query, body=body, extra_headers=extra_headers)
        url = f"{self.endpoint}{object_path}"
        if encoded_query:
            url += f"?{encoded_query}"
        return self.session.request(method.upper(), url, headers=headers, data=body, timeout=timeout)

    def test_connection(self) -> dict[str, object]:
        self.validate()
        response = self._request("GET", query={"list-type": "2", "max-keys": "1"}, timeout=30.0)
        if response.status_code >= 400:
            raise ImageStorageError(f"连接 R2 失败：HTTP {response.status_code}")
        return {"ok": True, "status": int(response.status_code)}

    def put(self, rel: str, payload: bytes, content_type: str = "image/png") -> dict[str, object]:
        self.validate()
        headers = {"content-type": content_type}
        response = self._request("PUT", rel, body=payload, extra_headers=headers)
        if response.status_code >= 400:
            raise ImageStorageError(f"R2 上传失败：HTTP {response.status_code}")
        return {"key": self.object_key(rel), "etag": str(response.headers.get("etag") or "").strip('"')}

    def get(self, rel: str) -> bytes:
        self.validate()
        response = self._request("GET", rel, timeout=90.0)
        if response.status_code == 404:
            raise ImageStorageError(f"R2 对象不存在：{rel}")
        if response.status_code >= 400:
            raise ImageStorageError(f"R2 读取失败：HTTP {response.status_code}")
        return bytes(response.content)

    def delete(self, rel: str) -> bool:
        self.validate()
        response = self._request("DELETE", rel, timeout=30.0)
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            raise ImageStorageError(f"R2 删除失败：HTTP {response.status_code}")
        return True

    def exists(self, rel: str) -> bool:
        self.validate()
        response = self._request("HEAD", rel, timeout=30.0)
        return response.status_code == 200

    def list_objects(self) -> list[dict[str, object]]:
        self.validate()
        items: list[dict[str, object]] = []
        continuation = ""
        while True:
            query = {"list-type": "2", "prefix": f"{self.prefix.rstrip('/')}/", "max-keys": "1000"}
            if continuation:
                query["continuation-token"] = continuation
            response = self._request("GET", query=query, timeout=30.0)
            if response.status_code >= 400:
                raise ImageStorageError(f"R2 列对象失败：HTTP {response.status_code}")
            text = response.text
            for block in text.split("<Contents>")[1:]:
                key = _clean(block.split("<Key>", 1)[1].split("</Key>", 1)[0]) if "<Key>" in block else ""
                if not key:
                    continue
                size_text = _clean(block.split("<Size>", 1)[1].split("</Size>", 1)[0]) if "<Size>" in block else "0"
                updated = _clean(block.split("<LastModified>", 1)[1].split("</LastModified>", 1)[0]) if "<LastModified>" in block else ""
                rel = key[len(self.prefix.rstrip("/")):].lstrip("/")
                items.append({"rel": rel, "size": int(size_text or 0), "updated_at": updated})
            if "<IsTruncated>true</IsTruncated>" not in text or "<NextContinuationToken>" not in text:
                break
            continuation = _clean(text.split("<NextContinuationToken>", 1)[1].split("</NextContinuationToken>", 1)[0])
            if not continuation:
                break
        items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return items

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass


class ImageStorageService:
    def __init__(self, index_file: Path = IMAGE_INDEX_FILE):
        self.index_file = index_file
        self._index_lock = IMAGE_INDEX_LOCK
        self._index_cache: dict[str, dict[str, object]] | None = None
        self._index_cache_at: float = 0.0
        self._INDEX_CACHE_TTL: float = 30.0

    def settings(self) -> dict[str, object]:
        return config.get_image_storage_settings()

    def mode(self) -> str:
        return _clean(self.settings().get("mode")) or "local"

    def _r2_enabled(self) -> bool:
        """R2 是否参与读写：mode 为 r2 / r2_local 时启用。"""
        return self.mode() in {"r2", "r2_local"}

    def _r2_primary(self) -> bool:
        return self.mode() == "r2"

    def _r2_client(self) -> R2Client:
        return R2Client(self.settings())

    def _load_index(self) -> dict[str, dict[str, object]]:
        now = time.time()
        if self._index_cache is not None and now - self._index_cache_at < self._INDEX_CACHE_TTL:
            return self._index_cache
        raw = _read_json_object(self.index_file)
        items = raw.get("items")
        if not isinstance(items, dict):
            self._index_cache = {}
            self._index_cache_at = now
            return {}
        result = {str(key): value for key, value in items.items() if isinstance(value, dict)}
        self._index_cache = result
        self._index_cache_at = now
        return result

    def _load_clean_index(self) -> dict[str, dict[str, object]]:
        items = self._load_index()
        return {rel: item for rel, item in items.items() if _is_image_rel(rel)}

    def _invalidate_index_cache(self) -> None:
        self._index_cache = None
        self._index_cache_at = 0.0

    def _save_index(self, items: dict[str, dict[str, object]]) -> None:
        _write_json_object(self.index_file, {"items": items})
        self._invalidate_index_cache()

    def _public_url(self, rel: str, base_url: str | None = None) -> str:
        settings = self.settings()
        public_base_url = _clean(settings.get("public_base_url"))
        if public_base_url:
            # R2 模式：public_base_url 指向 R2 公开访问域名（自定义域 / r2.dev 子域），
            # 拼接 {prefix}/{rel} 得到永久直链，客户端可直接 <img src> 渲染，无防盗链。
            if self._r2_enabled():
                prefix = _clean(settings.get("r2_prefix")) or "images"
                return f"{public_base_url.rstrip('/')}/{prefix.rstrip('/')}/{_safe_relative_path(rel)}"
            return f"{public_base_url.rstrip('/')}/{_safe_relative_path(rel)}"
        return f"{(base_url or config.base_url).rstrip('/')}/images/{_safe_relative_path(rel)}"

    def make_relative_path(self, image_data: bytes) -> str:
        file_hash = hashlib.md5(image_data).hexdigest()
        filename = f"{int(time.time())}_{file_hash}.png"
        relative_dir = Path(time.strftime("%Y"), time.strftime("%m"), time.strftime("%d"))
        return f"{relative_dir.as_posix()}/{filename}"

    def save(self, image_data: bytes, base_url: str | None = None) -> StoredImage:
        config.cleanup_old_images()
        rel = self.make_relative_path(image_data)
        mode = self.mode()
        if mode not in {"local", "webdav", "r2", "both", "r2_local"}:
            mode = "local"
        stored_local = False
        stored_webdav = False
        stored_r2 = False
        remote_url = ""

        if mode in {"local", "both"}:
            path = _local_image_path(rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(image_data)
            stored_local = True

        if mode in {"webdav", "both"}:
            try:
                remote_url = WebDAVClient(self.settings()).put(rel, image_data)
                stored_webdav = True
            except Exception as exc:  # noqa: BLE001
                # S-B1：both 模式 WebDAV 失败降级为 local 返回——本地副本已落盘，图仍可用，
                # 不让整个请求 502 + 已扣配额却无结果。记日志便于排查，下次 sync 会补传。
                logger.warning({"event": "image_webdav_upload_failed", "rel": rel, "error": str(exc)})
                if mode == "webdav":
                    # 纯 webdav 模式（本地无副本）失败必须抛错，调用方明确感知
                    raise
                stored_webdav = False

        if mode in {"r2", "r2_local"}:
            try:
                r2_result = self._r2_client().put(rel, image_data)
                remote_url = r2_result.get("key", "")
                stored_r2 = True
            except Exception as exc:  # noqa: BLE001
                # r2_local：R2 上传失败降级为本地落盘，图仍可用；纯 r2 模式必须抛错
                logger.warning({"event": "image_r2_upload_failed", "rel": rel, "error": str(exc)})
                if mode == "r2":
                    raise
                path = _local_image_path(rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(image_data)
                stored_local = True

        dimensions = _image_dimensions(image_data)
        storage = "local"
        if stored_r2 and stored_local:
            storage = "r2_local"
        elif stored_r2:
            storage = "r2"
        elif stored_local and stored_webdav:
            storage = "both"
        elif stored_webdav:
            storage = "webdav"
        item = {
            "rel": rel,
            "path": rel,
            "name": Path(rel).name,
            "date": "-".join(rel.split("/")[:3]),
            "size": len(image_data),
            "created_at": _now_iso(),
            "storage": storage,
            "local": stored_local,
            "webdav": stored_webdav,
            "r2": stored_r2,
            "remote_url": remote_url,
        }
        if dimensions:
            item["width"], item["height"] = dimensions
        with self._index_lock:
            items = self._load_clean_index()
            items[rel] = item
            self._save_index(items)
        return StoredImage(rel=rel, url=self._public_url(rel, base_url), storage=str(item["storage"]), size=len(image_data))

    def get_bytes(self, rel: str) -> bytes:
        safe_rel = _safe_relative_path(rel)
        if not _is_image_rel(safe_rel):
            raise HTTPException(status_code=404, detail="image not found")
        path = _local_image_path(safe_rel)
        if path.is_file():
            return path.read_bytes()
        item = self._load_clean_index().get(safe_rel, {})
        if item.get("webdav"):
            return WebDAVClient(self.settings()).get(safe_rel)
        if self._r2_enabled() and item.get("r2"):
            return self._r2_client().get(safe_rel)
        raise HTTPException(status_code=404, detail="image not found")

    def exists(self, rel: str) -> bool:
        safe_rel = _safe_relative_path(rel)
        if not _is_image_rel(safe_rel):
            return False
        if _local_image_path(safe_rel).is_file():
            return True
        item = self._load_clean_index().get(safe_rel, {})
        if item.get("webdav"):
            return True
        if self._r2_enabled() and item.get("r2"):
            try:
                return self._r2_client().exists(safe_rel)
            except Exception:
                return True  # 索引标记存在，网络抖动不误判 404
        return False

    def has_local(self, rel: str) -> bool:
        safe_rel = _safe_relative_path(rel)
        return _is_image_rel(safe_rel) and _local_image_path(safe_rel).is_file()

    def list_items(self, base_url: str, start_date: str = "", end_date: str = "") -> list[dict[str, object]]:
        with self._index_lock:
            indexed = self._load_clean_index()
            root = config.images_dir
            changed = False
            for path in root.rglob("*"):
                if not path.is_file() or not _is_image_rel(path.name):
                    continue
                rel = path.relative_to(root).as_posix()
                if rel in indexed:
                    continue
                dimensions = None
                try:
                    dimensions = _image_dimensions(path.read_bytes())
                except Exception:
                    dimensions = None
                indexed[rel] = {
                    "rel": rel,
                    "path": rel,
                    "name": path.name,
                    "date": "-".join(rel.split("/")[:3]) if len(rel.split("/")) >= 4 else datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d"),
                    "size": path.stat().st_size,
                    "created_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "storage": "local",
                    "local": True,
                    "webdav": False,
                    **({"width": dimensions[0], "height": dimensions[1]} if dimensions else {}),
                }
                changed = True

            items: list[dict[str, object]] = []
            for rel, item in list(indexed.items()):
                if not _is_image_rel(rel):
                    indexed.pop(rel, None)
                    changed = True
                    continue
                local = _local_image_path(rel).is_file()
                webdav = bool(item.get("webdav"))
                r2 = bool(item.get("r2")) and self._r2_enabled()
                if not local and not webdav and not r2:
                    indexed.pop(rel, None)
                    changed = True
                    continue
                if r2:
                    storage = "r2_local" if local else "r2"
                else:
                    storage = "both" if local and webdav else ("webdav" if webdav else "local")
                if item.get("local") != local or item.get("storage") != storage:
                    item = {
                        **item,
                        "local": local,
                        "storage": storage,
                    }
                    indexed[rel] = item
                    changed = True
                day = str(item.get("date") or "")
                if start_date and day < start_date:
                    continue
                if end_date and day > end_date:
                    continue
                items.append({
                    **item,
                    "rel": rel,
                    "path": rel,
                    "url": self._public_url(rel, base_url),
                })
            if changed:
                self._save_index(indexed)
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return items

    def delete(self, rel: str) -> bool:
        safe_rel = _safe_relative_path(rel)
        removed = False
        path = _local_image_path(safe_rel)
        if path.is_file():
            path.unlink()
            removed = True
        with self._index_lock:
            items = self._load_clean_index()
            item = items.get(safe_rel, {})
            if item.get("webdav"):
                try:
                    removed = WebDAVClient(self.settings()).delete(safe_rel) or removed
                except ImageStorageError:
                    if not removed:
                        raise
            if self._r2_enabled() and item.get("r2"):
                try:
                    removed = self._r2_client().delete(safe_rel) or removed
                except ImageStorageError:
                    if not removed:
                        raise
            if safe_rel in items:
                items.pop(safe_rel, None)
                self._save_index(items)
        return removed

    def test_r2(self) -> dict[str, object]:
        """测试 R2 连通性（用于管理后台「图片存储设置」面板）。"""
        if not self._r2_enabled():
            return {"ok": False, "status": 0, "error": "R2 未启用（mode 需为 r2 或 r2_local）"}
        try:
            return self._r2_client().test_connection()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": 0, "error": str(exc) or exc.__class__.__name__}

    def sync_all(self) -> dict[str, int]:
        settings = self.settings()
        target_webdav = self.mode() in {"webdav", "both"}
        target_r2 = self.mode() in {"r2", "r2_local"}
        if not target_webdav and not target_r2:
            raise ImageStorageError("WebDAV/R2 图片存储未启用（mode 需为 webdav/both/r2/r2_local）")
        uploaded = 0
        skipped = 0
        failed = 0
        with self._index_lock:
            items = self._load_clean_index()
            webdav_client = WebDAVClient(settings) if target_webdav else None
            r2_client = self._r2_client() if target_r2 else None
            for path in sorted(config.images_dir.rglob("*")):
                if not path.is_file() or not _is_image_rel(path.name):
                    continue
                rel = path.relative_to(config.images_dir).as_posix()
                item = items.get(rel, {})
                if (target_webdav and item.get("webdav")) and (target_r2 and item.get("r2")):
                    skipped += 1
                    continue
                if target_webdav and item.get("webdav") and not target_r2:
                    skipped += 1
                    continue
                if target_r2 and item.get("r2") and not target_webdav:
                    skipped += 1
                    continue
                try:
                    payload = path.read_bytes()
                    dimensions = _image_dimensions(payload)
                    new_item = {
                        **item,
                        "rel": rel,
                        "path": rel,
                        "name": path.name,
                        "date": "-".join(rel.split("/")[:3]) if len(rel.split("/")) >= 4 else datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d"),
                        "size": len(payload),
                        "created_at": str(item.get("created_at") or datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")),
                        "local": True,
                        **({"width": dimensions[0], "height": dimensions[1]} if dimensions else {}),
                    }
                    if target_webdav:
                        remote_url = webdav_client.put(rel, payload)
                        new_item["webdav"] = True
                        new_item["remote_url"] = remote_url
                    if target_r2:
                        r2_client.put(rel, payload)
                        new_item["r2"] = True
                    if new_item.get("r2") and new_item.get("webdav"):
                        new_item["storage"] = "both"
                    elif new_item.get("r2"):
                        new_item["storage"] = "r2"
                    elif new_item.get("webdav"):
                        new_item["storage"] = "webdav"
                    else:
                        new_item["storage"] = "local"
                    items[rel] = new_item
                    uploaded += 1
                except Exception:
                    failed += 1
            self._save_index(items)
        return {"uploaded": uploaded, "skipped": skipped, "failed": failed}

    def test_webdav(self) -> dict[str, object]:
        return WebDAVClient(self.settings()).test()


image_storage_service = ImageStorageService()
