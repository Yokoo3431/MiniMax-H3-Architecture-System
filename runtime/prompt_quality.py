"""Prompt Quality Evaluator Module (V0.7.1.5)
Evaluates completeness and architectural accuracy of generated prompts.
"""

from typing import Dict, Any, List

class PromptQualityEvaluator:
    """Scores generated prompts on completeness and architectural accuracy."""

    def evaluate(self, positive_prompt: str, intent_dict: Dict[str, Any]) -> dict:
        prompt_lower = positive_prompt.lower()
        missing = []
        score = 100

        # Check 1: Building Type Completeness
        b_type = intent_dict.get("building_type", "")
        if not b_type or b_type == "unknown":
            missing.append("building type topology")
            score -= 10

        # Check 2: Camera Description
        cam_mov = intent_dict.get("camera", {}).get("movement", "")
        if "shot" not in prompt_lower and "camera" not in prompt_lower and "lens" not in prompt_lower:
            missing.append("camera trajectory/lens description")
            score -= 15

        # Check 3: Lighting Specification
        time_light = intent_dict.get("lighting", {}).get("time", "")
        if "illumination" not in prompt_lower and "glow" not in prompt_lower and "daylight" not in prompt_lower:
            missing.append("lighting atmosphere specification")
            score -= 15

        # Check 4: Material Texture Detail
        if not any(m in prompt_lower for m in ["glass", "concrete", "timber", "metal", "stone", "marble", "facade"]):
            missing.append("material texture detail")
            score -= 15

        # Check 5: Geometry Constraint Lock
        if "geometry" not in prompt_lower and "integrity" not in prompt_lower and "proportions" not in prompt_lower:
            missing.append("geometry preservation lock constraint")
            score -= 15

        score = max(50, min(100, score))

        return {
            "quality_score": score,
            "status": "EXCELLENT" if score >= 85 else ("GOOD" if score >= 70 else "NEEDS_IMPROVEMENT"),
            "missing": missing
        }
