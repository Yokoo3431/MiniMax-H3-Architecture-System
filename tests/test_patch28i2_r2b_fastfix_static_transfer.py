"""CPU/static contracts for the R2B static-transfer fastfix."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PATCH = ROOT / "patches/support_layers/minimax_h3_static_transfer_headroom_incremental.patch"
BOUNDARY_PATCH = ROOT / "patches/support_layers/minimax_h3_language_boundary_instrumentation_incremental.patch"
MANIFEST = ROOT / "configs/support_layer_manifest.yaml"
RECONCILER = ROOT / "scripts/reconcile_h3_strategy_a.py"
REPORT = ROOT / "docs/PATCH2.8I2_R2B_D1_Language_Boundary_GPU_Probe.md"


class TestR2BFastfixStaticTransfer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = PATCH.read_text(encoding="utf-8")
        cls.boundary = BOUNDARY_PATCH.read_text(encoding="utf-8")
        cls.manifest = MANIFEST.read_text(encoding="utf-8")
        cls.reconciler = RECONCILER.read_text(encoding="utf-8")

    def test_uses_existing_model_patcher_partial_unload(self):
        self.assertIn("partially_unload", self.patch)
        self.assertIn("memory_to_free=requested", self.patch)
        self.assertNotIn("ModelPatcher(", self.patch)

    def test_headroom_formula_is_deterministic(self):
        self.assertIn("self._static_storage_bytes + TE_GPU_HEADROOM", self.patch)
        self.assertIn("requested = min(loaded, target)", self.patch)
        loaded = 4_192_336_272
        static_bytes = 1_556_874_496
        headroom = 3_221_225_472
        self.assertEqual(min(loaded, static_bytes + headroom), loaded)

    def test_mitigation_is_before_static_transfer(self):
        order = [
            "mm.load_models_gpu([patcher], memory_required=reserve)",
            '"LANGLOAD-02 AFTER_LOAD_MODELS_GPU"',
            "self._prepare_static_transfer_headroom(patcher)",
            '"LANGLOAD-03 BEFORE_MOVE_STATIC"',
            "self._move_static_tensors(self.load_device)",
        ]
        positions = [self.patch.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))

    def test_incomplete_release_fails_closed(self):
        self.assertIn("if freed < requested:", self.patch)
        self.assertIn("H3 static-transfer headroom incomplete", self.patch)
        self.assertIn("H3ComponentError", self.patch)

    def test_closed_contracts_are_not_changed(self):
        self.assertIn("203", REPORT.read_text(encoding="utf-8"))
        self.assertIn("BF16", REPORT.read_text(encoding="utf-8"))
        self.assertIn("350", REPORT.read_text(encoding="utf-8"))
        self.assertIn("FP32", REPORT.read_text(encoding="utf-8"))

    def test_visual_and_quantized_policy_are_pinned_in_manifest(self):
        self.assertIn("visual_dtype: preserved_fp32", self.manifest)
        self.assertIn("quantized_linear_contract: preserved_350", self.manifest)
        self.assertIn("target_dtype: bfloat16", self.manifest)

    def test_rollback_surface_is_untouched(self):
        self.assertIn("_rollback_failed_quantized_load", self.boundary)
        self.assertIn("_unload_linear_patcher", self.patch)
        self.assertNotIn("_linear_patcher = None", self.patch)

    def test_boundary_markers_remain_ordered(self):
        markers = [
            "LANGLOAD-01 BEFORE_LOAD_MODELS_GPU",
            "LANGLOAD-02 AFTER_LOAD_MODELS_GPU",
            "LANGLOAD-03 BEFORE_MOVE_STATIC",
            "LANGLOAD-04 AFTER_MOVE_STATIC",
        ]
        combined = self.boundary + self.patch
        positions = [combined.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))

    def test_fastfix_has_no_gpu_or_product_execution_surface(self):
        lowered = self.patch.lower()
        for forbidden in (
            "torch.cuda", "empty_cache", "free_memory(", "model.to(",
            "tensor.to(", "/prompt", "w01", "encode_ids", "studio",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_support_provenance_records_fastfix(self):
        self.assertIn("HEADROOM_FINAL_FINGERPRINT", self.reconciler)
        self.assertIn("HEADROOM_PATCH", self.reconciler)
        self.assertIn("static_transfer_headroom_patch_sha256", self.reconciler)
        self.assertIn("patches/support_layers/minimax_h3_static_transfer_headroom_incremental.patch", self.manifest)
        self.assertIn("c6342b0417f9adb8dacfb72cdacab9a6c58500a0fb7ee27192eca098148e5aeb", self.manifest)

    def test_no_model_workflow_or_prompt_files_in_fastfix_patch(self):
        self.assertNotIn("models/", self.patch)
        self.assertNotIn("workflow", self.patch.lower())
        self.assertNotIn("prompt_pipeline", self.patch.lower())


if __name__ == "__main__":
    unittest.main()
