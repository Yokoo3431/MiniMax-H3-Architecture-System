"""Unit test for Revision Executor.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.feedback_loop.revision_executor import RevisionExecutor

class TestRevisionExecutor(unittest.TestCase):
    def setUp(self):
        self.executor = RevisionExecutor()

    def test_execute_revision(self):
        critic_res = {
            "critic_result": {
                "issues": [{"category": "geometry_failure", "severity": "high"}],
                "recommendations": [{"action": "increase geometry_lock weight", "target": "prompt_rule"}]
            }
        }
        res = self.executor.execute_revision(
            positive_prompt="Architectural rendering of villa",
            negative_prompt="warped facade",
            base_params={"steps": 25},
            critic_result=critic_res
        )
        self.assertIn("positive_prompt", res)
        self.assertIn("revised_parameters", res)
        self.assertEqual(res["revised_parameters"]["geometry_preservation_weight"], 1.2)

if __name__ == "__main__":
    unittest.main()
