from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.product_hardening import (
    asset_cache_token,
    classify_comfy_exit,
    estimate_eta,
    map_comfy_event,
    unique_comfy_filename,
)
from runtime.h3_generation_parameters import (
    H3ParameterError,
    normalize_generation_parameters,
)
from runtime.adapters.production_workflow_binding import build_production_payload
from runtime.h3_low_memory_profiles import (
    BALANCED, COMPATIBILITY, QUALITY, model_selection, select_profile,
    validate_profile_loader_contract,
)
from runtime.windows_integration import registration_plan
from apps.architect_video_studio.mock_api.job_api import _classify_failure
from runtime.workflow_motion import normalize_camera_motion


class TestProductHardening(unittest.TestCase):
    def test_authoritative_progress_event_and_eta(self):
        event = map_comfy_event({"type": "progress", "data": {"value": 17, "max": 25}})
        self.assertEqual(event["stage"], "视频采样")
        self.assertEqual(event["progress"], 68.0)
        self.assertAlmostEqual(estimate_eta(120, 68), 56.4705, places=2)

        draft = normalize_generation_parameters({"quality": "draft"}, seed=7)
        standard = normalize_generation_parameters({"quality": "standard"}, seed=7)
        high = normalize_generation_parameters({"quality": "high"}, seed=7)
        self.assertEqual((draft["sigma_points"], draft["sampler_mode"]), (21, "res_multistep"))
        self.assertEqual((standard["sigma_points"], standard["sampler_mode"]), (50, "euler"))
        self.assertEqual(high["resolution"], "1344x768")
        self.assertEqual(normalize_generation_parameters({"generation_speed": "auto"})["accel"], "auto")
        self.assertEqual(normalize_generation_parameters({"velocity_cache": True})["accel"], "manual-velocity")

    def test_unknown_progress_does_not_fake_percentage(self):
        self.assertIsNone(map_comfy_event({"type": "executing"})["progress"])
        self.assertIsNone(estimate_eta(10, None))
        with self.assertRaises(H3ParameterError):
            normalize_generation_parameters({"duration": 3})
        with self.assertRaises(H3ParameterError):
            normalize_generation_parameters({"duration": 16})
        with self.assertRaises(H3ParameterError):
            normalize_generation_parameters({"velocity_cache": True, "cache_dit": True})

    def test_crash_exit_classification(self):
        self.assertEqual(classify_comfy_exit(0xC0000005), "COMFYUI_NATIVE_CRASH")
        self.assertEqual(classify_comfy_exit(1), "COMFYUI_CRASHED")

    def test_asset_name_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "reference.png"
            source.write_bytes(b"one")
            asset = {"id": "ref-1", "sha256": "A" * 64}
            name = unique_comfy_filename(asset, source)
            self.assertEqual(name, "avs_ref-1_aaaaaaaaaaaa.png")
            self.assertTrue(asset_cache_token(asset))

        payload = build_production_payload(
            {
                "reference_assets": [{"path_or_ref": "reference.png"}],
                "generation_parameters": {
                    "duration": 8,
                    "resolution": "832x480",
                    "aspect_ratio": "16:9",
                    "quality": "draft",
                    "generation_speed": "standard",
                    "seed": 19,
                },
                "prompt_payload": {"prompt": "architectural walkthrough"},
            },
            "05_Slow_Walkthrough",
        )
        self.assertEqual(payload["6"]["inputs"]["width"], 832)
        self.assertEqual(payload["6"]["inputs"]["height"], 480)
        self.assertEqual(payload["6"]["inputs"]["length"], 203)
        self.assertEqual(payload["9"]["inputs"]["noise_seed"], 19)
        self.assertEqual(payload["2"]["inputs"]["clip_name"],
                         "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
        self.assertEqual(select_profile(gpu_vram_gb=12, system_ram_gb=32),
                         COMPATIBILITY)
        self.assertEqual(select_profile(gpu_vram_gb=20, system_ram_gb=48),
                         BALANCED)
        self.assertEqual(select_profile(gpu_vram_gb=24, system_ram_gb=64), QUALITY)
        self.assertEqual(model_selection(COMPATIBILITY)["text_encoder"],
                         "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
        self.assertNotEqual(model_selection(COMPATIBILITY)["text_encoder"],
                            "qwen3-vl-32b-int8_convrot.safetensors")
        self.assertTrue(validate_profile_loader_contract(
            model_selection(COMPATIBILITY, gpu_vram_gb=12, system_ram_gb=32)
        )["ready"])
        incompatible = model_selection(COMPATIBILITY)
        incompatible["text_encoder_loader"] = "runninghub_int8_convrot"
        self.assertEqual(validate_profile_loader_contract(incompatible)["code"],
                         "PROFILE_LOADER_INCOMPATIBLE")
        category, friendly = _classify_failure(ValueError(
            "camera_motion 'slow_push' not supported by 05_Slow_Walkthrough"))
        self.assertEqual(category, "WORKFLOW_PARAMETER_ERROR")
        self.assertEqual(friendly, "参数配置错误，请检查当前视频类型的设置。")
        expected_motion = {
            "01_Exterior_Hero": "slow_push",
            "02_Day_Night_Transition": "static",
            "03_Material_Detail": "static",
            "04_Drone_Aerial": "aerial_reveal",
            "05_Slow_Walkthrough": "walkthrough",
        }
        for workflow, motion in expected_motion.items():
            self.assertEqual(normalize_camera_motion(workflow), motion)

    def test_windows_registration_is_side_effect_free_plan(self):
        plan = registration_plan(Path("D:/ArchitectVideoStudio"))
        self.assertEqual(plan["app_name"], "Architect Video Studio")
        self.assertFalse(plan["startup_default"])
        self.assertIn("ArchitectVideoStudioDesktop.exe", plan["executable"])

    def test_environment_center_exposes_managed_comfy_restart(self):
        root = Path(__file__).resolve().parent.parent
        setup_html = (root / "apps" / "architect_video_studio" / "frontend" / "setup.html").read_text(encoding="utf-8")
        setup_js = (root / "apps" / "architect_video_studio" / "frontend" / "js" / "setup.js").read_text(encoding="utf-8")
        engine_js = (root / "apps" / "architect_video_studio" / "frontend" / "js" / "engine_status.js").read_text(encoding="utf-8")
        self.assertIn('id="restart-comfyui-btn"', setup_html)
        self.assertIn("/api/system/restart-comfyui", setup_js)
        self.assertIn("/api/system/restart-comfyui", engine_js)

    def test_advanced_comfyui_uses_current_studio_workflow_handoff(self):
        root = Path(__file__).resolve().parent.parent
        service = (root / "apps" / "architect_video_studio" / "mock_api" / "environment_service.py").read_text(encoding="utf-8")
        server = (root / "apps" / "architect_video_studio" / "mock_api" / "server.py").read_text(encoding="utf-8")
        jobs = (root / "apps" / "architect_video_studio" / "frontend" / "js" / "jobs.js").read_text(encoding="utf-8")
        shell = (root / "launcher" / "DesktopShell.cs").read_text(encoding="utf-8")
        self.assertIn("def current_workflow", service)
        self.assertIn("/api/system/current-workflow", server)
        self.assertIn("打开当前任务工作流", jobs)
        self.assertIn("workflow-reset-v3", shell)
        self.assertIn("loadGraphData", shell)
        root = Path(__file__).resolve().parent.parent
        nvfp4 = (root / "patches/support_layers/minimax_h3_nvfp4_native_loader.patch").read_text(encoding="utf-8")
        vae = (root / "patches/support_layers/minimax_h3_vae_offload_sync.patch").read_text(encoding="utf-8")
        reconcile = (root / "scripts/reconcile_h3_runtime_unification.py").read_text(encoding="utf-8")
        self.assertIn("load_native_nvfp4_text_encoder", nvfp4)
        self.assertIn("class NativeComfyNVFP4TextEncoder", nvfp4)
        self.assertNotIn("quant_meta =", nvfp4)
        self.assertIn("torch.cuda.synchronize()", vae)
        self.assertIn("nvfp4_patch_sha256", reconcile)
        self.assertIn('"model_files_modified": False', reconcile)
        setup = (root / "installer/Setup.ps1").read_text(encoding="utf-8")
        release_builder = (root / "release/build_shareable_release.py").read_text(encoding="utf-8")
        self.assertIn("Reconcile-H3RuntimeSupport", setup)
        self.assertIn("minimax_h3_nvfp4_native_loader.patch", release_builder)
        job_api = (root / "apps/architect_video_studio/mock_api/job_api.py").read_text(encoding="utf-8")
        service = (root / "apps/architect_video_studio/mock_api/environment_service.py").read_text(encoding="utf-8")
        launcher = (root / "launcher/launcher.py").read_text(encoding="utf-8")
        shell = (root / "launcher/DesktopShell.cs").read_text(encoding="utf-8")
        self.assertIn("workflow_snapshot_id", job_api)
        self.assertIn("persisted = selected_job.get(\"workflow_snapshot\") or {}", service)
        self.assertIn("h3_snapshot", service)
        self.assertIn("opened = False", launcher)
        self.assertIn("loadGraphData", shell)
        self.assertIn("cache:'no-store'", shell)


if __name__ == "__main__":
    unittest.main()
