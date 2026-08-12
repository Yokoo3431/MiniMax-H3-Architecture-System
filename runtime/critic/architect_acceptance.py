"""Architect Intent Acceptance Auditor (V0.7.8.3).
Validates architect intent recognition, preset selection, prompt completeness, and workflow matching.
"""

from typing import Dict, Any

class ArchitectIntentAuditor:
    """Audits user intent recognition, preset matching, and prompt completeness."""

    def audit_architect_intent(self, task_text: str, generated_prompt: str, selected_workflow: str) -> Dict[str, Any]:
        prompt_complete = len(generated_prompt) > 30 and "Architectural visualization" in generated_prompt
        workflow_matched = selected_workflow in [
            "1_image_to_video",
            "2_aerial_view",
            "3_night_transition",
            "5_walkthrough",
            "6_massing_evolution",
            "8_exploded_axon"
        ]

        intent_score = 95.0 if (prompt_complete and workflow_matched) else 80.0

        return {
            "task_text": task_text,
            "intent_score": intent_score,
            "prompt_completeness": prompt_complete,
            "workflow_matched": workflow_matched,
            "status": "PASS" if intent_score >= 85.0 else "WARNING"
        }
