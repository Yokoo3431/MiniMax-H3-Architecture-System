"""Workflow Execution Package Dataclass (V0.7.4).
Final bridge between AI intelligence layers and ComfyUI backend execution.
"""

from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class WorkflowExecutionPackage:
    workflow_id: str = "3_night_transition"
    workflow_file: str = "3_建筑夜景灯光变化_NightTransition.json"
    input_image: str = "building.jpg"
    positive_prompt: str = ""
    negative_prompt: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    hardware_profile: str = "H3_STANDARD"
    output_path: str = "userdata/outputs"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_file": self.workflow_file,
            "input_image": self.input_image,
            "positive_prompt": self.positive_prompt,
            "negative_prompt": self.negative_prompt,
            "parameters": self.parameters,
            "hardware_profile": self.hardware_profile,
            "output_path": self.output_path
        }
