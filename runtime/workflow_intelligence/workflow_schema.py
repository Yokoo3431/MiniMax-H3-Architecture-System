"""Workflow Intelligence Schema Dataclasses (V0.7.2).
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class WorkflowSelectionPackage:
    workflow_id: str = "3_night_transition"
    workflow_filename: str = "3_建筑夜景灯光变化_NightTransition.json"
    workflow_type: str = "architecture_visualization"
    camera_motion: str = "slow_push"
    lighting_atmosphere: str = "soft_twilight"
    duration_seconds: float = 5.0
    quality_profile: str = "H3_STANDARD"
    preset_id: str = "day_night_transition"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_filename": self.workflow_filename,
            "workflow_type": self.workflow_type,
            "camera_motion": self.camera_motion,
            "lighting_atmosphere": self.lighting_atmosphere,
            "duration": f"{self.duration_seconds}s",
            "quality_profile": self.quality_profile,
            "preset_id": self.preset_id
        }
