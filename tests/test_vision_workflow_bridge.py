"""Unit test for Vision to Workflow Bridge Engine.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from skills.architecture_vision.image_analyzer import ArchitectureImageAnalyzer
from skills.architecture_vision.vision_intent_bridge import VisionIntentBridge
from runtime.workflow_intelligence.workflow_matcher import WorkflowMatcher

class TestVisionWorkflowBridge(unittest.TestCase):
    def setUp(self):
        self.analyzer = ArchitectureImageAnalyzer()
        self.bridge = VisionIntentBridge()
        self.matcher = WorkflowMatcher()

    def test_end_to_end_vision_bridge(self):
        v_dict = self.analyzer.analyze_image("concrete_museum.png", prompt_hint="安藤风格混凝土美术馆黄昏推进")
        intent = self.bridge.bridge_visual_to_intent(v_dict, text_hint="黄昏推进")

        self.assertEqual(intent.building_type, "museum")
        self.assertEqual(intent.scene_type, "night_transition")

        wf_id = self.matcher.match_intent_to_workflow(intent.scene_type, visual_dict=v_dict)
        self.assertEqual(wf_id, "3_night_transition")

if __name__ == "__main__":
    unittest.main()
