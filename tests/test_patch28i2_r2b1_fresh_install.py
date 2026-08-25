"""PATCH2.8-I2-R2B1 fresh-user installation validation.

These tests intentionally use only a temporary fixture environment.  They do
not read, install into, or launch the development machine's Native Runtime,
ComfyUI, or production model files.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import unittest
from pathlib import Path
from unittest import mock

from apps.architect_video_studio.mock_api.environment_service import EnvironmentService
from apps.architect_video_studio.mock_api.yaml_compat import safe_load
from runtime.support_layer import FROZEN_NODE_NAMES

from tests.test_patch28i2_installer import (  # noqa: E402
    SYSTEM_ROOT,
    FakeResponse,
    Harness,
    InstallerError,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


class InterruptingResponse(FakeResponse):
    """Emit one block and then fail, leaving a resumable .part file."""

    def __init__(self, data: bytes):
        super().__init__(data)
        self._failed = False

    def read(self, size=-1):
        if self._failed:
            raise OSError("simulated connection interruption")
        self._failed = True
        return super().read(min(7, size))


class InterruptingOpener:
    def __init__(self, data: bytes):
        self.data = data
        self.calls = 0

    def open(self, request, timeout=30):  # noqa: ARG002 - urllib opener contract
        self.calls += 1
        return InterruptingResponse(self.data)


class FreshUserHarness:
    """One clean user machine with no adopted environment."""

    def __init__(self):
        self.h = Harness()
        self.path_env_backup = {
            key: os.environ.get(key)
            for key in ("H3_NATIVE_ROOT", "H3_MODELS_ROOT", "H3_BASELINE", "H3_ENV_REPORT")
        }
        for key in self.path_env_backup:
            os.environ.pop(key, None)
        self.native = self.h.root / "fresh-user" / "runtime" / "native"
        self.models = self.h.root / "fresh-user" / "models"
        self.native.parent.mkdir(parents=True, exist_ok=True)
        self.models.mkdir(parents=True, exist_ok=True)

    def environment_service(self) -> EnvironmentService:
        return EnvironmentService(
            self.h.store,
            {
                "torch_available": True,
                "memory_gb": 64.0,
                "disk_free_gb": 100.0,
                "verify_model_sizes": False,
                "support_dependencies_ready": True,
                "h3_model_root_ready": True,
            },
        )

    def add_ready_capabilities(self) -> None:
        """Complete only the isolated synthetic runtime after install."""
        custom = self.native / "ComfyUI" / "custom_nodes"
        h3 = custom / "ComfyUI_RH_MinMaxH3"
        vhs = custom / "ComfyUI-VideoHelperSuite"
        h3.mkdir(parents=True, exist_ok=True)
        vhs.mkdir(parents=True, exist_ok=True)
        (h3 / "nodes.py").write_text("\n".join(FROZEN_NODE_NAMES[:-1]), encoding="utf-8")
        (vhs / "nodes.py").write_text("VHS_VideoCombine\n", encoding="utf-8")

        baseline = json.loads(
            (SYSTEM_ROOT / "configs" / "native_production_baseline.json")
            .read_text(encoding="utf-8")
        )
        for key, subdir in {
            "dit": "diffusion_models",
            "text_encoder": "text_encoders",
            "video_vae": "vae",
            "audio_vae": "vae",
        }.items():
            filename = baseline["models"][key]["filename"]
            target = self.models / subdir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            # Synthetic bytes only; no production model is copied or read.
            target.write_bytes((key + "-synthetic").encode("ascii"))

    def close(self):
        self.h.close()
        for key, value in self.path_env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TestR2B1FreshUserInstallation(unittest.TestCase):
    def setUp(self):
        self.fresh = FreshUserHarness()
        self.h = self.fresh.h

    def tearDown(self):
        self.fresh.close()

    def test_clean_user_routes_to_setup_required_without_production_paths(self):
        report = self.fresh.environment_service().environment()
        self.assertEqual(report["overall"], "SETUP_REQUIRED")
        self.assertEqual(report["models"]["ready"], 0)
        self.assertFalse(report["paths"]["configured"])
        self.assertEqual(report["environment_sources"]["active"]["native_root"], "")
        self.assertEqual(report["environment_sources"]["validation_target"]["native_root"], "")

    def test_install_plan_is_explicit_pinned_and_targets_only_fixture_roots(self):
        plan = self.h.service.build_install_plan(
            native_root=str(self.fresh.native),
            models_root=str(self.fresh.models),
            verify_existing=False,
            verify_dependencies=False,
        )
        self.assertTrue(plan["requires_confirmation"])
        self.assertGreater(plan["download_size_bytes"], 0)
        self.assertEqual(Path(plan["install_root"]), self.fresh.native.resolve())
        self.assertEqual(Path(plan["models_root"]), self.fresh.models.resolve())
        for item in plan["components"]:
            if item["type"] in {"runtime", "model", "support_layer"}:
                self.assertTrue(item["source"].startswith("https://"), item)
            self.assertTrue(
                str(item["target"]).startswith(str(self.fresh.native.resolve()))
                or str(item["target"]).startswith(str(self.fresh.models.resolve()))
                or item["type"] in {"prompt_skill", "python_dependencies"},
                item,
            )

    def test_production_manifest_keeps_pinned_sources_and_order(self):
        manifest = safe_load(
            (SYSTEM_ROOT / "configs" / "installation_manifest.yaml")
            .read_text(encoding="utf-8")
        )
        source = manifest["runtime"]["comfyui"]["source"]
        self.assertEqual(source["status"], "TRUSTED_PINNED_SOURCE")
        self.assertNotIn("latest", source["url"].lower())
        self.assertEqual(source["release_tag"], "v0.33.1")
        self.assertEqual(source["expected_size"], 2133107036)
        self.assertEqual(
            source["sha256"],
            "4a221588979b96b8244e0e50b2edca03af732acae1deba69d60aa3b4d60b9dba",
        )

        support = safe_load(
            (SYSTEM_ROOT / "configs" / "support_layer_manifest.yaml")
            .read_text(encoding="utf-8")
        )
        for entry in support["support_layers"].values():
            self.assertTrue(entry["repository"])
            self.assertRegex(entry["commit"], r"^[0-9a-f]{40}$")
            self.assertTrue(entry["source_archive_url"].startswith("https://"))
            self.assertNotIn("latest", entry["source_archive_url"].lower())

        order = manifest["support_layers"]["install_order"]
        self.assertLess(order.index("comfyui_runtime"), order.index("minimax_h3_nodes"))
        self.assertLess(order.index("minimax_h3_nodes"), order.index("models"))

        production_service = self.h.service.__class__(
            self.h.store,
            env_overrides={"disk_free_gb": 100.0},
            repo_root=SYSTEM_ROOT,
            job_root=self.h.jobs,
            cache_root=self.h.cache,
        )
        plan = production_service.build_install_plan(
            native_root=str(self.fresh.native),
            models_root=str(self.fresh.models),
            verify_existing=False,
            verify_dependencies=False,
        )
        component_ids = [item["component_id"] for item in plan["components"]]
        self.assertIn("minimax_h3_nodes", component_ids)
        self.assertIn("video_helper_suite", component_ids)
        self.assertIn("support_layer_dependencies", component_ids)
        self.assertTrue({"dit", "text_encoder", "video_vae", "audio_vae"}.issubset(component_ids))
        self.assertTrue(all(
            str(item["target"]).startswith(str(self.fresh.native.resolve()))
            or str(item["target"]).startswith(str(self.fresh.models.resolve()))
            or item["type"] in {"prompt_skill", "python_dependencies"}
            for item in plan["components"]
        ))

    def test_fixture_install_verifies_and_transitions_to_ready(self):
        before = self.fresh.environment_service().environment()
        self.assertEqual(before["overall"], "SETUP_REQUIRED")

        job = self.h.service.start_install({
            "confirmed": True,
            "native_root": str(self.fresh.native),
            "models_root": str(self.fresh.models),
        })
        final = self.h.wait(job["job_id"])
        self.assertEqual(final["status"], "READY", final)
        self.assertTrue((self.fresh.h.cache.parent / "runtime" / "comfyui_runtime" / "runtime.zip").is_file())
        self.assertTrue((self.fresh.native / "ComfyUI" / "main.py").is_file())
        self.assertTrue(
            (self.fresh.native / "ComfyUI" / "custom_nodes" / "windows_safe_load" / "__init__.py").is_file()
        )
        self.fresh.add_ready_capabilities()

        with mock.patch.dict(os.environ, {"H3_WINDOWS_SAFE_LOAD": "pread"}, clear=False):
            report = self.fresh.environment_service().environment()
        self.assertEqual(report["overall"], "READY")
        self.assertEqual(report["models"]["ready"], 4)
        self.assertEqual(report["support"]["h3"]["status"], "READY")
        self.assertEqual(report["support"]["video"]["status"], "READY")
        self.assertEqual(report["support"]["dependencies"]["status"], "READY")
        self.assertTrue(report["runtime"]["pread"])
        self.assertEqual(report["workflows"]["ready"], 5)
        self.assertTrue(all(report["production_gates"].values()))
        self.assertNotIn("validation", json.dumps(report["paths"]))

    def test_interrupted_download_keeps_resume_state_and_recovers(self):
        part = self.h.root / "interrupted" / "runtime.part"
        final = self.h.root / "interrupted" / "runtime.zip"
        interrupted = InterruptingOpener(self.h.runtime_zip)
        failing = self.h.service.__class__(
            self.h.store,
            repo_root=SYSTEM_ROOT,
            job_root=self.h.jobs,
            cache_root=self.h.cache,
            opener=interrupted,
            sleep=lambda _seconds: None,
        )
        with self.assertRaises(InstallerError) as ctx:
            failing.download_resumable(
                "https://fixture.local/runtime.zip",
                part,
                final,
                expected_size=len(self.h.runtime_zip),
                expected_sha256=_sha256(self.h.runtime_zip),
                retry_count=1,
            )
        self.assertEqual(ctx.exception.code, "DOWNLOAD_FAILED")
        self.assertTrue(part.is_file())
        self.assertFalse(final.exists())

        recovered = self.h.service.download_resumable(
            "https://fixture.local/runtime.zip",
            part,
            final,
            expected_size=len(self.h.runtime_zip),
            expected_sha256=_sha256(self.h.runtime_zip),
        )
        self.assertEqual(recovered.read_bytes(), self.h.runtime_zip)
        self.assertTrue(self.h.opener.ranges)

    def test_checksum_failure_does_not_promote_or_modify_runtime(self):
        target = self.fresh.native
        target.mkdir(parents=True, exist_ok=True)
        marker = target / "do-not-overwrite.txt"
        marker.write_text("existing runtime remains untouched", encoding="utf-8")
        with self.assertRaises(InstallerError) as ctx:
            self.h.service.download_resumable(
                "https://fixture.local/runtime.zip",
                self.h.root / "bad" / "runtime.part",
                self.h.root / "bad" / "runtime.zip",
                expected_size=len(self.h.runtime_zip),
                expected_sha256="0" * 64,
            )
        self.assertEqual(ctx.exception.code, "CHECKSUM_MISMATCH")
        self.assertEqual(marker.read_text(encoding="utf-8"), "existing runtime remains untouched")
        self.assertFalse((target / "ComfyUI" / "main.py").exists())

    def test_insufficient_disk_and_cancel_stop_before_install(self):
        self.h.service.overrides["disk_free_gb"] = 0.00000001
        with self.assertRaises(InstallerError) as ctx:
            self.h.service.start_install({
                "confirmed": True,
                "native_root": str(self.fresh.native),
                "models_root": str(self.fresh.models),
            })
        self.assertEqual(ctx.exception.code, "INSUFFICIENT_DISK")
        self.assertFalse(self.fresh.native.exists())
        self.assertFalse(any(self.fresh.models.rglob("*.bin")))

        event = threading.Event()
        event.set()
        with self.assertRaises(InstallerError) as ctx:
            self.h.service.download_resumable(
                "https://fixture.local/model.bin",
                self.h.root / "cancel" / "model.part",
                self.h.root / "cancel" / "model.bin",
                cancel_event=event,
            )
        self.assertEqual(ctx.exception.code, "INSTALL_CANCELLED")
        self.assertFalse((self.h.root / "cancel" / "model.bin").exists())


if __name__ == "__main__":
    unittest.main()
