"""Unit test for Architecture Video Preset Database.
"""

import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
PRESET_FILE = SYSTEM_ROOT / "configs" / "video_presets.json"

class TestVideoPreset(unittest.TestCase):
    def test_presets_exist(self):
        self.assertTrue(PRESET_FILE.is_file(), "video_presets.json must exist")
        with open(PRESET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        presets = data.get("presets", {})
        self.assertIn("exterior_hero", presets)
        self.assertIn("walkthrough", presets)
        self.assertIn("aerial_drone", presets)
        self.assertIn("day_night_transition", presets)
        self.assertIn("architecture_analysis", presets)

if __name__ == "__main__":
    unittest.main()
