"""PATCH2.8-I2-R2B0.1 active-environment adoption contracts.

These tests use tiny synthetic assets and temporary setup state.  They never
download, copy, hash, reinstall, or modify the real production assets.
"""

from __future__ import annotations

import json
import os
import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from apps.architect_video_studio.mock_api.environment_resolution import (  # noqa: E402
    is_native_root,
    model_files_present,
    resolve_active_environment,
)
from apps.architect_video_studio.mock_api.environment_service import EnvironmentService  # noqa: E402
from apps.architect_video_studio.mock_api.installer_service import InstallationService  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402


def _native(root: Path, support: bool = True) -> Path:
    (root / "python_embeded").mkdir(parents=True, exist_ok=True)
    (root / "python_embeded" / "python.exe").write_bytes(b"fixture")
    (root / "ComfyUI" / "main.py").parent.mkdir(parents=True, exist_ok=True)
    (root / "ComfyUI" / "main.py").write_text("main", encoding="utf-8")
    custom = root / "ComfyUI" / "custom_nodes"
    (custom / "windows_safe_load").mkdir(parents=True, exist_ok=True)
    if support:
        h3 = custom / "ComfyUI_RH_MinMaxH3"
        h3.mkdir(parents=True, exist_ok=True)
        h3.joinpath("nodes.py").write_text(
            "RHMiniMaxH3DecodeAV RHMiniMaxH3DualSigmaSampler "
            "RHMiniMaxH3EmptyAVLatent RHMiniMaxH3FL2VAEncode "
            "RHMiniMaxH3FL2VAFirstFrameCondition RHMiniMaxH3FL2VATarget "
            "RHMiniMaxH3ModelLoader RHMiniMaxH3T2VATextEncode "
            "RHMiniMaxH3TextEncoderLoader RHMiniMaxH3VAELoader",
            encoding="utf-8")
        vhs = custom / "ComfyUI-VideoHelperSuite"
        vhs.mkdir(parents=True, exist_ok=True)
        vhs.joinpath("nodes.py").write_text("VHS_VideoCombine", encoding="utf-8")
    return root


def _models(root: Path) -> Path:
    manifest = json.loads((SYSTEM_ROOT / "models" / "manifest.json").read_text(encoding="utf-8"))
    for key, meta in manifest["models"].items():
        sub = {"dit": "diffusion_models", "text_encoder": "text_encoders",
               "video_vae": "vae", "audio_vae": "vae"}[key]
        target = root / sub / meta["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture-model")
    return root


class TestEnvironmentAdoption(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path_env_backup = {
            key: os.environ.get(key)
            for key in ("H3_NATIVE_ROOT", "H3_MODELS_ROOT", "H3_BASELINE", "H3_ENV_REPORT")
        }
        for key in self.path_env_backup:
            os.environ.pop(key, None)
        self.pread_backup = os.environ.get("H3_WINDOWS_SAFE_LOAD")
        os.environ["H3_WINDOWS_SAFE_LOAD"] = "pread"
        self.validation = _native(self.root / "repo" / "validation" / "runtime_native_v0331")
        self.prod = _native(self.root / "adopted_runtime")
        self.model_root = _models(self.prod / "ComfyUI" / "models")
        self.project_validation = SYSTEM_ROOT / "validation" / "runtime_native_v0331"
        self.external_models = _models(self.root / "shared_models")

    def tearDown(self):
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

    def _service(self, state=None):
        store = StudioStore(self.root / "studio")
        service = EnvironmentService(store, {
            "torch_available": True, "memory_gb": 60, "disk_free_gb": 100,
            "verify_model_sizes": False, "support_dependencies_ready": True,
            "h3_model_root_ready": True,
            # Synthetic fixture nodes are capability-only; live adopted
            # runtimes perform the immutable source-tree fingerprint gate.
            "support_provenance_ready": True,
        })
        if state:
            service.state.save(state)
        return service

    def _fixture_installer(self, service):
        installer = InstallationService(service.store, repo_root=SYSTEM_ROOT,
                                         job_root=self.root / "jobs", cache_root=self.root / "cache")
        manifest = copy.deepcopy(installer.manifest())
        for meta in manifest["models"].values():
            if not isinstance(meta, dict) or "expected_size" not in meta:
                continue
            meta["expected_size"] = len(b"fixture-model")
            meta["sha256"] = hashlib.sha256(b"fixture-model").hexdigest().upper()
        return installer, manifest

    def test_active_environment_is_separate_from_validation_target(self):
        active = resolve_active_environment(
            self.root / "repo",
            {"native_root": str(self.validation), "models_root": str(self.model_root)},
            {},
        )
        self.assertEqual(active.native_root, self.prod.resolve())
        self.assertEqual(active.models_root, self.model_root.resolve())
        self.assertEqual(active.source, "adopted_from_models_root")

    def test_validation_target_never_overrides_active_environment(self):
        active = resolve_active_environment(
            self.root / "repo",
            {"native_root": str(self.validation), "models_root": str(self.model_root)},
            {},
        )
        self.assertNotIn("validation", str(active.native_root).lower())
        self.assertNotIn("validation", str(active.models_root).lower())

    def test_existing_native_detected(self):
        self.assertTrue(is_native_root(self.prod))

    def test_existing_models_four_of_four_detected(self):
        self.assertTrue(model_files_present(self.model_root, SYSTEM_ROOT, verify_size=False))

    def test_environment_reports_existing_models_ready(self):
        service = self._service({"native_root": str(self.validation), "models_root": str(self.model_root)})
        with mock.patch.object(service, "_write_native_env_path"):
            report = service.environment()
        self.assertEqual(report["models"]["ready"], 4)
        self.assertTrue(report["gates"]["models_4of4"])

    def test_existing_h3_support_detected(self):
        service = self._service({"native_root": str(self.prod), "models_root": str(self.model_root)})
        with mock.patch.object(service, "_write_native_env_path"):
            report = service.environment()
        self.assertEqual(report["support"]["h3"]["status"], "READY")

    def test_existing_vhs_detected(self):
        service = self._service({"native_root": str(self.prod), "models_root": str(self.model_root)})
        with mock.patch.object(service, "_write_native_env_path"):
            report = service.environment()
        self.assertEqual(report["support"]["video"]["status"], "READY")

    def test_existing_support_dependencies_detected(self):
        service = self._service({"native_root": str(self.prod), "models_root": str(self.model_root)})
        with mock.patch.object(service, "_write_native_env_path"):
            report = service.environment()
        self.assertEqual(report["support"]["dependencies"]["status"], "READY")

    def test_pread_detected_from_existing_shim(self):
        service = self._service({"native_root": str(self.prod), "models_root": str(self.model_root)})
        with mock.patch.dict(os.environ, {"H3_WINDOWS_SAFE_LOAD": "pread"}):
            with mock.patch.object(service, "_write_native_env_path"):
                report = service.environment()
        self.assertTrue(report["runtime"]["pread"])

    def test_ready_enables_production_gate(self):
        service = self._service({"native_root": str(self.prod), "models_root": str(self.model_root)})
        with mock.patch.object(service, "_write_native_env_path"):
            report = service.environment()
        self.assertEqual(report["overall"], "READY")
        self.assertTrue(all(report["production_gates"].values()))

    def test_fresh_missing_runtime_remains_setup_required(self):
        service = self._service()
        with mock.patch.object(service, "_write_native_env_path"):
            report = service.environment()
        self.assertEqual(report["overall"], "SETUP_REQUIRED")
        self.assertFalse(report["gates"]["native_root_configured"])

    def test_fresh_missing_models_remains_setup_required(self):
        service = self._service({"native_root": str(self.prod), "models_root": str(self.root / "missing")})
        with mock.patch.object(service, "_write_native_env_path"):
            report = service.environment()
        self.assertEqual(report["overall"], "SETUP_REQUIRED")
        self.assertFalse(report["gates"]["models_4of4"])

    def test_use_existing_paths_recheck_ready(self):
        service = self._service()
        with mock.patch.object(service, "_write_native_env_path"):
            report = service.configure(str(self.prod), str(self.model_root))
        self.assertEqual(report["overall"], "READY")

    def test_install_plan_uses_active_roots(self):
        service = self._service({"native_root": str(self.project_validation), "models_root": str(self.external_models)})
        installer, manifest = self._fixture_installer(service)
        with mock.patch.object(installer, "manifest", return_value=manifest):
            plan = installer.build_install_plan(verify_existing=False, verify_dependencies=False)
        self.assertEqual(Path(plan["install_root"]), (SYSTEM_ROOT / "runtime" / "native").resolve())
        self.assertEqual(Path(plan["models_root"]), self.external_models.resolve())

    def test_install_plan_skips_existing_models(self):
        service = self._service({"native_root": str(self.project_validation), "models_root": str(self.external_models)})
        installer, manifest = self._fixture_installer(service)
        with mock.patch.object(installer, "manifest", return_value=manifest):
            plan = installer.build_install_plan(verify_existing=False, verify_dependencies=False)
        self.assertTrue(all(item["status"] == "READY" for item in plan["components"]
                            if item["type"] == "model"))

    def test_no_model_download_in_adoption(self):
        service = self._service({"native_root": str(self.prod), "models_root": str(self.model_root)})
        installer = InstallationService(service.store, repo_root=SYSTEM_ROOT,
                                         job_root=self.root / "jobs", cache_root=self.root / "cache")
        with mock.patch.object(installer, "start_install") as start:
            installer.build_install_plan(verify_existing=False, verify_dependencies=False)
        start.assert_not_called()

    def test_no_runtime_reinstall_for_ready_runtime(self):
        service = self._service({"native_root": str(self.prod), "models_root": str(self.model_root)})
        installer = InstallationService(service.store, repo_root=SYSTEM_ROOT,
                                         job_root=self.root / "jobs", cache_root=self.root / "cache")
        plan = installer.build_install_plan(verify_existing=False, verify_dependencies=False)
        self.assertEqual(next(x for x in plan["components"] if x["component_id"] == "comfyui_runtime")["status"], "READY")

    def test_environment_sources_are_explicitly_separated(self):
        service = self._service({"native_root": str(self.project_validation), "models_root": str(self.model_root)})
        with mock.patch.object(service, "_write_native_env_path"):
            report = service.environment()
        self.assertIn("active", report["environment_sources"])
        self.assertIn("validation_target", report["environment_sources"])
        self.assertEqual(report["environment_sources"]["validation_target"]["native_root"], str(self.project_validation.resolve()))
        self.assertEqual(report["environment_sources"]["active"]["native_root"], str(self.prod.resolve()))

    def test_no_developer_absolute_path_in_resolution_code(self):
        text = (SYSTEM_ROOT / "apps" / "architect_video_studio" / "mock_api" / "environment_resolution.py").read_text(encoding="utf-8")
        self.assertNotIn("AntigravityWorkspace", text)
        self.assertNotIn("C:\\Users", text)

    def test_production_assets_are_read_only_during_probe(self):
        before = (self.prod / "ComfyUI" / "main.py").read_bytes()
        service = self._service({"native_root": str(self.prod), "models_root": str(self.model_root)})
        with mock.patch.object(service, "_write_native_env_path"):
            service.environment()
        self.assertEqual((self.prod / "ComfyUI" / "main.py").read_bytes(), before)

    def test_continue_gate_is_present_in_frontend_contract(self):
        js = (SYSTEM_ROOT / "apps" / "architect_video_studio" / "frontend" / "js" / "setup.js").read_text(encoding="utf-8")
        self.assertIn("production_gates", js)
        self.assertIn("continue-btn", js)

    def test_fresh_user_actions_remain_available(self):
        html = (SYSTEM_ROOT / "apps" / "architect_video_studio" / "frontend" / "setup.html").read_text(encoding="utf-8")
        for token in ("Install Native Runtime", "Use Existing Runtime", "Install Required Models", "Use Existing Models"):
            self.assertIn(token, html)

    def test_no_gpu_or_prompt_operation_added(self):
        source = (SYSTEM_ROOT / "apps" / "architect_video_studio" / "mock_api" / "environment_resolution.py").read_text(encoding="utf-8")
        self.assertNotIn("/prompt", source)
        self.assertNotIn("torch.cuda", source)


if __name__ == "__main__":
    unittest.main()
