"""CPU-only A1 Advanced Product Layer static contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from runtime.advanced_workflows import (
    ADVANCED_WORKFLOW_ID,
    comparable_api_pair,
    load_advanced_registry,
    validate_advanced_workflow,
)
from runtime.adapters.production_workflow_binding import CANONICAL_WORKFLOWS


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SHA256 = {
    "01_Exterior_Hero.json": "efd317df416f86c86f3c8d1ae4550c9dc494a8d440b71cb89819bcc677edf218",
    "02_Day_Night_Transition.json": "6525c0e5223ebc32835b3e98afc4668d0dd2208df3c2b1472a8138af1e6598fe",
    "03_Material_Detail.json": "1440d70d13b087b81b57a5e7fefbfb8229a0680e59638911149cc4c01d95b021",
    "04_Drone_Aerial.json": "b3c12052d4cd8f7be18d7c76237d5dec1eb6ab4bf55a1c0479b3f526c9aa6e88",
    "05_Slow_Walkthrough.json": "d81ff429d26ab32b107a5139f2a60be04be9c86e022d6fe44cb4b4802dae8035",
}


class TestAdvancedWorkflowStaticContract(unittest.TestCase):
    def test_a1_graph_and_native_reconstruction_are_ready(self):
        result = validate_advanced_workflow()
        self.assertTrue(result["ready"], result["errors"])
        self.assertEqual(result["node_count"], 15)
        self.assertEqual(result["link_count"], 18)
        self.assertTrue(result["ui_rebuilt"])

    def test_change_budget_is_prompt_and_identity_only(self):
        golden, advanced = comparable_api_pair()
        self.assertEqual(set(golden), set(advanced))
        changed = []
        for node_id in golden:
            if golden[node_id] != advanced[node_id]:
                changed.append(node_id)
        self.assertEqual(changed, ["6", "15"])
        for node_id in ("1", "2", "3", "4", "5", "7", "8", "9", "10", "11", "12", "13", "14"):
            self.assertEqual(golden[node_id], advanced[node_id], node_id)
        self.assertNotIn("CreateCameraInfo", {node["class_type"] for node in advanced.values()})

    def test_both_vae_decode_paths_are_explicit(self):
        _, advanced = comparable_api_pair()
        self.assertEqual(advanced["12"]["inputs"]["vae"], ["4", 0])
        self.assertEqual(advanced["13"]["inputs"]["vae"], ["5", 0])

    def test_registry_is_experimental_and_not_production_routed(self):
        registry = load_advanced_registry()
        entry = registry["workflows"][ADVANCED_WORKFLOW_ID]
        self.assertFalse(entry["production_selector_enabled"])
        self.assertEqual(entry["base_reference"], "04_Drone_Aerial")
        self.assertNotIn(ADVANCED_WORKFLOW_ID, CANONICAL_WORKFLOWS)

    def test_golden_v1_files_are_zero_diff(self):
        for name, expected in GOLDEN_SHA256.items():
            actual = hashlib.sha256((ROOT / "production_workflows" / "golden" / name).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, name)


if __name__ == "__main__":
    unittest.main()
