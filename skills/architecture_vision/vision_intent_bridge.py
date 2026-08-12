"""Vision to Architectural Intent Bridge Module (V0.7.3).
Bridges visual feature analysis into ArchitecturalIntent dataclass schema.
"""

from skills.architecture_vision.vision_schema import ArchitectureVisualAnalysis
from skills.architecture_prompt.intent_schema import ArchitecturalIntent

class VisionIntentBridge:
    """Converts ArchitectureVisualAnalysis into ArchitecturalIntent schema."""

    def bridge_visual_to_intent(self, visual_data: dict, text_hint: str = "") -> ArchitecturalIntent:
        intent = ArchitecturalIntent()

        # Map Building Type
        b_type = visual_data.get("type", "museum")
        intent.building_type = b_type

        # Map Scene Type
        rec_wf = visual_data.get("recommended_video", "1_image_to_video")
        if rec_wf == "3_night_transition" or "黄昏" in text_hint or "夜景" in text_hint:
            intent.scene_type = "night_transition"
            intent.lighting.time = "twilight_dusk"
            intent.lighting.interior_light = "3500K warm interior glow through curtainwall"
        elif rec_wf == "2_aerial_view" or "鸟瞰" in text_hint:
            intent.scene_type = "aerial"
            intent.camera.movement = "high_altitude_drone"
        elif rec_wf == "5_walkthrough" or "漫游" in text_hint:
            intent.scene_type = "interior"
            intent.camera.movement = "pedestrian_walkthrough"
        else:
            intent.scene_type = "exterior"

        # Map Reasoning Dimensions
        style = visual_data.get("style", "")
        if "concrete" in style or "安藤" in text_hint:
            intent.reasoning.design_language = "minimalism"
            intent.reasoning.spatial_character = "quiet"
            intent.reasoning.material_expression = "raw_concrete"
            intent.reasoning.emotional_target = "poetic"
        elif "timber" in style or "木" in text_hint:
            intent.reasoning.design_language = "modernism"
            intent.reasoning.spatial_character = "intimate"
            intent.reasoning.material_expression = "natural_timber"

        return intent
