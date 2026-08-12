"""Unit test for End-to-End Agent Video Generation API.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.h3_orchestrator import H3Orchestrator

class TestAgentVideoGeneration(unittest.TestCase):
    def setUp(self):
        self.orchestrator = H3Orchestrator()

    def test_generate_architecture_video_api(self):
        res = self.orchestrator.generate_architecture_video(
            image="museum.png",
            task="把这个安藤风格混凝土美术馆效果图制作成黄昏推进动画"
        )
        self.assertEqual(res["status"], "completed")
        self.assertIn("video_path", res)
        self.assertEqual(res["workflow"], "3_night_transition")
        self.assertGreaterEqual(res["prompt_score"], 85.0)
        self.assertIn("execution_package", res)
        self.assertIn("vision_analysis", res)

if __name__ == "__main__":
    unittest.main()
