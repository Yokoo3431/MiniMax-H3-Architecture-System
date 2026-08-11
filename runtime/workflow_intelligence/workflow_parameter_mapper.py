"""Workflow Parameter & Video Preset Mapping Engine (V0.7.2).
"""

import json
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
PRESETS_FILE = SYSTEM_ROOT / "configs" / "video_presets.json"

class WorkflowParameterMapper:
    """Maps selected workflow and intent into architectural video preset parameters."""

    def __init__(self):
        self.presets = self._load_presets()

    def _load_presets(self) -> dict:
        if PRESETS_FILE.is_file():
            try:
                with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f).get("presets", {})
            except Exception:
                pass
        return {}

    def get_preset_for_workflow(self, workflow_id: str) -> dict:
        if workflow_id == "3_night_transition":
            return self.presets.get("day_night_transition", {})
        elif workflow_id == "2_aerial_view":
            return self.presets.get("aerial_drone", {})
        elif workflow_id == "5_walkthrough":
            return self.presets.get("walkthrough", {})
        elif workflow_id in ["6_massing_evolution", "8_exploded_axon"]:
            return self.presets.get("architecture_analysis", {})
        else:
            return self.presets.get("exterior_hero", {})
