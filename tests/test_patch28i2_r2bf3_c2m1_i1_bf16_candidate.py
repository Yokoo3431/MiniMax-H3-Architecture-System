"""CPU/meta validation for the Strategy A BF16 static-target candidate."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest

from scripts.analyze_qwen_static_memory import analyze


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches" / "support_layers" / "minimax_h3_production_windows.patch"
INCREMENTAL = ROOT / "patches" / "support_layers" / "minimax_h3_strategy_a_incremental.patch"
MANIFEST = ROOT / "configs" / "support_layer_manifest.yaml"


def _fixture_checkpoint() -> Path:
    header = {
        "model.language_model.embed_tokens.weight": {
            "dtype": "BF16", "shape": [2, 3], "data_offsets": [0, 12]
        },
        "model.language_model.layers.0.input_layernorm.weight": {
            "dtype": "BF16", "shape": [3], "data_offsets": [12, 18]
        },
        "model.language_model.layers.0.post_attention_layernorm.weight": {
            "dtype": "BF16", "shape": [3], "data_offsets": [18, 24]
        },
        "model.visual.patch_embed.proj.weight": {
            "dtype": "BF16", "shape": [3, 3], "data_offsets": [24, 42]
        },
        "model.language_model.layers.50.input_layernorm.weight": {
            "dtype": "BF16", "shape": [3], "data_offsets": [42, 48]
        },
        "model.lm_head.weight": {
            "dtype": "BF16", "shape": [3, 3], "data_offsets": [48, 66]
        },
    }
    handle = tempfile.NamedTemporaryFile(suffix=".safetensors", delete=False)
    path = Path(handle.name)
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    handle.write(struct.pack("<Q", len(encoded)))
    handle.write(encoded)
    handle.close()
    return path


class TestC2M1I1BF16StaticCandidate(unittest.TestCase):
    def setUp(self):
        self.source = PATCH.read_text(encoding="utf-8")
        self.incremental = INCREMENTAL.read_text(encoding="utf-8")

    def test_strategy_policy_is_explicit(self):
        self.assertIn("H3_LANGUAGE_STATIC_TARGET_DTYPE", self.source)
        self.assertIn('"bfloat16"', self.source)

    def test_candidate_is_scoped_to_language_subtree(self):
        self.assertIn("language_model.to(dtype=torch.bfloat16)", self.source)
        self.assertIn("language subtree", self.source)
        self.assertIn("visual", self.source)

    def test_global_qwen_cast_is_not_used(self):
        self.assertNotIn("\n+    model.to(dtype=torch.bfloat16)", self.source)
        self.assertNotIn("\n+    causal_lm.to(dtype=torch.bfloat16)", self.source)
        self.assertNotIn("\n+    visual.to(dtype=torch.bfloat16)", self.source)

    def test_visual_fp32_behavior_is_preserved(self):
        self.assertIn("visual", self.source)
        self.assertIn("constructor's FP32 target dtype", self.source)
        self.assertNotIn("model.visual.to", self.source)

    def test_quantized_linear_path_is_unchanged(self):
        report = (ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_G0_BF16_Static_Validation.md").read_text(encoding="utf-8")
        self.assertIn("_swap_lang_linears", report)
        self.assertIn("dtype=model_dtype", report)
        self.assertIn("350", report)

    def test_assignment_still_uses_target_dtype(self):
        loading = (ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_G0_BF16_Static_Validation.md").read_text(encoding="utf-8")
        self.assertIn("tensor.to(dtype=target.dtype)", loading)
        self.assertIn("checkpoint BF16 → target BF16", loading)

    def test_candidate_inventory_preserves_static_count_and_bytes(self):
        checkpoint = _fixture_checkpoint()
        try:
            result = analyze(checkpoint)
        finally:
            checkpoint.unlink(missing_ok=True)
        self.assertEqual(result["static_tensor_count"], 3)
        self.assertEqual(result["strategy_a_candidate_bytes"], 24)
        self.assertEqual(result["strategy_a_candidate_target_dtype"], "BF16")
        self.assertTrue(all(row["strategy_a_candidate_target_dtype"] == "BF16" for row in result["tensors"]))

    def test_candidate_inventory_excludes_visual_trimmed_and_quantized_entries(self):
        checkpoint = _fixture_checkpoint()
        try:
            result = analyze(checkpoint)
        finally:
            checkpoint.unlink(missing_ok=True)
        self.assertEqual(result["excluded_header_entries"]["visual"], 1)
        self.assertEqual(result["excluded_header_entries"]["later_layer_or_lm_head"], 2)
        self.assertEqual(result["static_tensor_count"], 3)

    def test_candidate_norm_and_embedding_slots_are_bf16(self):
        checkpoint = _fixture_checkpoint()
        try:
            result = analyze(checkpoint)
        finally:
            checkpoint.unlink(missing_ok=True)
        names = {row["local_name"] for row in result["tensors"]}
        self.assertIn("language_model.embed_tokens.weight", names)
        self.assertIn("language_model.layers.0.input_layernorm.weight", names)
        self.assertIn("language_model.layers.0.post_attention_layernorm.weight", names)
        self.assertEqual({row["strategy_a_candidate_target_dtype"] for row in result["tensors"]}, {"BF16"})

    def test_full_patch_and_incremental_patch_share_candidate_contract(self):
        for text in (self.source, self.incremental):
            self.assertIn("H3_LANGUAGE_STATIC_TARGET_DTYPE", text)
            self.assertIn("language_model.to(dtype=torch.bfloat16)", text)

    def test_incremental_patch_has_no_machine_path(self):
        self.assertNotIn("D:\\\\", self.incremental)
        self.assertNotIn("C:\\\\Users", self.incremental)

    def test_support_patch_contains_no_gpu_execution_or_model_load(self):
        lower = self.source.lower()
        self.assertNotIn("torch.cuda", lower)
        self.assertNotIn("from_pretrained", lower)
        self.assertNotIn("/prompt", lower)

    def test_candidate_does_not_change_visual_setting(self):
        report = (ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_G0_BF16_Static_Validation.md").read_text(encoding="utf-8")
        self.assertIn("TE_VISUAL_ON_CPU=True", report)

    def test_runtime_consumer_compatibility_is_unproven(self):
        report = (ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_G0_BF16_Static_Validation.md").read_text(encoding="utf-8").lower()
        self.assertIn("runtime consumer compatibility remains unknown", report)
        self.assertIn("not runtime-proven", report)

    def test_installer_reproduction_contract_is_pinned(self):
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn("minimax_h3_production_windows.patch", manifest)
        self.assertIn("d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad", manifest)

    def test_no_model_or_runtime_execution_is_authorized(self):
        report = (ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_G0_BF16_Static_Validation.md").read_text(encoding="utf-8")
        self.assertIn("No GPU validation was executed", report)
        self.assertIn("No dtype change was implemented", report)

    def test_readiness_remains_closed(self):
        report = (ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_G0_BF16_Static_Validation.md").read_text(encoding="utf-8")
        self.assertIn("READY_FOR_G2", report)
        self.assertIn("READY_FOR_FULL_GPU_RETRY", report)


if __name__ == "__main__":
    unittest.main()
