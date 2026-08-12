"""Acceleration Schema Dataclasses (V0.7.5).
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class AccelerationProfile:
    profile_key: str = "H3_STANDARD"
    resolution: str = "1280x720"
    width: int = 1280
    height: int = 720
    frames: int = 48
    duration_seconds: float = 5.0
    sampler: str = "dual_sigma"
    steps: int = 25
    video_shift: float = 12.0
    audio_shift: float = 3.0
    offload: bool = True
    batch_size: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile_key,
            "resolution": self.resolution,
            "width": self.width,
            "height": self.height,
            "frames": self.frames,
            "duration_seconds": self.duration_seconds,
            "sampler": self.sampler,
            "steps": self.steps,
            "video_shift": self.video_shift,
            "audio_shift": self.audio_shift,
            "offload": self.offload,
            "batch_size": self.batch_size
        }

@dataclass
class ModelPackage:
    style_key: str = "minimal_concrete"
    camera_key: str = "slow_push"
    lighting_key: str = "twilight_dusk"
    checkpoint: str = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    loras: List[Dict[str, Any]] = field(default_factory=lambda: [
        {"name": "concrete_realism_v1.safetensors", "weight": 0.8}
    ])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "style_key": self.style_key,
            "camera_key": self.camera_key,
            "lighting_key": self.lighting_key,
            "checkpoint": self.checkpoint,
            "loras": self.loras
        }
