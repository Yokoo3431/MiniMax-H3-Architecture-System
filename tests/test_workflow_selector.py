"""Unit test for Workflow Intelligence Selector Engine.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.workflow_intelligence.workflow_selector import WorkflowIntelligenceSelector

class TestWorkflowSelector(unittest.TestCase):
    def setUp(self):
        self.selector = WorkflowIntelligenceSelector()

    def test_select_twilight_walkthrough(self):
        pkg = self.selector.select_intelligence_workflow("night_transition", "把现代博物馆效果图制作成黄昏慢推进动画")
        self.assertEqual(pkg.workflow_id, "3_night_transition")
        self.assertEqual(pkg.preset_id, "day_night_transition")
        self.assertEqual(pkg.duration_seconds, 5.0)

    def test_select_aerial_drone(self):
        pkg = self.selector.select_intelligence_workflow("aerial", "园区鸟瞰航拍动画")
        self.assertEqual(pkg.workflow_id, "2_aerial_view")
        self.assertEqual(pkg.preset_id, "aerial_drone")

if __name__ == "__main__":
    unittest.main()
