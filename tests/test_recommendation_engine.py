"""Unit test for Recommendation Engine.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.critic.critic_schema import CriticIssue
from runtime.critic.recommendation_engine import RecommendationEngine

class TestRecommendationEngine(unittest.TestCase):
    def setUp(self):
        self.recommender = RecommendationEngine()

    def test_generate_geometry_recommendation(self):
        issues = [CriticIssue(category="geometry_failure", severity="high")]
        recs = self.recommender.generate_recommendations(issues)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].target, "prompt_rule")
        self.assertIn("geometry_lock", recs[0].action)

if __name__ == "__main__":
    unittest.main()
