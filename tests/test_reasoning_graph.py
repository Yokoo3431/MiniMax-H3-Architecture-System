"""Unit test for Architecture Reasoning Graph.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_prompt.reasoning_engine import ArchitectureReasoningEngine

class TestReasoningGraph(unittest.TestCase):
    def setUp(self):
        self.engine = ArchitectureReasoningEngine()

    def test_reasoning_ando_concrete(self):
        text = "安藤风格清水混凝土艺术中心"
        res = self.engine.reason_about_text(text)
        self.assertIn("matched_reasoning_nodes", res)
        self.assertTrue(len(res["matched_reasoning_nodes"]) > 0)
        self.assertTrue(any("concrete" in p.lower() for p in res["reasoning_prompts"]))

    def test_reasoning_brutalism(self):
        text = "野兽派粗野建筑雕塑"
        res = self.engine.reason_about_text(text)
        self.assertTrue(any("brutalist" in p.lower() for p in res["reasoning_prompts"]))

if __name__ == "__main__":
    unittest.main()
