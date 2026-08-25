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
from runtime.windows_integration import registration_plan


class TestProductHardening(unittest.TestCase):
    def test_authoritative_progress_event_and_eta(self):
        event = map_comfy_event({"type": "progress", "data": {"value": 17, "max": 25}})
        self.assertEqual(event["stage"], "视频采样")
        self.assertEqual(event["progress"], 68.0)
        self.assertAlmostEqual(estimate_eta(120, 68), 56.4705, places=2)

    def test_unknown_progress_does_not_fake_percentage(self):
        self.assertIsNone(map_comfy_event({"type": "executing"})["progress"])
        self.assertIsNone(estimate_eta(10, None))

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

    def test_windows_registration_is_side_effect_free_plan(self):
        plan = registration_plan(Path("D:/ArchitectVideoStudio"))
        self.assertEqual(plan["app_name"], "Architect Video Studio")
        self.assertFalse(plan["startup_default"])
        self.assertIn("ArchitectVideoStudioDesktop.exe", plan["executable"])


if __name__ == "__main__":
    unittest.main()
