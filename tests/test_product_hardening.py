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
        self.assertEqual(payload["6"]["inputs"]["duration_seconds"], 8.0)
        self.assertEqual(payload["9"]["inputs"]["sigma_points"], 21)
        self.assertEqual(payload["9"]["inputs"]["accel"], "off")
        self.assertEqual(payload["6"]["inputs"]["aspect_ratio"], "16:9")
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


if __name__ == "__main__":
    unittest.main()
