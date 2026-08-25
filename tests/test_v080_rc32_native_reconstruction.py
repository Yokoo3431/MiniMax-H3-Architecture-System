"""Unit test suite for V0.8.0 RC3.2 Native Runtime Reconstruction.
"""

import sys
import json
import os
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from scripts.deploy_workflows import deploy_and_validate_workflows

WORKFLOWS_DIR = SYSTEM_ROOT / "workflows"
LAUNCHER_FILE = SYSTEM_ROOT / "launcher" / "Start_MiniMax_H3_Architect.bat"
# PATCH2.8-G: internal docs moved to docs/internal_archive/ (not public release).
REPORT_DOC = SYSTEM_ROOT / "docs" / "internal_archive" / "V0.8.0_RC3.2_Runtime_Reconstruction_Report.md"

FROZEN_WORKFLOW_FILES = [
    "01_Exterior_Hero.json",
    "02_Day_Night_Transition.json",
    "03_Material_Detail.json",
    "04_Drone_Aerial.json",
    "05_Slow_Walkthrough.json"
]

FORBIDDEN_PREFIXES = ["RHMiniMaxH3", "RunningHub"]

class TestV080RC32NativeReconstruction(unittest.TestCase):
    def test_zero_runninghub_nodes_in_all_workflows(self):
        for wf_file in FROZEN_WORKFLOW_FILES:
            p = WORKFLOWS_DIR / wf_file
            self.assertTrue(p.is_file())
            with open(p, "r", encoding="utf-8") as f:
                wf_json = json.load(f)

            nodes = wf_json.get("nodes", [])
            node_types = [n.get("type", "") for n in nodes]

            rh_nodes = [t for t in node_types if any(pref.lower() in t.lower() for pref in FORBIDDEN_PREFIXES)]
            self.assertEqual(len(rh_nodes), 0, f"Workflow {wf_file} contains forbidden RunningHub nodes: {rh_nodes}")

    def test_native_nodes_present(self):
        for wf_file in FROZEN_WORKFLOW_FILES:
            p = WORKFLOWS_DIR / wf_file
            with open(p, "r", encoding="utf-8") as f:
                wf_json = json.load(f)

            nodes = wf_json.get("nodes", [])
            node_types = [n.get("type", "") for n in nodes]

            self.assertIn("UNETLoader", node_types)
            self.assertIn("CLIPLoader", node_types)
            self.assertIn("VAELoader", node_types)
            self.assertIn("KSampler", node_types)

    @unittest.skipUnless(os.environ.get("H3_RUN_EXTERNAL_INTEGRATION_TESTS") == "1",
                         "historical external-machine deployer test is opt-in")
    def test_deployer_verifies_zero_runninghub_nodes(self):
        res = deploy_and_validate_workflows()
        self.assertEqual(res["status"], "PASS")
        self.assertTrue(res["zero_runninghub_nodes_verified"])

    def test_launcher_contains_health_polling(self):
        self.assertTrue(LAUNCHER_FILE.is_file())
        with open(LAUNCHER_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("system_stats", content)
        self.assertIn("FFmpeg", content)

    def test_report_exists(self):
        self.assertTrue(REPORT_DOC.is_file())

if __name__ == "__main__":
    unittest.main()
