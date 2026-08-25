"""CPU/static tests for the live-vs-frozen H3 inventory reconciliation."""

from __future__ import annotations

from pathlib import Path
import json
import struct
import tempfile
import unittest

from scripts.analyze_qwen_static_memory import analyze
from scripts.reconcile_qwen_static_inventory import compare


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "PATCH2.8I2_R2BF3_C2M1_I2F1_Static_Inventory_Reconciliation.md"
RECONCILER = ROOT / "scripts" / "reconcile_qwen_static_inventory.py"
I2_PATCH = ROOT / "patches" / "support_layers" / "minimax_h3_static_transfer_margin_incremental.patch"

FROZEN_NAMES = {
    "language_model.embed_tokens.weight",
    "language_model.norm.weight",
}
LIVE_NAMES = {
    "language_model.embed_tokens.weight",
    "language_model.rotary_emb.inv_freq",
    "language_model.rotary_emb.original_inv_freq",
}


def _header_fixture(directory: Path) -> Path:
    header = {
        "model.language_model.embed_tokens.weight": {
            "dtype": "BF16", "shape": [2, 3], "data_offsets": [0, 12]
        },
        "model.language_model.norm.weight": {
            "dtype": "BF16", "shape": [3], "data_offsets": [12, 18]
        },
        "model.language_model.layers.0.input_layernorm.weight": {
            "dtype": "BF16", "shape": [3], "data_offsets": [18, 24]
        },
        "model.language_model.layers.0.self_attn.q_proj.weight": {
            "dtype": "I8", "shape": [3, 3], "data_offsets": [24, 33]
        },
        "model.visual.patch_embed.proj.weight": {
            "dtype": "BF16", "shape": [3, 3], "data_offsets": [33, 51]
        },
        "model.language_model.layers.50.input_layernorm.weight": {
            "dtype": "BF16", "shape": [3], "data_offsets": [51, 57]
        },
        "model.lm_head.weight": {
            "dtype": "BF16", "shape": [3, 3], "data_offsets": [57, 75]
        },
    }
    path = directory / "qwen.safetensors"
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded)
    (directory / "config.json").write_text(
        json.dumps({"text_config": {"head_dim": 128}}), encoding="utf-8"
    )
    return path


class TestC2M1I2F1StaticInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT.read_text(encoding="utf-8")
        cls.reconciler = RECONCILER.read_text(encoding="utf-8")
        cls.i2_patch = I2_PATCH.read_text(encoding="utf-8")

    def test_exact_frozen_header_name_set(self):
        self.assertIn("FROZEN_NAME_COUNT = 202", self.report)
        self.assertIn("language_model.norm.weight", self.report)

    def test_exact_live_meta_name_set(self):
        self.assertIn("LIVE_NAME_COUNT = 203", self.report)
        self.assertIn("language_model.rotary_emb.inv_freq", self.report)
        self.assertIn("language_model.rotary_emb.original_inv_freq", self.report)

    def test_deterministic_set_difference(self):
        frozen = {name: {"name": name, "shape": [1], "numel": 1, "dtype": "torch.bfloat16", "kind": "parameter", "bytes": 2} for name in FROZEN_NAMES}
        live = {name: {"name": name, "shape": [1], "numel": 1, "dtype": "torch.bfloat16", "kind": "parameter", "bytes": 2} for name in LIVE_NAMES}
        result = compare(frozen, live)
        self.assertEqual(result["live_minus_frozen"], sorted(LIVE_NAMES - FROZEN_NAMES))
        self.assertEqual(result["frozen_minus_live"], sorted(FROZEN_NAMES - LIVE_NAMES))

    def test_exact_count_and_byte_reconciliation(self):
        self.assertIn("203", self.report)
        self.assertIn("1,556,874,496", self.report)
        self.assertIn("202 - 1 + 2 = 203", self.report)
        self.assertIn("128 + 128 - 10,240 = -9,984", self.report)

    def test_parameter_vs_buffer_classification(self):
        self.assertIn("language_model.norm.weight", self.report)
        self.assertIn("kind: buffer", self.report)
        self.assertIn("kind: parameter", self.report)

    def test_alias_handling_is_identity_aware(self):
        frozen = {"a": {"name": "a", "shape": [2], "numel": 2, "dtype": "torch.bfloat16", "kind": "parameter", "bytes": 4}}
        live = {"a": {"name": "a", "shape": [2], "numel": 2, "dtype": "torch.bfloat16", "kind": "parameter", "bytes": 4, "alias_group": "a"}}
        self.assertEqual(compare(frozen, live)["different_shape"], [])
        self.assertIn("alias", self.report.lower())

    def test_quantized_350_exclusion(self):
        with tempfile.TemporaryDirectory() as raw:
            result = analyze(_header_fixture(Path(raw)))
        self.assertEqual(result["excluded_header_entries"]["quantized_linear"], 1)
        self.assertIn("350", self.report)

    def test_visual_exclusion(self):
        with tempfile.TemporaryDirectory() as raw:
            result = analyze(_header_fixture(Path(raw)))
        self.assertEqual(result["excluded_header_entries"]["visual"], 1)

    def test_trimmed_later_layer_and_lm_head_exclusion(self):
        with tempfile.TemporaryDirectory() as raw:
            result = analyze(_header_fixture(Path(raw)))
        self.assertEqual(result["excluded_header_entries"]["later_layer_or_lm_head"], 2)

    def test_runtime_contract_excludes_removed_norm_and_adds_buffers(self):
        with tempfile.TemporaryDirectory() as raw:
            result = analyze(_header_fixture(Path(raw)), runtime_contract=True)
        self.assertEqual(result["excluded_header_entries"]["runtime_removed_language_norm"], 1)
        self.assertEqual(result["excluded_header_entries"]["runtime_generated_buffers"], 2)
        self.assertEqual(
            {row["local_name"] for row in result["tensors"] if row["classification"] == "RUNTIME_GENERATED_STATIC_BUFFER"},
            {"language_model.rotary_emb.inv_freq", "language_model.rotary_emb.original_inv_freq"},
        )

    def test_exact_runtime_contract_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            result = analyze(_header_fixture(Path(raw)), runtime_contract=True)
        self.assertEqual(result["static_tensor_count"], 4)
        self.assertEqual(result["strategy_a_candidate_bytes"], 274)

    def test_strategy_a_dtype_behavior_is_preserved(self):
        self.assertIn("language_model.to(dtype=torch.bfloat16)", self.report)
        self.assertIn("ordinary language static tensors", self.report)

    def test_i2_policy_is_read_only(self):
        self.assertIn("only READ", self.report)
        self.assertNotIn("create parameters", self.i2_patch)
        self.assertNotIn("duplicate aliases", self.i2_patch)

    def test_authoritative_inventory_is_runtime_semantics(self):
        self.assertIn("PINNED_MATERIALIZED_DIRECT_SLOT_CONTRACT", self.report)
        self.assertIn("_direct_tensor_slots", self.report)
        self.assertIn("authoritative", self.report.lower())

    def test_runtime_gate_uses_authoritative_definition(self):
        self.assertIn("same ownership / enumeration semantics", self.report)
        self.assertIn("203", self.report)
        self.assertIn("not approximate", self.report.lower())

    def test_no_approximate_comparison(self):
        self.assertIn("exact", self.report.lower())
        self.assertNotIn("approximately equal", self.report.lower())

    def test_no_hardcoded_machine_path(self):
        self.assertNotIn("D:\\ProgramFilesNormal", self.reconciler)
        self.assertNotIn("C:\\Users", self.reconciler)

    def test_no_cuda_or_inference(self):
        source = self.reconciler.lower()
        self.assertNotIn("torch.cuda", source)
        self.assertNotIn("load_for_inference(", source)
        self.assertNotIn("/prompt", source)
        self.assertNotIn("get_image_features", source)

    def test_future_post_materialization_commit_gate_is_explicit(self):
        self.assertIn("57.793 GiB", self.report)
        self.assertIn("28.798 GiB", self.report)
        self.assertIn("AFTER_QWEN_MATERIALIZATION", self.report)
        self.assertIn("BEFORE_LOAD_FOR_INFERENCE", self.report)

    def test_authoritative_analyzer_cli_mode_is_present(self):
        analyzer = (ROOT / "scripts" / "analyze_qwen_static_memory.py").read_text(encoding="utf-8")
        self.assertIn("runtime_contract", analyzer)
        self.assertIn("runtime-generated", self.report.lower())

    def test_readiness_and_stop_policy(self):
        self.assertIn("READY_FOR_LANGUAGE_MEMORY_GPU_VALIDATION: YES", self.report)
        self.assertIn("READY_FOR_RETAINED_PATCHER_VISUAL_PROBE: NO", self.report)
        self.assertIn("READY_FOR_G2: NO", self.report)
        self.assertIn("No GPU", self.report)


if __name__ == "__main__":
    unittest.main()
