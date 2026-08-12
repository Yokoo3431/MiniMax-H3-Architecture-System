"""Unit test for generate_from_architect_request High-Level Generation API.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.h3_orchestrator import H3Orchestrator
from runtime.interface.architect_request import ArchitectRequest

class TestGenerationAPI(unittest.TestCase):
    def setUp(self):
        self.orchestrator = H3Orchestrator()

    def test_generate_from_architect_request_api(self):
        req = ArchitectRequest(
            images=["museum.jpg"],
            task_description="把这个博物馆效果图制作成30秒黄昏建筑宣传动画"
        )
        res = self.orchestrator.generate_from_architect_request(req)
        self.assertEqual(res["status"], "completed")
        self.assertIn("video_path", res)
        self.assertIn("selected_workflow", res)
        self.assertIn("generated_prompt", res)
        self.assertGreaterEqual(res["critic_score"], 80.0)

if __name__ == "__main__":
    unittest.main()
