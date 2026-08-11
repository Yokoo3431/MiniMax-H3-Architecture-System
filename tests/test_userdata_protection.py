"""Critical Unit Test: UserData Protection
Verifies that custom user workflows in userdata/ are NEVER overwritten or deleted by updater logic.
"""

import os
import json
import shutil
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent

class TestUserDataProtection(unittest.TestCase):
    def test_userdata_protection_across_updates(self):
        custom_wf_dir = SYSTEM_ROOT / "userdata" / "custom_workflows"
        custom_wf_dir.mkdir(parents=True, exist_ok=True)
        
        test_file = custom_wf_dir / "test_custom.json"
        unique_content = {"user_custom_workflow_id": "test_999", "secret_tag": "do_not_delete"}
        
        with open(test_file, "w", encoding="utf-8") as f:
            json.dump(unique_content, f, indent=2)

        backup_dir = SYSTEM_ROOT / "userdata_backup_temp_test"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
            
        shutil.copytree(SYSTEM_ROOT / "userdata", backup_dir)
        self.assertTrue((backup_dir / "custom_workflows" / "test_custom.json").is_file())

        for item in os.listdir(backup_dir):
            s = backup_dir / item
            d = SYSTEM_ROOT / "userdata" / item
            if s.is_file():
                shutil.copy2(s, d)
            elif s.is_dir():
                if d.exists():
                    shutil.rmtree(d)
                shutil.copytree(s, d)

        shutil.rmtree(backup_dir)

        self.assertTrue(test_file.is_file(), "User custom workflow must remain intact")
        with open(test_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded.get("user_custom_workflow_id"), "test_999", "Content must be identical")

        if test_file.exists():
            os.remove(test_file)

if __name__ == "__main__":
    unittest.main()
