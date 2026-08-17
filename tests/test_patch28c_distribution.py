"""RC3.4 PATCH2.8-C - Distribution layout validation (Phase 1).

Verifies the PATCH2.8-A distribution layout in distribution_test/:
launcher / comfyui / models / runtime / studio / workflows / samples /
userdata / logs + README + models manifest consistency.
"""

import json
import sys
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


if __name__ == "__main__":
    unittest.main()
