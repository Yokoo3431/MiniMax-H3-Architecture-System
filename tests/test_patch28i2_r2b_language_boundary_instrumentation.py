"""CPU/static contracts for the R2B language lifecycle boundary markers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


PATCH = ROOT / "patches/support_layers/minimax_h3_language_boundary_instrumentation_incremental.patch"
MANIFEST = ROOT / "configs/support_layer_manifest.yaml"
RECONCILER = ROOT / "scripts/reconcile_h3_strategy_a.py"


class TestLanguageBoundaryInstrumentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch_text = PATCH.read_text(encoding="utf-8")
        cls.encoder_hunk = cls.patch_text.split("--- a/minimax_h3_nodes/runtime/qwen_encoder/encoder.py", 1)[1]

    def test_four_markers_are_exact_and_ordered(self):
        markers = [
            "LANGLOAD-01 BEFORE_LOAD_MODELS_GPU",
            "LANGLOAD-02 AFTER_LOAD_MODELS_GPU",
            "LANGLOAD-03 BEFORE_MOVE_STATIC",
            "LANGLOAD-04 AFTER_MOVE_STATIC",
        ]
        positions = [self.encoder_hunk.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(self.patch_text.count("LANGLOAD-"), 8)

    def test_markers_wrap_existing_production_calls(self):
        order = [
            '"LANGLOAD-01 BEFORE_LOAD_MODELS_GPU"',
            "mm.load_models_gpu([patcher], memory_required=reserve)",
            '"LANGLOAD-02 AFTER_LOAD_MODELS_GPU"',
            '"LANGLOAD-03 BEFORE_MOVE_STATIC"',
            "self._move_static_tensors(self.load_device)",
            '"LANGLOAD-04 AFTER_MOVE_STATIC"',
        ]
        positions = [self.encoder_hunk.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))

    def test_observational_payload_is_complete(self):
        for field in (
            "timestamp", "windows_free_commit", "cuda_allocated", "cuda_reserved",
            "cuda_free", "comfy_current_loaded_models", "model_patcher_loaded_size",
            "quantized_linear_cpu_count", "quantized_linear_cuda_count",
            "direct_static_cpu_count", "direct_static_cuda_count",
        ):
            self.assertIn(f'"{field}"', self.patch_text)

    def test_traceback_and_rollback_states_are_separate(self):
        for token in (
            "last_marker", "traceback.format_exc()", "pre_rollback_state",
            "post_rollback_state", "_rollback_failed_quantized_load",
            '"traceback"', '"pre_rollback_state"', '"post_rollback_state"',
        ):
            self.assertIn(token, self.patch_text)

    def test_instrumentation_does_not_add_lifecycle_mutations(self):
        self.assertNotIn("torch.cuda.empty_cache", self.patch_text)
        self.assertNotIn("free_memory(", self.patch_text)
        self.assertNotIn("model.to(", self.patch_text)
        self.assertNotIn("tensor.to(", self.patch_text)
        self.assertNotIn("load_for_inference(", self.patch_text)

    def test_snapshot_failure_is_nonfatal(self):
        self.assertIn("_safe_language_load_boundary_snapshot", self.patch_text)
        self.assertIn("except BaseException:", self.patch_text)
        self.assertIn("return record", self.patch_text)

    def test_reconciler_and_manifest_pin_the_patch(self):
        recon = RECONCILER.read_text(encoding="utf-8")
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn("BOUNDARY_FINAL_FINGERPRINT", recon)
        self.assertIn("BOUNDARY_PATCH", recon)
        self.assertIn("language_boundary_instrumentation_patch_sha256", recon)
        self.assertIn("patches/support_layers/minimax_h3_language_boundary_instrumentation_incremental.patch", manifest)
        self.assertIn("67ca71fd28ddedf7cad6f3bb837b6b825ee08145efe518671574e19522dad2ac", manifest)

    def test_future_classifier_contract_is_source_documented(self):
        self.assertIn("LANGLOAD-02 NOT emitted", (ROOT / "docs/PATCH2.8I2_R2B_Language_Lifecycle_Boundary_Instrumentation.md").read_text(encoding="utf-8"))
        report = (ROOT / "docs/PATCH2.8I2_R2B_Language_Lifecycle_Boundary_Instrumentation.md").read_text(encoding="utf-8")
        self.assertIn("LANGLOAD-04 emitted", report)
        self.assertIn("LANGLOAD-04 NOT emitted", report)

    def test_no_gpu_or_product_execution_surface(self):
        lowered = self.patch_text.lower()
        for forbidden in ("/prompt", "w01", "encode_ids", "encode_fl2va_conditioning", "studio generation"):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
