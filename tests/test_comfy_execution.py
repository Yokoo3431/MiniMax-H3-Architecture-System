"""Unit test for ComfyUI Execution Manager & API Client.
"""

import unittest
from runtime.execution.comfy_api_client import ComfyAPIClient
from runtime.execution.execution_manager import ExecutionManager

class TestComfyExecution(unittest.TestCase):
    def setUp(self):
        self.client = ComfyAPIClient("http://127.0.0.1:8188")
        self.manager = ExecutionManager("http://127.0.0.1:8188")

    def test_offline_detection(self):
        # Health check returns bool
        is_healthy = self.client.check_health()
        self.assertIsInstance(is_healthy, bool)

    def test_manager_offline_execution_handling(self):
        # When server offline or online, manager should return clean ExecutionResult status without crashing
        res = self.manager.execute_package(payload={}, workflow_id="3_night_transition", timeout_seconds=0.1)
        self.assertIn(res.status, ["offline", "timeout", "completed", "error"])

if __name__ == "__main__":
    unittest.main()
