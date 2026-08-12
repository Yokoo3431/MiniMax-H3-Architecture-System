"""Failure Classifier Engine (V0.7.6).
Classifies architecture video generation failures into 5 controlled categories:
1. Geometry Failure
2. Material Failure
3. Camera Failure
4. Lighting Failure
5. Architectural Intent Failure
"""

from typing import List
from runtime.critic.critic_schema import CriticIssue

class FailureClassifier:
    """Classifies video issues into controlled architectural failure categories."""

    def classify_task_and_video(self, task_text: str, video_path: str, prompt_score: float = 95.0) -> List[CriticIssue]:
        issues = []
        desc = task_text.lower()

        # Rule 1: Geometry Failure Check
        if "变形" in desc or "柱子" in desc or prompt_score < 80.0:
            issues.append(CriticIssue(
                category="geometry_failure",
                severity="medium",
                description="Potential architectural geometry drift or structural element deformation"
            ))

        # Rule 2: Material Failure Check
        if "模糊" in desc or "材质" in desc:
            issues.append(CriticIssue(
                category="material_failure",
                severity="low",
                description="Architectural material texture definition could be enhanced"
            ))

        # Rule 3: Camera Failure Check
        if "抖动" in desc or "晃动" in desc:
            issues.append(CriticIssue(
                category="camera_failure",
                severity="medium",
                description="Unstable camera motion or perspective drift"
            ))

        # Rule 4: Lighting Failure Check
        if "曝光" in desc or "阴影" in desc:
            issues.append(CriticIssue(
                category="lighting_failure",
                severity="low",
                description="Lighting atmosphere or shadow contrast mismatch"
            ))

        # Rule 5: Architectural Intent Failure Check
        if prompt_score < 70.0:
            issues.append(CriticIssue(
                category="architectural_intent_failure",
                severity="high",
                description="Generated visual character strays from original architectural design intent"
            ))

        return issues
