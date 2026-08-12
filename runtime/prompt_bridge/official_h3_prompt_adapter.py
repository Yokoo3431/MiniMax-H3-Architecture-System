"""Official MiniMax H3 Prompt Adapter Engine (V0.8.0 RC2).
Adapts natural language design intent into MiniMax H3 structured prompts (camera, motion, lighting, geometry, material, atmosphere).
"""

from typing import Dict, Any

class OfficialH3PromptAdapter:
    """Adapts user design intent into official MiniMax H3 prompt format."""

    def adapt_prompt(self, user_intent: str, workflow_key: str = "01_Exterior_Hero") -> Dict[str, Any]:
        camera = "slow cinematic push-in shot with 35mm architectural lens"
        motion = "subtle architectural reveal"
        lighting = "twilight dusk illumination with warm 3500K interior glow"
        geometry = "preserve building geometry, stable facade structural integrity"
        material = "fair-faced architectural concrete facade, raw tactile texture"
        atmosphere = "quiet monumental atmosphere, soft twilight dusk sky"

        if "夜景" in user_intent or "黄昏" in user_intent or "night" in user_intent or "twilight" in user_intent:
            lighting = "sunset twilight illumination transitioning to night, warm 3500K interior glow through curtainwall"
        if "漫游" in user_intent or "室内" in user_intent or "walkthrough" in user_intent:
            camera = "pedestrian eye level walkthrough shot, steady camera movement"
            motion = "steady walkthrough through atrium"
        if "鸟瞰" in user_intent or "aerial" in user_intent or "drone" in user_intent:
            camera = "high altitude drone orbit flight trajectory"
            motion = "sweeping masterplan orbit"
        if "材质" in user_intent or "细节" in user_intent or "material" in user_intent:
            material = "tactile material detail, timber louvers and raw concrete texture"

        structured_prompt = (
            f"Architectural visualization of building, {camera}, {motion}, {lighting}, "
            f"{geometry}, {material}, {atmosphere}, photorealistic architectural photography, 4k ultra detailed"
        )

        negative_prompt = (
            "abrupt lighting jump, wall deformation, window artifacting, structural drift, "
            "noise, flickering, unstable structure, impossible camera movement"
        )

        return {
            "original_intent": user_intent,
            "workflow_key": workflow_key,
            "structured_elements": {
                "camera": camera,
                "motion": motion,
                "lighting": lighting,
                "geometry_preservation": geometry,
                "material_preservation": material,
                "atmosphere": atmosphere
            },
            "positive_prompt": structured_prompt,
            "negative_prompt": negative_prompt
        }

if __name__ == "__main__":
    adapter = OfficialH3PromptAdapter()
    res = adapter.adapt_prompt("把这个安藤风格混凝土美术馆效果图制作成30秒黄昏建筑宣传动画", "01_Exterior_Hero")
    import json
    print(json.dumps(res, indent=2, ensure_ascii=False))
