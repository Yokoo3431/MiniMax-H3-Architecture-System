"""Unit test for Prompt Quality Evaluator.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.prompt_quality import PromptQualityEvaluator

class TestPromptQuality(unittest.TestCase):
    def setUp(self):
        self.evaluator = PromptQualityEvaluator()

    def test_quality_evaluation_high_score(self):
        pos_prompt = "Architectural visualization of museum, slow push in shot with 35mm lens, twilight dusk illumination, warm 3500K interior glow, pristine glass facade, preserve building geometry integrity"
        intent_dict = {
            "building_type": "museum",
            "camera": {"movement": "slow_push"},
            "lighting": {"time": "twilight_dusk"}
        }
        res = self.evaluator.evaluate(pos_prompt, intent_dict)
        self.assertGreaterEqual(res["quality_score"], 85)
        self.assertEqual(res["status"], "EXCELLENT")
        self.assertIn("scores", res)
        self.assertIn("architectural_accuracy", res["scores"])

    def test_quality_evaluation_missing_fields(self):
        pos_prompt = "simple rendering animation"
        intent_dict = {}
        res = self.evaluator.evaluate(pos_prompt, intent_dict)
        self.assertLessEqual(res["quality_score"], 75.0)
        self.assertGreater(len(res["missing"]), 0)

if __name__ == "__main__":
    unittest.main()
