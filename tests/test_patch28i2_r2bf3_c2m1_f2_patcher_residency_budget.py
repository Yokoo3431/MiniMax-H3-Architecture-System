"""CPU/static tests for C2M1-F2 partial-residency budget analysis."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_F2_Patcher_Residency_Budget_Analysis.md"
ANALYZER = ROOT / "scripts" / "analyze_qwen_static_memory.py"
SUPPORT_MANIFEST = ROOT / "configs" / "support_layer_manifest.yaml"

OLD_STATIC = 3_113_768_960
BF16_STATIC = 1_556_884_480
HEADROOM = 3 << 30
WINDOWS_EXTRA_RESERVED = 600 * 1024 * 1024
RESERVE_DELTA = OLD_STATIC - BF16_STATIC


class PatcherResidencyBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT.read_text(encoding="utf-8")
        cls.analyzer = ANALYZER.read_text(encoding="utf-8")
        cls.manifest = SUPPORT_MANIFEST.read_text(encoding="utf-8")

    def test_frozen_strategy_a_bytes(self):
        self.assertEqual(BF16_STATIC, 1_556_884_480)

    def test_frozen_old_fp32_bytes(self):
        self.assertEqual(OLD_STATIC, 3_113_768_960)

    def test_exact_headroom_value(self):
        self.assertEqual(HEADROOM, 3_221_225_472)
        self.assertIn("TE_GPU_HEADROOM = 3 << 30", self.report)

    def test_h3_reserve_formula(self):
        self.assertEqual(HEADROOM + OLD_STATIC, 6_334_994_432)
        self.assertEqual(HEADROOM + BF16_STATIC, 4_778_109_952)
        self.assertIn("memory_required = TE_GPU_HEADROOM + static_storage_bytes", self.report)

    def test_comfy_memory_required_semantics(self):
        self.assertIn("input to free-memory target / partial-load budget", self.report)
        self.assertIn("extra_mem = max", self.report)
        self.assertIn("minimum_memory_required = extra_mem", self.report)

    def test_partial_load_decision_path(self):
        self.assertIn("lowvram_model_memory = max", self.report)
        self.assertIn("MIN_WEIGHT_MEMORY_RATIO = 0.0", self.report)
        self.assertIn("loaded_model.model_load(lowvram_model_memory)", self.report)

    def test_direct_static_scope_is_separate(self):
        self.assertIn("202 direct static language tensors", self.report)
        self.assertIn("direct static language tensors are excluded from patcher size", self.report)

    def test_quantized_linear_contract(self):
        self.assertIn("Selected logical Linear modules: 350", self.report)
        self.assertIn("quantized_linear_contract: preserved_350", self.manifest)

    def test_patcher_size_uses_physical_state_dict_bytes(self):
        self.assertIn("_physical_module_bytes(bank)", self.report)
        self.assertIn("state-dictionary byte totals", self.report)
        self.assertIn("QuantizedTensor", self.report)

    def test_partial_load_granularity_is_module_level(self):
        self.assertIn("selected quantized Linear module", self.report)
        self.assertIn("5.004 MiB", self.report)

    def test_fp32_bf16_reserve_delta(self):
        self.assertEqual(RESERVE_DELTA, 1_556_884_480)
        self.assertIn("reserve delta is exactly", self.report.lower())
        self.assertIn("1.449962 GiB", self.report)

    def test_reserve_recapture_classification_is_explicit(self):
        self.assertIn("RESERVE_RECAPTURE_PLAUSIBLE", self.report)
        self.assertNotIn("RESERVE_RECAPTURE_PROVEN", self.report)

    def test_strategy_a_verdict_is_single_and_conservative(self):
        self.assertIn("STRATEGY_A_INSUFFICIENT_WITH_PARTIAL_RESIDENCY_PRESSURE", self.report)
        self.assertNotIn("STRATEGY_A_SAVING_RECAPTURED_BY_PATCHER_RESIDENCY", self.report)

    def test_no_invented_cuda_residency(self):
        self.assertIn("not proof that every byte was resident", self.report)
        self.assertIn("exact resident Linear", self.report)
        self.assertIn("amount was not logged", self.report)

    def test_historical_unknowns_preserved(self):
        self.assertIn("UNKNOWN", self.report)
        self.assertIn("not logged", self.report)
        self.assertIn("exact bytes resident", self.report)

    def test_no_gpu(self):
        self.assertIn("No CUDA", self.report)
        self.assertIn("GPU:                        NO", self.report)
        self.assertNotIn("torch.cuda", self.analyzer)

    def test_no_cuda_execution(self):
        self.assertIn("CPU/static/source/log-forensics", self.report)
        self.assertNotIn("load_for_inference() was executed", self.report)

    def test_no_prompt(self):
        self.assertIn("/prompt", self.report)
        self.assertIn("No mitigation", self.report)

    def test_no_w01(self):
        self.assertIn("W01", self.report)
        self.assertIn("No mitigation", self.report)

    def test_no_model_mutation(self):
        self.assertIn("model mutation", self.report)
        self.assertIn("Model binaries:             UNCHANGED", self.report)

    def test_no_runtime_or_version_change(self):
        self.assertIn("Runtime versions:           UNCHANGED", self.report)
        self.assertIn("No value is selected here, and no memory policy is changed", self.report)


if __name__ == "__main__":
    unittest.main()
