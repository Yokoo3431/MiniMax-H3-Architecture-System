"""Unit test for Failure Classifier Engine.
"""

import sys
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.critic.failure_classifier import FailureClassifier

class TestFailureClassifier(unittest.TestCase):
    def setUp(self):
        self.classifier = FailureClassifier()

    def test_classify_geometry_failure(self):
        issues = self.classifier.classify_task_and_video("柱子变形了", "test.mp4")
        self.assertTrue(any(i.category == "geometry_failure" for i in issues))

    def test_classify_camera_failure(self):
        issues = self.classifier.classify_task_and_video("镜头明显晃动", "test.mp4")
        self.assertTrue(any(i.category == "camera_failure" for i in issues))

if __name__ == "__main__":
    unittest.main()
