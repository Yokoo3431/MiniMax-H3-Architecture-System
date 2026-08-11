"""Prompt Quality Evaluator Module (V0.7.1.6 Upgraded).
Evaluates completeness and architectural accuracy across 5 distinct dimensions.
"""

from typing import Dict, Any, List

class PromptQualityEvaluator:
    """Scores generated prompts across 5 architectural dimensions."""

    def evaluate(self, positive_prompt: str, intent_dict: Dict[str, Any]) -> dict:
        prompt_lower = positive_prompt.lower()
        missing = []

        # 1. Architectural Accuracy (0-100)
        arch_acc = 100
        b_type = intent_dict.get("building_type", "")
        if not b_type or b_type == "unknown":
            missing.append("building type topology")
            arch_acc -= 20

        # 2. Camera Quality (0-100)
        cam_qual = 100
        if "shot" not in prompt_lower and "camera" not in prompt_lower and "lens" not in prompt_lower:
            missing.append("camera trajectory/lens description")
            cam_qual -= 30

        # 3. Lighting Quality (0-100)
        light_qual = 100
        if "illumination" not in prompt_lower and "glow" not in prompt_lower and "daylight" not in prompt_lower:
            missing.append("lighting atmosphere specification")
            light_qual -= 30

        # 4. Material Quality (0-100)
        mat_qual = 100
        if not any(m in prompt_lower for m in ["glass", "concrete", "timber", "metal", "stone", "marble", "facade"]):
            missing.append("material texture detail")
            mat_qual -= 30

        # 5. Constraint Compliance (0-100)
        const_comp = 100
        if "geometry" not in prompt_lower and "integrity" not in prompt_lower and "proportions" not in prompt_lower:
            missing.append("geometry preservation lock constraint")
            const_comp -= 30

        overall_score = round(
            (arch_acc * 0.25) +
            (cam_qual * 0.20) +
            (light_qual * 0.20) +
            (mat_qual * 0.20) +
            (const_comp * 0.15),
            1
        )

        return {
          "scores": {
            "architectural_accuracy": max(50, arch_acc),
            "camera_quality": max(50, cam_qual),
            "lighting_quality": max(50, light_qual),
            "material_quality": max(50, mat_qual),
            "constraint_compliance": max(50, const_comp)
          },
          "quality_score": overall_score,
          "status": "EXCELLENT" if overall_score >= 85 else ("GOOD" if overall_score >= 70 else "NEEDS_IMPROVEMENT"),
          "missing": missing
        }
