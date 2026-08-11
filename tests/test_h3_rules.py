"""Unit test for MiniMax H3 Prompt Rule Engine.
"""

import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = SYSTEM_ROOT / "skills" / "architecture_prompt" / "h3_rules"

class TestH3Rules(unittest.TestCase):
    def test_h3_rules_files_exist(self):
        self.assertTrue(RULES_DIR.is_dir(), "h3_rules directory must exist")
        required_rules = [
            "geometry_lock.yaml",
            "camera_motion.yaml",
            "lighting_transition.yaml",
            "architectural_material.yaml",
            "negative_prompt.yaml"
        ]
        for r in required_rules:
            self.assertTrue((RULES_DIR / r).is_file(), f"Rule file {r} must exist")

if __name__ == "__main__":
    unittest.main()
