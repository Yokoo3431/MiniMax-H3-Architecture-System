"""RC3.4 PATCH2.8-I0 - Public user entry point tests.

Verifies the one-click startup entry points for the public repository:
- root launcher exists
- root launcher calls launcher.py
- no absolute developer path
- README startup path matches the actual file
- advanced ComfyUI launcher exists
- distribution includes both launchers
No GPU / ComfyUI inference / model loading.
"""

import re
import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

ROOT_BAT = SYSTEM_ROOT / "Start_ArchitectVideoStudio.bat"
ADV_BAT = SYSTEM_ROOT / "Open_Native_ComfyUI.bat"
LAUNCHER_PY = SYSTEM_ROOT / "launcher" / "launcher.py"
DIST = SYSTEM_ROOT / "distribution_test" / "ArchitectVideoStudio"


class TestPublicEntryPoints(unittest.TestCase):
    def test_root_launcher_exists(self):
        self.assertTrue(ROOT_BAT.is_file(), "Start_ArchitectVideoStudio.bat missing at repo root")

    def test_root_launcher_calls_launcher_py(self):
        text = ROOT_BAT.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("launcher.py", text)
        self.assertIn("start", text.lower())
        self.assertTrue(LAUNCHER_PY.is_file())

    def test_no_absolute_developer_path(self):
        for path in (ROOT_BAT, ADV_BAT,
                     SYSTEM_ROOT / "native_env.path.example",
                     SYSTEM_ROOT / "README.md",
                     SYSTEM_ROOT / ".gitignore"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("AntigravityWorkspace", text, path.name)
            self.assertNotIn("D:\\AntigravityWorkspace", text, path.name)

    def test_readme_startup_path_matches_actual_file(self):
        readme = (SYSTEM_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Start_ArchitectVideoStudio.bat", readme)
        # README must not point into launcher/ subdirectory for normal users.
        self.assertNotIn("launcher\\start_architect_video_studio.bat", readme)
        self.assertNotIn("launcher/start_architect_video_studio.bat", readme)

    def test_advanced_comfyui_launcher_exists(self):
        self.assertTrue(ADV_BAT.is_file())
        text = ADV_BAT.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("8189", text)
        self.assertIn("H3_WINDOWS_SAFE_LOAD=pread", text)
        readme = (SYSTEM_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Open_Native_ComfyUI.bat", readme)

    def test_distribution_includes_both_launchers(self):
        self.assertTrue((DIST / "Start_ArchitectVideoStudio.bat").is_file())
        self.assertTrue((DIST / "Open_Native_ComfyUI.bat").is_file())
        self.assertTrue((DIST / "native_env.path.example").is_file())

    def test_launcher_bat_not_excluded_by_gitignore(self):
        # The launcher/start_architect_video_studio.bat must not be ignored.
        out = __import__("subprocess").run(
            ["git", "check-ignore", "launcher/start_architect_video_studio.bat"],
            capture_output=True, text=True, cwd=SYSTEM_ROOT)
        self.assertNotEqual(out.returncode, 0,
                            "launcher/start_architect_video_studio.bat must NOT be git-ignored")
        out2 = __import__("subprocess").run(
            ["git", "check-ignore", "Start_ArchitectVideoStudio.bat"],
            capture_output=True, text=True, cwd=SYSTEM_ROOT)
        self.assertNotEqual(out2.returncode, 0,
                            "root Start_ArchitectVideoStudio.bat must NOT be git-ignored")


if __name__ == "__main__":
    unittest.main()
