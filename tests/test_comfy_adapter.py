"""Unit test for ComfyUI Workflow Parameter Adapter Engine.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.comfy_workflow_adapter import ComfyWorkflowAdapter

class TestComfyAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = ComfyWorkflowAdapter()

    def test_prepare_execution_payload(self):
        hw_params = {
            "width": 1280,
            "height": 720,
            "fps": 24,
            "duration_seconds": 5.0,
            "steps": 25,
            "profile_key": "H3_STANDARD"
        }
        payload = self.adapter.prepare_execution_payload(
            image_path="test_building.jpg",
            positive_prompt="Architectural rendering of villa",
            negative_prompt="warped geometry",
            hw_params=hw_params
        )

        self.assertIn("1", payload)
        self.assertEqual(payload["1"]["inputs"]["image"], "test_building.jpg")
        self.assertIn("6", payload)
        self.assertEqual(payload["6"]["inputs"]["prompt"], "Architectural rendering of villa")
        self.assertEqual(payload["11"]["inputs"]["filename_prefix"], "H3_V0.7.2_H3_STANDARD_Video")

if __name__ == "__main__":
    unittest.main()
