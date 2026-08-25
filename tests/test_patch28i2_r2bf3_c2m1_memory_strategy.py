"""CPU/static tests for the C2-M1 language memory strategy design."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_Language_Memory_Strategy_Design.md"
RUNTIME = ROOT / "runtime"

STATIC_FP32_BYTES = 3_113_768_960
STATIC_BF16_BYTES = 1_556_884_480
VISUAL_FP32_BYTES = 2_381_067_272
H3_HEADROOM_BYTES = 3 * 1024**3


def strategy_estimate(name: str) -> dict[str, int | None]:
    """Pure design arithmetic; this is not a runtime policy implementation."""
    if name == "A":
        return {
            "cuda_static_bytes": STATIC_BF16_BYTES,
            "theoretical_static_saving_bytes": STATIC_FP32_BYTES - STATIC_BF16_BYTES,
        }
    if name == "B":
        return {
            "cuda_static_bytes": 0,
            "theoretical_static_saving_bytes": STATIC_FP32_BYTES,
        }
    if name == "C":
        return {
            "cuda_static_bytes": None,
            "theoretical_static_saving_bytes": None,
        }
    raise ValueError(name)


class TestC2M1LanguageMemoryStrategy(unittest.TestCase):
    def setUp(self):
        self.report = REPORT.read_text(encoding="utf-8")

    def test_report_contains_frozen_evidence(self):
        self.assertIn("3,113,768,960 bytes", self.report)
        self.assertIn("language_model.embed_tokens.weight", self.report)
        self.assertIn("3,111,649,280 bytes", self.report)
        self.assertIn("STATIC_TENSOR_MEMORY_ESTIMATE_TOO_HIGH", self.report)

    def test_report_has_memory_budget_schema(self):
        for label in ("visual memory", "language static memory", "int8 linear residency", "h3 headroom", "allocator uncertainty"):
            self.assertIn(label, self.report.lower())

    def test_strategy_a_preserves_bf16_theoretical_saving(self):
        estimate = strategy_estimate("A")
        self.assertEqual(estimate["cuda_static_bytes"], STATIC_BF16_BYTES)
        self.assertEqual(estimate["theoretical_static_saving_bytes"], 1_556_884_480)

    def test_strategy_b_removes_static_cuda_requirement(self):
        estimate = strategy_estimate("B")
        self.assertEqual(estimate["cuda_static_bytes"], 0)
        self.assertEqual(estimate["theoretical_static_saving_bytes"], STATIC_FP32_BYTES)

    def test_strategy_c_peak_is_not_claimed_without_schedule(self):
        estimate = strategy_estimate("C")
        self.assertIsNone(estimate["cuda_static_bytes"])
        self.assertIsNone(estimate["theoretical_static_saving_bytes"])
        self.assertIn("not a proven byte saving", self.report.lower())

    def test_all_three_strategies_are_compared(self):
        for name in ("Strategy A", "Strategy B", "Strategy C"):
            self.assertIn(name, self.report)
        for column in ("Memory saving", "Compatibility risk", "Performance impact", "Implementation risk"):
            self.assertIn(column, self.report)

    def test_preferred_strategy_is_explicit_and_not_implemented(self):
        self.assertIn("Preferred design candidate: Strategy A", self.report)
        self.assertIn("not an implementation authorization", self.report)
        self.assertIn("No fix is implemented", self.report)

    def test_strategy_a_risk_is_not_hidden(self):
        for phrase in ("numerical", "dtype", "FP32", "BF16", "compatibility risk"):
            self.assertIn(phrase.lower(), self.report.lower())

    def test_strategy_b_and_c_are_not_presented_as_free_fixes(self):
        self.assertIn("CPU execution or transfers", self.report)
        self.assertIn("higher architecture risk", self.report.lower())

    def test_future_gpu_gate_is_descriptive_only(self):
        self.assertIn("C2M1-G1", self.report)
        self.assertIn("one separately authorized child-process validation", self.report.lower())
        self.assertIn("No GPU validation was executed", self.report)

    def test_budget_arithmetic_is_consistent(self):
        self.assertEqual(STATIC_FP32_BYTES - STATIC_BF16_BYTES, 1_556_884_480)
        self.assertEqual(STATIC_FP32_BYTES + VISUAL_FP32_BYTES, 5_494_836_232)
        self.assertEqual(STATIC_BF16_BYTES + VISUAL_FP32_BYTES, 3_937_951_752)
        self.assertEqual(H3_HEADROOM_BYTES, 3_221_225_472)

    def test_allocator_and_residency_uncertainty_is_preserved(self):
        self.assertIn("not persisted", self.report.lower())
        self.assertIn("unknown", self.report.lower())
        self.assertIn("zero loaded-model", self.report.lower())

    def test_no_cuda_or_model_execution_in_test_or_design_artifact(self):
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertNotIn("torch" + ".cuda", source)
        self.assertNotIn("load_for_inference" + "(", source)
        self.assertNotIn("/" + "prompt", source)
        self.assertNotIn("sub" + "process", source)
        self.assertNotIn("model" + ".load", source)

    def test_no_runtime_strategy_hook_was_added(self):
        changed_design_text = self.report.lower()
        self.assertIn("runtime:", changed_design_text)
        self.assertIn("production h3:", changed_design_text)
        self.assertIn("unchanged", changed_design_text)
        self.assertEqual(list(RUNTIME.glob("**/*c2m1*")), [])

    def test_readiness_remains_closed(self):
        self.assertIn("READY_FOR_G2", self.report)
        self.assertIn("READY_FOR_FULL_GPU_RETRY", self.report)
        self.assertIn("NO", self.report)
        self.assertIn("Stop condition", self.report)


if __name__ == "__main__":
    unittest.main()
