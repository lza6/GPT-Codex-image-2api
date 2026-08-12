#!/usr/bin/env python3
"""对 web_dist 静态资源生成预压缩 .gz（gzip level 9），配合 app.py 自定义静态路由返回。

背景：GZipMiddleware 已移除（gzip+chunked 在代理链路触发 ERR_INVALID_CHUNKED_ENCODING）。
但静态资源（Next.js JS/CSS）不压缩在远距离代理链路下传输慢。本脚本预生成 .gz 文件，
`/_next/static` 路由在客户端接受 gzip 时直接返回 .gz（FileResponse 带 Content-Length，
非 chunked），既压缩加速又不触发浏览器 chunked 解析错误。

用法：
  python scripts/compress_static.py [web_dist 路径，默认 web_dist]
"""
from __future__ import annotations

import gzip
import mimetypes
import sys
from pathlib import Path

# 可压缩的 MIME（文本类 + 常见前端资源）
_COMPRESSIBLE = (
    "text/",
    "application/javascript",
    "application/json",
    "image/svg+xml",
    "application/xml",
    "application/x-javascript",
)


def is_compressible(path: Path) -> bool:
    if not path.is_file() or path.suffix == ".gz":
        return False
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        # 无 MIME 的文本类（如 .txt/.map）按扩展名兜底
        return path.suffix in {".txt", ".map", ".js", ".css", ".svg", ".html", ".json"}
    return mime.startswith(_COMPRESSIBLE)


def compress_dir(root: Path) -> tuple[int, int]:
    """返回 (生成数, 跳过数)。已存在且不比重压大的 .gz 跳过。"""
    generated = skipped = 0
    files = sorted(root.rglob("*")) if root.exists() else []
    for p in files:
        if not is_compressible(p):
            continue
        gz = Path(str(p) + ".gz")
        data = p.read_bytes()
        if gz.exists() and gz.stat().st_size <= gzip.compress(data, compresslevel=9).__len__():
            skipped += 1
            continue
        gz.write_bytes(gzip.compress(data, compresslevel=9))
        generated += 1
    return generated, skipped


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("web_dist")
    generated, skipped = compress_dir(root)
    total_saved = 0
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file() and p.suffix == ".gz":
                raw = Path(str(p)[:-3])
                if raw.exists():
                    total_saved += raw.stat().st_size - p.stat().st_size
    print(f"生成 .gz: {generated}，跳过(已压缩): {skipped}，总节省: {total_saved/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
