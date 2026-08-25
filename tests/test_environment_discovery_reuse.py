"""Release discovery/reuse tests for existing ComfyUI/H3 installations.

These tests use only small marker files.  They never load weights, start
ComfyUI, initialize CUDA, or perform downloads.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.environment_resolution import (  # noqa: E402
    resolve_active_environment,
)
from apps.architect_video_studio.mock_api.installer_service import InstallationService  # noqa: E402
from apps.architect_video_studio.mock_api.store import StudioStore  # noqa: E402


MODEL_NAMES = {
    "diffusion_models": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "text_encoders": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "vae": "minimax_h3_video_vae_fp16.safetensors",
}


def make_native(root: Path) -> Path:
    (root / "python_embeded").mkdir(parents=True)
    (root / "python_embeded" / "python.exe").write_bytes(b"marker")
    (root / "ComfyUI").mkdir()
    (root / "ComfyUI" / "main.py").write_text("main", encoding="utf-8")
    custom = root / "ComfyUI" / "custom_nodes"
    (custom / "windows_safe_load").mkdir(parents=True)
    h3 = custom / "ComfyUI_RH_MinMaxH3"
    h3.mkdir()
    (h3 / "nodes.py").write_text(
        "RHMiniMaxH3ModelLoader RHMiniMaxH3FL2VAEncode", encoding="utf-8")
    vhs = custom / "ComfyUI-VideoHelperSuite"
    vhs.mkdir()
    (vhs / "nodes.py").write_text("VHS_VideoCombine", encoding="utf-8")
    return root


def make_models(root: Path) -> Path:
    for subdir, filename in MODEL_NAMES.items():
        path = root / subdir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"marker")
    audio = root / "vae" / "minimax_h3_audio_vae_fp32.safetensors"
    audio.write_bytes(b"marker")
    return root


class TestEnvironmentDiscoveryReuse(unittest.TestCase):
    def test_auto_discovery_replaces_empty_install_target(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            healthy_native = make_native(root / "other-drive" / "ComfyUI_windows_portable")
            healthy_models = make_models(healthy_native / "ComfyUI" / "models")
            with mock.patch.dict(os.environ, {
                "H3_NATIVE_ROOT": str(healthy_native),
                "H3_MODELS_ROOT": str(healthy_models),
                "H3_WINDOWS_SAFE_LOAD": "pread",
            }, clear=False):
                with mock.patch(
                    "apps.architect_video_studio.mock_api.environment_resolution.discover_existing_native",
                    return_value=healthy_native):
                    with mock.patch(
                        "apps.architect_video_studio.mock_api.environment_resolution.discover_existing_models",
                        return_value=healthy_models):
                        active = resolve_active_environment(
                            ROOT,
                            {"native_root": str(root / "app" / "runtime"),
                             "models_root": str(root / "app" / "models")},
                            os.environ,
                            auto_discover=True,
                        )
            self.assertEqual(active.native_root, healthy_native.resolve())
            self.assertEqual(active.models_root, healthy_models.resolve())
            self.assertEqual(active.source, "auto_discovered_existing_runtime")

    def test_h3_root_environment_is_normalized_to_comfy_models_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            native = make_native(root / "ComfyUI")
            models = make_models(native / "ComfyUI" / "models")
            with mock.patch.dict(os.environ, {
                "H3_NATIVE_ROOT": str(native),
                "H3_MODELS_ROOT": "",
                "MINIMAX_H3_MODEL_ROOTS": str(models / "MiniMax-H3"),
                "MINIMAX_H3_WEIGHTS_ROOTS": str(models / "MiniMax-H3"),
            }, clear=False):
                active = resolve_active_environment(
                    ROOT, {}, os.environ, auto_discover=True)
            self.assertEqual(active.models_root, models.resolve())

    def test_installer_uses_discovered_pair_before_planning_downloads(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            healthy_native = make_native(root / "existing" / "Runtime")
            healthy_models = make_models(root / "shared" / "models")
            store = StudioStore(root / "studio")
            store_path = store.data_root.parent / "system" / "setup_state.json"
            store_path.parent.mkdir(parents=True, exist_ok=True)
            store_path.write_text(
                '{"native_root":"%s","models_root":"%s"}' %
                (root / "new" / "runtime", root / "new" / "models"),
                encoding="utf-8")
            installer = InstallationService(
                store, repo_root=ROOT, job_root=root / "jobs", cache_root=root / "cache")
            with mock.patch.dict(os.environ, {
                "H3_NATIVE_ROOT": str(healthy_native),
                "H3_MODELS_ROOT": str(healthy_models),
                "H3_WINDOWS_SAFE_LOAD": "pread",
            }, clear=False):
                native, models = installer._configured_roots()
            self.assertEqual(native, healthy_native.resolve())
            self.assertEqual(models, healthy_models.resolve())

    def test_discovery_is_opt_in_for_library_callers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            healthy = make_native(root / "existing")
            with mock.patch.dict(os.environ, {
                "H3_NATIVE_ROOT": str(healthy),
                "H3_MODELS_ROOT": "",
            }, clear=False):
                active = resolve_active_environment(
                    ROOT, {}, {
                        "H3_NATIVE_ROOT": "",
                        "H3_MODELS_ROOT": "",
                        "H3_WINDOWS_SAFE_LOAD": "pread",
                    })
            self.assertIsNone(active.native_root)


if __name__ == "__main__":
    unittest.main()
