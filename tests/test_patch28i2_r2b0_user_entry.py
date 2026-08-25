"""PATCH2.8-I2-R2B0 user-entry and Setup GUI acceptance contracts.

These tests are deliberately CPU/API-only. They never start ComfyUI and never
submit a generation request.
"""

from __future__ import annotations

import json
import os
import subprocess
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
ROOT_BAT = SYSTEM_ROOT / "Start_ArchitectVideoStudio.bat"
ADV_BAT = SYSTEM_ROOT / "Open_Native_ComfyUI.bat"


class TestUserEntryContracts(unittest.TestCase):
    def test_root_bat_exists_and_resolves_own_directory(self):
        text = ROOT_BAT.read_text(encoding="utf-8", errors="ignore")
        self.assertTrue(ROOT_BAT.is_file())
        self.assertIn("%~dp0", text)
        self.assertIn("launcher\\launcher.py", text)
        self.assertNotIn("D:\\ProgramFilesNormal", text)
        self.assertNotIn("D:\\AntigravityWorkspace", text)

    def test_advanced_bat_is_path_independent(self):
        text = ADV_BAT.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("%~dp0", text)
        self.assertIn("launcher.py\" native", text)
        self.assertIn("Native Runtime is not configured", text)
        self.assertNotIn("D:\\ProgramFilesNormal", text)

    def test_setup_mode_does_not_require_comfyui(self):
        text = (SYSTEM_ROOT / "launcher" / "launcher.py").read_text(encoding="utf-8")
        manager = (SYSTEM_ROOT / "launcher" / "process_manager.py").read_text(encoding="utf-8")
        self.assertIn("start_studio(setup_mode=True)", text)
        self.assertIn('"--runtime", runtime', manager)
        self.assertIn('"mock" if setup_mode else "real"', manager)

    def test_health_endpoint_contract_and_setup_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "studio-data"
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            command = [sys.executable, str(SYSTEM_ROOT / "apps" / "architect_video_studio" / "run_prototype.py"),
                       "--runtime", "mock", "--port", str(port), "--data", str(data)]
            env = os.environ.copy()
            env["H3_NATIVE_ROOT"] = str(Path(tmp) / "missing-native")
            proc = subprocess.Popen(command, cwd=SYSTEM_ROOT, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 15
                payload = None
                while time.time() < deadline:
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                            payload = json.loads(response.read().decode("utf-8"))
                            break
                    except Exception:
                        time.sleep(0.1)
                self.assertIsNotNone(payload)
                self.assertEqual(payload["data"], {"status": "ok", "mode": "setup"})
                with urlopen(f"http://127.0.0.1:{port}/setup.html", timeout=2) as response:
                    self.assertEqual(response.status, 200)
            finally:
                proc.terminate()
                proc.wait(timeout=10)

    def test_setup_page_has_real_actions_and_no_fake_action_contract(self):
        html = (SYSTEM_ROOT / "apps" / "architect_video_studio" / "frontend" / "setup.html").read_text(encoding="utf-8")
        js = (SYSTEM_ROOT / "apps" / "architect_video_studio" / "frontend" / "js" / "setup.js").read_text(encoding="utf-8")
        for token in ("SYSTEM", "NATIVE RUNTIME", "MODELS", "PROMPT", "WORKFLOWS", "ADVANCED",
                      "Install Native Runtime", "Use Existing Runtime", "Use Existing Models",
                      "Install H3 Support Layer", "Install Video Support", "Install Required Models",
                      "Re-check Environment", "Continue to Studio"):
            self.assertIn(token, html)
        for token in ("/api/system/environment", "/api/system/configure", "/api/system/recheck",
                      "/api/system/install", "/api/system/install-plan", "startComponents"):
            self.assertIn(token, js)
        self.assertIn("/api/health", (SYSTEM_ROOT / "apps" / "architect_video_studio" / "mock_api" / "server.py").read_text(encoding="utf-8"))

    def test_no_global_environment_mutation_or_c_drive_regression(self):
        for path in (ROOT_BAT, ADV_BAT,
                     SYSTEM_ROOT / "launcher" / "process_manager.py",
                     SYSTEM_ROOT / "runtime" / "storage_policy.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("setx ", text.lower())
            self.assertNotIn("C:\\Users\\", text)
        self.assertIn("process_environment", (SYSTEM_ROOT / "launcher" / "process_manager.py").read_text(encoding="utf-8"))

    def test_production_ui_and_workflow_surfaces_are_untouched(self):
        for name in ("workspace.html", "index.html"):
            self.assertTrue((SYSTEM_ROOT / "apps" / "architect_video_studio" / "frontend" / name).is_file())
        registry = json.loads((SYSTEM_ROOT / "configs" / "rc34_patch27c2b_workflow_registry_validation.json").read_text(encoding="utf-8"))
        self.assertEqual(len(registry["workflows"]), 5)


if __name__ == "__main__":
    unittest.main()
