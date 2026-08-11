"""Unit test for Semantic Memory Retrieval Engine.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_prompt.memory_retriever import MemoryRetriever

class TestMemoryRetrieval(unittest.TestCase):
    def setUp(self):
        self.retriever = MemoryRetriever()

    def test_retrieve_similar_case_museum(self):
        text = "安藤风格混凝土美术馆黄昏动画"
        case_data = self.retriever.retrieve_similar_case(text)
        self.assertIn("project_info", case_data)
        self.assertEqual(case_data["project_info"]["building_type"], "museum")

    def test_suggest_prompt_strategy(self):
        text = "安藤风格混凝土美术馆黄昏动画"
        strategy = self.retriever.suggest_prompt_strategy(text)
        self.assertIn("recommended_camera", strategy)
        self.assertIn("recommended_light", strategy)
        self.assertIn("avoid", strategy)
        self.assertEqual(strategy["avoid"], "dramatic fast cinematic motion")

if __name__ == "__main__":
    unittest.main()
