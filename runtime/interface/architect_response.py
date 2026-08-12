"""Architect Response Dataclass (V0.7.8).
Schema for architect video generation API response.
"""

from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class ArchitectResponse:
    status: str = "completed"
    generated_prompt: str = ""
    selected_workflow: str = "3_night_transition"
    execution_status: str = "completed"
    video_path: str = ""
    critic_score: float = 95.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "generated_prompt": self.generated_prompt,
            "selected_workflow": self.selected_workflow,
            "execution_status": self.execution_status,
            "video_path": self.video_path,
            "critic_score": self.critic_score,
            "details": self.details
        }
