"""Unit test for Comparison Engine.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.critic.comparison_engine import ComparisonEngine

class TestComparisonEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ComparisonEngine()

    def test_compare_generations_improved(self):
        init = {"overall_score": 82.0, "dimensions": {"geometry_consistency": 80.0}}
        final = {"overall_score": 90.0, "dimensions": {"geometry_consistency": 88.0}}
        res = self.engine.compare_generations(init, final)
        self.assertEqual(res["before"], 82.0)
        self.assertEqual(res["after"], 90.0)
        self.assertEqual(res["delta"], "+8.0")
        self.assertEqual(res["status"], "improved")

if __name__ == "__main__":
    unittest.main()
