"""Unit test for Intent Parser.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_prompt.intent_parser import IntentParser

class TestIntentParser(unittest.TestCase):
    def setUp(self):
        self.parser = IntentParser()

    def test_parse_night_transition(self):
        text = "把建筑白天效果图转换成黄昏"
        intent = self.parser.parse(text)
        self.assertEqual(intent.scene_type, "night_transition")
        self.assertEqual(intent.lighting.time, "twilight_dusk")

    def test_parse_massing_evolution(self):
        text = "展示建筑体块生成过程"
        intent = self.parser.parse(text)
        self.assertEqual(intent.task_type, "architecture_analysis")
        self.assertEqual(intent.scene_type, "massing_evolution")

    def test_parse_aerial_drone(self):
        text = "生成建筑鸟瞰环绕动画"
        intent = self.parser.parse(text)
        self.assertEqual(intent.scene_type, "aerial")
        self.assertEqual(intent.camera.movement, "high_altitude_drone")

if __name__ == "__main__":
    unittest.main()
