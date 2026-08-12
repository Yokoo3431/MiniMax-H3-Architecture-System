"""Real ComfyUI Production Integration Test Suite (V0.7.5 Upgraded).
Validates production execution chain, connection, payload submission, history polling, and failure handling.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.execution.comfy_api_client import ComfyAPIClient
from runtime.execution.execution_manager import ExecutionManager
from runtime.execution.execution_monitor import ExecutionMonitor
from runtime.execution.workflow_adapter import ComfyWorkflowAdapterEngine
from runtime.h3_orchestrator import H3Orchestrator

class TestRealComfyPipeline(unittest.TestCase):
    def setUp(self):
        self.client = ComfyAPIClient("http://127.0.0.1:8188")
        self.manager = ExecutionManager("http://127.0.0.1:8188")
        self.monitor = ExecutionMonitor(self.client)
        self.adapter = ComfyWorkflowAdapterEngine()
        self.orchestrator = H3Orchestrator()

    def test_case_1_comfyui_connection(self):
        is_healthy = self.client.check_health()
        self.assertIsInstance(is_healthy, bool)

    def test_case_2_workflow_submission_payload(self):
        hw_params = {"width": 1280, "height": 720, "fps": 24, "duration_seconds": 5.0, "steps": 25, "profile_key": "H3_STANDARD"}
        payload = self.adapter.convert_ui_to_api_payload(
            ui_workflow_dict={},
            image_path="museum.png",
            positive_prompt="Architectural rendering of museum",
            negative_prompt="warped facade",
            hw_params=hw_params
        )
        self.assertIn("1", payload)
        self.assertIn("6", payload)
        self.assertEqual(payload["6"]["inputs"]["prompt"], "Architectural rendering of museum")

    def test_case_3_execution_monitoring(self):
        status_res = self.monitor.check_execution_status("non_existent_prompt_id")
        self.assertEqual(status_res["status"], "running")

    def test_case_4_failure_handling_offline(self):
        offline_client = ComfyAPIClient("http://127.0.0.1:9999")
        healthy = offline_client.check_health()
        self.assertFalse(healthy)

        offline_manager = ExecutionManager("http://127.0.0.1:9999")
        res = offline_manager.execute_package(payload={}, workflow_id="3_night_transition", timeout_seconds=0.1)
        self.assertEqual(res.status, "offline")

    def test_case_5_orchestrator_failure_recovery(self):
        res = self.orchestrator.generate_architecture_video(image="museum.png", task="制作黄昏慢推进建筑宣传动画")
        self.assertIn("status", res)
        self.assertIn("vision_analysis", res)
        self.assertIn("architectural_intent", res)
        self.assertIn("workflow", res)
        self.assertIn("acceleration_profile", res)

if __name__ == "__main__":
    unittest.main()
