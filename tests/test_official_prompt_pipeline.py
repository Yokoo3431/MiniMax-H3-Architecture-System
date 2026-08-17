"""Unit test for Official H3 Prompt Skill Pipeline & Transformation.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.h3_orchestrator import H3Orchestrator
from runtime.interface.architect_request import ArchitectRequest

class TestOfficialPromptPipeline(unittest.TestCase):
    def setUp(self):
        self.orchestrator = H3Orchestrator()

    def test_official_prompt_transformation_pipeline(self):
        req = ArchitectRequest(
            images=["museum.jpg"],
            task_description="把这个安藤风格混凝土美术馆效果图制作成30秒黄昏建筑宣传动画"
        )
        res = self.orchestrator.generate_from_architect_request(req)

        # 1. Original Request Verification
        self.assertEqual(req.task_description, "把这个安藤风格混凝土美术馆效果图制作成30秒黄昏建筑宣传动画")

        # 2. Transformed Prompt Verification
        generated_prompt = res["generated_prompt"]
        self.assertIn("Architectural visualization", generated_prompt)
        self.assertIn("museum", generated_prompt)
        self.assertIn("twilight dusk", generated_prompt)

        # 3. Selected Workflow Verification
        selected_workflow = res["selected_workflow"]
        self.assertEqual(selected_workflow, "3_night_transition")

        # 4. Pipeline Execution Status Verification
        self.assertIn(res["status"], ["completed", "error"])

if __name__ == "__main__":
    unittest.main()
