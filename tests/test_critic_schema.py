"""Unit test for Critic Schema.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.critic.critic_schema import CriticScore, CriticIssue, Recommendation, CriticResult

class TestCriticSchema(unittest.TestCase):
    def test_critic_score_dict(self):
        score = CriticScore(overall_score=92.0)
        d = score.to_dict()
        self.assertEqual(d["overall_score"], 92.0)
        self.assertIn("dimensions", d)

    def test_critic_result_serialization(self):
        result = CriticResult(
            score=CriticScore(overall_score=90.0),
            issues=[CriticIssue(category="geometry_failure", severity="medium")],
            recommendations=[Recommendation(action="increase geometry lock", target="prompt_rule")]
        )
        d = result.to_dict()
        self.assertEqual(d["overall_score"], 90.0)
        self.assertEqual(len(d["issues"]), 1)
        self.assertEqual(d["issues"][0]["category"], "geometry_failure")
        self.assertEqual(d["recommendations"][0]["action"], "increase geometry lock")

if __name__ == "__main__":
    unittest.main()
