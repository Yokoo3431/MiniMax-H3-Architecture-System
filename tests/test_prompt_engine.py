"""Unit test for Architecture Prompt Engine.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_prompt.prompt_engine import ArchitecturePromptEngine

class TestPromptEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ArchitecturePromptEngine()

    def test_prompt_generation_visualization(self):
        text = "把这个博物馆效果图制作成黄昏动画，保持建筑体量不变，镜头缓慢推进，室内增加暖光"
        res = self.engine.process_request(text)

        self.assertIn("intent_schema", res)
        self.assertIn("positive_prompt", res)
        self.assertIn("negative_prompt", res)
        self.assertEqual(res["recommended_workflow"], "3_night_transition")
        self.assertTrue("museum" in res["positive_prompt"].lower())
        self.assertTrue("warped" in res["negative_prompt"].lower())

    def test_prompt_generation_analysis(self):
        text = "展示建筑体块生成与演变过程动画"
        res = self.engine.process_request(text)

        self.assertEqual(res["recommended_workflow"], "6_massing_evolution")
        self.assertEqual(res["intent_schema"]["task_type"], "architecture_analysis")

if __name__ == "__main__":
    unittest.main()
