"""R2B1.1 binding tests; no ComfyUI submission, model download, or GPU work."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.adapters.production_workflow_binding import (  # noqa: E402
    CANONICAL_WORKFLOWS,
    build_production_payload,
    deploy_production_collection,
    load_registry,
    validate_frozen_capability,
    validate_production_payload,
)
from runtime.adapters.native_runtime_adapter import NativeRuntimeAdapter  # noqa: E402
from runtime.adapters.runtime_adapter import VideoGenerationRequest  # noqa: E402


def request(workflow: str) -> dict:
    mode = "FL2VA" if workflow == "02_Day_Night_Transition" else "I2VA"
    refs = [{"path_or_ref": "first.png", "role": "first_frame"}]
    if mode == "FL2VA":
        refs.append({"path_or_ref": "last.png", "role": "last_frame"})
    return {
        "study_id": "r2b11-test",
        "reference_assets": refs,
        "workflow_id": workflow,
        "camera_motion": "static" if workflow == "02_Day_Night_Transition" else (
            "aerial_reveal" if workflow == "04_Drone_Aerial" else "slow_push"),
        "generation_parameters": {"resolution": "1344x768", "fps": 24, "duration": 4.0, "seed": 7},
        "prompt_payload": {"mode": mode, "prompt": "official prompt", "prompt_hash": "a" * 64},
        "output_spec": {"container": "mp4", "codec": "h264", "fps": 24,
                        "resolution": "1344x768", "report_format": "json"},
        "gates": {"reference_approved": True, "intent_confirmed": True,
                  "prompt_verified": True, "risk_reviewed": True},
    }


class _BindingClient:
    """Offline ComfyUI contract stub; this test validates binding only."""

    def health_check(self):
        return {"status": "ok"}

    def object_info(self):
        names = (
            "LoadImage", "UNETLoader", "CLIPLoader", "VAELoader",
            "RHMiniMaxH3DecodeAV", "RHMiniMaxH3DualSigmaSampler",
            "RHMiniMaxH3EmptyAVLatent", "RHMiniMaxH3FL2VAEncode",
            "RHMiniMaxH3FL2VAFirstFrameCondition", "RHMiniMaxH3FL2VATarget",
            "RHMiniMaxH3ModelLoader", "RHMiniMaxH3TextEncoderLoader",
            "RHMiniMaxH3T2VATextEncode", "RHMiniMaxH3VAELoader", "VHS_VideoCombine")
        inputs = {
            "LoadImage": "image", "UNETLoader": "unet_name",
            "CLIPLoader": "clip_name", "VAELoader": "vae_name",
        }
        result = {name: {} for name in names}
        for node, input_name in inputs.items():
            result[node] = {"input": {"required": {input_name: [[
                "example.png" if node == "LoadImage" else (
                    "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
                    if node == "UNETLoader" else (
                        "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
                        if node == "CLIPLoader" else "minimax_h3_video_vae_fp16.safetensors"
                    )
                )
            ]]}}}
        return result


class TestProductionConsolidation(unittest.TestCase):
    def test_exactly_one_active_source_and_no_implicit_fallback(self):
        data = json.loads((ROOT / "configs/production_runtime_binding.json").read_text())
        self.assertEqual(data["active_role"], "ACTIVE_PRODUCTION_NATIVE")
        self.assertEqual(data["selection_policy"][-1], "SETUP_REQUIRED")
        self.assertIn("retired validation runtime", data["forbidden_implicit_fallbacks"])

    def test_support_fingerprints_are_immutable(self):
        data = json.loads((ROOT / "configs/production_runtime_binding.json").read_text())
        self.assertEqual(len(data["support_layers"]["minimax_h3_nodes"]["commit"]), 40)
        self.assertEqual(len(data["support_layers"]["video_helper_suite"]["commit"]), 40)
        self.assertEqual(data["support_layers"]["pread"], "H3_WINDOWS_SAFE_LOAD=pread")

    def test_registry_has_exactly_five_project_workflows(self):
        self.assertEqual(tuple(load_registry()["workflows"]), CANONICAL_WORKFLOWS)
        for entry in load_registry()["workflows"].values():
            self.assertTrue((ROOT / entry["canonical_source"]).is_file())
            self.assertTrue((ROOT / entry["payload_template"]).is_file())

    def test_payloads_have_explicit_images_models_and_prompt(self):
        for workflow in CANONICAL_WORKFLOWS:
            payload = build_production_payload(request(workflow), workflow)
            classes = {node["class_type"] for node in payload.values()}
            self.assertNotIn("MiniMaxH3ImageToVideo", classes)
            self.assertIn("RHMiniMaxH3ModelLoader", classes)
            self.assertIn("RHMiniMaxH3TextEncoderLoader", classes)
            self.assertIn("RHMiniMaxH3VAELoader", classes)
            self.assertIn("VHS_VideoCombine", classes)
            self.assertEqual(payload["1"]["inputs"]["image"], "first.png")
            self.assertEqual(payload["7"]["inputs"]["prompt"], "official prompt")

    def test_all_payloads_resolve_against_frozen_node_contract(self):
        object_info = {name: {} for name in (
            "LoadImage", "RHMiniMaxH3DecodeAV", "RHMiniMaxH3DualSigmaSampler",
            "RHMiniMaxH3EmptyAVLatent", "RHMiniMaxH3FL2VAEncode",
            "RHMiniMaxH3FL2VAFirstFrameCondition", "RHMiniMaxH3FL2VATarget",
            "RHMiniMaxH3ModelLoader", "RHMiniMaxH3TextEncoderLoader",
            "RHMiniMaxH3T2VATextEncode", "RHMiniMaxH3VAELoader", "VHS_VideoCombine")}
        for workflow in CANONICAL_WORKFLOWS:
            result = validate_production_payload(build_production_payload(request(workflow), workflow), object_info)
            self.assertEqual(result["unknown_node_types"], [])
            self.assertTrue(result["ready"])
        self.assertTrue(validate_frozen_capability(object_info)["ready"])

    def test_missing_node_is_runtime_mismatch_not_gpu_failure(self):
        self.assertEqual(NativeRuntimeAdapter._execution_error_code("missing_node_type: MiniMaxH3ImageToVideo"), "MISSING_RUNTIME_NODE")

    def test_native_adapter_production_mode_ignores_browser_graph(self):
        adapter = NativeRuntimeAdapter(client=_BindingClient(), production_binding=True)
        prepared = adapter.prepare(VideoGenerationRequest.from_dict(request("04_Drone_Aerial")))
        self.assertTrue(prepared["binding"]["browser_state_ignored"])
        self.assertNotIn("MiniMaxH3ImageToVideo", {n["class_type"] for n in prepared["translated_payload"].values()})

    def test_no_model_copy_or_download_in_binding_module(self):
        source = (ROOT / "runtime/adapters/production_workflow_binding.py").read_text()
        self.assertNotIn("urlopen", source)

    def test_collection_deployment_is_exactly_five_and_idempotent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            first = deploy_production_collection(Path(tmp))
            second = deploy_production_collection(Path(tmp))
            self.assertEqual(len(first), 5)
            self.assertEqual({p.name for p in first}, {p.name for p in second})
            self.assertEqual(len(list((Path(tmp) / "ComfyUI/user/default/workflows/ARCHITECTURE_PRODUCTION").glob("*.json"))), 5)

    def test_ui_has_no_development_identity_labels(self):
        frontend = ROOT / "apps/architect_video_studio/frontend"
        visible = "\n".join(p.read_text(encoding="utf-8") for p in frontend.glob("*.html"))
        self.assertNotIn("Mock", visible)
        self.assertNotIn("PATCH2.6-D", visible)


if __name__ == "__main__":
    unittest.main()
