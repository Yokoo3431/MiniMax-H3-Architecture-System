"""Workflow Revision & Parameter Adjustment Engine (V0.7.7).
Adjusts camera speed, motion strength, steps, guidance, and geometry preservation weights based on Critic feedback.
"""

from typing import Dict, Any, List

class WorkflowRevisionEngine:
    """Adjusts workflow parameters based on Critic issues and recommendations."""

    def adjust_workflow_parameters(
        self,
        base_params: Dict[str, Any],
        critic_issues: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        adjusted = dict(base_params)

        for issue in critic_issues:
            cat = issue.get("category", "")
            if cat == "camera_failure":
                adjusted["camera_speed"] = 0.35
                adjusted["motion_strength"] = 0.45
            elif cat == "geometry_failure":
                adjusted["geometry_preservation_weight"] = 1.2
                adjusted["steps"] = max(30, adjusted.get("steps", 25) + 5)
            elif cat == "lighting_failure":
                adjusted["lighting_transition_strength"] = 0.85
            elif cat == "material_failure":
                adjusted["denoise_video"] = True
                adjusted["steps"] = max(28, adjusted.get("steps", 25) + 3)

        return adjusted
