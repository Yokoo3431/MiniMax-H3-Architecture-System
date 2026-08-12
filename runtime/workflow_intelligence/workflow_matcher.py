"""Intent to Workflow Semantic Matcher Engine (V0.7.3 Upgraded).
Supports text intent as well as image-derived visual analysis feature matching.
"""

import json
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_FILE = SYSTEM_ROOT / "configs" / "workflow_registry.json"

class WorkflowMatcher:
    """Matches architectural intent & text/visual feature descriptions to workflow registry IDs."""

    def __init__(self):
        self.registry = self._load_registry()

    def _load_registry(self) -> dict:
        if REGISTRY_FILE.is_file():
            try:
                with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def match_intent_to_workflow(self, scene_type: str, text: str = "", visual_dict: dict = None) -> str:
        desc = text.lower()
        v_dict = visual_dict or {}

        # 1. Visual Feature Matching
        rec_video = v_dict.get("recommended_video", "")
        if rec_video in ["3_night_transition", "2_aerial_view", "5_walkthrough", "6_massing_evolution", "8_exploded_axon"]:
            return rec_video

        # 2. Text Keyword Matching
        if "夜景" in desc or "黄昏" in desc or scene_type == "night_transition":
            return "3_night_transition"
        elif "鸟瞰" in desc or "航拍" in desc or scene_type == "aerial":
            return "2_aerial_view"
        elif "漫游" in desc or "室内" in desc or scene_type == "interior":
            return "5_walkthrough"
        elif "体块" in desc or "massing" in desc or scene_type == "massing_evolution":
            return "6_massing_evolution"
        elif "爆炸" in desc or "exploded" in desc or scene_type == "exploded_axon":
            return "8_exploded_axon"
        else:
            return "1_image_to_video"
