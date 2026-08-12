"""Unit test for Architecture Image Analyzer.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_vision.image_analyzer import ArchitectureImageAnalyzer

class TestImageAnalysis(unittest.TestCase):
    def setUp(self):
        self.analyzer = ArchitectureImageAnalyzer()

    def test_analyze_image_concrete_museum(self):
        res = self.analyzer.analyze_image("modern_concrete_museum.png", prompt_hint="安藤风格混凝土美术馆黄昏推进")
        self.assertEqual(res["type"], "museum")
        self.assertEqual(res["style"], "minimal_concrete_architecture")
        self.assertIn("fair-faced_concrete", res["material"])

    def test_analyze_image_timber_villa(self):
        res = self.analyzer.analyze_image("timber_villa.jpg", prompt_hint="北欧木质别墅庭院漫游")
        self.assertEqual(res["type"], "villa")
        self.assertEqual(res["style"], "nordic_timber_architecture")

if __name__ == "__main__":
    unittest.main()
