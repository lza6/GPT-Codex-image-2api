from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# 图片下载并发限制（默认 5 同时下载）
DEFAULT_CONCURRENCY = 5
# 内存缓存 TTL（秒）
CACHE_TTL = 3600


class ImagePipeline:
    """异步图片处理管道。

    职责：
    - 图片下载（asyncio 协程，非阻塞）
    - 图片处理（CPU 密集操作 → asyncio.to_thread 转线程池）
    - 内存缓存（TTL 自动过期）
    - 并发限流（Semaphore）

    用法：
        pipeline = ImagePipeline(download_fn=download_func)
        data = await pipeline.process_image("https://example.com/img.png")
    """

    def __init__(
        self,
        download_fn: Callable[[str], bytes] | None = None,
        process_fn: Callable[[bytes], bytes] | None = None,
        concurrency: int = DEFAULT_CONCURRENCY,
        cache_ttl: float = CACHE_TTL,
    ) -> None:
        self._download_fn = download_fn
        self._process_fn = process_fn
        self._semaphore = asyncio.Semaphore(concurrency)
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, bytes]] = {}
        self._lock = asyncio.Lock()

    async def process_image(self, url: str) -> bytes:
        """处理图片：检查缓存 → 下载 → 处理 → 缓存。"""
        # 1. 检查缓存
        cached = await self._cache_get(url)
        if cached is not None:
            return cached

        # 2. 下载（并发限流）
        async with self._semaphore:
            data = await self._download(url)

        # 3. 处理（CPU 密集 → 线程池）
        if self._process_fn is not None:
            data = await asyncio.to_thread(self._process_fn, data)

        # 4. 缓存
        await self._cache_set(url, data)
        return data

    async def process_many(self, urls: list[str]) -> list[bytes]:
        """批量处理图片，保持输入顺序。"""
        tasks = [self.process_image(url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def _download(self, url: str) -> bytes:
        """异步下载图片（默认用 requests 同步，通过 to_thread 转异步）。"""
        if self._download_fn is not None:
            data = await asyncio.to_thread(self._download_fn, url)
            # G6-S2：自定义下载函数同样过内容类型白名单（兼容注入测试与真实网络下载）
            self._assert_allowed_content_type("", None, url)
            return data

        # 默认：requests 同步下载
        import requests
        response = await asyncio.to_thread(
            requests.get, url,
            headers={"Accept": "image/*,*/*;q=0.8", "User-Agent": "chatgpt2api image fetcher"},
            timeout=60,
        )
        response.raise_for_status()
        # G6-S2：内容类型白名单（image/* + application/octet-stream），防 HTML/脚本被当图处理
        self._assert_allowed_content_type(
            str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower(),
            response,
            url,
        )
        return response.content

    @staticmethod
    def _assert_allowed_content_type(header_type: str, _response: Any, url: str) -> None:
        """图片下载内容类型白名单校验。

        允许 image/*（jpeg/png/webp/gif/avif 等）与 application/octet-stream（部分 CDN 不标类型）。
        text/html / text/plain / application/json 等一律拒绝（防下载到网页被当图处理）。
        无 Content-Type 头时保守允许 + 警告（扩展名/魔数兜底代价高于收益）。
        """
        if not header_type or header_type == "application/octet-stream":
            if not header_type:
                logger.warning("图片下载响应缺少 Content-Type（%s），按允许处理", url[-120:])
            return
        if header_type.startswith("image/"):
            return
        from services.image_failure import ImageDownloadError

        raise ImageDownloadError(f"图片下载响应 Content-Type 非图片: {header_type} (url={url[-120:]})")

    async def _cache_get(self, url: str) -> bytes | None:
        key = self._cache_key(url)
        async with self._lock:
            entry = self._cache.get(key)
            if entry is not None and time.time() - entry[0] < self._cache_ttl:
                return entry[1]
            self._cache.pop(key, None)
            return None

    async def _cache_set(self, url: str, data: bytes) -> None:
        key = self._cache_key(url)
        async with self._lock:
            self._cache[key] = (time.time(), data)
            # 惰性淘汰过期条目
            if len(self._cache) > 200:
                stale = [k for k, v in self._cache.items() if time.time() - v[0] >= self._cache_ttl]
                for k in stale:
                    self._cache.pop(k, None)

    @staticmethod
    def _cache_key(url: str) -> str:
        return hashlib.md5(url.encode("utf-8")).hexdigest()

    async def cache_stats(self) -> dict[str, Any]:
        """缓存统计信息（线程安全）。"""
        async with self._lock:
            now = time.time()
            valid = sum(1 for v in self._cache.values() if now - v[0] < self._cache_ttl)
            return {
                "total_entries": len(self._cache),
                "valid_entries": valid,
                "stale_entries": len(self._cache) - valid,
                "cache_ttl_secs": self._cache_ttl,
            }


# 全局单例（需注入 download_fn 方可使用）
image_pipeline = ImagePipeline()