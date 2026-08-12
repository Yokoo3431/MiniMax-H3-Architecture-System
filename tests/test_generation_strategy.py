"""Unit test for Generation Profile & Strategy Selector Engine.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.acceleration.generation_profile_selector import GenerationProfileSelector
from runtime.h3_orchestrator import H3Orchestrator

class TestGenerationStrategy(unittest.TestCase):
    def setUp(self):
        self.selector = GenerationProfileSelector()
        self.orchestrator = H3Orchestrator()

    def test_select_strategy_concrete_museum(self):
        res = self.selector.select_strategy("H3_STANDARD", "制作安藤混凝土美术馆黄昏推进动画")
        self.assertIn("acceleration_profile", res)
        self.assertIn("model_package", res)
        self.assertEqual(res["model_package"]["style_key"], "minimal_concrete")
        self.assertEqual(res["model_package"]["lighting_key"], "twilight_dusk")

    def test_orchestrator_generation_strategy_integration(self):
        res = self.orchestrator.generate_architecture_video(
            image="museum.jpg",
            task="制作安藤混凝土美术馆黄昏推进动画"
        )
        self.assertEqual(res["status"], "completed")
        self.assertIn("acceleration_profile", res)
        self.assertIn("model_package", res)
        self.assertIn("optimization_strategy", res)

if __name__ == "__main__":
    unittest.main()
