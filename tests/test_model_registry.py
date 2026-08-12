"""Unit test for Model Ecosystem Registry.
"""

import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = SYSTEM_ROOT / "configs" / "model_registry.json"

class TestModelRegistry(unittest.TestCase):
    def test_model_registry_file_exists(self):
        self.assertTrue(REGISTRY_FILE.is_file(), "model_registry.json must exist")
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("models", data)
        self.assertIn("architecture_styles", data)
        self.assertIn("minimal_concrete", data["architecture_styles"])

if __name__ == "__main__":
    unittest.main()
