"""Unit test for Intent Parser Reasoning Extraction.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_prompt.intent_parser import IntentParser

class TestIntentReasoning(unittest.TestCase):
    def setUp(self):
        self.parser = IntentParser()

    def test_intent_reasoning_minimalism(self):
        text = "日式极简清水混凝土静谧大堂"
        intent = self.parser.parse(text)
        self.assertEqual(intent.reasoning.design_language, "minimalism")
        self.assertEqual(intent.reasoning.spatial_character, "quiet")
        self.assertEqual(intent.reasoning.emotional_target, "poetic")

    def test_intent_reasoning_brutalism(self):
        text = "粗野主义重型展厅"
        intent = self.parser.parse(text)
        self.assertEqual(intent.reasoning.design_language, "brutalism")
        self.assertEqual(intent.reasoning.spatial_character, "monumental")

if __name__ == "__main__":
    unittest.main()
