"""Unit test for End-to-End Agent Video Generation API (V0.7.5 Upgraded).
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
            task="制作安藤混凝土美术馆黄昏推进动画"
        )
        self.assertIn(res["status"], ["completed", "error"])
        self.assertIn("video_path", res)
        self.assertEqual(res["workflow"], "3_night_transition")
        self.assertGreaterEqual(res["prompt_score"], 85.0)
        self.assertIn("acceleration_profile", res)
        self.assertIn("model_package", res)
        self.assertIn("vision_analysis", res)
        self.assertIn("architectural_intent", res)

if __name__ == "__main__":
    unittest.main()
