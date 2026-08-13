"""fomimage 定价/模型映射单元测试（v2.36.0，不触网）。

覆盖：
- 12 模型对外名 ↔ 上游 modelId 映射
- estimate_credits 积分公式（含参考图加价、quality|resolution 组合键）
- 文生图/图生图 maxImages/mode 判定
- /v1/models 暴露 fomimage 模型
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.fomimage_pricing import (
    estimate_credits,
    is_text_to_image,
    max_images_for,
    upstream_meta,
    upstream_model_id,
)
from services.providers.registry import fomimage_models, is_fomimage_model


class FomimageModelMappingTests(unittest.TestCase):
    def test_all_12_models_mapped(self) -> None:
        self.assertEqual(len(fomimage_models()), 12)
        # 每个对外模型都能映射到上游
        for external in fomimage_models():
            self.assertNotEqual(upstream_model_id(external), external)
            self.assertNotEqual(upstream_model_id(external), "")

    def test_known_mapping(self) -> None:
        self.assertEqual(upstream_model_id("fomimage-gpt-image-2"), "gpt-image-2")
        self.assertEqual(upstream_model_id("fomimage-seedream-4.5-text"), "seedream-4.5-text")
        self.assertEqual(upstream_model_id("not-fomimage-model"), "not-fomimage-model")

    def test_is_fomimage_model(self) -> None:
        self.assertTrue(is_fomimage_model("fomimage-gpt-image-2"))
        self.assertFalse(is_fomimage_model("gpt-image-2"))
        self.assertFalse(is_fomimage_model("grok-3-image"))

    def test_mode_and_max_images(self) -> None:
        self.assertTrue(is_text_to_image("fomimage-gpt-image-2-text"))
        self.assertFalse(is_text_to_image("fomimage-gpt-image-2"))
        self.assertEqual(max_images_for("fomimage-gpt-image-2-text"), 0)  # 文生图不接受参考图
        self.assertGreater(max_images_for("fomimage-gpt-image-2"), 0)
        self.assertGreater(max_images_for("fomimage-nano-banana-2"), 0)

    def test_meta_present(self) -> None:
        meta = upstream_meta("fomimage-gpt-image-2")
        self.assertEqual(meta.get("family"), "openai")
        self.assertIn("options", meta)
        self.assertIn("pricing", meta)


class FomimagePricingTests(unittest.TestCase):
    """积分公式验证（对齐 fromimage HAR 实测：gpt-image-2 medium|2K +2图 = 50）。"""

    def test_gpt_image_2_two_ref_medium_2k(self) -> None:
        # HAR 实测：2 张参考图 + medium|2K → costCredits 50（45 + 1*5）
        self.assertEqual(
            estimate_credits("fomimage-gpt-image-2", {"quality": "medium", "resolution": "2K"}, 2), 50
        )

    def test_gpt_image_2_one_ref_free(self) -> None:
        # 第 1 张参考图免费（includedInputImages=1）
        self.assertEqual(
            estimate_credits("fomimage-gpt-image-2", {"quality": "medium", "resolution": "2K"}, 1), 45
        )

    def test_gpt_image_2_price_table(self) -> None:
        # 用户实测（2 张图）：low|2K=15、high|2K=170、medium|1K=35、medium|4K=80
        self.assertEqual(estimate_credits("fomimage-gpt-image-2", {"quality": "low", "resolution": "2K"}, 2), 15)
        self.assertEqual(estimate_credits("fomimage-gpt-image-2", {"quality": "high", "resolution": "2K"}, 2), 170)
        self.assertEqual(estimate_credits("fomimage-gpt-image-2", {"quality": "medium", "resolution": "1K"}, 2), 35)
        self.assertEqual(estimate_credits("fomimage-gpt-image-2", {"quality": "medium", "resolution": "4K"}, 2), 80)

    def test_gpt_image_1_5_extra_image_cost(self) -> None:
        # gpt-image-1.5：每张超 1 张 +25；medium|1024*1024=40 → 2 图 = 65
        self.assertEqual(
            estimate_credits("fomimage-gpt-image-1.5", {"quality": "medium", "size": "1024*1024"}, 2), 65
        )

    def test_fixed_price_models(self) -> None:
        self.assertEqual(estimate_credits("fomimage-wan-2.7-text", {}, 0), 10)
        self.assertEqual(estimate_credits("fomimage-seedream-4.5", {}, 0), 15)

    def test_resolution_models(self) -> None:
        self.assertEqual(estimate_credits("fomimage-nano-banana-2", {"resolution": "4K"}, 0), 55)
        self.assertEqual(estimate_credits("fomimage-nano-banana-pro", {"resolution": "4K"}, 0), 95)
        # 0.5K 仅 nano-banana-2-text 支持
        self.assertEqual(estimate_credits("fomimage-nano-banana-2-text", {"resolution": "0.5K"}, 0), 20)
        # i2i 无 0.5K → 查表未命中回退 baseCredits=30
        self.assertEqual(estimate_credits("fomimage-nano-banana-2", {"resolution": "0.5K"}, 0), 30)

    def test_quality_resolution_models(self) -> None:
        self.assertEqual(estimate_credits("fomimage-gpt-image-2-text", {"quality": "medium", "resolution": "2K"}, 0), 40)
        self.assertEqual(estimate_credits("fomimage-gpt-image-2", {"quality": "high", "resolution": "4K"}, 1), 290)

    def test_unknown_option_falls_back_base(self) -> None:
        # 未命中组合键回退 baseCredits
        self.assertEqual(estimate_credits("fomimage-gpt-image-2", {"quality": "unknown", "resolution": "X"}, 0), 30)


class FomimageModelsEndpointTests(unittest.TestCase):
    def test_v1_models_includes_fomimage(self) -> None:
        from services.protocol.openai_v1_models import list_models

        with patch("services.account_service.account_service.list_accounts", return_value=[]):
            data = list_models().get("data") or []
        ids = {str(item.get("id")) for item in data}
        self.assertIn("fomimage-gpt-image-2", ids)
        self.assertIn("fomimage-seedream-4.5-text", ids)
        # fomimage 模型 owned_by=fomimage
        fom = next(item for item in data if item.get("id") == "fomimage-gpt-image-2")
        self.assertEqual(fom.get("owned_by"), "fomimage")


if __name__ == "__main__":
    unittest.main()
