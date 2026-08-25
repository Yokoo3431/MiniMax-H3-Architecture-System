"""CPU/static tests for the I2 static-transfer safety-margin policy."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_I2_Static_Transfer_Safety_Margin.md"
PATCH = ROOT / "patches" / "support_layers" / "minimax_h3_static_transfer_margin_incremental.patch"
RECONCILER = ROOT / "scripts" / "reconcile_h3_strategy_a.py"
MANIFEST = ROOT / "configs" / "support_layer_manifest.yaml"

STATIC_COUNT = 202
BF16_STATIC_BYTES = 1_556_884_480
FP32_STATIC_BYTES = 3_113_768_960
HEADROOM = 3_221_225_472
WINDOWS_EXTRA_RESERVED = 629_145_600


class StaticTransferMarginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT.read_text(encoding="utf-8")
        cls.patch = PATCH.read_text(encoding="utf-8")
        cls.reconciler = RECONCILER.read_text(encoding="utf-8")
        cls.manifest = MANIFEST.read_text(encoding="utf-8")

    def test_static_contract_count_is_preserved(self):
        self.assertIn("ordinary direct static tensors:      202", self.report)

    def test_bf16_actual_bytes_are_preserved(self):
        self.assertEqual(BF16_STATIC_BYTES, 1_556_884_480)
        self.assertIn("actual Strategy-A static bytes:     1,556,884,480", self.report)

    def test_fp32_equivalent_bytes_are_derived(self):
        self.assertEqual(FP32_STATIC_BYTES, 3_113_768_960)
        self.assertIn("FP32-equivalent static bytes:       3,113,768,960", self.report)
        self.assertIn("numel * 4", self.report)

    def test_strategy_saving_is_derived(self):
        self.assertEqual(FP32_STATIC_BYTES - BF16_STATIC_BYTES, BF16_STATIC_BYTES)
        self.assertIn("max(0, fp32_equivalent_static_bytes - actual_static_storage_bytes)", self.report)
        self.assertIn("without a machine-tuned constant", self.patch)

    def test_frozen_margin_value(self):
        self.assertIn("derived safety margin:               1,556,884,480", self.report)
        self.assertIn("1.449962 GiB", self.report)

    def test_fp32_path_margin_is_zero(self):
        self.assertIn("actual tensors already occupy the FP32-equivalent size, no margin", self.patch)
        self.assertIn("actual FP32 path produces zero", self.report)

    def test_headroom_is_unchanged(self):
        self.assertEqual(HEADROOM, 3 << 30)
        self.assertIn("TE_GPU_HEADROOM:                    3,221,225,472", self.report)
        self.assertNotIn("TE_GPU_HEADROOM =", self.patch)

    def test_memory_required_formula(self):
        self.assertIn("TE_GPU_HEADROOM", self.report)
        self.assertIn("actual_static_storage_bytes", self.report)
        self.assertIn("safety_margin", self.report)
        self.assertIn("+ self._static_transfer_safety_margin_bytes", self.patch)
        self.assertEqual(HEADROOM + BF16_STATIC_BYTES + BF16_STATIC_BYTES, 6_334_994_432)

    def test_effective_windows_target_is_policy_derived(self):
        self.assertEqual(6_334_994_432 + WINDOWS_EXTRA_RESERVED, 6_964_140_032)
        self.assertIn("6,334,994,432 + 629,145,600", self.report)
        self.assertIn("policy targets, not physical CUDA allocations", self.report)

    def test_partial_load_semantics_are_unchanged(self):
        self.assertIn("memory_required=reserve", self.report)
        self.assertIn("free-memory target", self.report)
        self.assertIn("partial-load budget", self.report)
        self.assertIn("no new residency state machine", self.report)

    def test_load_order_is_unchanged(self):
        self.assertIn("load_models_gpu", self.report)
        self.assertIn("_move_static_tensors", self.report)
        self.assertIn("load_models_gpu before static transfer", self.manifest)
        self.assertNotIn("move static tensors before ModelPatcher", self.patch)

    def test_offload_order_is_unchanged(self):
        self.assertIn("offload_after_inference()", self.report)
        self.assertIn("_unload_linear_patcher()", self.report)
        self.assertNotIn("offload_after_inference", self.patch)

    def test_quantized_linear_contract_is_preserved(self):
        self.assertIn("350 quantized Linears", self.report)
        self.assertIn("quantized_linear_contract", self.manifest)
        self.assertNotIn("QuantizedTensor", self.patch)

    def test_visual_fp32_contract_is_preserved(self):
        self.assertIn("visual dtype:                   FP32", self.report)
        self.assertIn("visual FP32", self.manifest)
        self.assertNotIn("visual.to", self.patch)

    def test_strategy_a_activation_is_explicit(self):
        self.assertIn("H3_LANGUAGE_STATIC_TARGET_DTYPE == bfloat16", self.manifest)
        self.assertIn('H3_LANGUAGE_STATIC_TARGET_DTYPE != "bfloat16"', self.patch)

    def test_no_double_reservation_for_fp32(self):
        self.assertIn("already occupy the FP32-equivalent size, no margin", self.patch)
        self.assertIn("actual FP32 path produces zero", self.report)

    def test_support_reconciliation_is_deterministic(self):
        self.assertIn("MARGIN_FINAL_FINGERPRINT", self.reconciler)
        self.assertIn("MARGIN_PATCH", self.reconciler)
        self.assertIn("static_transfer_margin_patch_sha256", self.reconciler)
        self.assertIn("strategy_reconciled", self.reconciler)
        self.assertIn("apply_unified_patch(margin_patch_path, h3_root)", self.reconciler)

    def test_installer_contract_contains_policy(self):
        self.assertIn("static_transfer_margin_reconciliation_patch", self.manifest)
        self.assertIn("CPU_META_POLICY_IMPLEMENTED", self.manifest)
        self.assertIn("pending_human_authorized_gpu_gate", self.manifest)

    def test_arbitrary_install_drive_supported(self):
        self.assertNotIn("D:\\\\", self.patch)
        self.assertNotIn("D:/", self.patch)
        self.assertIn("--runtime-root", self.reconciler)

    def test_no_cuda_execution(self):
        self.assertNotIn("torch.cuda", self.patch)
        self.assertNotIn("load_for_inference()", self.patch)
        self.assertIn("No CUDA execution", self.report)

    def test_no_model_execution(self):
        self.assertIn("model inference", self.report)
        self.assertNotIn("load_models_gpu(", self.patch)

    def test_no_prompt_or_w01(self):
        self.assertIn("/prompt", self.report)
        self.assertIn("W01", self.report)
        self.assertNotIn("/prompt", self.patch)

    def test_official_prompt_pipeline_untouched(self):
        self.assertIn("Official Prompt Pipeline:   FROZEN", self.report)
        self.assertNotIn("prompt_bridge", self.patch)

    def test_readiness_remains_closed(self):
        self.assertIn("READY_FOR_MEMORY_POLICY_GPU_VALIDATION: YES", self.report)
        self.assertIn("READY_FOR_G2:                           NO", self.report)
        self.assertIn("READY_FOR_FULL_GPU_RETRY:               NO", self.report)


if __name__ == "__main__":
    unittest.main()
