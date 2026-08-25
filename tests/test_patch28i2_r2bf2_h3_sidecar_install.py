"""PATCH2.8-I2-R2B-F2 sidecar provenance and installer contract tests.

These tests are CPU/static only.  They do not call ComfyUI, /prompt, CUDA, or
download production weights.
"""

from __future__ import annotations

import tempfile
import hashlib
import threading
import unittest
from pathlib import Path
from unittest import mock

from apps.architect_video_studio.mock_api.installer_service import InstallationService, InstallerError
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.h3_sidecar import (
    EXPECTED_REPOSITORY,
    load_h3_sidecar_manifest,
    sidecar_target_root,
    validate_h3_sidecar_manifest,
    validate_h3_sidecar_tree,
)


ROOT = Path(__file__).resolve().parents[1]


class H3SidecarInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_h3_sidecar_manifest(ROOT)

    def test_official_source_and_immutable_revision(self):
        source = self.manifest["source"]
        self.assertEqual(source["repository"], EXPECTED_REPOSITORY)
        self.assertRegex(source["revision"], r"^[0-9a-f]{40}$")
        self.assertNotIn("/main/", source["base_url"])
        self.assertNotIn("/latest/", source["base_url"])

    def test_exact_allow_list_is_non_weight_fl2va_contract(self):
        paths = {item["path"] for item in self.manifest["files"]}
        self.assertIn("FL2VA/model_index.json", paths)
        for required in (
            "FL2VA/transformer/config.json",
            "FL2VA/text_encoder/config.json",
            "FL2VA/processor/tokenizer_config.json",
            "FL2VA/processor/tokenizer.json",
            "FL2VA/processor/vocab.json",
            "FL2VA/processor/preprocessor_config.json",
            "FL2VA/video_vae/config.json",
            "FL2VA/audio_vae/config.json",
        ):
            self.assertIn(required, paths)
        self.assertTrue(all(not item["path"].lower().endswith(".safetensors")
                            for item in self.manifest["files"]))
        self.assertNotIn("Ref2VA", "\n".join(paths))

    def test_each_file_has_exact_size_sha_and_https_source(self):
        for item in self.manifest["files"]:
            self.assertGreater(item["expected_size"], 0, item["path"])
            self.assertRegex(item["sha256"], r"^[0-9A-F]{64}$", item["path"])
            self.assertTrue(item["source_url"].startswith("https://"), item["path"])

    def test_license_metadata_is_present(self):
        license_data = self.manifest["license"]
        self.assertEqual(license_data["identifier"], "MiniMax H3 Community License Agreement")
        self.assertEqual(license_data["path"], "LICENSE")
        self.assertTrue(license_data["notice_required"])
        self.assertIn("MiniMax H3 is licensed", license_data["notice_text"])

    def test_moving_source_and_safetensors_are_rejected(self):
        moving = dict(self.manifest)
        moving["source"] = dict(self.manifest["source"])
        moving["source"]["base_url"] = "https://huggingface.co/MiniMaxAI/MiniMax-H3/resolve/main/"
        with self.assertRaises(ValueError):
            validate_h3_sidecar_manifest(moving)
        weighted = dict(self.manifest)
        weighted["files"] = [dict(self.manifest["files"][0], path="FL2VA/model.safetensors")]
        with self.assertRaises(ValueError):
            validate_h3_sidecar_manifest(weighted)

    def test_custom_models_root_and_missing_tree_do_not_claim_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            models = Path(temp) / "custom-models"
            state = validate_h3_sidecar_tree(models, self.manifest)
            self.assertEqual(state["target"], str(sidecar_target_root(models)))
            self.assertFalse(state["ready"])
            self.assertEqual(len(state["missing"]), len(self.manifest["files"]))

    def test_production_plan_has_distinct_h3_configuration_component(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            managed = root / "managed-runtime"
            models = root / "shared-models"
            store = StudioStore(root / "data")
            service = InstallationService(store, repo_root=ROOT,
                                          job_root=root / "jobs",
                                          cache_root=root / "cache")
            plan = service.build_install_plan(
                native_root=str(managed), models_root=str(models),
                verify_existing=False, verify_dependencies=False,
            )
            item = next(c for c in plan["components"]
                        if c["component_id"] == service.H3_SIDECAR_COMPONENT)
            self.assertEqual(item["repository"], EXPECTED_REPOSITORY)
            self.assertEqual(item["revision"], self.manifest["source"]["revision"])
            self.assertEqual(item["type"], "model_configuration")

    def test_existing_compatible_development_layout_is_not_redownloaded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = InstallationService(
                StudioStore(root / "data"), repo_root=ROOT,
                job_root=root / "jobs", cache_root=root / "cache",
            )
            content = b'fixture-sidecar\n'
            digest = hashlib.sha256(content).hexdigest().upper()
            fixture_manifest = {
                "schema_version": 1,
                "source": dict(self.manifest["source"]),
                "license": self.manifest["license"],
                "files": [{
                    "path": "FL2VA/model_index.json",
                    "source_url": self.manifest["source"]["base_url"] + "FL2VA/model_index.json",
                    "expected_size": len(content), "sha256": digest,
                }],
            }
            models = root / "shared-models"
            target = sidecar_target_root(models)
            target.joinpath("FL2VA/model_index.json").parent.mkdir(parents=True, exist_ok=True)
            target.joinpath("FL2VA/model_index.json").write_bytes(content)
            with mock.patch.object(service, "_h3_sidecar_manifest", return_value=fixture_manifest):
                state = service._h3_sidecar_state(models, verify=True)
            self.assertEqual(state["status"], "READY")
            self.assertEqual(state["missing"], [])

    def test_fresh_fixture_requires_sidecar_before_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = InstallationService(
                StudioStore(root / "data"), repo_root=ROOT,
                job_root=root / "jobs", cache_root=root / "cache",
            )
            state = service._h3_sidecar_state(root / "models", verify=True)
            self.assertEqual(state["status"], "FAILED")
            self.assertEqual(state["code"], "INCOMPATIBLE_RUNTIME")

    def test_sidecar_task_does_not_include_model_weight_downloads(self):
        for item in self.manifest["files"]:
            self.assertNotIn("safetensors", item["source_url"].lower())
        self.assertEqual(self.manifest["source"].get("downloaded_weight_bytes", 0), 0)

    def test_fixture_sidecar_install_is_atomic_and_reaches_tree_ready(self):
        content = b'{"_class_name":"fixture"}\n'
        digest = hashlib.sha256(content).hexdigest().upper()
        fixture_manifest = {
            "schema_version": 1,
            "source": {
                "repository": EXPECTED_REPOSITORY,
                "revision": self.manifest["source"]["revision"],
                "base_url": self.manifest["source"]["base_url"],
            },
            "license": self.manifest["license"],
            "files": [{
                "path": "FL2VA/model_index.json",
                "source_url": self.manifest["source"]["base_url"] + "FL2VA/model_index.json",
                "expected_size": len(content), "sha256": digest,
            }],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.bin"
            source.write_bytes(content)
            service = InstallationService(
                StudioStore(root / "data"), repo_root=ROOT,
                job_root=root / "jobs", cache_root=root / "cache",
            )
            item = {"component_id": service.H3_SIDECAR_COMPONENT,
                    "target": str(sidecar_target_root(root / "models"))}
            job = {"job_id": "fixture", "bytes_downloaded": 0,
                   "bytes_total": len(content), "progress": 0.0}
            with mock.patch.object(service, "_h3_sidecar_manifest", return_value=fixture_manifest), \
                 mock.patch.object(service, "_download_component", return_value=source):
                service._install_h3_sidecar(item, root / "models", job, threading.Event())
            state = validate_h3_sidecar_tree(root / "models", fixture_manifest)
            self.assertTrue(state["ready"])
            self.assertFalse((root / "models" / "diffusers" / "MiniMax-H3.installing").exists())

    def test_sidecar_checksum_failure_has_explicit_error_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = InstallationService(
                StudioStore(root / "data"), repo_root=ROOT,
                job_root=root / "jobs", cache_root=root / "cache",
            )
            with mock.patch.object(service, "_download_component",
                                  side_effect=InstallerError("CHECKSUM_MISMATCH", "bad")):
                with self.assertRaises(InstallerError) as caught:
                    service._install_h3_sidecar(
                        {"component_id": service.H3_SIDECAR_COMPONENT},
                        root / "models", {"job_id": "fixture"}, threading.Event())
            self.assertEqual(caught.exception.code, "H3_SUPPORT_DATA_HASH_MISMATCH")
            self.assertFalse((root / "models" / "diffusers" / "MiniMax-H3.installing").exists())

    def test_f1_model_root_contract_remains_unchanged(self):
        text = (ROOT / "runtime" / "h3_model_root.py").read_text(encoding="utf-8")
        self.assertIn("MINIMAX_H3_MODEL_ROOTS", text)
        self.assertIn("MINIMAX_H3_WEIGHTS_ROOTS", text)
        self.assertIn('"MODEL_PATH_FAILURE"', text)

    def test_no_gpu_or_prompt_in_sidecar_path(self):
        for path in (ROOT / "runtime" / "h3_sidecar.py",
                     ROOT / "apps" / "architect_video_studio" / "mock_api" / "installer_service.py"):
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("/prompt", text)

    def test_resume_and_cancel_contract_is_present(self):
        text = (ROOT / "apps" / "architect_video_studio" / "mock_api" /
                "installer_service.py").read_text(encoding="utf-8")
        self.assertIn("download_resumable", text)
        self.assertIn(".part", text)
        self.assertIn("INSTALL_CANCELLED", text)

    def test_sidecar_allow_list_uses_safe_relative_paths(self):
        for item in self.manifest["files"]:
            path = Path(item["path"])
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)

    def test_regression_delta_is_explicitly_recorded(self):
        report = (ROOT / "docs" / "PATCH2.8I2_R2BF2_H3_Sidecar_Provenance.md")
        if report.exists():
            text = report.read_text(encoding="utf-8")
            self.assertIn("35", text)


if __name__ == "__main__":
    unittest.main()
