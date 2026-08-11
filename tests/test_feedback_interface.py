"""Unit test for Feedback Schema & Prompt Revision Engine.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.feedback.feedback_schema import ArchitecturalCriticFeedback
from runtime.feedback.prompt_revision import PromptRevisionEngine

class TestFeedbackInterface(unittest.TestCase):
    def setUp(self):
        self.engine = PromptRevisionEngine()

    def test_prompt_revision_on_low_geometry_score(self):
        feedback = ArchitecturalCriticFeedback(
            overall_pass=False,
            geometry_score=70.0,
            material_score=90.0
        )
        pos = "Architectural visualization of villa"
        neg = "warped facade"
        rev_pos, rev_neg = self.engine.revise_prompt(pos, neg, feedback)

        self.assertIn("strict geometric lock", rev_pos)
        self.assertIn("distorted geometry", rev_neg)

if __name__ == "__main__":
    unittest.main()
