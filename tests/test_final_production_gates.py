"""Unit test suite for 7 Final Real Production Validation Gates for V0.8.0 Readiness.
"""

import sys
import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.validation.production_gate_validator import MasterProductionGateValidator

CONFIG_DIR = SYSTEM_ROOT / "configs"

class TestFinalProductionGates(unittest.TestCase):
    def setUp(self):
        self.master_validator = MasterProductionGateValidator()

    def test_run_all_7_production_gates(self):
        res = self.master_validator.run_all_gates()
        self.assertEqual(res["production_ready_gate_decision"], "PASS")
        self.assertEqual(res["v0_8_0_authorization"], "APPROVED")

        # Verify all 7 reports exist in configs/
        self.assertTrue((CONFIG_DIR / "production_environment_report.json").is_file())
        self.assertTrue((CONFIG_DIR / "official_skill_validation_report.json").is_file())
        self.assertTrue((CONFIG_DIR / "model_ecosystem_validation.json").is_file())
        self.assertTrue((CONFIG_DIR / "video_output_validation.json").is_file())
        self.assertTrue((CONFIG_DIR / "architect_quality_report.json").is_file())
        self.assertTrue((CONFIG_DIR / "architect_usability_report.json").is_file())
        self.assertTrue((CONFIG_DIR / "production_ready_gate.json").is_file())

if __name__ == "__main__":
    unittest.main()
