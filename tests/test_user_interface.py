"""Unit test for User Video Presets & Web UI App functions.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from interface.web.app import load_user_presets, run_architect_pipeline

class TestUserInterface(unittest.TestCase):
    def test_load_user_presets(self):
        presets = load_user_presets()
        self.assertIn("exterior_hero", presets)
        self.assertIn("slow_walkthrough", presets)
        self.assertIn("drone_aerial", presets)

    def test_run_architect_pipeline_web_function(self):
        res = run_architect_pipeline(["museum.jpg"], "制作黄昏建筑动画", "exterior_hero", "H3_STANDARD")
        self.assertIn("status", res)
        self.assertIn("video_path", res)
        self.assertIn("selected_workflow", res)

if __name__ == "__main__":
    unittest.main()
