"""Unit test suite for V0.8.0 RC2 Architect Daily Usage Layer.
"""

import sys
import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.prompt_bridge.workspace_manager import initialize_personal_workspace
from runtime.prompt_bridge.official_h3_prompt_adapter import OfficialH3PromptAdapter

TEST_WORKSPACE = SYSTEM_ROOT / "tests" / "personal_workspace"
LAUNCHER_FILE = SYSTEM_ROOT / "launcher" / "Start_MiniMax_H3_Architect.bat"
CATALOG_FILE = SYSTEM_ROOT / "configs" / "workflow_catalog.json"
QUICK_START_DOC = SYSTEM_ROOT / "docs" / "Architect_Quick_Start.md"
REPORT_DOC = SYSTEM_ROOT / "docs" / "V0.8.0_RC2_Architect_Daily_Usage_Report.md"

class TestArchitectDailyUsage(unittest.TestCase):
    def setUp(self):
        self.prompt_adapter = OfficialH3PromptAdapter()

    def test_personal_workspace_initialization(self):
        res = initialize_personal_workspace(TEST_WORKSPACE)
        self.assertEqual(res["status"], "initialized")
        self.assertTrue((TEST_WORKSPACE / "input_images").is_dir())
        self.assertTrue((TEST_WORKSPACE / "generated_prompts").is_dir())
        self.assertTrue((TEST_WORKSPACE / "outputs").is_dir())

    def test_launcher_bat_exists(self):
        self.assertTrue(LAUNCHER_FILE.is_file(), "Start_MiniMax_H3_Architect.bat must exist")

    def test_workflow_catalog_exists(self):
        self.assertTrue(CATALOG_FILE.is_file(), "workflow_catalog.json must exist")
        with open(CATALOG_FILE, "r", encoding="utf-8") as f:
            cat = json.load(f)
        self.assertEqual(cat["total_workflows"], 5)
        self.assertIn("01_Exterior_Hero", cat["workflows"])

    def test_official_h3_prompt_adapter(self):
        res = self.prompt_adapter.adapt_prompt("制作黄昏慢推进动画", "01_Exterior_Hero")
        self.assertIn("positive_prompt", res)
        self.assertIn("slow cinematic push-in", res["structured_elements"]["camera"])

    def test_documentation_exists(self):
        self.assertTrue(QUICK_START_DOC.is_file(), "Architect_Quick_Start.md must exist")
        self.assertTrue(REPORT_DOC.is_file(), "V0.8.0_RC2_Architect_Daily_Usage_Report.md must exist")

if __name__ == "__main__":
    unittest.main()
