"""Unit test for Feedback Controller & Max Iterations Safety Bound.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.feedback_loop.feedback_controller import FeedbackController
from runtime.h3_orchestrator import H3Orchestrator

class TestFeedbackController(unittest.TestCase):
    def setUp(self):
        self.controller = FeedbackController()
        self.orchestrator = H3Orchestrator()

    def test_feedback_controller_max_iterations_bound(self):
        # Even if 10 iterations requested, controller should cap at 2
        res = self.controller.run_closed_loop(
            orchestrator=self.orchestrator,
            image="museum.jpg",
            task="安藤混凝土美术馆黄昏推进动画",
            max_iterations=10
        )
        self.assertLessEqual(res["iterations"], 2)
        self.assertIn("initial_score", res)
        self.assertIn("final_score", res)
        self.assertIn("improvement", res)

if __name__ == "__main__":
    unittest.main()
