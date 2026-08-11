"""Architectural Prompt Revision Engine (V0.7.1.7 Upgraded).
Revises prompt payload based on Quality Evaluator feedback and Memory Retrieval recommendations.
"""

from runtime.feedback.feedback_schema import ArchitecturalCriticFeedback

class PromptRevisionEngine:
    """Revises positive and negative prompts based on Critic Agent feedback & Quality suggestions."""

    def revise_prompt(self, positive_prompt: str, negative_prompt: str, feedback: ArchitecturalCriticFeedback) -> tuple[str, str]:
        revised_pos = positive_prompt
        revised_neg = negative_prompt

        if feedback.geometry_score < 80.0:
            revised_pos += ", strict geometric lock, uncompromising facade alignment"
            revised_neg += ", distorted geometry, warped structural lines"

        if feedback.material_score < 80.0:
            revised_pos += ", high-definition material specularity, realistic glass and concrete"
            revised_neg += ", material texture morphing, blurry surfaces"

        for note in feedback.revision_notes:
            if "enhance concrete" in note.lower():
                revised_pos += ", fair-faced architectural concrete texture detail"
            elif "reduce camera" in note.lower():
                revised_pos += ", slow steady tripod camera motion"

        return revised_pos, revised_neg
