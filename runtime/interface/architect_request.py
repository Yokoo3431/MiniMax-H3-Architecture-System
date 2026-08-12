"""Architect Request Dataclass (V0.7.8).
Schema for 1~5 architectural images and natural language task prompts.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class ArchitectRequest:
    images: List[str] = field(default_factory=list)
    task_description: str = "制作黄昏建筑宣传动画"
    video_style: str = "exterior_hero"
    duration: float = 5.0
    quality_level: str = "H3_STANDARD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "images": self.images,
            "task_description": self.task_description,
            "video_style": self.video_style,
            "duration": self.duration,
            "quality_level": self.quality_level
        }
