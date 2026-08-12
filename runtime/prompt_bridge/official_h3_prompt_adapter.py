"""Official MiniMax H3 Prompt Adapter Engine (V0.8.0 RC3).
Adapts Chinese & English natural language design intent into MiniMax H3 structured prompts (Camera, Motion, Lighting, Geometry, Material, Atmosphere).
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

        if "黄昏" in user_intent or "夜景" in user_intent or "twilight" in user_intent or "dusk" in user_intent or "sunset" in user_intent:
            lighting = "sunset twilight illumination transitioning to evening, warm 3500K interior glow through curtainwall"
        if "漫游" in user_intent or "室内" in user_intent or "walkthrough" in user_intent or "atrium" in user_intent:
            camera = "pedestrian eye level walkthrough shot, steady camera movement"
            motion = "steady walkthrough through atrium courtyard"
        if "鸟瞰" in user_intent or "aerial" in user_intent or "drone" in user_intent or "环绕" in user_intent:
            camera = "high altitude drone orbit flight trajectory"
            motion = "sweeping masterplan orbit"
        if "材质" in user_intent or "细节" in user_intent or "material" in user_intent or "texture" in user_intent:
            material = "tactile material detail, timber louvers and raw fair-faced concrete texture"

        structured_prompt = (
            f"Architectural visualization of building, Camera: {camera}, Motion: {motion}, Lighting: {lighting}, "
            f"Geometry: {geometry}, Material: {material}, Atmosphere: {atmosphere}, photorealistic architectural photography, 4k ultra detailed"
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
    res = adapter.adapt_prompt("生成建筑鸟瞰宣传视频，保持建筑体量，缓慢无人机环绕，黄昏光线", "04_Drone_Aerial")
    import json
    print(json.dumps(res, indent=2, ensure_ascii=False))
