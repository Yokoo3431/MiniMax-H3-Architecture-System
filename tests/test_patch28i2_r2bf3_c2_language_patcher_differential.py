"""CPU/static checks for the C2 Qwen language/patcher differential."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "PATCH2.8I2_R2BF3_C2_Language_Patcher_State_Differential.md"
C1_REPORT = ROOT / "docs" / "PATCH2.8I2_R2BF3_C1G1_Staged_Helper_Context_Probe.md"
C1_PROBE = ROOT / "scripts" / "probe_qwen_staged_helper_context.py"


class TestC2LanguagePatcherDifferential(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT.read_text(encoding="utf-8")
        cls.c1_report = C1_REPORT.read_text(encoding="utf-8")
        cls.probe = C1_PROBE.read_text(encoding="utf-8")

    def test_c1_g1_staged_context_recorded_pass(self):
        self.assertIn("STAGED_CONTEXT_PASS", self.report)
        self.assertIn("child exit: `0`", self.report)

    def test_direct_visual_gate_closed(self):
        self.assertIn("direct visual lifecycle: PASS", self.report)

    def test_staged_visual_gate_closed(self):
        self.assertIn("production staged visual helper: PASS", self.report)

    def test_linear_patcher_state_machine_schema(self):
        for value in ("_linear_patcher", "Fresh `__init__`", "ModelPatcher"):
            self.assertIn(value, self.report)

    def test_compute_device_state_machine_schema(self):
        self.assertIn("_compute_device", self.report)
        self.assertIn("_set_compute_device(load_device)", self.report)

    def test_inference_active_state_machine_schema(self):
        self.assertIn("_inference_active", self.report)
        self.assertIn("_inference_active=True", self.report)

    def test_load_for_inference_transition_captured(self):
        self.assertIn("load_models_gpu()", self.report)
        self.assertIn("_move_static_tensors(load_device)", self.report)

    def test_offload_after_inference_transition_captured(self):
        self.assertIn("offload_after_inference()", self.report)
        self.assertIn("soft_empty_cache()", self.report)

    def test_visual_staged_entry_calls_offload_first(self):
        self.assertIn("begins with an unconditional", self.report)
        self.assertIn("`offload_after_inference()`", self.report)
        self.assertNotIn("self.offload_after_inference()", self.probe)

    def test_language_patcher_ownership_documented(self):
        self.assertIn("350 selected INT8/convrot language linears", self.report)
        self.assertIn("is excluded by `_movable()` when `TE_VISUAL_ON_CPU=True`", self.report)

    def test_static_tensor_ownership_documented(self):
        self.assertIn("direct static language tensors", self.report)
        self.assertIn("visual tower", self.report)

    def test_unknown_historical_state_remains_unknown(self):
        self.assertIn("remain `UNKNOWN`", self.report)
        self.assertIn("UNKNOWN", self.report)

    def test_no_invented_r2b_r1_patcher_values(self):
        self.assertIn("does not persist exact values", self.report)
        self.assertIn("not reconstructed facts", self.report)

    def test_wrapper_reuse_classification_explicit(self):
        self.assertIn("REUSE_POSSIBLE", self.report)
        self.assertIn("REUSE_PROVEN: no", self.report)

    def test_cache_reuse_path_inspected(self):
        self.assertIn("runtime/encode_cache.py", self.report)
        self.assertIn("_multimodal_qwen_encode()", self.report)

    def test_one_factor_next_probe_rule(self):
        self.assertIn("LANGUAGE_PATCHER_CREATED_THEN_OFFLOADED", self.report)
        self.assertIn("Exactly one candidate", self.report)

    def test_no_full_w01_next_probe(self):
        self.assertIn("must not jump to G2 or a full W01 retry", self.report)

    def test_no_g2(self):
        self.assertIn("READY_FOR_G2", self.report)
        self.assertIn("`NO`", self.report)

    def test_no_gpu(self):
        self.assertIn("No GPU", self.report)
        self.assertNotIn("C2G1", self.probe)

    def test_no_prompt(self):
        self.assertIn("`/prompt`", self.report)
        self.assertIn('"prompt_submitted": False', self.probe)

    def test_no_runtime_change(self):
        self.assertIn("Runtime Versions:      UNCHANGED", self.report)
        self.assertIn("runtime/version\nchange", self.report)

    def test_no_model_change(self):
        self.assertIn("Model Binaries:        UNCHANGED", self.report)
        self.assertIn("model mutation", self.report)

    def test_no_dependency_version_change(self):
        self.assertIn("dependency change", self.report)
        self.assertIn("Production H3:         UNCHANGED", self.report)

    def test_c2_classification_and_readiness(self):
        self.assertIn("LANGUAGE_CONTEXT_NARROWED", self.report)
        self.assertIn("READY_FOR_TARGETED_CONTEXT_PROBE", self.report)
        self.assertIn("YES — recommendation only", self.report)

    def test_report_has_no_machine_result_claim(self):
        # C2 is design-only; it must not claim a GPU probe result.
        self.assertIn("No C2-G1 probe was executed", self.report)
        self.assertNotIn("C2G1 result: PASS", self.report)


if __name__ == "__main__":
    unittest.main()
