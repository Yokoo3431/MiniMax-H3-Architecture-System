"""Unit test for Plugin Discovery & Manifest Schema Validation.
"""

import json
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent

class TestPluginLoading(unittest.TestCase):
    def test_plugin_discovery_and_schema(self):
        plugins_dir = SYSTEM_ROOT / "plugins"
        self.assertTrue(plugins_dir.is_dir(), "plugins/ directory must exist")

        found_plugins = 0
        for child in plugins_dir.iterdir():
            if child.is_dir():
                plugin_json = child / "plugin.json"
                if plugin_json.is_file():
                    found_plugins += 1
                    with open(plugin_json, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.assertIn("plugin_id", data, f"Plugin {child.name} missing plugin_id")
                    self.assertIn("name", data, f"Plugin {child.name} missing name")
                    self.assertIn("version", data, f"Plugin {child.name} missing version")

        self.assertGreaterEqual(found_plugins, 2, "Must discover at least 2 default plugin bundles")

if __name__ == "__main__":
    unittest.main()
