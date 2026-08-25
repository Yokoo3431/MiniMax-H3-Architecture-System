"""RC3.4 PATCH2.8-I1 - First-run Setup / Environment Center tests.

15 required checks: SETUP_REQUIRED/BLOCK/READY mapping, configure paths,
setup_state serialization + secrets rejection, skill pin behavior,
workflow registry 5/5, API contract, production-launch compatibility,
no absolute developer path. No GPU inference.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from apps.architect_video_studio.mock_api.environment_service import (  # noqa: E402
    EnvironmentService,
)
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402
from apps.architect_video_studio.mock_api.system_api import SystemAPI  # noqa: E402


def _write_models(root: Path) -> Path:
    baseline = json.loads(
        (SYSTEM_ROOT / "configs" / "native_production_baseline.json")
        .read_text(encoding="utf-8"))
    for key in ("dit", "text_encoder", "video_vae", "audio_vae"):
        meta = baseline["models"][key]
        sub = {"dit": "diffusion_models", "text_encoder": "text_encoders",
               "video_vae": "vae", "audio_vae": "vae"}[key]
        p = root / sub / meta["filename"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"model-bytes")
    return root


def _write_native(root: Path) -> Path:
    (root / "ComfyUI" / "custom_nodes" / "windows_safe_load").mkdir(parents=True, exist_ok=True)
    (root / "ComfyUI" / "main.py").write_text("main", encoding="utf-8")
    h3 = root / "ComfyUI" / "custom_nodes" / "ComfyUI_RH_MinMaxH3"
    h3.mkdir(parents=True, exist_ok=True)
    h3.joinpath("nodes.py").write_text(
        "\n".join((
            "RHMiniMaxH3DecodeAV", "RHMiniMaxH3DualSigmaSampler",
            "RHMiniMaxH3EmptyAVLatent", "RHMiniMaxH3FL2VAEncode",
            "RHMiniMaxH3FL2VAFirstFrameCondition", "RHMiniMaxH3FL2VATarget",
            "RHMiniMaxH3ModelLoader", "RHMiniMaxH3T2VATextEncode",
            "RHMiniMaxH3TextEncoderLoader", "RHMiniMaxH3VAELoader",
        )), encoding="utf-8")
    vhs = root / "ComfyUI" / "custom_nodes" / "ComfyUI-VideoHelperSuite"
    vhs.mkdir(parents=True, exist_ok=True)
    vhs.joinpath("nodes.py").write_text("VHS_VideoCombine", encoding="utf-8")
    return root


class Harness:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = StudioStore(self.root / "data")
        self.native = _write_native(self.root / "native")
        self.models = _write_models(self.root / "models")
        self.env_path = SYSTEM_ROOT / "native_env.path"
        self.env_path_backup = self.env_path.read_text(encoding="utf-8") \
            if self.env_path.is_file() else None
        # The developer machine may already have a production native_env.path.
        # First-run tests must exercise the clean-user state without deleting
        # that configuration permanently; close() restores the saved content.
        if self.env_path.exists():
            self.env_path.unlink()
        self.path_env_backup = {
            key: os.environ.get(key)
            for key in ("H3_NATIVE_ROOT", "H3_MODELS_ROOT", "H3_BASELINE", "H3_ENV_REPORT")
        }
        for key in self.path_env_backup:
            os.environ.pop(key, None)
        self.pread_backup = os.environ.get("H3_WINDOWS_SAFE_LOAD")
        os.environ["H3_WINDOWS_SAFE_LOAD"] = "pread"
        self.overrides = {
            "torch_available": True,
            "memory_gb": 60.0,
            "disk_free_gb": 120.0,
            "comfyui_version": "0.33.1",
            "frontend_version": "1.48.7",
            "gpu_name": "RTX 5070",
            "ram_gb": 64,
            "support_dependencies_ready": True,
            "h3_model_root_ready": True,
        }
        self.service = EnvironmentService(self.store, self.overrides)

    def close(self):
        if self.env_path_backup is None:
            if self.env_path.exists():
                self.env_path.unlink()
        else:
            self.env_path.write_text(self.env_path_backup, encoding="utf-8")
        if self.pread_backup is None:
            os.environ.pop("H3_WINDOWS_SAFE_LOAD", None)
        else:
            os.environ["H3_WINDOWS_SAFE_LOAD"] = self.pread_backup
        for key, value in self.path_env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()


class TestFirstRunSetup(unittest.TestCase):
    def test_no_native_config_setup_required(self):
        h = Harness()
        try:
            report = h.service.environment()
            self.assertEqual(report["overall"], "SETUP_REQUIRED")
            self.assertFalse(report["setup_completed"])
            self.assertFalse(report["gates"]["native_root_configured"])
        finally:
            h.close()

    def test_missing_models_setup_required(self):
        h = Harness()
        try:
            (h.models / "diffusion_models"
             / "minimax_h3_fl2va_pruned_int8_convrot.safetensors").unlink()
            h.service.configure(native_root=str(h.native), models_root=str(h.models))
            report = h.service.environment()
            self.assertEqual(report["overall"], "SETUP_REQUIRED")
            self.assertFalse(report["gates"]["models_4of4"])
        finally:
            h.close()

    def test_no_cuda_block(self):
        h = Harness()
        try:
            h.overrides["torch_available"] = False
            report = h.service.environment()
            self.assertEqual(report["overall"], "BLOCK")
            self.assertFalse(report["gates"]["gpu_ready"])
        finally:
            h.close()

    def test_valid_environment_ready(self):
        h = Harness()
        try:
            report = h.service.configure(
                native_root=str(h.native), models_root=str(h.models))
            self.assertEqual(report["overall"], "READY")
            self.assertTrue(report["setup_completed"])
            self.assertTrue(all(report["gates"].values()))
        finally:
            h.close()

    def test_configure_native_root(self):
        h = Harness()
        try:
            h.service.configure(native_root=str(h.native), models_root=str(h.models))
            state = h.service.state.load()
            self.assertEqual(state["native_root"], str(h.native))
            env_path = SYSTEM_ROOT / "native_env.path"
            if env_path.exists():
                self.assertIn(str(h.native), env_path.read_text(encoding="utf-8"))
        finally:
            h.close()

    def test_configure_models_root(self):
        h = Harness()
        try:
            h.service.configure(native_root=str(h.native), models_root=str(h.models))
            report = h.service.environment()
            self.assertEqual(report["paths"]["models_root"], str(h.models))
            self.assertEqual(report["models"]["ready"], 4)
        finally:
            h.close()

    def test_setup_state_serialization(self):
        h = Harness()
        try:
            h.service.configure(native_root=str(h.native), models_root=str(h.models))
            state = h.service.state.load()
            self.assertEqual(state["schema_version"], 1)
            self.assertTrue(state["setup_completed"])
            self.assertIn("last_validation", state)
            self.assertIn("environment_status", state)
            self.assertIn("skill_status", state)
            file = h.store.data_root.parent / "system" / "setup_state.json"
            self.assertTrue(file.is_file())
        finally:
            h.close()

    def test_secrets_rejected(self):
        h = Harness()
        try:
            with self.assertRaises(ValueError):
                h.service.state.save({"api_key": "secret"})
            with self.assertRaises(ValueError):
                h.service.state.save({"prompt": "x"})
        finally:
            h.close()

    def test_skill_mismatch_blocks_generation(self):
        h = Harness()
        try:
            fake = {"status": "BLOCKED",
                    "flags": ["INSTALLED_SKILL_MISMATCH_PINNED"],
                    "pinned_revision": "p", "installed_skill_revision": {"SKILL.md": "x"},
                    "latest_upstream_skill_revision": "U"}
            with mock.patch("runtime.prompt_bridge.skill_version.check_skill_version",
                            return_value=fake):
                report = h.service.environment()
            self.assertEqual(report["skill"]["status"], "REVISION_MISMATCH")
            self.assertFalse(report["gates"]["skill_pinned_ready"])
        finally:
            h.close()

    def test_skill_update_available_does_not_switch(self):
        h = Harness()
        try:
            h.service.configure(native_root=str(h.native), models_root=str(h.models))
            fake = {"status": "GENERATION_ALLOWED",
                    "flags": ["OFFICIAL_SKILL_UPDATE_AVAILABLE"],
                    "pinned_revision": "p", "installed_skill_revision": {"SKILL.md": "p"},
                    "latest_upstream_skill_revision": "newer"}
            with mock.patch("runtime.prompt_bridge.skill_version.check_skill_version",
                            return_value=fake):
                report = h.service.environment()
            self.assertEqual(report["skill"]["status"], "UPDATE_AVAILABLE")
            self.assertTrue(report["skill"]["generation_allowed"])
            self.assertEqual(report["overall"], "WARNING")
        finally:
            h.close()

    def test_workflow_registry_5of5(self):
        h = Harness()
        try:
            report = h.service.environment()
            self.assertEqual(report["workflows"]["count"], 5)
            self.assertEqual(report["workflows"]["ready"], 5)
        finally:
            h.close()

    def test_no_absolute_developer_path(self):
        files = [
            SYSTEM_ROOT / "apps" / "architect_video_studio" / "mock_api"
            / "environment_service.py",
            SYSTEM_ROOT / "apps" / "architect_video_studio" / "mock_api"
            / "setup_state.py",
            SYSTEM_ROOT / "apps" / "architect_video_studio" / "mock_api"
            / "system_api.py",
            SYSTEM_ROOT / "apps" / "architect_video_studio" / "frontend"
            / "setup.html",
        ]
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("AntigravityWorkspace", text, f.name)
            self.assertNotIn("D:\\AntigravityWorkspace", text, f.name)

    def test_existing_production_launch_still_works(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "launcher_mod", SYSTEM_ROOT / "launcher" / "launcher.py")
        launcher_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher_mod)
        Launcher = launcher_mod.Launcher
        launcher = Launcher(dry_run=True)
        ready_report = {"checks": {
            "gpu": {"status": "PASS"},
            "memory": {"status": "PASS"},
            "comfyui": {"status": "PASS"},
            "models": {"status": "PASS"},
            "pread": {"status": "PASS"},
        }}
        self.assertTrue(launcher._production_ready(ready_report))
        pending_report = {"checks": {
            "gpu": {"status": "PASS"},
            "memory": {"status": "PASS"},
            "comfyui": {"status": "BLOCK"},
            "models": {"status": "BLOCK"},
            "pread": {"status": "PASS"},
        }}
        self.assertFalse(launcher._production_ready(pending_report))

    def test_environment_api_contract(self):
        h = Harness()
        try:
            api = SystemAPI(h.store, h.overrides)
            report = api.environment()
            for key in ("overall", "setup_completed", "system", "runtime",
                        "models", "skill", "workflows", "paths", "gates"):
                self.assertIn(key, report, key)
            self.assertIn("READY", ("READY", "WARNING", "SETUP_REQUIRED", "BLOCK"))
            self.assertTrue(report["overall"] in
                            ("READY", "WARNING", "SETUP_REQUIRED", "BLOCK"))
        finally:
            h.close()

    def test_ready_to_production_transition(self):
        h = Harness()
        try:
            report = h.service.configure(
                native_root=str(h.native), models_root=str(h.models))
            self.assertEqual(report["overall"], "READY")
            self.assertTrue(report["setup_completed"])
            state = h.service.state.load()
            self.assertTrue(state["setup_completed"])
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
