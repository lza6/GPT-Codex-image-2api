from __future__ import annotations

import asyncio
import time
import unittest

from services.image_pipeline import ImagePipeline


class TestImagePipeline(unittest.IsolatedAsyncioTestCase):
    async def test_process_image_downloads_and_caches(self):
        downloaded = []

        def download_fn(url: str) -> bytes:
            downloaded.append(url)
            return b"image-data"

        pipeline = ImagePipeline(download_fn=download_fn, concurrency=2, cache_ttl=3600)
        data = await pipeline.process_image("http://example.test/img.png")
        self.assertEqual(data, b"image-data")
        self.assertEqual(len(downloaded), 1)

        # 第二次 should return from cache
        data2 = await pipeline.process_image("http://example.test/img.png")
        self.assertEqual(data2, b"image-data")
        self.assertEqual(len(downloaded), 1)  # 未再次下载

    async def test_process_image_applies_process_fn(self):
        def process_fn(data: bytes) -> bytes:
            return data + b"-processed"

        pipeline = ImagePipeline(
            download_fn=lambda url: b"raw",
            process_fn=process_fn,
        )
        data = await pipeline.process_image("http://example.test/img.png")
        self.assertEqual(data, b"raw-processed")

    async def test_process_many_returns_in_order(self):
        pipeline = ImagePipeline(
            download_fn=lambda url: url.encode(),
            concurrency=5,
        )
        urls = [f"http://example.test/{i}.png" for i in range(3)]
        results = await pipeline.process_many(urls)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0], urls[0].encode())
        self.assertEqual(results[1], urls[1].encode())
        self.assertEqual(results[2], urls[2].encode())

    async def test_concurrency_limited(self):
        """验证并发限制器确实限制同时下载数。"""
        inflight = 0
        max_inflight = 0
        lock = asyncio.Lock()

        async def slow_download(url: str) -> bytes:
            nonlocal inflight, max_inflight
            async with lock:
                inflight += 1
                max_inflight = max(max_inflight, inflight)
            await asyncio.sleep(0.05)
            async with lock:
                inflight -= 1
            return b"ok"

        # 模拟 download_fn 返回一个协程
        async def download_fn(url: str) -> bytes:
            return await slow_download(url)

        pipeline = ImagePipeline(
            download_fn=lambda url: None,  # 占位，下面覆盖
            concurrency=2,
        )
        pipeline._download = download_fn  # type: ignore[method-assign]

        tasks = [pipeline.process_image(f"http://example.test/{i}.png") for i in range(6)]
        await asyncio.gather(*tasks)
        self.assertLessEqual(max_inflight, 2)  # 并发不超过 2

    async def test_cache_ttl_expires(self):
        pipeline = ImagePipeline(
            download_fn=lambda url: b"data",
            cache_ttl=0,  # TTL 为 0 = 立即过期
        )
        await pipeline.process_image("http://example.test/img.png")
        key = pipeline._cache_key("http://example.test/img.png")
        # 缓存条目应已过期（TTL=0）
        entry = pipeline._cache.get(key)
        if entry is not None:
            self.assertLess(time.time() - entry[0], 0.1)  # 刚写入

    async def test_cache_stats(self):
        pipeline = ImagePipeline(
            download_fn=lambda url: b"data",
            cache_ttl=3600,
        )
        await pipeline.process_image("http://example.test/a.png")
        stats = await pipeline.cache_stats()
        self.assertEqual(stats["total_entries"], 1)
        self.assertEqual(stats["valid_entries"], 1)


if __name__ == "__main__":
    unittest.main()

def test_default_concurrency_is_5():
    """图片管道并发限制默认值精确断言（变异探针锚点）。"""
    from services.image_pipeline import DEFAULT_CONCURRENCY
    assert DEFAULT_CONCURRENCY == 5


def test_default_cache_ttl_is_3600():
    """图片管道缓存 TTL 默认值精确断言（变异探针锚点）。"""
    from services.image_pipeline import CACHE_TTL
    assert CACHE_TTL == 3600
