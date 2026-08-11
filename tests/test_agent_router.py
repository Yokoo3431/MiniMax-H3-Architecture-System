"""Unit test for Agent Runtime Pipeline (TaskPlanner -> WorkflowSelector -> PromptComposer -> HardwareAdapter).
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.task_planner import TaskPlanner
from runtime.workflow_selector import WorkflowSelector
from runtime.prompt_composer import PromptComposer
from runtime.hardware_adapter import HardwareAdapter

class TestAgentRouter(unittest.TestCase):
    def test_agent_router_pipeline(self):
        planner = TaskPlanner()
        selector = WorkflowSelector(SYSTEM_ROOT / "configs" / "workflow_registry.json")
        composer = PromptComposer(SYSTEM_ROOT / "prompts" / "architectural_animation_prompts.json")
        adapter = HardwareAdapter(profile_override="H3_STANDARD")

        task = "Breathtaking aerial view animation of hospital masterplan"
        plan = planner.plan_task(task)
        self.assertTrue(plan["has_aerial_intent"])

        wf_spec, filename = selector.select_workflow(plan)
        self.assertIsNotNone(filename)

        pos_p, neg_p = composer.compose_prompt(task, wf_spec.get("prompt_template_key", "1_image_to_video"))
        self.assertTrue("aerial" in pos_p.lower() or "hospital" in pos_p.lower())

        hw = adapter.adapt_parameters()
        self.assertEqual(hw["profile_key"], "H3_STANDARD")
        self.assertEqual(hw["width"], 1280)
        self.assertEqual(hw["height"], 720)

if __name__ == "__main__":
    unittest.main()
