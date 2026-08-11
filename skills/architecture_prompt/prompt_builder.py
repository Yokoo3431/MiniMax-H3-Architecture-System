"""MiniMax H3 Optimized Prompt Builder.
Formats positive and negative architectural prompts based on ArchitecturalIntent.
"""

from skills.architecture_prompt.intent_schema import ArchitecturalIntent

class PromptBuilder:
    """Builds MiniMax H3 optimized positive & negative prompts."""

    def build_prompts(self, intent: ArchitecturalIntent, raw_text: str) -> tuple[str, str]:
        # Positive Prompt Components
        pos_parts = [
            f"Architectural visualization of {intent.building_type}",
            f"{intent.camera.movement.replace('_', ' ')} shot with {intent.camera.lens}",
            f"{intent.lighting.time.replace('_', ' ')} illumination",
            intent.lighting.interior_light,
            "preserve building geometry, stable facade structural integrity",
            "photorealistic architectural photography, 4k ultra detailed"
        ]

        if raw_text:
            pos_parts.insert(0, raw_text)

        positive_prompt = ", ".join(pos_parts)

        # Negative Prompt Components
        negative_prompt = (
            "warped building geometry, melted columns, flickering glass facade, "
            "unstable architectural structure, distorted window frames, camera jitter, "
            "low resolution textures, artifacting, blur"
        )

        return positive_prompt, negative_prompt
