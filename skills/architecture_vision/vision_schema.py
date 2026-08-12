"""Architecture Visual Schema Dataclasses (V0.7.3).
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class ArchitectureVisualAnalysis:
    building_type: str = "museum"
    architectural_style: str = "minimal_concrete_architecture"
    materials: List[str] = field(default_factory=lambda: ["fair-faced_concrete", "glass"])
    spatial_character: str = "courtyard"
    camera_character: str = "architectural_photography_tilt_shift"
    lighting_condition: str = "golden_hour_twilight"
    emotional_target: str = "quiet_monumental"
    recommended_workflows: List[str] = field(default_factory=lambda: ["3_night_transition", "1_image_to_video"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.building_type,
            "style": self.architectural_style,
            "material": self.materials,
            "space": self.spatial_character,
            "camera": self.camera_character,
            "lighting": self.lighting_condition,
            "mood": self.emotional_target,
            "recommended_video": self.recommended_workflows[0] if self.recommended_workflows else "1_image_to_video",
            "recommended_workflows": self.recommended_workflows
        }
