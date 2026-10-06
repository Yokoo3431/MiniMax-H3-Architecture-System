"""RC3.4 PATCH2.8-C - Distribution layout validation (Phase 1).

Verifies the PATCH2.8-A distribution layout in distribution_test/:
launcher / comfyui / models / runtime / studio / workflows / samples /
userdata / logs + README + models manifest consistency.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

DIST = SYSTEM_ROOT / "distribution_test" / "ArchitectVideoStudio"

REQUIRED_DIRS = ("launcher", "comfyui", "models", "runtime", "studio",
                 "workflows", "samples", "userdata", "logs")

LAUNCHER_FILES = ("launcher.py", "env_check.py", "process_manager.py",
                  "lock_manager.py", "logger.py",
                  "start_architect_video_studio.bat")

WORKFLOWS = ("01_Exterior_Hero_NATIVE.json", "02_Day_Night_Transition_NATIVE.json",
             "03_Material_Detail_NATIVE.json", "04_Drone_Aerial_NATIVE_GOLDEN.json",
             "05_Slow_Walkthrough_NATIVE.json")

RUNTIME_CONTRACTS = ("video_generation_request.yaml", "workflow_mapping.yaml",
                     "native_runtime_contract.yaml")
RUNTIME_ADAPTERS = ("runtime_adapter.py", "native_runtime_adapter.py",
                    "comfyui_client.py")


class TestDistributionLayout(unittest.TestCase):
    def test_distribution_root_exists(self):
        self.assertTrue(DIST.is_dir(), str(DIST))

    def test_required_directories(self):
        for sub in REQUIRED_DIRS:
            self.assertTrue((DIST / sub).is_dir(), sub)

    def test_launcher_files(self):
        for name in LAUNCHER_FILES:
            self.assertTrue((DIST / "launcher" / name).is_file(), name)

    def test_workflow_assets(self):
        for name in WORKFLOWS:
            self.assertTrue((DIST / "workflows" / name).is_file(), name)

    def test_runtime_contracts_and_adapters(self):
        for name in RUNTIME_CONTRACTS:
            self.assertTrue((DIST / "runtime" / "contracts" / name).is_file(), name)
        for name in RUNTIME_ADAPTERS:
            self.assertTrue((DIST / "runtime" / "adapters" / name).is_file(), name)

    def test_studio_app_present(self):
        studio = DIST / "studio" / "apps" / "architect_video_studio"
        self.assertTrue((studio / "run_prototype.py").is_file())
        self.assertTrue((studio / "frontend" / "index.html").is_file())
        self.assertTrue((studio / "mock_api" / "server.py").is_file())
        self.assertTrue((studio / "state_machine" / "machine.py").is_file())

    def test_samples_present(self):
        self.assertTrue((DIST / "samples" / "01_Exterior_Hero.png").is_file())

    def test_models_manifest_matches_frozen_baseline(self):
        manifest = json.loads(
            (DIST / "models" / "manifest.json").read_text(encoding="utf-8"))
        baseline = json.loads(
            (SYSTEM_ROOT / "configs" / "native_production_baseline.json")
            .read_text(encoding="utf-8"))
        for key in ("dit", "text_encoder", "video_vae", "audio_vae"):
            self.assertIn(key, manifest["models"], key)
            self.assertEqual(
                manifest["models"][key]["sha256"],
                baseline["models"][key]["sha256"], key)
            self.assertEqual(
                manifest["models"][key]["filename"],
                baseline["models"][key]["filename"], key)

    def test_readme_present(self):
        self.assertTrue((DIST / "README.md").is_file())
        text = (DIST / "README.md").read_text(encoding="utf-8")
        self.assertIn("launcher\\start_architect_video_studio.bat", text)

    def test_runtime_and_userdata_writable_areas(self):
        self.assertTrue((DIST / "userdata").is_dir())
        self.assertTrue((DIST / "logs").is_dir())

    def test_uninstaller_is_packaged_and_plan_preserves_user_data(self):
        script = SYSTEM_ROOT / "installer" / "Uninstall.ps1"
        self.assertTrue(script.is_file())
        uninstaller = script.read_text(encoding="utf-8")
        builder = (SYSTEM_ROOT / "release" / "build_shareable_release.py").read_text(encoding="utf-8")
        setup = (SYSTEM_ROOT / "installer" / "Setup.ps1").read_text(encoding="utf-8")
        self.assertIn('"installer/Uninstall.ps1"', builder)
        self.assertIn("installer\\Uninstall.ps1", setup)
        cleanup_mode = uninstaller.split("if ($CleanupOnly) {", 1)[1].split("\nif (-not (Test-PathWithin", 1)[0]
        self.assertLess(cleanup_mode.index("Remove-ManagedEntry"), cleanup_mode.index("Remove-Registration"))

        powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if not powershell.is_file():
            self.skipTest("Windows PowerShell 5.1 is unavailable")
        policy_probe = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
             "-Command", "Get-ExecutionPolicy"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        policy = policy_probe.stdout.strip().splitlines()[-1] if policy_probe.stdout.strip() else ""
        if policy_probe.returncode != 0 or policy not in {"RemoteSigned", "Unrestricted"}:
            self.skipTest("effective PowerShell policy does not permit unsigned local test scripts; policy will not be overridden")
        with tempfile.TemporaryDirectory(prefix="avs-uninstall-contract-") as temp:
            root = Path(temp)
            (root / "launcher").mkdir(parents=True)
            (root / "launcher" / "launcher.py").write_text("fixture", encoding="utf-8")
            (root / "userdata" / "projects").mkdir(parents=True)
            (root / "userdata" / "projects" / "keep.json").write_text("{}", encoding="utf-8")
            (root / "Models" / "diffusion_models").mkdir(parents=True)
            (root / "Models" / "diffusion_models" / "keep.bin").write_bytes(b"fixture")
            (root / "models_env.path").write_text(str(root / "Models"), encoding="utf-8")
            (root / "app-owned.txt").write_text("remove", encoding="utf-8")

            result = subprocess.run(
                [str(powershell), "-NoProfile", "-File",
                 str(script), "-InstallRoot", str(root), "-PlanOnly"],
                cwd=SYSTEM_ROOT, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            report = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(report["status"], "PLAN_ONLY")
            self.assertTrue(report["user_data_preserved"])
            self.assertTrue(any(item.casefold() == "models" for item in report["preserved_roots"]))
            self.assertGreater(report["app_entries_to_remove"], 0)
            self.assertFalse(report["absolute_paths_emitted"])
            self.assertNotIn(str(root), result.stdout)
            self.assertTrue((root / "userdata" / "projects" / "keep.json").is_file())
            self.assertTrue((root / "Models" / "diffusion_models" / "keep.bin").is_file())

            cleanup = subprocess.run(
                [str(powershell), "-NoProfile", "-File",
                 str(script), "-InstallRoot", str(root), "-CleanupOnly", "-TestFixture"],
                cwd=SYSTEM_ROOT, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(cleanup.returncode, 0, cleanup.stderr or cleanup.stdout)
            self.assertFalse((root / "app-owned.txt").exists())
            self.assertTrue((root / "userdata" / "projects" / "keep.json").is_file())
            self.assertTrue((root / "Models" / "diffusion_models" / "keep.bin").is_file())


if __name__ == "__main__":
    unittest.main()
