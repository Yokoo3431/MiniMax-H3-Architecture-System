"""Architectural Natural Language Intent Parser.
Extracts task type, building type, scene type, camera motion, and lighting settings from text.
"""

import json
from pathlib import Path
from skills.architecture_prompt.intent_schema import ArchitecturalIntent, CameraIntent, LightingIntent, ConstraintIntent

SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
VOCAB_FILE = SYSTEM_ROOT / "configs" / "architecture_vocabulary.json"

class IntentParser:
    """Parses natural language requests into ArchitecturalIntent."""

    def __init__(self):
        self.vocab = self._load_vocab()

    def _load_vocab(self) -> dict:
        if VOCAB_FILE.is_file():
            try:
                with open(VOCAB_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def parse(self, text: str) -> ArchitecturalIntent:
        desc = text.lower()
        intent = ArchitecturalIntent()

        # 1. Task Type Detection
        if any(kw in desc for kw in ["体块", "演变", "爆炸", "流线", "结构", "分析", "massing", "exploded", "circulation", "structure"]):
            intent.task_type = "architecture_analysis"
        else:
            intent.task_type = "architecture_visualization"

        # 2. Scene Type Detection
        if any(kw in desc for kw in ["鸟瞰", "航拍", "aerial", "drone"]):
            intent.scene_type = "aerial"
            intent.camera.movement = "high_altitude_drone"
        elif any(kw in desc for kw in ["夜景", "黄昏", "灯光", "night", "twilight", "dusk", "lighting"]):
            intent.scene_type = "night_transition"
            intent.lighting.time = "twilight_dusk"
            intent.lighting.interior_light = "3500K warm interior glow through curtainwall"
        elif any(kw in desc for kw in ["室内", "漫游", "walkthrough", "interior"]):
            intent.scene_type = "interior"
            intent.camera.movement = "pedestrian_walkthrough"
        elif any(kw in desc for kw in ["环绕", "旋转", "orbit"]):
            intent.scene_type = "exterior"
            intent.camera.movement = "slow_orbit"
        elif "体块" in desc or "massing" in desc:
            intent.scene_type = "massing_evolution"
            intent.camera.movement = "stationary_timelapse"
        elif "爆炸" in desc or "exploded" in desc:
            intent.scene_type = "exploded_axon"
            intent.camera.movement = "vertical_explode"
        elif "流线" in desc or "circulation" in desc:
            intent.scene_type = "circulation_analysis"
        elif "结构" in desc or "structure" in desc:
            intent.scene_type = "structure_animation"

        # 3. Building Type Detection
        if any(kw in desc for kw in ["博物馆", "美术馆", "museum", "gallery"]):
            intent.building_type = "museum"
        elif any(kw in desc for kw in ["别墅", "住宅", "villa", "residence"]):
            intent.building_type = "villa"
        elif any(kw in desc for kw in ["高层", "塔楼", "写字楼", "skyscraper", "office"]):
            intent.building_type = "skyscraper"
        elif any(kw in desc for kw in ["园区", "校园", "campus"]):
            intent.building_type = "campus"

        # 4. Camera Push Detection
        if "推进" in desc or "push" in desc or "dolly" in desc:
            intent.camera.movement = "slow_push"

        return intent
