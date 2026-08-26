"""PATCH2.8-I2-R2B-F1 H3 model-root contract tests.

All tests are path-only. The managed-runtime probe hides CUDA and never calls
ComfyUI /prompt or a model tensor loader.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from runtime.h3_model_root import (
    H3_MODEL_ROOTS_ENV,
    H3_WEIGHTS_ROOTS_ENV,
    canonical_h3_model_root,
    h3_process_environment,
    h3_model_root_bridge_status,
    h3_model_root_bridge_target,
    model_root_trace,
    validate_h3_model_contract,
)
from runtime.adapters.production_workflow_binding import (
    CANONICAL_WORKFLOWS,
    build_production_payload,
    load_registry,
)
from launcher.process_manager import ProcessManager


ROOT = Path(__file__).resolve().parents[1]
MANAGED = Path(r"D:\\ProgramFilesNormal\\ComfyUI\\ArchitectVideoStudio_Runtime")
MODELS = Path(r"D:\\ProgramFilesNormal\\ComfyUI\\Models")


class H3ModelRootContractTests(unittest.TestCase):
    def test_contract_uses_pinned_plugin_environment_names(self):
        manifest = (ROOT / "configs" / "installation_manifest.yaml").read_text(encoding="utf-8")
        self.assertIn("MINIMAX_H3_MODEL_ROOTS", manifest)
        self.assertIn("MINIMAX_H3_WEIGHTS_ROOTS", manifest)
        self.assertIn("MiniMax-H3", manifest)

    def test_canonical_root_is_derived_from_selected_models_root(self):
        self.assertEqual(canonical_h3_model_root(MODELS), MODELS / "MiniMax-H3")
        self.assertEqual(canonical_h3_model_root(MODELS / "MiniMax-H3"), MODELS / "MiniMax-H3")

    def test_runtime_bridge_target_is_derived_from_selected_roots(self):
        self.assertEqual(
            h3_model_root_bridge_target(MANAGED),
            MANAGED / "ComfyUI" / "models" / "MiniMax-H3",
        )

    def test_missing_bridge_is_reported_without_mutation(self):
        with __import__("tempfile").TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            models = root / "Models"
            (models / "MiniMax-H3").mkdir(parents=True)
            status = h3_model_root_bridge_status(runtime, models)
            self.assertEqual(status["status"], "MISSING")
            self.assertFalse(status["ready"])
            self.assertFalse((runtime / "ComfyUI").exists())

    def test_process_environment_has_both_pinned_root_contracts(self):
        env = h3_process_environment(MODELS)
        self.assertEqual(env[H3_MODEL_ROOTS_ENV], str(MODELS / "MiniMax-H3"))
        self.assertEqual(env[H3_WEIGHTS_ROOTS_ENV], str(MODELS / "MiniMax-H3"))

    def test_managed_comfyui_child_receives_both_root_variables(self):
        with mock.patch.dict(os.environ, {"H3_MODELS_ROOT": str(MODELS)}, clear=False):
            manager = ProcessManager(
                native_root=MANAGED, repo_root=ROOT,
                python=MANAGED / "python_embeded" / "python.exe", dry_run=True,
            )
            env_extra = manager.comfyui_service().env_extra
        self.assertEqual(env_extra[H3_MODEL_ROOTS_ENV], str(MODELS / "MiniMax-H3"))
        self.assertEqual(env_extra[H3_WEIGHTS_ROOTS_ENV], str(MODELS / "MiniMax-H3"))

    def test_trace_does_not_scan_legacy_or_test_runtime(self):
        trace = model_root_trace(MODELS, {})
        paths = {item["path"] for item in trace["candidates"]}
        self.assertEqual(paths, {str(MODELS / "MiniMax-H3")})
        self.assertNotIn("ComfyUI_H3_NATIVE_TEST", "\n".join(paths))
        self.assertNotIn("ArchitectVideoStudio_Runtime", "\n".join(paths))

    def test_missing_root_is_model_path_failure(self):
        missing = ROOT / "tests" / "fixtures" / "f1_missing_models"
        result = validate_h3_model_contract(MANAGED, missing, {})
        self.assertEqual(result["status"], "CONFIGURATION_REQUIRED")
        self.assertFalse(result["ready"])
        self.assertEqual(result["failure_code"], "MODEL_PATH_FAILURE")

    def test_no_native_path_does_not_fallback(self):
        result = validate_h3_model_contract(None, MODELS, {})
        self.assertEqual(result["status"], "NEEDS_PATH")
        self.assertFalse(result["ready"])

    def test_real_shared_root_and_all_loader_paths_resolve_without_gpu(self):
        if not (MANAGED / "python_embeded" / "python.exe").is_file():
            self.skipTest("managed Runtime unavailable on this machine")
        if not (MODELS / "MiniMax-H3").is_dir():
            self.skipTest("shared H3 root unavailable on this machine")
        result = validate_h3_model_contract(MANAGED, MODELS, {})
        self.assertEqual(result["status"], "READY", result.get("error"))
        self.assertTrue(result["ready"])
        self.assertTrue(result["bridge"]["ready"])
        self.assertEqual(Path(result["canonical_root"]), MODELS / "MiniMax-H3")
        for key in ("transformer", "text_encoder", "video_vae", "audio_vae", "tokenizer", "processor"):
            self.assertTrue(Path(result["components"][key]).is_dir(), key)
        self.assertEqual(set(result["weights"]), {"transformer", "text_encoder", "video_vae", "audio_vae"})
        self.assertEqual(result["missing"], [])

    def test_existing_four_weights_are_reused(self):
        expected = {
            "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors": 20970379616,
            "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors": 15687142551,
            "vae/minimax_h3_video_vae_fp16.safetensors": 5207808496,
            "vae/minimax_h3_audio_vae_fp32.safetensors": 605254808,
        }
        for relative, size in expected.items():
            path = MODELS / relative
            if path.is_file():
                self.assertEqual(path.stat().st_size, size, relative)

    def test_no_workflow_changes_are_needed(self):
        request = {
            "reference_assets": [{"path_or_ref": "reference.png"}],
            "generation_parameters": {"resolution": "1344x768", "fps": 24, "duration": 4.0},
            "prompt_payload": {"prompt": "diagnostic"},
        }
        for workflow in CANONICAL_WORKFLOWS:
            count = 2 if load_registry()["workflows"][workflow]["input_mode"] == "FL2VA" else 1
            request["reference_assets"] = [
                {"path_or_ref": f"reference-{index}.png"} for index in range(count)
            ]
            payload = build_production_payload(request, workflow)
            self.assertEqual(payload["2"]["inputs"]["clip_name"],
                             "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
            self.assertEqual(payload["3"]["class_type"], "UNETLoader")
            self.assertEqual(payload["4"]["class_type"], "VAELoader")

    def test_no_prompt_submission_in_contract_module(self):
        source = (ROOT / "runtime" / "h3_model_root.py").read_text(encoding="utf-8")
        self.assertNotIn("/prompt", source)
        self.assertNotIn("torch.cuda", source)

    def test_no_global_setx_or_developer_path_in_new_contract(self):
        source = (ROOT / "runtime" / "h3_model_root.py").read_text(encoding="utf-8")
        self.assertNotIn("setx", source.lower())
        self.assertNotIn(r"D:ProgramFilesNormal", source)

    def test_models_manifest_declares_logical_h3_root(self):
        data = json.loads((ROOT / "models" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["h3_model_root"]["directory_name"], "MiniMax-H3")
        self.assertEqual(
            data["h3_model_root"]["resolver_environment"]["model_roots"],
            H3_MODEL_ROOTS_ENV,
        )

    def test_installer_uses_junction_and_never_copies_h3_weights(self):
        source = (ROOT / "installer" / "Setup.ps1").read_text(encoding="utf-8")
        self.assertIn("Ensure-H3ModelRootBridge", source)
        self.assertIn("ItemType Junction", source)
        self.assertIn("targetItem.Target", source)
        self.assertIn('targetItem.LinkType -eq "Junction"', source)
        self.assertNotIn("Copy-Item -LiteralPath $source", source)


if __name__ == "__main__":
    unittest.main()
