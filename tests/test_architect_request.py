"""Unit test for Architect Request & Response Dataclasses.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.interface.architect_request import ArchitectRequest
from runtime.interface.architect_response import ArchitectResponse

class TestArchitectRequest(unittest.TestCase):
    def test_architect_request_serialization(self):
        req = ArchitectRequest(
            images=["museum01.jpg", "museum02.jpg"],
            task_description="制作30秒黄昏建筑宣传动画",
            video_style="exterior_hero",
            duration=5.0
        )
        d = req.to_dict()
        self.assertEqual(len(d["images"]), 2)
        self.assertEqual(d["task_description"], "制作30秒黄昏建筑宣传动画")
        self.assertEqual(d["video_style"], "exterior_hero")

    def test_architect_response_serialization(self):
        resp = ArchitectResponse(
            status="completed",
            generated_prompt="Architectural rendering",
            selected_workflow="3_night_transition",
            video_path="outputs/test.mp4",
            critic_score=95.0
        )
        d = resp.to_dict()
        self.assertEqual(d["status"], "completed")
        self.assertEqual(d["selected_workflow"], "3_night_transition")

if __name__ == "__main__":
    unittest.main()
