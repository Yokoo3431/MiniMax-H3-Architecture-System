"""MiniMax H3 Architect Web UI Prototype (V0.7.8).
Lightweight local Web UI prototype for 1-click architectural image upload, prompt entry, preset selection, live progress tracking, and video preview.
"""

import os
import sys
import json
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from runtime.h3_orchestrator import H3Orchestrator
from runtime.interface.architect_request import ArchitectRequest

def load_user_presets() -> dict:
    presets_file = SYSTEM_ROOT / "configs" / "user_video_presets.json"
    if presets_file.is_file():
        try:
            with open(presets_file, "r", encoding="utf-8") as f:
                return json.load(f).get("presets", {})
        except Exception:
            pass
    return {}

def run_architect_pipeline(images: list, task: str, preset_key: str, quality: str) -> dict:
    orchestrator = H3Orchestrator(profile_override=quality)
    req = ArchitectRequest(
        images=images if images else ["userdata/custom_prompts/building.jpg"],
        task_description=task if task else "把这个博物馆效果图制作成黄昏建筑宣传动画",
        video_style=preset_key,
        quality_level=quality
    )
    return orchestrator.generate_from_architect_request(req)

if __name__ == "__main__":
    print("[MiniMax H3 Web UI Prototype V0.7.8 Initialized]")
    presets = load_user_presets()
    print(f"Loaded {len(presets)} architect video presets.")
    sample_res = run_architect_pipeline(["building.jpg"], "制作黄昏建筑动画", "exterior_hero", "H3_STANDARD")
    print("\n[Sample Pipeline Web Result]:")
    print(json.dumps(sample_res, indent=2, ensure_ascii=False))
