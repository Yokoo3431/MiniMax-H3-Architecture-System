"""Unit test for Closed Loop Pipeline Integration via H3Orchestrator.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.h3_orchestrator import H3Orchestrator

class TestClosedLoopPipeline(unittest.TestCase):
    def setUp(self):
        self.orchestrator = H3Orchestrator()

    def test_run_feedback_loop_api(self):
        res = self.orchestrator.run_feedback_loop(
            image="museum.jpg",
            task="安藤混凝土美术馆黄昏推进动画",
            max_iterations=2
        )
        self.assertIn("iterations", res)
        self.assertLessEqual(res["iterations"], 2)
        self.assertIn("initial_score", res)
        self.assertIn("final_score", res)
        self.assertIn("improvement", res)
        self.assertIn("status", res)
        self.assertIn("successful_strategy", res)

if __name__ == "__main__":
    unittest.main()
