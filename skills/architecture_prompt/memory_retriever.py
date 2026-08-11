"""Semantic Memory Retrieval Engine.
Retrieves historical architectural case memories, compares intent, and suggests prompt strategies.
"""

import json
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
MEMORY_FILE = SYSTEM_ROOT / "configs" / "architecture_memory.json"

class MemoryRetriever:
    """Retrieves similar architectural memory cases and provides prompt strategy recommendations."""

    def __init__(self):
        self.memory = self._load_memory()

    def _load_memory(self) -> dict:
        if MEMORY_FILE.is_file():
            try:
                with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def retrieve_similar_case(self, text: str) -> dict:
        desc = text.lower()
        cases = self.memory.get("cases", [])
        matched_case = None

        if "安藤" in desc or "清水混凝土" in desc or "museum" in desc or "美术馆" in desc:
            matched_case = cases[0] if len(cases) > 0 else None
        elif "庭院" in desc or "courtyard" in desc or "villa" in desc or "别墅" in desc:
            matched_case = cases[1] if len(cases) > 1 else None
        elif "玻璃" in desc or "高层" in desc or "skyscraper" in desc:
            matched_case = cases[2] if len(cases) > 2 else None

        if not matched_case and len(cases) > 0:
            matched_case = cases[0]

        return matched_case or {}

    def compare_architectural_intent(self, text: str, case_data: dict) -> float:
        desc = text.lower()
        intent = case_data.get("architectural_intent", {})
        score = 0.5

        if intent.get("material_expression", "") in desc or "混凝土" in desc or "木" in desc or "玻璃" in desc:
            score += 0.25
        if intent.get("design_language", "") in desc or "安藤" in desc or "日式" in desc or "现代" in desc:
            score += 0.25

        return round(min(1.0, score), 2)

    def suggest_prompt_strategy(self, text: str) -> dict:
        matched = self.retrieve_similar_case(text)
        b_type = matched.get("project_info", {}).get("building_type", "museum")

        if b_type == "museum" or "混凝土" in text or "安藤" in text:
            return {
                "recommended_camera": "slow architectural reveal",
                "recommended_light": "soft twilight dusk sky with 3500K warm interior glow",
                "avoid": "dramatic fast cinematic motion",
                "matched_memory_id": matched.get("project_info", {}).get("memory_id", "mem_001")
            }
        elif "庭院" in text or "villa" in text:
            return {
                "recommended_camera": "smooth orbital pan at pedestrian eye-level",
                "recommended_light": "filtered natural daylight through foliage",
                "avoid": "unnatural high-speed drone zoom",
                "matched_memory_id": matched.get("project_info", {}).get("memory_id", "mem_002")
            }
        else:
            return {
                "recommended_camera": "steady tripod push-in dolly shot",
                "recommended_light": "golden hour twilight illumination",
                "avoid": "fisheye lens distortion",
                "matched_memory_id": matched.get("project_info", {}).get("memory_id", "mem_003")
            }
