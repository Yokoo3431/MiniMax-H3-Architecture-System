"""PATCH2.8-I2-R2B1.2 managed-runtime promotion contracts.

These tests inspect the explicit local promotion state and use synthetic
object_info for payload checks.  They never download, copy models, or submit
an inference prompt.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.architect_video_studio.mock_api.yaml_compat import safe_load  # noqa: E402
from runtime.adapters.production_workflow_binding import (  # noqa: E402
    CANONICAL_WORKFLOWS,
    build_production_payload,
    deploy_production_collection,
    validate_production_payload,
)
from runtime.production_roles import (  # noqa: E402
    ACTIVE_PRODUCTION_NATIVE,
    LEGACY_VALIDATED_REFERENCE,
    TEST_RUNTIME,
    can_promote_validation_runtime,
    is_managed_runtime_path,
)
from runtime.support_layer import source_tree_fingerprint  # noqa: E402


def _state() -> dict:
    return json.loads((ROOT / "userdata/system/setup_state.json").read_text(encoding="utf-8"))


def _managed_root() -> Path:
    return Path((ROOT / "native_env.path").read_text(encoding="utf-8").strip())


def _request(workflow: str) -> dict:
    mode = "FL2VA" if workflow == "02_Day_Night_Transition" else "I2VA"
    refs = [{"path_or_ref": "first.png", "role": "first_frame"}]
    if mode == "FL2VA":
        refs.append({"path_or_ref": "last.png", "role": "last_frame"})
    return {
        "study_id": "r2b12-test",
        "reference_assets": refs,
        "workflow_id": workflow,
        "camera_motion": "static",
        "generation_parameters": {"resolution": "1344x768", "fps": 24, "duration": 4.0, "seed": 7},
        "prompt_payload": {"mode": mode, "prompt": "official prompt", "prompt_hash": "a" * 64},
        "output_spec": {"container": "mp4", "codec": "h264", "fps": 24,
                        "resolution": "1344x768", "report_format": "json"},
        "gates": {"reference_approved": True, "intent_confirmed": True,
                  "prompt_verified": True, "risk_reviewed": True},
    }


class TestManagedRuntimePromotion(unittest.TestCase):
    def test_one_explicit_active_runtime(self):
        state = _state()
        self.assertEqual(state["active_role"], ACTIVE_PRODUCTION_NATIVE)
        self.assertEqual(Path((ROOT / "native_env.path").read_text().strip()).resolve(), _managed_root().resolve())
        self.assertTrue(is_managed_runtime_path(_managed_root()))

    def test_legacy_and_test_runtime_roles_are_preserved(self):
        state = _state()
        self.assertIsNone(state["legacy_validated_reference"])
        self.assertIsNone(state["test_runtime"])
        self.assertEqual(LEGACY_VALIDATED_REFERENCE, "LEGACY_VALIDATED_REFERENCE")
        self.assertEqual(TEST_RUNTIME, "TEST_RUNTIME")

    def test_validation_runtime_cannot_silently_self_promote(self):
        state = _state()
        self.assertIsNone(state["validation_runtime"])
        self.assertTrue(can_promote_validation_runtime(
            ROOT / "validation/runtime_native_v0331",
            Path("D:/ProgramFilesNormal/ComfyUI/ArchitectVideoStudio_Runtime")))
        self.assertFalse(can_promote_validation_runtime(
            ROOT / "validation/runtime_native_v0331",
            ROOT / "validation/runtime_native_v0331"))

    def test_managed_runtime_contract(self):
        root = _managed_root()
        self.assertTrue(root.is_dir())
        version = json.loads((root / "runtime_version.json").read_text(encoding="utf-8"))
        self.assertEqual(version["comfyui"], "0.33.1")
        self.assertEqual(version["frontend"], "1.48.7")
        self.assertTrue(version["python"].startswith("Python 3.13."))
        self.assertEqual(version["torch"], "2.13.0+cu130")

    def test_exact_support_lock_and_pread(self):
        root = _managed_root()
        lock = json.loads((root / "ComfyUI/custom_nodes/support_layer.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["h3"]["commit"], "d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad")
        self.assertEqual(lock["h3"]["source_tree_fingerprint"], "887ddf87371e703f27c52694d849171e90ef455a52a2ae811aa3b8b934c38ae0")
        self.assertEqual(lock["h3"]["strategy_a"]["target_dtype"], "bfloat16")
        self.assertEqual(lock["h3"]["strategy_a"]["visual_dtype"], "preserved_fp32")
        self.assertEqual(lock["h3"]["memory_policy"]["name"], "static_transfer_safety_margin")
        self.assertEqual(lock["h3"]["memory_policy"]["status"], "CPU_META_POLICY_IMPLEMENTED")
        self.assertEqual(lock["h3"]["strategy_a"]["language_boundary_instrumentation_patch_sha256"], "67ca71fd28ddedf7cad6f3bb837b6b825ee08145efe518671574e19522dad2ac")
        self.assertEqual(lock["h3"]["strategy_a"]["language_boundary_instrumentation"]["status"], "OBSERVATIONAL_CPU_VALIDATED")
        self.assertEqual(lock["h3"]["strategy_a"]["static_transfer_headroom_patch_sha256"], "c6342b0417f9adb8dacfb72cdacab9a6c58500a0fb7ee27192eca098148e5aeb")
        self.assertEqual(lock["h3"]["strategy_a"]["static_transfer_headroom"]["method"], "ModelPatcher.partially_unload")
        self.assertTrue(lock["h3"]["strategy_a"]["static_transfer_headroom"]["before_static_transfer"])
        self.assertEqual(lock["video_helper_suite"]["commit"], "4ee72c065db22c9d96c2427954dc69e7b908444b")
        self.assertEqual(lock["video_helper_suite"]["source_tree_fingerprint"], "5d881ddec68ee6deec3140f58c26e6b397ae82ad6a9aaa92c933c1e770101a82")
        self.assertEqual(lock["pread"]["environment"], "H3_WINDOWS_SAFE_LOAD=pread")
        self.assertEqual(source_tree_fingerprint(root / "ComfyUI/custom_nodes/ComfyUI_RH_MinMaxH3"), lock["h3"]["source_tree_fingerprint"])
        self.assertEqual(source_tree_fingerprint(root / "ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite"), lock["video_helper_suite"]["source_tree_fingerprint"])

    def test_shared_models_root_is_explicit_and_not_copied(self):
        state = _state()
        models = Path(state["models_root"])
        self.assertTrue(models.is_dir())
        self.assertNotEqual(models.resolve(), (_managed_root() / "ComfyUI/models").resolve())
        extra = (_managed_root() / "ComfyUI/extra_model_paths.yaml").read_text(encoding="utf-8")
        self.assertIn("architect_studio_models", extra)
        self.assertIn("D:/ProgramFilesNormal/ComfyUI/Models", extra)
        self.assertNotIn("ComfyUI_windows_portable/ComfyUI/models", extra)

    def test_five_payloads_have_zero_unknown_nodes_and_no_stale_node(self):
        names = {
            "LoadImage", "RHMiniMaxH3DecodeAV", "RHMiniMaxH3DualSigmaSampler",
            "RHMiniMaxH3EmptyAVLatent", "RHMiniMaxH3FL2VAEncode",
            "RHMiniMaxH3FL2VAFirstFrameCondition", "RHMiniMaxH3FL2VATarget",
            "RHMiniMaxH3ModelLoader", "RHMiniMaxH3TextEncoderLoader",
            "RHMiniMaxH3T2VATextEncode", "RHMiniMaxH3VAELoader", "VHS_VideoCombine",
        }
        object_info = {name: {} for name in names}
        for workflow in CANONICAL_WORKFLOWS:
            payload = build_production_payload(_request(workflow), workflow)
            result = validate_production_payload(payload, object_info)
            self.assertEqual(result["unknown_node_types"], [])
            self.assertNotIn("MiniMaxH3ImageToVideo", {n["class_type"] for n in payload.values()})

    def test_architecture_production_is_exactly_five_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = deploy_production_collection(Path(tmp))
            second = deploy_production_collection(Path(tmp))
            self.assertEqual({p.name for p in first}, {p.name for p in second})
            self.assertEqual(len(list((Path(tmp) / "ComfyUI/user/default/workflows/ARCHITECTURE_PRODUCTION").glob("*.json"))), 5)

    def test_installer_converges_on_managed_baseline(self):
        install = safe_load((ROOT / "configs/installation_manifest.yaml").read_text(encoding="utf-8"))
        support = safe_load((ROOT / "configs/support_layer_manifest.yaml").read_text(encoding="utf-8"))
        self.assertEqual(install["runtime"]["comfyui"]["version"], "0.33.1")
        self.assertEqual(install["runtime"]["frontend"]["version"], "1.48.7")
        self.assertEqual(support["support_layers"]["minimax_h3_nodes"]["commit"], "d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad")
        self.assertEqual(support["support_layers"]["video_helper_suite"]["commit"], "4ee72c065db22c9d96c2427954dc69e7b908444b")
        self.assertEqual(install["support_layers"]["promotion_policy"]["active_role"], ACTIVE_PRODUCTION_NATIVE)

    def test_entry_points_use_persisted_active_runtime_without_validation_fallback(self):
        for name in ("Start_ArchitectVideoStudio.bat", "Open_Native_ComfyUI.bat", "launcher/bootstrap.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("validation\\runtime_native_v0331\\python_embeded", text)
        self.assertNotIn("D:\\ProgramFilesNormal\\ComfyUI", (ROOT / "Start_ArchitectVideoStudio.bat").read_text(encoding="utf-8"))

    def test_no_gpu_or_model_download_in_promotion_contract(self):
        text = (ROOT / "runtime/production_roles.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("download", text)
        self.assertNotIn("copy", text)
        self.assertNotIn("prompt", text)

    def test_ui_identity_regression_absent(self):
        visible = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "apps/architect_video_studio/frontend").glob("*.html"))
        self.assertNotIn("Mock", visible)
        self.assertNotIn("Prototype", visible)
        self.assertNotIn("PATCH2.6-D", visible)


if __name__ == "__main__":
    unittest.main()
