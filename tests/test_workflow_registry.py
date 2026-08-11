"""Unit test for Workflow Registry Schema & Categorization.
"""

import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent

class TestWorkflowRegistry(unittest.TestCase):
    def test_workflow_registry_schema(self):
        reg_file = SYSTEM_ROOT / "configs" / "workflow_registry.json"
        self.assertTrue(reg_file.is_file(), "workflow_registry.json must exist")

        with open(reg_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("categories", data, "workflow_registry.json must contain categories")
        categories = data["categories"]
        self.assertIn("architecture_visualization", categories)
        self.assertIn("architecture_analysis", categories)

    def test_workflow_files_exist(self):
        workflows_dir = SYSTEM_ROOT / "workflows"
        self.assertTrue(workflows_dir.is_dir())
        json_files = list(workflows_dir.glob("*.json"))
        self.assertGreaterEqual(len(json_files), 3, "Must contain at least 3 production workflow JSONs")

if __name__ == "__main__":
    unittest.main()
