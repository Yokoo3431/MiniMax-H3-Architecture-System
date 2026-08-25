"""CPU/static validation tests for the C2-M1-G0 BF16 source gate."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_G0_BF16_Static_Validation.md"


class TestC2M1G0BF16StaticValidation(unittest.TestCase):
    def setUp(self):
        self.report = REPORT.read_text(encoding="utf-8")

    def test_dtype_trace_names_the_meta_construction_point(self):
        self.assertIn("init_empty_weights()", self.report)
        lower = self.report.lower()
        self.assertIn("model_cls._from_config", lower)
        self.assertIn("dtype override", lower)
        self.assertIn("meta construction", lower)

    def test_dtype_trace_names_the_assignment_conversion(self):
        self.assertIn("tensor.to(dtype=target.dtype)", self.report)
        self.assertIn("_assign_param(model, local, tensor.to(device=offload_device))", self.report)
        self.assertIn("target dtype", self.report.lower())

    def test_candidate_bf16_path_is_distinguished_from_current_path(self):
        self.assertIn("checkpoint BF16 → target FP32", self.report)
        self.assertIn("checkpoint BF16 → target BF16", self.report)
        self.assertIn("1,556,884,480 bytes", self.report)

    def test_static_ownership_is_explicit(self):
        self.assertIn("202 direct static tensors", self.report)
        self.assertIn("350 quantized Linear modules", self.report)
        self.assertIn("visual tower is excluded", self.report)

    def test_quantized_linears_are_independent(self):
        lower = self.report.lower()
        self.assertIn("_swap_lang_linears", lower)
        self.assertIn("dtype=model_dtype", lower)
        self.assertIn("separate from", lower)
        self.assertIn("direct static tensors", lower)
        self.assertIn("modelpatcher", lower)

    def test_model_patcher_has_no_fp32_requirement(self):
        self.assertIn("no FP32 requirement", self.report)
        self.assertIn("only the 350 quantized linears", self.report)

    def test_alias_behavior_is_separated_by_phase(self):
        lower = self.report.lower()
        self.assertIn("_move_direct_tensors() preserves shared aliases", lower)
        self.assertIn("_assign_param() has no separate alias table", lower)
        self.assertIn("lm_head", lower)
        self.assertIn("intentionally", lower)

    def test_consumers_are_classified_as_unknown_not_assumed_safe(self):
        lower = self.report.lower()
        self.assertIn("no explicit fp32-only consumer", lower)
        self.assertIn("runtime consumer compatibility remains", lower)
        self.assertIn("unknown", lower)
        self.assertIn("not runtime-proven", lower)

    def test_source_result_is_conditional(self):
        self.assertIn("SOURCE_COMPATIBLE_WITH_CONDITIONS", self.report)
        self.assertIn("not an implementation authorization", self.report)
        self.assertIn("No dtype change was implemented", self.report)

    def test_no_cuda_or_model_execution_in_test_source(self):
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertNotIn("torch" + ".cuda", source)
        self.assertNotIn("load_for_inference" + "(", source)
        self.assertNotIn("model" + ".to", source)
        self.assertNotIn("/" + "prompt", source)

    def test_no_model_mutation_or_runtime_edit_is_claimed(self):
        lower = self.report.lower()
        self.assertIn("h3 source:", lower)
        self.assertIn("runtime:", lower)
        self.assertIn("model:", lower)
        self.assertIn("unchanged", lower)
        self.assertIn("not loaded or mutated", lower)

    def test_future_gpu_validation_is_descriptive_only(self):
        self.assertIn("C2M1-G1", self.report)
        self.assertIn("one separately authorized child process", self.report)
        self.assertIn("No GPU validation was executed", self.report)

    def test_readiness_remains_closed(self):
        self.assertIn("READY_FOR_G2", self.report)
        self.assertIn("READY_FOR_FULL_GPU_RETRY", self.report)
        self.assertIn("STOP", self.report)


if __name__ == "__main__":
    unittest.main()
