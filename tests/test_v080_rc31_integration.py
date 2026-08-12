"""Unit test suite for V0.8.0 RC3.1 Local Integration Fix.
"""

import sys
import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from scripts.deploy_workflows import deploy_and_validate_workflows

CONFIG_DIR = SYSTEM_ROOT / "configs"
LAUNCHER_FILE = SYSTEM_ROOT / "launcher" / "Start_MiniMax_H3_Architect.bat"
REPORT_DOC = SYSTEM_ROOT / "docs" / "V0.8.0_RC3.1_Integration_Fix_Report.md"

class TestV080RC31Integration(unittest.TestCase):
    def test_workflow_deployer_and_validator(self):
        res = deploy_and_validate_workflows()
        self.assertEqual(res["status"], "PASS")
        self.assertTrue(res["zero_missing_nodes_verified"])
        self.assertEqual(len(res["deployed_production_workflows"]), 5)
        self.assertTrue((CONFIG_DIR / "workflow_validation_report.json").is_file())

    def test_launcher_bat_contains_rc31_features(self):
        self.assertTrue(LAUNCHER_FILE.is_file())
        with open(LAUNCHER_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("GIT_PYTHON_GIT_EXECUTABLE", content)
        self.assertIn("deploy_workflows.py", content)

    def test_integration_fix_report_exists(self):
        self.assertTrue(REPORT_DOC.is_file())

if __name__ == "__main__":
    unittest.main()
