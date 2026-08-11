"""Unit test for Architecture Memory Schema.
"""

import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = SYSTEM_ROOT / "configs" / "architecture_memory_schema.json"
MEMORY_FILE = SYSTEM_ROOT / "configs" / "architecture_memory.json"

class TestMemorySchema(unittest.TestCase):
    def test_memory_schema_file_exists(self):
        self.assertTrue(SCHEMA_FILE.is_file(), "architecture_memory_schema.json must exist")
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("properties", data)
        self.assertIn("project_info", data["properties"])

    def test_memory_database_file_exists(self):
        self.assertTrue(MEMORY_FILE.is_file(), "architecture_memory.json must exist")
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            db = json.load(f)
        self.assertIn("cases", db)
        self.assertGreater(len(db["cases"]), 0)

if __name__ == "__main__":
    unittest.main()
