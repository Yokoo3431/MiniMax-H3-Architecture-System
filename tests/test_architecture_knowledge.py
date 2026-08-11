"""Unit test for Architectural Knowledge Base.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_prompt.knowledge_mapper import KnowledgeMapper

class TestArchitectureKnowledge(unittest.TestCase):
    def setUp(self):
        self.mapper = KnowledgeMapper()

    def test_knowledge_mapping_courtyard(self):
        text = "半围合庭院画廊效果图"
        res = self.mapper.map_text_to_keywords(text)
        self.assertIn("mapped_keywords", res)
        self.assertGreater(res["concept_count"], 0)
        self.assertTrue(any("courtyard" in k.lower() or "daylight" in k.lower() for k in res["mapped_keywords"]))

    def test_knowledge_mapping_concrete(self):
        text = "清水混凝土立面"
        res = self.mapper.map_text_to_keywords(text)
        self.assertTrue(any("concrete" in k.lower() for k in res["mapped_keywords"]))

if __name__ == "__main__":
    unittest.main()
