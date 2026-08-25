"""CPU/static tests for the C2-F1 language-load memory boundary analysis."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest

from scripts.analyze_qwen_static_memory import analyze


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "PATCH2.8I2_R2BF3_C2F1_Language_Load_Memory_Boundary.md"
ANALYZER = ROOT / "scripts" / "analyze_qwen_static_memory.py"


def _fixture_checkpoint() -> Path:
    header = {
        "model.language_model.embed_tokens.weight": {"dtype": "BF16", "shape": [2, 3], "data_offsets": [0, 12]},
        "model.language_model.layers.0.input_layernorm.weight": {"dtype": "BF16", "shape": [3], "data_offsets": [12, 18]},
        "model.language_model.layers.0.self_attn.q_proj.weight": {"dtype": "BF16", "shape": [3, 3], "data_offsets": [18, 36]},
        "model.visual.patch_embed.proj.weight": {"dtype": "BF16", "shape": [3, 3], "data_offsets": [36, 54]},
        "model.language_model.layers.50.input_layernorm.weight": {"dtype": "BF16", "shape": [3], "data_offsets": [54, 60]},
        "model.lm_head.weight": {"dtype": "BF16", "shape": [3, 3], "data_offsets": [60, 78]},
    }
    handle = tempfile.NamedTemporaryFile(suffix=".safetensors", delete=False)
    path = Path(handle.name)
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    handle.write(struct.pack("<Q", len(encoded)))
    handle.write(encoded)
    handle.close()
    return path


class TestC2F1MemoryBoundary(unittest.TestCase):
    def setUp(self):
        self.checkpoint = _fixture_checkpoint()

    def tearDown(self):
        self.checkpoint.unlink(missing_ok=True)

    def test_static_tensor_inventory_schema(self):
        result = analyze(self.checkpoint)
        self.assertEqual(result["analysis"], "CPU_STATIC_HEADER_ONLY")
        self.assertTrue(result["no_tensor_bodies_loaded"])
        self.assertIn("groups", result)
        self.assertIn("tensors", result)
        self.assertEqual(result["static_tensor_count"], 2)

    def test_dtype_classification_and_target(self):
        result = analyze(self.checkpoint)
        self.assertEqual({row["checkpoint_dtype"] for row in result["tensors"]}, {"BF16"})
        self.assertEqual({row["target_dtype_from_pinned_loader"] for row in result["tensors"]}, {"F32"})

    def test_owner_classification(self):
        result = analyze(self.checkpoint)
        groups = {row["owner_group"] for row in result["tensors"]}
        self.assertEqual(groups, {"language_embeddings", "language_layer_norms"})

    def test_memory_estimate_generation(self):
        result = analyze(self.checkpoint)
        self.assertEqual(result["static_checkpoint_bytes"], 18)
        self.assertEqual(result["static_estimated_target_bytes"], 36)
        self.assertEqual(sum(group["estimated_target_bytes"] for group in result["groups"]), 36)

    def test_no_tensor_movement(self):
        source = ANALYZER.read_text(encoding="utf-8")
        self.assertNotIn(".to(", source)

    def test_no_cuda_call(self):
        source = ANALYZER.read_text(encoding="utf-8")
        self.assertNotIn("torch.cuda", source)
        self.assertTrue("no_torch_or_cuda_import" in source)

    def test_no_prompt(self):
        source = ANALYZER.read_text(encoding="utf-8")
        self.assertNotIn("/prompt", source)

    def test_no_workflow_execution(self):
        source = ANALYZER.read_text(encoding="utf-8")
        self.assertNotIn("NativeRuntimeAdapter", source)
        self.assertNotIn("JobAPI", source)

    def test_historical_unknowns_preserved(self):
        report = REPORT.read_text(encoding="utf-8")
        self.assertIn("not persisted", report)
        self.assertIn("unproven", report)
        self.assertIn("historical", report.lower())

    def test_no_runtime_modification(self):
        source = ANALYZER.read_text(encoding="utf-8")
        self.assertNotIn("write_text", source)
        self.assertNotIn("unlink", source)
        self.assertNotIn("shutil.copy", source)

    def test_header_only_contract(self):
        result = analyze(self.checkpoint)
        self.assertTrue(result["no_tensor_bodies_loaded"])
        self.assertTrue(result["no_torch_or_cuda_import"])

    def test_quantized_linear_entries_excluded(self):
        result = analyze(self.checkpoint)
        self.assertEqual(result["excluded_header_entries"]["quantized_linear"], 1)
        self.assertFalse(any("q_proj" in row["local_name"] for row in result["tensors"]))

    def test_visual_entries_excluded(self):
        result = analyze(self.checkpoint)
        self.assertEqual(result["excluded_header_entries"]["visual"], 1)
        self.assertFalse(any(row["local_name"].startswith("visual.") for row in result["tensors"]))

    def test_later_layer_and_lm_head_excluded(self):
        result = analyze(self.checkpoint)
        self.assertEqual(result["excluded_header_entries"]["later_layer_or_lm_head"], 2)

    def test_target_device_documented(self):
        result = analyze(self.checkpoint)
        self.assertEqual(
            {row["expected_target_device"] for row in result["tensors"]},
            {"cuda during load_for_inference"},
        )

    def test_report_selects_one_bottleneck(self):
        report = REPORT.read_text(encoding="utf-8")
        section = report.split("## 11. Bottleneck Classification", 1)[1].split("Secondary factors", 1)[0]
        choices = {
            "STATIC_TENSOR_MEMORY_ESTIMATE_TOO_HIGH",
            "RESIDENCY_CONFLICT",
            "CACHE_OR_ALLOCATOR_PRESSURE",
            "UNKNOWN_MEMORY_BOUNDARY",
        }
        self.assertEqual(sum(choice in section for choice in choices), 1)

    def test_no_gpu_generation_boundary(self):
        report = REPORT.read_text(encoding="utf-8")
        self.assertIn("READY_FOR_G2:             NO", report)
        self.assertIn("READY_FOR_FULL_GPU_RETRY: NO", report)
        self.assertIn("No GPU", report)


if __name__ == "__main__":
    unittest.main()
