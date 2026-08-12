"""Unit test for Architecture Visual Schema.
"""

import json
import unittest
from pathlib import Path
from skills.architecture_vision.vision_schema import ArchitectureVisualAnalysis

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = SYSTEM_ROOT / "configs" / "architecture_visual_schema.json"

class TestVisionSchema(unittest.TestCase):
    def test_schema_file_exists(self):
        self.assertTrue(SCHEMA_FILE.is_file(), "architecture_visual_schema.json must exist")
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("properties", data)
        self.assertIn("building_type", data["properties"])

    def test_visual_analysis_dataclass(self):
        analysis = ArchitectureVisualAnalysis(
            building_type="museum",
            architectural_style="minimal_concrete_architecture"
        )
        d = analysis.to_dict()
        self.assertEqual(d["type"], "museum")
        self.assertEqual(d["style"], "minimal_concrete_architecture")

if __name__ == "__main__":
    unittest.main()
