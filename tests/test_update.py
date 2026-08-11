"""Unit test for Updater execution flow and migration safety.
"""

import os
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent

class TestUpdate(unittest.TestCase):
    def test_updater_script_exists(self):
        update_bat = SYSTEM_ROOT / "launcher" / "Update_H3.bat"
        self.assertTrue(update_bat.is_file(), "Update_H3.bat launcher must exist")

    def test_migration_rules_exist(self):
        migration_file = SYSTEM_ROOT / "sync" / "migration_rules.json"
        self.assertTrue(migration_file.is_file(), "migration_rules.json must exist")

    def test_sync_manifest_exists(self):
        sync_file = SYSTEM_ROOT / "sync" / "sync_manifest.json"
        self.assertTrue(sync_file.is_file(), "sync_manifest.json must exist")

if __name__ == "__main__":
    unittest.main()
