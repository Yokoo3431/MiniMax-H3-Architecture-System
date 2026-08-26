"""RC3.4 PATCH2.8-C - Distribution runtime tests (Phases 2-4, NO GPU).

Covers: relative path validation, launcher path independence, manifest
validation, userdata/logs writability, distribution boot contract, and a dev
path leak scan (AntigravityWorkspace absent from shipped execution code).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from runtime.yaml_compat import safe_load

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))
sys.path.insert(0, str(SYSTEM_ROOT / "launcher"))

from dist_config import DistributionConfig  # noqa: E402
from env_check import EnvPaths  # noqa: E402

DIST = SYSTEM_ROOT / "distribution_test" / "ArchitectVideoStudio"
CONFIG = DIST / "distribution_config.yaml"


class TestRelativePathValidation(unittest.TestCase):
    def test_config_exists_and_all_paths_relative(self):
        self.assertTrue(CONFIG.is_file())
        data = safe_load(CONFIG.read_text(encoding="utf-8"))
        for key, value in data["distribution"].items():
            if isinstance(value, str) and value != ".":
                self.assertFalse(Path(value).is_absolute(), f"{key} absolute: {value}")
        for key, value in data["native_runtime"].items():
            if isinstance(value, str) and key != "safe_load":
                self.assertFalse(Path(value).is_absolute(), f"{key} absolute: {value}")

    def test_config_resolves_to_existing_dirs(self):
        cfg = DistributionConfig(CONFIG)
        for name, path in (
                ("studio_app", cfg.studio_app),
                ("studio_workdir", cfg.studio_workdir),
                ("userdata", cfg.userdata),
                ("logs", cfg.logs),
                ("configs", cfg.configs),
                ("workflows", cfg.workflows),
                ("runtime", cfg.runtime),
                ("samples", cfg.samples)):
            self.assertTrue(path.is_dir(), f"{name}: {path}")
        self.assertTrue((cfg.configs / "native_production_baseline.json").is_file())

    def test_native_runtime_paths_resolve(self):
        cfg = DistributionConfig(CONFIG)
        self.assertTrue(cfg.native_comfyui_root.is_dir())
        self.assertTrue(cfg.models_root.is_dir())
        self.assertTrue(cfg.comfy_input.is_dir())
        self.assertTrue(cfg.comfy_output.is_dir())
        self.assertEqual(cfg.comfyui_port, 8189)
        self.assertEqual(cfg.studio_port, 8788)
        self.assertEqual(cfg.runtime_mode, "real")
        self.assertEqual(cfg.safe_load, "pread")
        self.assertEqual(
            safe_load(CONFIG.read_text(encoding="utf-8"))["native_runtime"]["profile_selection"],
            "AUTO",
        )
        self.assertTrue((DIST / "configs" / "h3_runtime_profiles.json").is_file())


class TestLauncherPathIndependence(unittest.TestCase):
    def test_env_paths_override(self):
        with tempfile.TemporaryDirectory() as tmpd:
            os.environ["H3_NATIVE_ROOT"] = tmpd
            os.environ["H3_MODELS_ROOT"] = tmpd
            os.environ["H3_BASELINE"] = str(Path(tmpd) / "baseline.json")
            os.environ["H3_ENV_REPORT"] = str(Path(tmpd) / "env_report.json")
            try:
                paths = EnvPaths()
                self.assertEqual(str(paths.native_root), tmpd)
                self.assertEqual(str(paths.models_root), tmpd)
                self.assertEqual(str(paths.baseline_path), str(Path(tmpd) / "baseline.json"))
                self.assertEqual(str(paths.env_report_path), str(Path(tmpd) / "env_report.json"))
            finally:
                for key in ("H3_NATIVE_ROOT", "H3_MODELS_ROOT", "H3_BASELINE", "H3_ENV_REPORT"):
                    os.environ.pop(key, None)

    def test_no_antigravity_workspace_in_shipped_code(self):
        # Scan execution code (exclude __main__ demo defaults which are never run).
        roots = [DIST / "launcher", DIST / "studio"]
        offenders = []
        for root in roots:
            for py in root.rglob("*.py"):
                lines = py.read_text(encoding="utf-8", errors="ignore").splitlines()
                in_main = False
                for line in lines:
                    if line.strip().startswith("if __name__"):
                        in_main = True
                    if not in_main and "AntigravityWorkspace" in line:
                        offenders.append(f"{py.relative_to(DIST)}:{line.strip()[:80]}")
        self.assertEqual(offenders, [])

    def test_distribution_config_absent_from_dev_paths(self):
        text = CONFIG.read_text(encoding="utf-8")
        self.assertNotIn("AntigravityWorkspace", text)


class TestManifestValidation(unittest.TestCase):
    def test_manifest_matches_baseline(self):
        manifest = json.loads((DIST / "models" / "manifest.json").read_text(encoding="utf-8"))
        baseline = json.loads(
            (SYSTEM_ROOT / "configs" / "native_production_baseline.json")
            .read_text(encoding="utf-8"))
        for key in ("dit", "text_encoder", "video_vae", "audio_vae"):
            self.assertEqual(manifest["models"][key]["sha256"],
                             baseline["models"][key]["sha256"], key)


class TestWritableAreas(unittest.TestCase):
    def test_userdata_writable(self):
        probe = DIST / "userdata" / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        self.assertTrue(probe.is_file())
        probe.unlink()

    def test_logs_writable(self):
        probe = DIST / "logs" / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        self.assertTrue(probe.is_file())
        probe.unlink()


class TestDistributionBootContract(unittest.TestCase):
    def test_boot_contract_fields(self):
        cfg = DistributionConfig(CONFIG)
        required = {
            "launcher": "launcher",
            "studio_app": "studio/apps/architect_video_studio",
            "studio_workdir": "studio",
            "userdata": "userdata",
            "logs": "logs",
            "workflows": "workflows",
        }
        for key, rel in required.items():
            self.assertEqual(cfg.data["distribution"][key], rel, key)
        self.assertEqual(cfg.data["studio"]["runtime_mode"], "real")


if __name__ == "__main__":
    unittest.main()
