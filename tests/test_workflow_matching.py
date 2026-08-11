"""Unit test for Workflow Semantic Matching.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_prompt.prompt_engine import ArchitecturePromptEngine

class TestWorkflowMatching(unittest.TestCase):
    def setUp(self):
        self.engine = ArchitecturePromptEngine()

    def test_case_1_night_transition_matching(self):
        text = "把建筑白天效果图转换成黄昏"
        res = self.engine.process_request(text)
        self.assertEqual(res["recommended_workflow"], "3_night_transition")

    def test_case_2_massing_evolution_matching(self):
        text = "展示建筑体块生成过程"
        res = self.engine.process_request(text)
        self.assertEqual(res["recommended_workflow"], "6_massing_evolution")

    def test_case_3_aerial_view_matching(self):
        text = "生成建筑鸟瞰环绕动画"
        res = self.engine.process_request(text)
        self.assertEqual(res["recommended_workflow"], "2_aerial_view")

if __name__ == "__main__":
    unittest.main()
