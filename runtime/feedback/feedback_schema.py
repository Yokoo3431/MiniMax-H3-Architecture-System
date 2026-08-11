"""Architectural Critic Feedback Schema Definition (V0.7.1.6).
Prepares future Critic Agent integration.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class ArchitecturalCriticFeedback:
    critic_id: str = "arch_critic_v1"
    overall_pass: bool = True
    geometry_score: float = 90.0
    material_score: float = 90.0
    camera_score: float = 95.0
    lighting_score: float = 85.0
    revision_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "critic_id": self.critic_id,
            "overall_pass": self.overall_pass,
            "scores": {
                "geometry": self.geometry_score,
                "material": self.material_score,
                "camera": self.camera_score,
                "lighting": self.lighting_score
            },
            "revision_notes": self.revision_notes
        }
