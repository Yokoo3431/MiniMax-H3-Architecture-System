"""Unit test suite for V0.8.0 RC1 Production Freeze Validation Gates.
"""

import sys
import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.production_freeze.freeze_validator import FreezeValidator

CONFIG_DIR = SYSTEM_ROOT / "configs"

class TestV080RC1FreezeGates(unittest.TestCase):
    def setUp(self):
        self.validator = FreezeValidator()

    def test_run_all_v080_rc1_freeze_gates(self):
        res = self.validator.run_all_freeze_gates()
        self.assertEqual(res["production_freeze_decision"], "PASS")
        self.assertEqual(res["v0_8_0_authorization"], "APPROVED")

        # Verify all reports exist in configs/
        self.assertTrue((CONFIG_DIR / "production_environment_report.json").is_file())
        self.assertTrue((CONFIG_DIR / "official_skill_validation_report.json").is_file())
        self.assertTrue((CONFIG_DIR / "model_ecosystem_validation.json").is_file())
        self.assertTrue((CONFIG_DIR / "workflow_reality_report.json").is_file())
        self.assertTrue((CONFIG_DIR / "video_output_validation.json").is_file())
        self.assertTrue((CONFIG_DIR / "architect_quality_report.json").is_file())
        self.assertTrue((CONFIG_DIR / "architect_usability_report.json").is_file())
        self.assertTrue((CONFIG_DIR / "production_ready_gate.json").is_file())

if __name__ == "__main__":
    unittest.main()
