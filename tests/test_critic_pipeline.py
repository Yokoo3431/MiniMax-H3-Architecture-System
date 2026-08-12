"""Unit test for Critic Pipeline & Orchestrator Integration.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.critic.critic_pipeline import CriticPipeline
from runtime.h3_orchestrator import H3Orchestrator

class TestCriticPipeline(unittest.TestCase):
    def setUp(self):
        self.pipeline = CriticPipeline()
        self.orchestrator = H3Orchestrator()

    def test_run_critic_pipeline(self):
        res = self.pipeline.run_critic_pipeline(
            video_path="userdata/outputs/test.mp4",
            original_image="museum.jpg",
            task="安藤风格混凝土美术馆黄昏推进动画"
        )
        self.assertIn("critic_result", res)
        self.assertIn("revision_strategy", res)
        self.assertIn("memory_feedback", res)
        self.assertGreaterEqual(res["critic_result"]["overall_score"], 60.0)

    def test_orchestrator_critic_api(self):
        res = self.orchestrator.critic_generation_result(
            video_path="userdata/outputs/test.mp4",
            original_image="museum.jpg",
            task="安藤风格混凝土美术馆黄昏推进动画"
        )
        self.assertIn("overall_score", res)
        self.assertIn("dimensions", res)
        self.assertIn("issues", res)
        self.assertIn("recommendations", res)

if __name__ == "__main__":
    unittest.main()
