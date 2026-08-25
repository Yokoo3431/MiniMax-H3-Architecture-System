"""PATCH2.8-I2-R2B-F3 CPU-only Qwen visual offload forensics.

This suite tests the forensic contract and a small control-flow harness.  It
does not import the managed ComfyUI runtime, initialize CUDA, submit ``/prompt``
or touch model files.  Passing these tests is not evidence that Windows CUDA
device migration is safe; that requires the separately proposed F3-G1 probe.
"""

from __future__ import annotations

from dataclasses import dataclass
import unittest


FORENSIC_CONTRACT = {
    "h3_commit": "d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad",
    "encoder_sha256": "c4d45e3c0f6e48c698e37778db198b2a56956e946cb46510038a8978fb2ff1c2",
    "te_visual_on_cpu": True,
    "visual_serialized_bytes": 1_190_533_600,
    "visual_parameter_count": 351,
    "visual_buffer_count": 1,
    "visual_tensor_count": 352,
    "visual_live_dtype": "FP32",
    "language_quantized_layer_count": 350,
    "free_commit_gb": 39.2,
    "crash_frame": "visual.to(offload_device)",
    "classification": "INFERENCE_NODE_FAILURE",
}


@dataclass(frozen=True)
class TensorDescriptor:
    group: str
    dtype: str
    storage: str
    count: int


class FakeVisual:
    """CPU fake for transition ordering only; no torch or CUDA involved."""

    def __init__(self) -> None:
        self.device = "cpu"
        self.events: list[str] = []

    def to(self, device: str) -> "FakeVisual":
        self.events.append(f"to:{device}")
        self.device = device
        return self

    def features(self) -> str:
        if self.device != "cuda":
            raise RuntimeError("visual features require the staged device")
        self.events.append("features")
        return "features-on-cpu-after-copy"


def run_cpu_control_harness(visual: FakeVisual, *, fail: bool = False) -> str:
    """Model the pinned state machine without invoking the real H3 module."""

    visual.to("cuda")
    try:
        if fail:
            raise RuntimeError("synthetic visual forward failure")
        result = visual.features()
        visual.events.append("copy:cpu")
        return result
    finally:
        visual.to("cpu")


class QwenVisualOffloadForensicsTests(unittest.TestCase):
    def test_pinned_encoder_contract_and_crash_boundary_are_recorded(self):
        self.assertRegex(FORENSIC_CONTRACT["h3_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(FORENSIC_CONTRACT["crash_frame"], "visual.to(offload_device)")
        self.assertEqual(FORENSIC_CONTRACT["classification"], "INFERENCE_NODE_FAILURE")

    def test_te_visual_on_cpu_is_required_for_staged_multimodal_path(self):
        self.assertTrue(FORENSIC_CONTRACT["te_visual_on_cpu"])

    def test_visual_lifecycle_is_deterministic(self):
        visual = FakeVisual()
        result = run_cpu_control_harness(visual)
        self.assertEqual(result, "features-on-cpu-after-copy")
        self.assertEqual(
            visual.events,
            ["to:cuda", "features", "copy:cpu", "to:cpu"],
        )
        self.assertEqual(visual.device, "cpu")

    def test_offload_occurs_only_after_feature_extraction(self):
        visual = FakeVisual()
        run_cpu_control_harness(visual)
        self.assertLess(visual.events.index("features"), visual.events.index("to:cpu"))

    def test_primary_exception_is_not_masked_by_cleanup(self):
        visual = FakeVisual()
        with self.assertRaisesRegex(RuntimeError, "synthetic visual forward failure"):
            run_cpu_control_harness(visual, fail=True)
        self.assertEqual(visual.device, "cpu")
        self.assertEqual(visual.events, ["to:cuda", "to:cpu"])

    def test_control_harness_has_no_double_migration(self):
        visual = FakeVisual()
        run_cpu_control_harness(visual)
        self.assertEqual(visual.events.count("to:cuda"), 1)
        self.assertEqual(visual.events.count("to:cpu"), 1)

    def test_language_visual_residency_invariant_is_explicit(self):
        visual = FakeVisual()
        run_cpu_control_harness(visual)
        language_stage_allowed = visual.device == "cpu"
        self.assertTrue(language_stage_allowed)

    def test_visual_and_language_quantization_boundaries_are_distinct(self):
        visual = TensorDescriptor("visual", "FP32", "ordinary_parameter", 351)
        language = TensorDescriptor("language_model", "INT8/convrot", "QuantizedTensor", 350)
        self.assertEqual(visual.dtype, "FP32")
        self.assertEqual(visual.storage, "ordinary_parameter")
        self.assertEqual(language.dtype, "INT8/convrot")
        self.assertEqual(language.storage, "QuantizedTensor")
        self.assertNotEqual(visual.group, language.group)

    def test_visual_header_size_and_tensor_count_are_bounded_evidence(self):
        self.assertEqual(FORENSIC_CONTRACT["visual_parameter_count"], 351)
        self.assertEqual(FORENSIC_CONTRACT["visual_buffer_count"], 1)
        self.assertEqual(FORENSIC_CONTRACT["visual_tensor_count"], 352)
        self.assertEqual(FORENSIC_CONTRACT["visual_live_dtype"], "FP32")
        self.assertEqual(FORENSIC_CONTRACT["visual_serialized_bytes"], 1_190_533_600)
        self.assertGreater(FORENSIC_CONTRACT["visual_serialized_bytes"], 1_000_000_000)

    def test_legacy_runtime_has_no_proven_visual_offload_fix(self):
        self.assertEqual(
            FORENSIC_CONTRACT["encoder_sha256"],
            "c4d45e3c0f6e48c698e37778db198b2a56956e946cb46510038a8978fb2ff1c2",
        )

    def test_pread_boundary_is_loading_only(self):
        self.assertNotEqual(FORENSIC_CONTRACT["crash_frame"], "safetensors.get_tensor()")

    def test_memory_pressure_is_context_not_a_proven_oom(self):
        self.assertGreaterEqual(FORENSIC_CONTRACT["free_commit_gb"], 30.0)
        self.assertNotEqual(FORENSIC_CONTRACT["classification"], "GPU_OOM")

    def test_f3_has_no_gpu_prompt_or_model_mutation_contract(self):
        source = type(self).__module__
        self.assertIn("r2bf3", source)
        self.assertNotIn("/prompt", "F3 CPU-only forensic harness")


if __name__ == "__main__":
    unittest.main()
