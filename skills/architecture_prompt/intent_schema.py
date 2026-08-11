"""Architectural Intent Schema Dataclass Representation (V0.7.1.6 Upgraded).
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class CameraIntent:
    movement: str = "slow_push"
    lens: str = "35mm architectural lens"

@dataclass
class LightingIntent:
    time: str = "golden_hour"
    temperature: str = "warm"
    interior_light: str = "3500K warm interior glow"

@dataclass
class ConstraintIntent:
    geometry_lock: bool = True
    material_lock: bool = True
    composition_lock: bool = True

@dataclass
class ReasoningIntent:
    design_language: str = "modernism"
    spatial_character: str = "monumental"
    material_expression: str = "glass_transparency"
    emotional_target: str = "cinematic"

@dataclass
class ArchitecturalIntent:
    task_type: str = "architecture_visualization"
    building_type: str = "modern_museum"
    scene_type: str = "exterior"
    camera: CameraIntent = field(default_factory=CameraIntent)
    lighting: LightingIntent = field(default_factory=LightingIntent)
    constraints: ConstraintIntent = field(default_factory=ConstraintIntent)
    reasoning: ReasoningIntent = field(default_factory=ReasoningIntent)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type,
            "building_type": self.building_type,
            "scene_type": self.scene_type,
            "camera": {
                "movement": self.camera.movement,
                "lens": self.camera.lens
            },
            "lighting": {
                "time": self.lighting.time,
                "temperature": self.lighting.temperature,
                "interior_light": self.lighting.interior_light
            },
            "constraints": {
                "geometry_lock": self.constraints.geometry_lock,
                "material_lock": self.constraints.material_lock,
                "composition_lock": self.constraints.composition_lock
            },
            "reasoning": {
                "design_language": self.reasoning.design_language,
                "spatial_character": self.reasoning.spatial_character,
                "material_expression": self.reasoning.material_expression,
                "emotional_target": self.reasoning.emotional_target
            }
        }
