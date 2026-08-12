"""Workflow Execution Package Dataclass (V0.7.5 Upgraded).
Enhanced bridge containing acceleration profiles, model packages, and optimization strategies.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

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
    model_requirements: Dict[str, Any] = field(default_factory=lambda: {
        "checkpoint": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "vae": "video_vae",
        "lora": []
    })
    camera_intent: str = "slow_push"
    motion_intent: str = "architectural_reveal"
    quality_profile: str = "H3_STANDARD"
    execution_constraints: Dict[str, Any] = field(default_factory=lambda: {
        "geometry_lock": True,
        "aspect_ratio": "16:9"
    })
    acceleration_profile: Dict[str, Any] = field(default_factory=lambda: {
        "profile": "H3_STANDARD",
        "resolution": "1280x720",
        "steps": 25,
        "offload": True
    })
    model_package: Dict[str, Any] = field(default_factory=lambda: {
        "style_key": "minimal_concrete",
        "camera_key": "slow_push",
        "lighting_key": "twilight_dusk"
    })
    optimization_strategy: str = "H3_STANDARD_visualization_optimized"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_file": self.workflow_file,
            "input_image": self.input_image,
            "positive_prompt": self.positive_prompt,
            "negative_prompt": self.negative_prompt,
            "parameters": self.parameters,
            "hardware_profile": self.hardware_profile,
            "output_path": self.output_path,
            "model_requirements": self.model_requirements,
            "camera_intent": self.camera_intent,
            "motion_intent": self.motion_intent,
            "quality_profile": self.quality_profile,
            "execution_constraints": self.execution_constraints,
            "acceleration_profile": self.acceleration_profile,
            "model_package": self.model_package,
            "optimization_strategy": self.optimization_strategy
        }
