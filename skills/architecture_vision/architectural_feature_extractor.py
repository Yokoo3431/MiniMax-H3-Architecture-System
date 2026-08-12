"""Architectural Feature Extractor Engine (V0.7.3).
Extracts building typology, architectural style, materials, camera perspective, lighting, and spatial character.
"""

import os
from skills.architecture_vision.vision_schema import ArchitectureVisualAnalysis

class ArchitecturalFeatureExtractor:
    """Extracts architectural visual features from rendering images and prompt hints."""

    def extract_features(self, image_path: str, prompt_hint: str = "") -> ArchitectureVisualAnalysis:
        filename = os.path.basename(image_path).lower()
        hint = prompt_hint.lower()
        text_context = f"{filename} {hint}"

        # 1. Building Typology
        if any(kw in text_context for kw in ["museum", "美术馆", "博物馆", "gallery"]):
            b_type = "museum"
        elif any(kw in text_context for kw in ["villa", "别墅", "residence", "住宅"]):
            b_type = "villa"
        elif any(kw in text_context for kw in ["skyscraper", "高层", "塔楼", "office", "写字楼"]):
            b_type = "skyscraper"
        elif any(kw in text_context for kw in ["campus", "校园", "园区"]):
            b_type = "campus"
        elif any(kw in text_context for kw in ["courtyard", "庭院"]):
            b_type = "courtyard_building"
        else:
            b_type = "museum"

        # 2. Architectural Style & Materials
        materials = []
        if any(kw in text_context for kw in ["安藤", "混凝土", "concrete"]):
            style = "minimal_concrete_architecture"
            materials.append("fair-faced_concrete")
        elif any(kw in text_context for kw in ["木", "timber", "wood"]):
            style = "nordic_timber_architecture"
            materials.append("warm_cedar_timber")
        elif any(kw in text_context for kw in ["玻璃", "幕墙", "glass", "curtainwall"]):
            style = "high_tech_glass_architecture"
            materials.append("double-glazed_curtainwall")
        else:
            style = "modern_architectural_style"
            materials.append("fair-faced_concrete")

        if "glass" not in materials and "玻璃" in text_context:
            materials.append("structural_glass")

        # 3. Spatial & Lighting Character
        if any(kw in text_context for kw in ["黄昏", "夜景", "twilight", "dusk"]):
            lighting = "golden_hour_twilight"
            rec_wfs = ["3_night_transition", "1_image_to_video"]
        elif any(kw in text_context for kw in ["鸟瞰", "航拍", "aerial", "drone"]):
            lighting = "crisp_daylight"
            rec_wfs = ["2_aerial_view", "1_image_to_video"]
        elif any(kw in text_context for kw in ["漫游", "室内", "walkthrough"]):
            lighting = "warm_interior_ambient"
            rec_wfs = ["5_walkthrough", "1_image_to_video"]
        else:
            lighting = "soft_daylight"
            rec_wfs = ["1_image_to_video", "3_night_transition"]

        return ArchitectureVisualAnalysis(
            building_type=b_type,
            architectural_style=style,
            materials=materials,
            spatial_character="courtyard" if "庭院" in text_context else "open_plaza",
            camera_character="architectural_tilt_shift",
            lighting_condition=lighting,
            emotional_target="quiet_monumental" if "安藤" in text_context else "serene_cinematic",
            recommended_workflows=rec_wfs
        )
