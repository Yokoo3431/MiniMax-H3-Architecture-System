"""Hardware Adapter Module (HAL Wrapper)
Adapts workflow parameters (resolution, steps, fps, VRAM mode) according to matched HAL profile (H3_LOW / H3_STANDARD / H3_PRO).
"""

import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from hardware.detect_gpu import detect_hardware

class HardwareAdapter:
    """Adapts workflow payload execution settings to GPU hardware capacity."""

    def __init__(self, profile_override: str = None):
        self.hw_info = detect_hardware()
        if profile_override and profile_override in ["H3_LOW", "H3_STANDARD", "H3_PRO"]:
            import json
            prof_file = SYSTEM_ROOT / "hardware" / "hardware_profiles.json"
            if prof_file.is_file():
                with open(prof_file, "r", encoding="utf-8") as f:
                    all_profiles = json.load(f).get("profiles", {})
                    self.hw_info["matched_profile_key"] = profile_override
                    self.hw_info["profile"] = all_profiles.get(profile_override, self.hw_info["profile"])

        self.profile = self.hw_info["profile"]
        self.profile_key = self.hw_info["matched_profile_key"]

    def adapt_parameters(self, duration_override: float = None) -> dict:
        res_w, res_h = self.profile["resolution"]
        return {
            "profile_key": self.profile_key,
            "width": res_w,
            "height": res_h,
            "steps": self.profile["steps"],
            "fps": self.profile["fps"],
            "duration_seconds": duration_override or self.profile["duration_seconds"],
            "vram_mode": self.profile["vram_allocation_mode"],
            "cpu_offload": self.profile.get("cpu_offload", True)
        }
