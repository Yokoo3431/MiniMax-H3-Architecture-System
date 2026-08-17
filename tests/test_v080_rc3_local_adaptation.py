"""Unit test suite for V0.8.0 RC3 Local Production Workflow Adaptation.
"""

import sys
import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.validation.rc3_environment_checker import RC3EnvironmentChecker
from runtime.prompt_bridge.official_h3_prompt_adapter import OfficialH3PromptAdapter

WORKFLOWS_DIR = SYSTEM_ROOT / "workflows"
RC3_CHECKER = RC3EnvironmentChecker()

FROZEN_WORKFLOW_FILES = [
    "01_Exterior_Hero.json",
    "02_Day_Night_Transition.json",
    "03_Material_Detail.json",
    "04_Drone_Aerial.json",
    "05_Slow_Walkthrough.json"
]

class TestV080RC3LocalAdaptation(unittest.TestCase):
    def setUp(self):
        self.prompt_adapter = OfficialH3PromptAdapter()

    def test_five_real_workflows_exist_and_valid_json(self):
        for wf_file in FROZEN_WORKFLOW_FILES:
            p = WORKFLOWS_DIR / wf_file
            self.assertTrue(p.is_file(), f"{wf_file} must exist in workflows/")
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("nodes", data)
            self.assertIn("links", data)

    def test_environment_checker_status(self):
        res = RC3_CHECKER.check_rc3_environment()
        self.assertEqual(res["system_status"], "READY")
        self.assertEqual(res["hardware_checks"]["status"], "PASS")
        self.assertEqual(res["model_paths_checks"]["status"], "PASS")

    def test_chinese_prompt_bridge_adaptation(self):
        res = self.prompt_adapter.adapt_prompt("生成建筑鸟瞰宣传视频，保持建筑体量，缓慢无人机环绕，黄昏光线", "04_Drone_Aerial")
        self.assertIn("high altitude drone orbit", res["structured_elements"]["camera"])
        self.assertIn("positive_prompt", res)

    def test_rc3_docs_exist(self):
        # PATCH2.8-G: internal docs moved to docs/internal_archive/ (not public release).
        self.assertTrue((SYSTEM_ROOT / "docs" / "internal_archive" / "Architect_RC3_Test_Guide.md").is_file())
        self.assertTrue((SYSTEM_ROOT / "docs" / "internal_archive" / "V0.8.0_RC3_Adaptation_Report.md").is_file())

if __name__ == "__main__":
    unittest.main()
