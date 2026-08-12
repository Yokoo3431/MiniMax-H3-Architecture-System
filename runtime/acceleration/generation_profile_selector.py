"""Generation Profile & Strategy Selector Engine (V0.7.5).
Combines VRAM optimization, timestep scheduling, and model ecosystem registry matching.
"""

import json
from pathlib import Path
from runtime.acceleration.vram_optimizer import VRAMOptimizer
from runtime.acceleration.timestep_optimizer import TimestepOptimizer
from runtime.acceleration.acceleration_schema import AccelerationProfile, ModelPackage

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_REGISTRY_FILE = SYSTEM_ROOT / "configs" / "model_registry.json"

class GenerationProfileSelector:
    """Combines hardware profiles and model ecosystem registry to produce optimal generation strategy."""

    def __init__(self):
        self.vram_opt = VRAMOptimizer()
        self.timestep_opt = TimestepOptimizer()
        self.registry = self._load_registry()

    def _load_registry(self) -> dict:
        if MODEL_REGISTRY_FILE.is_file():
            try:
                with open(MODEL_REGISTRY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def select_strategy(self, profile_key: str = "H3_STANDARD", task_text: str = "") -> dict:
        desc = task_text.lower()

        # 1. Acceleration Profile Optimization
        raw_profile = self.vram_opt.get_profile(profile_key)
        task_type = "analysis" if any(kw in desc for kw in ["体块", "爆炸", "分析"]) else "visualization"
        acc_profile: AccelerationProfile = self.timestep_opt.optimize_schedule(raw_profile, task_type=task_type)

        # 2. Model Ecosystem Registry Matching
        if "安藤" in desc or "混凝土" in desc or "concrete" in desc:
            style_key = "minimal_concrete"
        elif "木" in desc or "timber" in desc:
            style_key = "nordic_timber"
        elif "玻璃" in desc or "幕墙" in desc:
            style_key = "hightech_glass"
        else:
            style_key = "minimal_concrete"

        if "黄昏" in desc or "夜景" in desc:
            lighting_key = "twilight_dusk"
        elif "日出" in desc or "晨光" in desc:
            lighting_key = "golden_hour"
        else:
            lighting_key = "twilight_dusk"

        camera_key = "high_altitude_orbit" if "鸟瞰" in desc else ("eye_level_walkthrough" if "漫游" in desc else "slow_push")

        style_data = self.registry.get("architecture_styles", {}).get(style_key, {})
        loras = []
        if "lora_name" in style_data:
            loras.append({"name": style_data["lora_name"], "weight": style_data.get("weight", 0.8)})

        model_pkg = ModelPackage(
            style_key=style_key,
            camera_key=camera_key,
            lighting_key=lighting_key,
            checkpoint="minimax_h3_fl2va_pruned_int8_convrot.safetensors",
            loras=loras
        )

        return {
            "acceleration_profile": acc_profile.to_dict(),
            "model_package": model_pkg.to_dict(),
            "optimization_strategy": f"{acc_profile.profile_key}_{task_type}_optimized"
        }
