"""CPU/static validation for the selected-root ComfyUI model contract."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from launcher.process_manager import ProcessManager
from runtime.adapters.production_workflow_binding import (
    CANONICAL_WORKFLOWS,
    validate_all_ui_workflow_model_bindings,
)
from runtime.h3_model_root import (
    render_comfy_model_paths_config,
    write_comfy_model_paths_config,
)


def _live_object_info() -> dict:
    return {
        "LoadImage": {"input": {"required": {"image": [["example.png"]]}}},
        "UNETLoader": {"input": {"required": {"unet_name": [[
            "minimax_h3_fl2va_pruned_int8_convrot.safetensors"]]}}},
        "CLIPLoader": {"input": {"required": {"clip_name": [[
            "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"]],
            "type": [["minimax"]]}}},
        "VAELoader": {"input": {"required": {"vae_name": [[
            "minimax_h3_video_vae_fp16.safetensors"]]}}},
    }


class TestFinalModelPathWorkflowBinding(unittest.TestCase):
    def test_all_five_workflows_match_live_comfy_enums(self):
        result = validate_all_ui_workflow_model_bindings(_live_object_info())
        self.assertTrue(result["ready"])
        self.assertEqual(set(result["workflows"]), set(CANONICAL_WORKFLOWS))

    def test_stale_category_prefix_is_rejected(self):
        from runtime.adapters.production_workflow_binding import validate_ui_workflow_model_bindings
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stale.json"
            path.write_text(
                '{"nodes":[{"type":"UNETLoader","widgets_values":["diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors"]}]}',
                encoding="utf-8")
            result = validate_ui_workflow_model_bindings(path, _live_object_info())
        self.assertFalse(result["ready"])
        self.assertEqual(result["errors"][0]["reason"], "value_not_in_live_comfyui_enum")

    def test_generated_config_uses_selected_root_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shared models"
            target = Path(tmp) / "data" / "paths.yaml"
            written = write_comfy_model_paths_config(root, target)
            text = written.read_text(encoding="utf-8")
        self.assertIn(root.as_posix(), text)
        self.assertIn("diffusion_models", text)
        self.assertNotIn("D:/ProgramFilesNormal", text)

    def test_process_manager_passes_generated_config_to_comfy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, {"H3_MODELS_ROOT": str(root / "models")}, clear=False):
                manager = ProcessManager(
                    native_root=root / "native", repo_root=root / "repo",
                    python=root / "native" / "python.exe",
                    studio_data=root / "data", dry_run=True)
                service = manager.comfyui_service()
            self.assertIn("--extra-model-paths-config", service.command)
            config_index = service.command.index("--extra-model-paths-config") + 1
            self.assertTrue(Path(service.command[config_index]).is_file())


if __name__ == "__main__":
    unittest.main()
