"""Prompt Revision Strategy Engine (V0.7.6 Upgraded).
Revises positive and negative prompts based on Critic Agent feedback.
"""

from typing import Dict, Any, Tuple

class PromptRevisionEngine:
    """Applies Critic Feedback to revise prompts dynamically."""

    def revise_prompt(self, positive_prompt: str, negative_prompt: str, feedback: Any) -> Tuple[str, str]:
        revised_pos = positive_prompt
        revised_neg = negative_prompt

        # Backward compatibility with ArchitecturalCriticFeedback object
        geom_score = getattr(feedback, "geometry_score", 100.0)
        if geom_score < 80.0:
            revised_pos += ", strict geometric lock, structural alignment"
            revised_neg += ", distorted geometry, warped structural beams"

        return revised_pos, revised_neg

    def revise_prompt_with_critic_feedback(
        self,
        positive_prompt: str,
        negative_prompt: str,
        critic_feedback: Dict[str, Any]
    ) -> Dict[str, str]:
        revised_pos = positive_prompt
        revised_neg = negative_prompt

        revision_strat = critic_feedback.get("revision_strategy", {})
        action = revision_strat.get("recommended_action", "")

        if "geometry_lock" in action:
            revised_pos += ", strict perspective preservation, avoid dramatic cinematic distortion"
            revised_neg += ", distorted facade grid, bent structural columns"
        elif "material" in action:
            revised_pos += ", highly detailed tactile material surface texture"
        elif "tilt-shift" in action:
            revised_pos += ", 35mm architectural tilt-shift lens perspective"

        return {
            "positive_prompt": revised_pos,
            "negative_prompt": revised_neg,
            "revision_applied": True
        }
