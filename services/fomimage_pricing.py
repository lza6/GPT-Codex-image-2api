"""fomimage 模型/控件/积分定价静态元数据（v2.36.0）。

数据来源：fromimage 前端 SSR payload（GET /api/ai/image-models 快照，2026-08-13 抓取）
与 HAR 实测（gpt-image-2 + medium|2K + 1 参考图 = costCredits 50 命中公式）。
运行时 `/api/ai/image-models` 可能调整价格，此处为静态映射基准 + 对账参考。

积分公式（alert-C8vENeqy.js `_`）：
    base = pricing.baseCredits
    若 unitCreditsBy: key = controlKeys(或 controlKey) 各键当前值 join('|')，values[key] ?? base
    quantity = quantityControlKey 时 max(1, Number(options[key]) || 1)，否则 1
    extra = max(0, 参考图数 - (includedInputImages ?? 1)) * (additionalInputImageCredits ?? 0)
    costCredits = ceil(base * quantity + extra)
"""

from __future__ import annotations

from typing import Any

# 对外模型名 → 上游 modelId（与 providers/registry.py 一致，避免循环导入）
_UPSTREAM_MODEL_IDS: dict[str, str] = {
    "fomimage-gpt-image-2": "gpt-image-2",
    "fomimage-gpt-image-2-text": "gpt-image-2-text",
    "fomimage-gpt-image-1.5": "gpt-image-1.5",
    "fomimage-gpt-image-1.5-text": "gpt-image-1.5-text",
    "fomimage-nano-banana-2": "nano-banana-2",
    "fomimage-nano-banana-2-text": "nano-banana-2-text",
    "fomimage-nano-banana-pro": "nano-banana-pro",
    "fomimage-nano-banana-pro-text": "nano-banana-pro-text",
    "fomimage-seedream-4.5": "seedream-4.5",
    "fomimage-seedream-4.5-text": "seedream-4.5-text",
    "fomimage-wan-2.7-image": "wan-2.7-image",
    "fomimage-wan-2.7-text": "wan-2.7-text",
}

# 上游 modelId → 完整配置（pricing + controls 默认值）
# 文生图（-text 后缀）maxImages=0 不接受参考图；图生图 maxImages=3~16。
_UPSTREAM_META: dict[str, dict[str, Any]] = {
    "wan-2.7-text": {
        "mode": "text-to-image", "family": "alibaba", "badge": "default",
        "maxImages": 0, "maxPromptLength": 5000,
        "options": {"aspectRatio": "1:1"},
        "pricing": {"baseCredits": 10},
    },
    "wan-2.7-image": {
        "mode": "image-to-image", "family": "alibaba", "badge": "default",
        "maxImages": 3, "maxPromptLength": 5000,
        "options": {"aspectRatio": "match_input_image"},
        "pricing": {"baseCredits": 10},
    },
    "nano-banana-2-text": {
        "mode": "text-to-image", "family": "google", "badge": "quality",
        "maxImages": 0, "maxPromptLength": 4000,
        "options": {"aspectRatio": "1:1", "resolution": "1K", "outputFormat": "png"},
        "pricing": {"baseCredits": 30, "unitCreditsBy": {"controlKey": "resolution",
                    "values": {"0.5K": 20, "1K": 30, "2K": 40, "4K": 55}}},
    },
    "nano-banana-2": {
        "mode": "image-to-image", "family": "google", "badge": "quality",
        "maxImages": 14, "maxPromptLength": 4000,
        "options": {"aspectRatio": "match_input_image", "resolution": "1K", "outputFormat": "png"},
        "pricing": {"baseCredits": 30, "unitCreditsBy": {"controlKey": "resolution",
                    "values": {"1K": 30, "2K": 40, "4K": 55}}},
    },
    "gpt-image-2-text": {
        "mode": "text-to-image", "family": "openai", "badge": "quality",
        "maxImages": 0, "maxPromptLength": 10000,
        "options": {"aspectRatio": "1:1", "resolution": "1K", "quality": "medium"},
        "pricing": {"baseCredits": 25, "unitCreditsBy": {"controlKeys": ["quality", "resolution"],
                    "values": {
                        "low|1K": 5, "low|2K": 10, "low|4K": 10,
                        "medium|1K": 25, "medium|2K": 40, "medium|4K": 70,
                        "high|1K": 90, "high|2K": 160, "high|4K": 290,
                    }}},
    },
    "gpt-image-2": {
        "mode": "image-to-image", "family": "openai", "badge": "quality",
        "maxImages": 16, "maxPromptLength": 10000,
        "options": {"aspectRatio": "match_input_image", "resolution": "1K", "quality": "medium"},
        "pricing": {"baseCredits": 30, "unitCreditsBy": {"controlKeys": ["quality", "resolution"],
                    "values": {
                        "low|1K": 10, "low|2K": 10, "low|4K": 15,
                        "medium|1K": 30, "medium|2K": 45, "medium|4K": 75,
                        "high|1K": 90, "high|2K": 165, "high|4K": 290,
                    }},
                    "includedInputImages": 1, "additionalInputImageCredits": 5},
    },
    "nano-banana-pro-text": {
        "mode": "text-to-image", "family": "google", "badge": "pro",
        "maxImages": 0, "maxPromptLength": 10000,
        "options": {"aspectRatio": "1:1", "resolution": "2K", "outputFormat": "png"},
        "pricing": {"baseCredits": 55, "unitCreditsBy": {"controlKey": "resolution",
                    "values": {"1K": 55, "2K": 55, "4K": 95}}},
    },
    "nano-banana-pro": {
        "mode": "image-to-image", "family": "google", "badge": "pro",
        "maxImages": 14, "maxPromptLength": 10000,
        "options": {"aspectRatio": "match_input_image", "resolution": "2K", "outputFormat": "png"},
        "pricing": {"baseCredits": 55, "unitCreditsBy": {"controlKey": "resolution",
                    "values": {"1K": 55, "2K": 55, "4K": 95}}},
    },
    "seedream-4.5-text": {
        "mode": "text-to-image", "family": "bytedance", "badge": "quality",
        "maxImages": 0, "maxPromptLength": 4000,
        "options": {"aspectRatio": "1:1"},
        "pricing": {"baseCredits": 15},
    },
    "seedream-4.5": {
        "mode": "image-to-image", "family": "bytedance", "badge": "quality",
        "maxImages": 10, "maxPromptLength": 4000,
        "options": {"aspectRatio": "match_input_image"},
        "pricing": {"baseCredits": 15},
    },
    "gpt-image-1.5-text": {
        "mode": "text-to-image", "family": "openai", "badge": None,
        "maxImages": 0, "maxPromptLength": 4000,
        "options": {"size": "1024*1024", "quality": "medium", "background": "opaque", "outputFormat": "jpeg"},
        "pricing": {"baseCredits": 15, "unitCreditsBy": {"controlKeys": ["quality", "size"],
                    "values": {
                        "low|auto": 10, "low|1024*1024": 5, "low|1024*1536": 10, "low|1536*1024": 10,
                        "medium|auto": 25, "medium|1024*1024": 15, "medium|1024*1536": 25, "medium|1536*1024": 25,
                        "high|auto": 85, "high|1024*1024": 55, "high|1024*1536": 85, "high|1536*1024": 85,
                    }}},
    },
    "gpt-image-1.5": {
        "mode": "image-to-image", "family": "openai", "badge": None,
        "maxImages": 10, "maxPromptLength": 4000,
        "options": {"size": "auto", "quality": "medium", "background": "opaque", "outputFormat": "png"},
        "pricing": {"baseCredits": 50, "unitCreditsBy": {"controlKeys": ["quality", "size"],
                    "values": {
                        "low|auto": 30, "low|1024*1024": 30, "low|1024*1536": 30, "low|1536*1024": 30,
                        "medium|auto": 50, "medium|1024*1024": 40, "medium|1024*1536": 50, "medium|1536*1024": 50,
                        "high|auto": 105, "high|1024*1024": 80, "high|1024*1536": 105, "high|1536*1024": 105,
                    }},
                    "includedInputImages": 1, "additionalInputImageCredits": 25},
    },
}

# 控件可选项（供前端展示与预检）
_UPSTREAM_CONTROLS: dict[str, list[str]] = {
    "aspectRatio": ["match_input_image", "1:1", "1:2", "2:1", "1:3", "3:1", "2:3", "3:2",
                    "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "1:4", "1:8", "4:1", "8:1"],
    "resolution": ["0.5K", "1K", "2K", "4K"],
    "quality": ["low", "medium", "high"],
    "size": ["auto", "1024*1024", "1024*1536", "1536*1024"],
    "background": ["auto", "transparent", "opaque"],
    "outputFormat": ["png", "jpg", "jpeg"],
}

# 图生图参考图上限（maxImages）
_UPSTREAM_MAX_IMAGES: dict[str, int] = {
    m: int(meta.get("maxImages") or 0) for m, meta in _UPSTREAM_META.items()
}


def upstream_model_id(model: str) -> str:
    """对外模型名 → 上游 modelId；非 fomimage 模型原样返回。"""
    return _UPSTREAM_MODEL_IDS.get(str(model or "").strip().lower(), str(model or "").strip())


def upstream_meta(model: str) -> dict[str, Any]:
    """对外模型名的完整元数据（mode/family/maxImages/options/pricing）。未命中返回 {}。"""
    uid = upstream_model_id(model)
    meta = _UPSTREAM_META.get(uid)
    return dict(meta) if meta else {}


def is_text_to_image(model: str) -> bool:
    """该 fomimage 模型是否为文生图（-text 后缀 / mode=text-to-image）。"""
    meta = upstream_meta(model)
    return str(meta.get("mode") or "") == "text-to-image"


def max_images_for(model: str) -> int:
    """图生图参考图上限（0 = 文生图不接受参考图）。"""
    return int(upstream_meta(model).get("maxImages") or 0)


def estimate_credits(model: str, options: dict[str, Any] | None = None, input_images: int = 0) -> int:
    """按 fomimage 积分公式预估消耗（与上游一致，本地不扣分仅展示/预检）。

    options：{aspectRatio, resolution, quality, size, ...}，缺省取模型默认值。
    input_images：参考图数量（文生图传 0）。
    返回预估 costCredits（>= 0；未命中查表回退 baseCredits）。
    """
    meta = upstream_meta(model)
    pricing = meta.get("pricing") or {}
    opts = dict(options or {})
    base = int(pricing.get("baseCredits") or 0)
    unit_by = pricing.get("unitCreditsBy")
    if isinstance(unit_by, dict):
        keys = unit_by.get("controlKeys") or ([unit_by.get("controlKey")] if unit_by.get("controlKey") else [])
        values = unit_by.get("values") if isinstance(unit_by.get("values"), dict) else {}
        key = "|".join(str(opts.get(k) or "") for k in keys)
        base = int(values.get(key, base) or base)
    quantity = 1
    qk = pricing.get("quantityControlKey")
    if qk:
        try:
            quantity = max(1, int(opts.get(qk) or 1))
        except (TypeError, ValueError):
            quantity = 1
    included = int(pricing.get("includedInputImages") or 1)
    extra_rate = int(pricing.get("additionalInputImageCredits") or 0)
    extra = max(0, int(input_images) - included) * extra_rate
    import math
    return math.ceil(base * quantity + extra)


def fomimage_model_ids() -> dict[str, str]:
    """对外模型名 → 上游 modelId 映射（供 /v1/models 与前端）。"""
    return dict(_UPSTREAM_MODEL_IDS)
