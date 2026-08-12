"""Execution Schema Dataclasses (V0.7.4).
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class ExecutionResult:
    status: str = "completed"
    prompt_id: str = ""
    video_path: str = ""
    workflow_id: str = "3_night_transition"
    prompt_score: float = 95.0
    error_message: str = ""
    node_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "prompt_id": self.prompt_id,
            "video_path": self.video_path,
            "workflow": self.workflow_id,
            "prompt_score": self.prompt_score,
            "error_message": self.error_message,
            "node_errors": self.node_errors
        }
