"""Unit test for Installation Launcher and environment structure.
"""

import os
import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent

class TestInstall(unittest.TestCase):
    def test_launcher_installer_structure(self):
        install_bat = SYSTEM_ROOT / "launcher" / "Install_H3.bat"
        self.assertTrue(install_bat.is_file(), "Install_H3.bat launcher must exist")

    def test_required_directories_exist(self):
        required_dirs = ["core", "configs", "hardware", "launcher", "models", "plugins", "prompts", "runtime", "scripts", "skills", "sync", "userdata", "workflows"]
        for d in required_dirs:
            dir_path = SYSTEM_ROOT / d
            self.assertTrue(dir_path.is_dir(), f"Required directory '{d}' must exist")

    def test_system_config_exists(self):
        cfg_file = SYSTEM_ROOT / "configs" / "system_config.json"
        self.assertTrue(cfg_file.is_file(), "system_config.json must exist")

if __name__ == "__main__":
    unittest.main()
