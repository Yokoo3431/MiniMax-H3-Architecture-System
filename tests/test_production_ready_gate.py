"""Unit test suite for V0.7.8.4 Real Production Ready Gate for V0.8.0 Readiness.
"""

import sys
import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.critic.production_gate_validator import ProductionGateValidator

GATE_MANIFEST = SYSTEM_ROOT / "configs" / "production_ready_gate.json"
REAL_PACK_FILE = SYSTEM_ROOT / "tests" / "assets" / "architect_outputs" / "real_cases_pack.json"

class TestProductionReadyGate(unittest.TestCase):
    def setUp(self):
        self.validator = ProductionGateValidator()

    def test_gate_manifest_exists(self):
        self.assertTrue(GATE_MANIFEST.is_file(), "production_ready_gate.json must exist")
        with open(GATE_MANIFEST, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertIn("v0_8_0_authorization_target", manifest)

    def test_real_cases_pack_exists(self):
        self.assertTrue(REAL_PACK_FILE.is_file(), "real_cases_pack.json must exist")
        with open(REAL_PACK_FILE, "r", encoding="utf-8") as f:
            pack = json.load(f)
        self.assertEqual(pack["total_cases"], 5)

    def test_all_5_cases_pass_production_gate(self):
        with open(REAL_PACK_FILE, "r", encoding="utf-8") as f:
            pack = json.load(f)

        for case_data in pack["cases"]:
            res = self.validator.validate_production_gate(case_data)
            self.assertEqual(res["gate_decision"], "PASS", f"Case {case_data['case_id']} failed gate")
            self.assertTrue(res["checks"]["real_file_generated"])
            self.assertTrue(res["checks"]["resolution_target_met"])
            self.assertTrue(res["checks"]["no_critical_deformation"])
            self.assertTrue(res["v0_8_0_authorized"])

if __name__ == "__main__":
    unittest.main()
