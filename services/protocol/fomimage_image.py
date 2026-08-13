"""fomimage 图片生成协议适配（v2.36.0）。

把 protocol 层的 ConversationRequest 转为 fomimage 上游调用：
    参考图(base64) → 上传(POST /api/storage/upload-image) → 建任务(POST /api/ai/image-tasks/)
    → 轮询(GET /api/ai/image-tasks/{id}) → 下载结果图 → 存本图库 → 产出 ImageOutput

扣积分：fomimage 创建任务时服务端已扣 costCredits，本地按 account_service.mark_image_result
的 provider 专用扣费（按 costCredits 扣本地 quota，quota 归零自动剔除——用完即弃）。
"""
from __future__ import annotations

import base64
from typing import Any

from services.fomimage_backend_api import FomimageBackendAPI, FomimageTaskError
from services.fomimage_pricing import (
    estimate_credits,
    is_text_to_image,
    upstream_meta,
)
from services.protocol.conversation import ImageOutput

_OPENAI_SIZE_TO_RATIO = {
    "1024x1024": "1:1",
    "1024x1536": "2:3",
    "1536x1024": "3:2",
    "256x256": "1:1",
    "512x512": "1:1",
}


def _sniff_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"


def _mime_ext(mime: str) -> str:
    return {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}.get(mime, "png")


def build_fomimage_options(request: Any, model: str) -> dict[str, str]:
    """把 OpenAI 请求参数（size/quality）映射为 fomimage options。

    优先级：request.options（若前端直传 fomimage 选项）> OpenAI size/quality 映射 > 模型默认。
    """
    meta = upstream_meta(model)
    defaults = dict(meta.get("options") or {})
    opts: dict[str, str] = {}

    # 前端若已传 fomimage 原生 options 则直接采用（图片工作台按模型控件直传）
    raw_options = getattr(request, "options", None)
    if isinstance(raw_options, dict):
        for k, v in raw_options.items():
            if v not in (None, ""):
                opts[str(k)] = str(v)

    size = str(getattr(request, "size", "") or "").strip().lower()
    quality = str(getattr(request, "quality", "") or "").strip().lower()

    if "aspectRatio" not in opts:
        ratio = _OPENAI_SIZE_TO_RATIO.get(size)
        if ratio:
            opts["aspectRatio"] = ratio
        elif is_text_to_image(model):
            opts["aspectRatio"] = defaults.get("aspectRatio", "1:1")
        else:
            opts["aspectRatio"] = "match_input_image"
    if "resolution" not in opts:
        opts["resolution"] = _pick_resolution(size, defaults.get("resolution", "1K"))
    if "quality" not in opts:
        if quality and quality in {"low", "medium", "high"}:
            opts["quality"] = quality
        elif "quality" in defaults:
            opts["quality"] = str(defaults["quality"])
    if "size" not in opts and size in _OPENAI_SIZE_TO_RATIO:
        opts["size"] = size
    return opts


def _pick_resolution(size: str, default: str) -> str:
    """按 OpenAI size 高度粗选 fomimage resolution（>=2048→4K, >=1536→2K, 否则默认）。"""
    try:
        _, h = str(size).lower().split("x")
        height = int(h)
        if height >= 2048:
            return "4K"
        if height >= 1536:
            return "2K"
    except (ValueError, TypeError):
        pass
    return default


def _decode_images(images: list[str]) -> list[tuple[bytes, str, str]]:
    files: list[tuple[bytes, str, str]] = []
    for i, b64 in enumerate(images or []):
        if not b64:
            continue
        try:
            data = base64.b64decode(b64, validate=True)
        except Exception:
            continue
        mime = _sniff_mime(data)
        files.append((data, f"ref_{i}.{_mime_ext(mime)}", mime))
    return files


def generate_fomimage_images(
    backend: FomimageBackendAPI,
    request: Any,
    index: int,
    total: int,
) -> list[ImageOutput]:
    """执行单张 fomimage 图片生成，返回 ImageOutput 列表（含 progress + result）。

    成功时最后一个 result 携带 data=[{b64_json,url,revised_prompt}]。
    """
    model = str(request.model or "")
    options = build_fomimage_options(request, model)
    prompt = str(request.prompt or "")

    # 1) 参考图上传（图生图）
    image_urls: list[str] = []
    ref_files = _decode_images(request.images or [])
    if ref_files:
        image_urls = backend.upload_images(ref_files)

    # 2) 创建任务（fomimage 侧已按 costCredits 扣分）
    task = backend.create_task(model, prompt, image_urls, options)
    task_id = str(task.get("id") or "")
    cost_credits = int(task.get("costCredits") or estimate_credits(model, options, len(ref_files)))
    # 结构化回传实际扣分（供 _generate_fomimage_image 记账，避免从文本解析）
    try:
        request._fomimage_credits = cost_credits
    except Exception:
        pass
    yield ImageOutput(
        kind="progress",
        model=model,
        index=index,
        total=total,
        text=f"fomimage 任务已创建（消耗 {cost_credits} 积分）",
        conversation_id=task_id,
    )

    # 3) 轮询到终态
    final = backend.poll_task(task_id)
    urls = [str(u) for u in (final.get("images") or []) if str(u)]
    if not urls:
        raise FomimageTaskError("fomimage 任务成功但无结果图", code=-10, data=final)
    account_email = str(getattr(request, "_account_email", "") or "")

    # 4) 下载结果图 → 存本图库 → 产出 result
    data_items: list[dict[str, Any]] = []
    for url in urls:
        try:
            img_bytes = backend.download_image(url, proxy=backend.proxy)
        except Exception as exc:
            raise FomimageTaskError(f"fomimage 结果图下载失败: {url} ({exc})", code=-11, data={"url": url}) from exc
        b64 = base64.b64encode(img_bytes).decode("ascii")
        from services.protocol.conversation import save_image_bytes

        stored_url = save_image_bytes(img_bytes, request.base_url)
        item: dict[str, Any] = {"b64_json": b64, "url": stored_url, "revised_prompt": prompt}
        if request.response_format == "url":
            item.pop("b64_json", None)
        data_items.append(item)

    out = ImageOutput(
        kind="result",
        model=model,
        index=index,
        total=total,
        data=data_items,
        account_email=account_email,
        conversation_id=task_id,
    )
    yield out
