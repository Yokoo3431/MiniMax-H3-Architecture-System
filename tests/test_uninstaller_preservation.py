"""Uninstaller preservation contracts using disposable synthetic fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
UNINSTALLER = ROOT / "installer" / "Uninstall.ps1"
POWERSHELL = (
    Path(os.environ.get("WINDIR", r"C:\Windows"))
    / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
)


class TestUninstallerPreservation(unittest.TestCase):
    def test_plan_and_cleanup_preserve_user_data_and_models(self):
        if not POWERSHELL.is_file():
            self.skipTest("Windows PowerShell 5.1 is unavailable")

        with tempfile.TemporaryDirectory(prefix="avs-uninstaller-test-") as temp:
            parent = Path(temp)
            install_root = parent / "avs-uninstall-contract-fixture"
            launcher = install_root / "launcher" / "launcher.py"
            user_data = install_root / "userdata" / "projects" / "study.json"
            model = install_root / "Models" / "synthetic-model.safetensors"
            app_file = install_root / "apps" / "frontend" / "index.html"
            external_model = parent / "external-models" / "synthetic-model.safetensors"

            for path in (launcher, user_data, model, app_file, external_model):
                path.parent.mkdir(parents=True, exist_ok=True)
            launcher.write_text("fixture", encoding="utf-8")
            user_data.write_text('{"fixture":"preserve"}', encoding="utf-8")
            model.write_bytes(b"synthetic-model")
            app_file.write_text("app fixture", encoding="utf-8")
            external_model.write_bytes(b"external synthetic model")
            (install_root / "models_env.path").write_text(
                str(external_model.parent), encoding="utf-8"
            )

            common = [
                str(POWERSHELL),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(UNINSTALLER),
                "-InstallRoot",
                str(install_root),
                "-TestFixture",
            ]
            plan_result = subprocess.run(
                [*common, "-PlanOnly"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(
                plan_result.returncode,
                0,
                plan_result.stderr or plan_result.stdout,
            )
            plan = json.loads(plan_result.stdout.strip())
            self.assertEqual(plan["status"], "PLAN_ONLY")
            self.assertTrue(plan["user_data_preserved"])
            self.assertFalse(plan["absolute_paths_emitted"])
            self.assertTrue(
                any(root.casefold() == "models" for root in plan["preserved_roots"])
            )
            self.assertIn("userdata", plan["preserved_roots"])
            self.assertTrue(app_file.is_file(), "PlanOnly must not remove app files")

            cleanup_result = subprocess.run(
                [*common, "-CleanupOnly"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(
                cleanup_result.returncode,
                0,
                cleanup_result.stderr or cleanup_result.stdout,
            )
            self.assertEqual(user_data.read_text(encoding="utf-8"), '{"fixture":"preserve"}')
            self.assertEqual(model.read_bytes(), b"synthetic-model")
            self.assertEqual(external_model.read_bytes(), b"external synthetic model")
            self.assertFalse(app_file.exists())
            self.assertFalse(launcher.exists())


if __name__ == "__main__":
    unittest.main()
