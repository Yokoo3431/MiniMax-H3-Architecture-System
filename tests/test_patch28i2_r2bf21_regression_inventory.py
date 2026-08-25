"""PATCH2.8-I2-R2B-F2.1 regression baseline freeze tests."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.check_regression_inventory import (
    CANONICAL_COMMAND,
    INVENTORY_PATH,
    ROOT,
    SOURCE_MANIFEST_PATH,
    compare_inventory,
    compare_skip_inventory,
    discover_cases,
    discovered_ids,
    expected_skips,
)


class RegressionInventoryFreezeTests(unittest.TestCase):
    def setUp(self):
        self.baseline = json.loads((ROOT / "configs" / "regression_baseline.json").read_text(encoding="utf-8"))
        self.inventory = [line.strip() for line in INVENTORY_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.sources = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_inventory_matches_current_discovery(self):
        self.assertEqual(self.inventory, discovered_ids())

    def test_inventory_is_sorted_and_unique(self):
        self.assertEqual(self.inventory, sorted(set(self.inventory)))

    def test_inventory_hash_and_count_are_frozen(self):
        digest = hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest().upper()
        self.assertEqual(digest, self.baseline["inventory_sha256"])
        self.assertEqual(len(self.inventory), self.baseline["discovered_count"])

    def test_source_manifest_hash_and_paths_are_frozen(self):
        digest = hashlib.sha256(SOURCE_MANIFEST_PATH.read_bytes()).hexdigest().upper()
        self.assertEqual(digest, self.baseline["test_source_manifest_sha256"])
        self.assertTrue(self.sources["files"])
        self.assertEqual(sum(item["discovered_test_count"] for item in self.sources["files"]), len(self.inventory))

    def test_expected_skip_ids_are_explicit(self):
        skips = self.baseline["expected_skip_ids"]
        self.assertEqual(len(skips), self.baseline["expected_skip_count"])
        self.assertEqual({item["id"] for item in skips}, {item["id"] for item in expected_skips(discover_cases())})
        self.assertTrue(all(item["reason"] for item in skips))

    def test_canonical_command_is_frozen(self):
        self.assertEqual(self.baseline["canonical_command"], CANONICAL_COMMAND)

    def test_f1_and_f2_suites_are_present(self):
        joined = "\n".join(self.inventory)
        for marker in ("test_patch28i2_r2bf1_model_root_contract", "test_patch28i2_r2bf2_h3_sidecar_install"):
            self.assertIn(marker, joined)
        self.assertEqual(sum(marker in item for item in self.inventory
                             for marker in ("test_patch28i2_r2bf2_h3_sidecar_install",)), 17)

    def test_major_i2_stage_suites_are_present(self):
        joined = "\n".join(self.inventory)
        for marker in (
            "test_patch28i2_installer", "test_patch28i2_r2a_support_layer",
            "test_patch28i2_r2b0_user_entry", "test_patch28i2_r2b01_environment_adoption",
            "test_patch28i2_r2b1_fresh_install", "test_patch28i2_r2b11_production_consolidation",
            "test_patch28i2_r2b12_managed_runtime",
        ):
            self.assertIn(marker, joined)

    def test_runtime_tests_are_explicitly_excluded_integration_sources(self):
        excluded = {item["path"]: item for item in self.sources["excluded_sources"]}
        self.assertIn("tests/runtime/test_rc33_patch2_gpu_execution.py", excluded)
        self.assertIn("tests/runtime/test_rc33_real_h3_golden.py", excluded)
        self.assertTrue(all(item["classification"] == "INTEGRATION" for item in excluded.values()))

    def test_inventory_guard_detects_added_and_removed_ids(self):
        delta = compare_inventory(self.inventory + ["new.Test.test_added"], self.inventory)
        self.assertEqual(delta["ADDED"], ["new.Test.test_added"])
        delta = compare_inventory(self.inventory[:-1], self.inventory)
        self.assertEqual(delta["REMOVED"], [self.inventory[-1]])

    def test_inventory_guard_detects_skip_changes(self):
        frozen = [{"id": self.inventory[0], "reason": "old"}]
        current = [{"id": self.inventory[0], "reason": "new"}]
        self.assertEqual(compare_skip_inventory(current, frozen), [self.inventory[0]])

    def test_inventory_guard_does_not_auto_update(self):
        source = (ROOT / "scripts" / "check_regression_inventory.py").read_text(encoding="utf-8")
        self.assertIn("Baseline files are never auto-generated", source)
        self.assertNotIn("write_text", source)

    def test_no_gpu_or_prompt_in_inventory_infrastructure(self):
        forbidden_gpu_marker = ".".join(("torch", "cuda"))
        forbidden_http_marker = ".".join(("requests", "post"))
        for path in (ROOT / "scripts" / "check_regression_inventory.py", Path(__file__)):
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn(forbidden_gpu_marker, text)
            self.assertNotIn(forbidden_http_marker, text)


if __name__ == "__main__":
    unittest.main()
