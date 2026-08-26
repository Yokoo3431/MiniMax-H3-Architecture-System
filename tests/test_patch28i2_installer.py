"""PATCH2.8-I2 installer regression tests.

All tests use tiny local in-memory HTTPS-shaped fixtures. They never download
production models, invoke ComfyUI, or run GPU inference.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from apps.architect_video_studio.mock_api.installer_service import (  # noqa: E402
    InstallationService,
    InstallerError,
)
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402
from apps.architect_video_studio.mock_api.system_api import SystemAPI  # noqa: E402
from apps.architect_video_studio.mock_api.yaml_compat import safe_load  # noqa: E402
from runtime.storage_policy import cache_paths, process_environment  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


class FakeResponse:
    def __init__(self, data: bytes, status: int = 200):
        self.data = data
        self.status = status
        self.headers = {"Content-Length": str(len(data))}
        self.pos = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.data) - self.pos
        out = self.data[self.pos:self.pos + size]
        self.pos += len(out)
        return out


class FixtureOpener:
    def __init__(self, resources):
        self.resources = resources
        self.ranges = []
        self.failures = 0

    def open(self, request, timeout=30):
        url = request.full_url
        if isinstance(self.resources.get(url), Exception):
            self.failures += 1
            raise self.resources[url]
        data = self.resources[url]
        range_header = request.headers.get("Range")
        if range_header:
            start = int(range_header.split("=", 1)[1].split("-", 1)[0])
            self.ranges.append(start)
            return FakeResponse(data[start:], status=206)
        return FakeResponse(data)


class Harness:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.store = StudioStore(self.data)
        self.native = self.root / "native"
        self.models = self.root / "models"
        self.cache = self.root / "cache"
        self.jobs = self.root / "jobs"
        self.log = self.root / "installer.log"
        self.runtime_zip = self._make_runtime_zip()
        self.model = b"fixture-model-payload-0123456789"
        self.manifest = self._make_manifest()
        self.opener = FixtureOpener({
            "https://fixture.local/runtime.zip": self.runtime_zip,
            "https://fixture.local/model.bin": self.model,
        })
        self.service = InstallationService(
            self.store,
            env_overrides={"disk_free_gb": 100.0},
            manifest_path=self.manifest,
            repo_root=SYSTEM_ROOT,
            job_root=self.jobs,
            cache_root=self.cache,
            log_path=self.log,
            opener=self.opener,
            sleep=lambda _seconds: None,
        )

    def _make_runtime_zip(self) -> bytes:
        path = self.root / "runtime.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("ComfyUI/main.py", "# fixture ComfyUI\n")
            zf.writestr("python_embeded/python.exe", "fixture python\n")
        return path.read_bytes()

    def _make_manifest(self) -> Path:
        path = self.root / "manifest.yaml"
        data = {
            "schema_version": 1,
            "manifest_id": "fixture",
            "runtime": {
                "comfyui": {
                    "version": "0.33.1",
                    "source": {"type": "archive", "url": "https://fixture.local/runtime.zip", "status": "FIXTURE"},
                    "checksum": _sha(self.runtime_zip),
                    "expected_size": len(self.runtime_zip),
                },
                "frontend": {"version": "1.48.7"},
                "pread_shim": {"version": "project-pinned", "source": {"path": "runtime/native_shim/windows_safe_load.py"}},
            },
            "models": {
                "dit": {"filename": "dit.bin", "target_subdir": "diffusion_models", "expected_size": len(self.model), "sha256": _sha(self.model), "source": {"url": "https://fixture.local/model.bin"}},
                "text_encoder": {"filename": "te.bin", "target_subdir": "text_encoders", "expected_size": len(self.model), "sha256": _sha(self.model), "source": {"url": "https://fixture.local/model.bin"}},
                "video_vae": {"filename": "video.bin", "target_subdir": "vae", "expected_size": len(self.model), "sha256": _sha(self.model), "source": {"url": "https://fixture.local/model.bin"}},
                "audio_vae": {"filename": "audio.bin", "target_subdir": "vae", "expected_size": len(self.model), "sha256": _sha(self.model), "source": {"url": "https://fixture.local/model.bin"}},
            },
            "prompt_skill": {"pinned_revision": "fixture", "path": "references/known_good_h3"},
            "installation": {"default_runtime_root": "runtime/native", "default_models_root": "runtime/native/ComfyUI/models", "safety_margin_gb": 0, "max_retries": 3},
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def wait(self, job_id: str) -> dict:
        for _ in range(100):
            job = self.service.get_job(job_id)
            if job["status"] in ("READY", "FAILED", "CANCELLED"):
                return job
            time.sleep(0.01)
        raise AssertionError("installer job did not finish")

    def close(self):
        self.tmp.cleanup()


class TestInstallerPlanning(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def tearDown(self):
        self.h.close()

    def test_fresh_install_plan(self):
        plan = self.h.service.build_install_plan(verify_existing=False)
        self.assertEqual(plan["schema_version"], 1)
        self.assertEqual(len(plan["components"]), 7)
        self.assertTrue(plan["requires_confirmation"])

    def test_default_storage_roots_are_project_local(self):
        service = InstallationService(self.h.store, repo_root=SYSTEM_ROOT,
                                       job_root=self.h.jobs)
        paths = cache_paths(SYSTEM_ROOT)
        self.assertEqual(service.cache_root, paths["downloads"])
        self.assertTrue(str(service.cache_root).startswith(str(SYSTEM_ROOT)))
        self.assertTrue(str(service.extract_root).startswith(str(SYSTEM_ROOT)))

    def test_project_local_7zip_extractor_is_preferred(self):
        service = InstallationService(self.h.store, repo_root=SYSTEM_ROOT,
                                       job_root=self.h.jobs)
        self.assertTrue(str(service.extract_root).startswith(str(SYSTEM_ROOT)))
        self.assertNotIn(r"C:\\Users", str(service._extractor or ""))

    def test_process_cache_environment_is_scoped_and_project_local(self):
        base = {"TEMP": r"C:\\Users\\Pondsi\\AppData\\Local\\Temp",
                "TMP": r"C:\\Users\\Pondsi\\AppData\\Local\\Temp",
                "PIP_CACHE_DIR": "old-pip", "HF_HOME": "old-hf",
                "HF_HUB_CACHE": "old-hub", "KEEP": "yes"}
        env = process_environment(SYSTEM_ROOT, base)
        self.assertEqual(base["TEMP"], r"C:\\Users\\Pondsi\\AppData\\Local\\Temp")
        for key in ("TEMP", "TMP", "PIP_CACHE_DIR", "HF_HOME", "HF_HUB_CACHE"):
            self.assertTrue(env[key].startswith(str(SYSTEM_ROOT)))
        self.assertEqual(env["KEEP"], "yes")

    def test_storage_policy_has_no_global_setx_or_hardcoded_user_path(self):
        source = (SYSTEM_ROOT / "runtime" / "storage_policy.py").read_text(encoding="utf-8")
        self.assertNotIn("setx", source.lower())
        self.assertNotIn(r"C:\\Users", source)

    def test_project_cache_policy_preserves_protected_runtime_and_models(self):
        paths = cache_paths(SYSTEM_ROOT)
        self.assertEqual(paths["runtime"], SYSTEM_ROOT / "userdata" / "cache" / "runtime")
        self.assertNotEqual(paths["downloads"], SYSTEM_ROOT / "runtime" / "native")
        self.assertNotEqual(paths["downloads"], SYSTEM_ROOT / "models")

    def test_model_target_mapping(self):
        plan = self.h.service.build_install_plan(verify_existing=False)
        targets = {x["component_id"]: x["target"] for x in plan["components"]}
        self.assertTrue(targets["dit"].endswith("diffusion_models\\dit.bin"))
        self.assertTrue(targets["text_encoder"].endswith("text_encoders\\te.bin"))
        self.assertTrue(targets["video_vae"].endswith("vae\\video.bin"))
        self.assertTrue(targets["audio_vae"].endswith("vae\\audio.bin"))

    def test_custom_models_root(self):
        custom = self.h.root / "custom-models"
        plan = self.h.service.build_install_plan(models_root=str(custom), verify_existing=False)
        self.assertTrue(plan["models_root"].endswith("custom-models"))
        self.assertTrue(all(str(custom) in x["target"] for x in plan["components"] if x["type"] == "model"))

    def test_required_components_plan_requires_confirmation(self):
        plan = self.h.service.build_install_plan(verify_existing=False)
        self.assertTrue(plan["requires_confirmation"])
        self.assertIn("model_license_notice", plan)

    def test_insufficient_disk_block(self):
        self.h.service.overrides["disk_free_gb"] = 0.00000001
        with self.assertRaises(InstallerError) as ctx:
            self.h.service.start_install({"confirmed": True, "components": ["dit"]})
        self.assertEqual(ctx.exception.code, "INSUFFICIENT_DISK")

    def test_runtime_source_must_be_explicit(self):
        data = safe_load(self.h.manifest.read_text(encoding="utf-8"))
        data["runtime"]["comfyui"]["source"]["url"] = None
        self.h.manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        with self.assertRaises(InstallerError) as ctx:
            self.h.service.start_install({"confirmed": True, "components": ["comfyui_runtime"]})
        self.assertEqual(ctx.exception.code, "MANUAL_SOURCE_REQUIRED")

    def test_official_runtime_source_contract(self):
        service = InstallationService(self.h.store, repo_root=SYSTEM_ROOT, job_root=self.h.jobs, cache_root=self.h.cache)
        source = service.manifest()["runtime"]["comfyui"]["source"]
        self.assertEqual(source["status"], "TRUSTED_PINNED_SOURCE")
        self.assertEqual(source["url"], "https://github.com/Comfy-Org/ComfyUI/releases/download/v0.33.1/ComfyUI_windows_portable_nvidia.7z")
        self.assertEqual(source["asset"], "ComfyUI_windows_portable_nvidia.7z")
        self.assertEqual(source["expected_size"], 2133107036)
        self.assertEqual(source["sha256"], "4a221588979b96b8244e0e50b2edca03af732acae1deba69d60aa3b4d60b9dba")
        self.assertEqual(service._validate_runtime_source(source), "TRUSTED_PINNED_SOURCE")

    def test_official_runtime_source_rejects_latest_wrong_release_and_asset(self):
        service = InstallationService(self.h.store, repo_root=SYSTEM_ROOT, job_root=self.h.jobs, cache_root=self.h.cache)
        base = service.manifest()["runtime"]["comfyui"]["source"]
        for field, value in (("url", base["url"].replace("v0.33.1", "latest")), ("release_tag", "v0.33.0"), ("asset", "ComfyUI_windows_portable_amd.7z")):
            candidate = dict(base)
            candidate[field] = value
            with self.assertRaises(InstallerError) as ctx:
                service._validate_runtime_source(candidate)
            self.assertEqual(ctx.exception.code, "UNTRUSTED_RUNTIME_SOURCE")

    def test_runtime_archive_root_normalization(self):
        archive = self.h.root / "nested.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("ComfyUI_windows_portable/python_embeded/python.exe", "fixture")
            zf.writestr("ComfyUI_windows_portable/ComfyUI/main.py", "fixture")
        stage = self.h.root / "stage"
        stage.mkdir()
        self.h.service._extract_archive(archive, stage)
        self.assertTrue((stage / "python_embeded" / "python.exe").is_file())
        self.assertTrue((stage / "ComfyUI" / "main.py").is_file())

    def test_existing_compatible_runtime_skipped(self):
        (self.h.native / "ComfyUI" / "custom_nodes" / "windows_safe_load").mkdir(parents=True)
        (self.h.native / "ComfyUI" / "main.py").parent.mkdir(parents=True, exist_ok=True)
        (self.h.native / "ComfyUI" / "main.py").write_text("main", encoding="utf-8")
        plan = self.h.service.build_install_plan(native_root=str(self.h.native), verify_existing=False)
        runtime = next(x for x in plan["components"] if x["component_id"] == "comfyui_runtime")
        self.assertEqual(runtime["status"], "READY")

    def test_incompatible_runtime_not_modified(self):
        (self.h.native / "ComfyUI").mkdir(parents=True)
        marker = self.h.native / "runtime_version.json"
        marker.write_text(json.dumps({"comfyui": "0.1"}), encoding="utf-8")
        before = marker.read_bytes()
        with self.assertRaises(InstallerError) as ctx:
            self.h.service.start_install({"confirmed": True, "native_root": str(self.h.native), "components": ["comfyui_runtime"]})
        self.assertEqual(ctx.exception.code, "INCOMPATIBLE_RUNTIME")
        self.assertEqual(marker.read_bytes(), before)


class TestInstallerDownloadAndSafety(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def tearDown(self):
        self.h.close()

    def test_resumable_download_logic(self):
        part = self.h.root / "resume.part"
        part.write_bytes(self.h.model[:7])
        final = self.h.root / "resume.bin"
        out = self.h.service.download_resumable("https://fixture.local/model.bin", part, final, expected_size=len(self.h.model), expected_sha256=_sha(self.h.model))
        self.assertEqual(out.read_bytes(), self.h.model)
        self.assertEqual(self.h.opener.ranges, [7])

    def test_checksum_success(self):
        out = self.h.service.download_resumable("https://fixture.local/model.bin", self.h.root / "x.part", self.h.root / "x.bin", expected_size=len(self.h.model), expected_sha256=_sha(self.h.model))
        self.assertEqual(out.read_bytes(), self.h.model)

    def test_checksum_mismatch(self):
        with self.assertRaises(InstallerError) as ctx:
            self.h.service.download_resumable("https://fixture.local/model.bin", self.h.root / "bad.part", self.h.root / "bad.bin", expected_size=len(self.h.model), expected_sha256="0" * 64)
        self.assertEqual(ctx.exception.code, "CHECKSUM_MISMATCH")
        self.assertTrue((self.h.root / "bad.part.corrupt").is_file())

    def test_network_failure(self):
        opener = FixtureOpener({"https://fixture.local/fail": OSError("offline")})
        service = InstallationService(self.h.store, repo_root=SYSTEM_ROOT, job_root=self.h.jobs, cache_root=self.h.cache, opener=opener, sleep=lambda _seconds: None)
        with self.assertRaises(InstallerError) as ctx:
            service.download_resumable("https://fixture.local/fail", self.h.root / "f.part", self.h.root / "f.bin")
        self.assertEqual(ctx.exception.code, "DOWNLOAD_FAILED")
        self.assertEqual(opener.failures, 3)

    def test_retry_cap(self):
        opener = FixtureOpener({"https://fixture.local/fail": OSError("offline")})
        service = InstallationService(self.h.store, repo_root=SYSTEM_ROOT, job_root=self.h.jobs, cache_root=self.h.cache, opener=opener, sleep=lambda _seconds: None)
        with self.assertRaises(InstallerError):
            service.download_resumable("https://fixture.local/fail", self.h.root / "f.part", self.h.root / "f.bin", retry_count=2)
        self.assertEqual(opener.failures, 2)

    def test_insecure_url_rejected(self):
        with self.assertRaises(InstallerError) as ctx:
            self.h.service.download_resumable("http://fixture.local/model.bin", self.h.root / "x.part", self.h.root / "x.bin")
        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")

    def test_credential_url_rejected(self):
        with self.assertRaises(InstallerError):
            self.h.service.download_resumable("https://fixture.local/model.bin?token=secret", self.h.root / "x.part", self.h.root / "x.bin")

    def test_secret_redaction_in_log(self):
        opener = FixtureOpener({"https://fixture.local/fail": OSError("Authorization: Bearer secret")})
        service = InstallationService(self.h.store, repo_root=SYSTEM_ROOT, job_root=self.h.jobs, cache_root=self.h.cache, log_path=self.h.log, opener=opener, sleep=lambda _seconds: None)
        with self.assertRaises(InstallerError):
            service.download_resumable("https://fixture.local/fail", self.h.root / "f.part", self.h.root / "f.bin", retry_count=1)
        service._log("Authorization: Bearer secret https://x.invalid/a?token=secret")
        log = self.h.log.read_text(encoding="utf-8")
        self.assertNotIn("Bearer secret", log)
        self.assertNotIn("token=secret", log)

    def test_cancel(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(InstallerError) as ctx:
            self.h.service.download_resumable("https://fixture.local/model.bin", self.h.root / "x.part", self.h.root / "x.bin", cancel_event=event)
        self.assertEqual(ctx.exception.code, "INSTALL_CANCELLED")

    def test_path_traversal_archive_rejected(self):
        archive = self.h.root / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../outside.txt", "bad")
        with self.assertRaises(InstallerError):
            self.h.service._extract_archive(archive, self.h.root / "stage")
        self.assertFalse((self.h.root / "outside.txt").exists())

    def test_atomic_install_promotion(self):
        stage = self.h.root / "native.installing"
        (stage / "ComfyUI").mkdir(parents=True)
        (stage / "ComfyUI" / "main.py").write_text("new", encoding="utf-8")
        (stage / "ComfyUI" / "custom_nodes" / "windows_safe_load").mkdir(parents=True)
        target = self.h.root / "native"
        self.h.service._promote_runtime(stage, target)
        self.assertEqual((target / "ComfyUI" / "main.py").read_text(encoding="utf-8"), "new")
        self.assertFalse(stage.exists())

    def test_gpu_job_lock_blocks_install(self):
        lock = self.h.root / "runtime.lock"
        lock.write_text(json.dumps({"pid": os.getpid(), "job_running": True}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"H3_RUNTIME_LOCK": str(lock)}):
            with self.assertRaises(InstallerError) as ctx:
                self.h.service._assert_no_gpu_job()
        self.assertEqual(ctx.exception.code, "INSTALL_BLOCKED_JOB_RUNNING")


class TestInstallerExecutionAndIntegration(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def tearDown(self):
        self.h.close()

    def test_full_fixture_install(self):
        job = self.h.service.start_install({"confirmed": True, "native_root": str(self.h.native), "models_root": str(self.h.models)})
        final = self.h.wait(job["job_id"])
        self.assertEqual(final["status"], "READY", final)
        self.assertTrue((self.h.native / "ComfyUI" / "main.py").is_file())
        self.assertTrue((self.h.native / "ComfyUI" / "custom_nodes" / "windows_safe_load" / "__init__.py").is_file())
        self.assertTrue((self.h.models / "diffusion_models" / "dit.bin").is_file())

    def test_setup_state_integration(self):
        job = self.h.service.start_install({"confirmed": True, "native_root": str(self.h.native), "models_root": str(self.h.models), "components": ["comfyui_runtime", "pread_shim"]})
        final = self.h.wait(job["job_id"])
        self.assertEqual(final["status"], "READY")
        state = self.h.service.state.load()
        self.assertEqual(Path(state["native_root"]), self.h.native.resolve())
        self.assertEqual(Path(state["models_root"]), self.h.models.resolve())

    def test_skill_pinned_revision_installation(self):
        plan = self.h.service.build_install_plan(verify_existing=False)
        skill = next(x for x in plan["components"] if x["component_id"] == "prompt_skill")
        self.assertEqual(skill["status"], "READY")

    def test_skill_latest_does_not_auto_switch(self):
        with mock.patch("runtime.prompt_bridge.skill_version.check_skill_version", return_value={"status": "GENERATION_ALLOWED", "flags": ["OFFICIAL_SKILL_UPDATE_AVAILABLE"], "pinned_revision": "p"}):
            plan = self.h.service.build_install_plan(verify_existing=False)
        self.assertEqual(next(x for x in plan["components"] if x["component_id"] == "prompt_skill")["status"], "READY")

    def test_existing_runtime_adoption_does_not_download(self):
        (self.h.native / "ComfyUI" / "custom_nodes" / "windows_safe_load").mkdir(parents=True)
        (self.h.native / "ComfyUI" / "main.py").parent.mkdir(parents=True, exist_ok=True)
        (self.h.native / "ComfyUI" / "main.py").write_text("existing", encoding="utf-8")
        plan = self.h.service.build_install_plan(native_root=str(self.h.native), verify_existing=False)
        self.assertEqual(next(x for x in plan["components"] if x["component_id"] == "comfyui_runtime")["status"], "READY")
        self.assertEqual(self.h.opener.ranges, [])

    def test_frontend_status_contract(self):
        html = (SYSTEM_ROOT / "apps" / "architect_video_studio" / "frontend" / "setup.html").read_text(encoding="utf-8")
        js = (SYSTEM_ROOT / "apps" / "architect_video_studio" / "frontend" / "js" / "setup.js").read_text(encoding="utf-8")
        for token in ("install-plan", "install-consent", "install-all-btn", "cancel-install-btn"):
            self.assertIn(token, html)
        for token in ("/api/system/install-plan", "/api/system/install", "/api/system/install/", "confirmed"):
            self.assertIn(token, js)

    def test_system_api_contract(self):
        api = SystemAPI(self.h.store, {"disk_free_gb": 100.0})
        plan = api.install_plan()
        self.assertIn("components", plan)
        self.assertTrue(plan["requires_confirmation"])

    def test_no_developer_absolute_path(self):
        for path in (SYSTEM_ROOT / "apps" / "architect_video_studio" / "mock_api" / "installer_service.py", SYSTEM_ROOT / "configs" / "installation_manifest.yaml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("AntigravityWorkspace", text)
            self.assertNotIn("D:\\AntigravityWorkspace", text)

    def test_no_model_binary_tracked(self):
        result = subprocess.run(["git", "ls-files", "*.safetensors"], cwd=SYSTEM_ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "")

    def test_ready_path_not_touched(self):
        (self.h.native / "ComfyUI" / "custom_nodes" / "windows_safe_load").mkdir(parents=True)
        (self.h.native / "ComfyUI" / "main.py").parent.mkdir(parents=True, exist_ok=True)
        (self.h.native / "ComfyUI" / "main.py").write_text("ready", encoding="utf-8")
        before = (self.h.native / "ComfyUI" / "main.py").read_bytes()
        plan = self.h.service.build_install_plan(native_root=str(self.h.native), verify_existing=False)
        self.assertEqual(next(x for x in plan["components"] if x["component_id"] == "comfyui_runtime")["status"], "READY")
        self.assertEqual((self.h.native / "ComfyUI" / "main.py").read_bytes(), before)

    def test_setup_required_plan_does_not_download_on_page_load(self):
        self.h.service.build_install_plan(verify_existing=False)
        self.assertEqual(self.h.opener.ranges, [])

    def test_release_manifest_includes_installer_surface(self):
        manifest = json.loads((SYSTEM_ROOT / "release" / "release_manifest.json").read_text(encoding="utf-8"))
        self.assertIn("apps", manifest["include_directories"])
        self.assertIn("models/manifest.json", manifest["include_files"])
        self.assertIn("configs/h3_runtime_profiles.json", manifest["include_files"])
        self.assertNotIn("yaml.py", manifest["include_files"])
        self.assertTrue((SYSTEM_ROOT / "runtime" / "yaml_compat.py").is_file())
        self.assertTrue((SYSTEM_ROOT / "configs" / "installation_manifest.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
