"""Unit test for Workflow Execution Package.
"""

import unittest
from runtime.workflow_intelligence.workflow_execution_package import WorkflowExecutionPackage

class TestExecutionPackage(unittest.TestCase):
    def test_execution_package_fields(self):
        pkg = WorkflowExecutionPackage(
            workflow_id="3_night_transition",
            workflow_file="3_建筑夜景灯光变化_NightTransition.json",
            input_image="museum.png",
            positive_prompt="Architectural rendering of museum",
            negative_prompt="warped facade"
        )
        d = pkg.to_dict()
        self.assertEqual(d["workflow_id"], "3_night_transition")
        self.assertEqual(d["input_image"], "museum.png")
        self.assertEqual(d["hardware_profile"], "H3_STANDARD")

if __name__ == "__main__":
    unittest.main()
