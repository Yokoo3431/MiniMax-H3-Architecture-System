"""Unit test for Quality Improvement Generator.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.prompt_quality import PromptQualityEvaluator

class TestPromptImprovement(unittest.TestCase):
    def setUp(self):
        self.evaluator = PromptQualityEvaluator()

    def test_improvement_generator_output(self):
        score = 75.0
        missing = ["material texture detail", "camera trajectory/lens description"]
        res = self.evaluator.improvement_generator(score, missing)

        self.assertIn("score", res)
        self.assertIn("issues", res)
        self.assertIn("suggestions", res)
        self.assertEqual(len(res["issues"]), 2)
        self.assertTrue(any("material" in i for i in res["issues"]))

if __name__ == "__main__":
    unittest.main()
