"""Revision Executor Engine (V0.7.7).
Executes prompt and workflow parameter revisions based on Critic recommendations.
"""

from typing import Dict, Any, List
from runtime.feedback.prompt_revision import PromptRevisionEngine
from runtime.workflow_intelligence.workflow_revision import WorkflowRevisionEngine

class RevisionExecutor:
    """Combines prompt and workflow parameter revisions into an updated execution strategy."""

    def __init__(self):
        self.prompt_reviser = PromptRevisionEngine()
        self.workflow_reviser = WorkflowRevisionEngine()

    def execute_revision(
        self,
        positive_prompt: str,
        negative_prompt: str,
        base_params: Dict[str, Any],
        critic_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        prompt_rev = self.prompt_reviser.revise_prompt_with_critic_feedback(
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            critic_feedback=critic_result
        )

        issues = critic_result.get("critic_result", {}).get("issues", [])
        revised_params = self.workflow_reviser.adjust_workflow_parameters(base_params, issues)

        strategies = []
        for rec in critic_result.get("critic_result", {}).get("recommendations", []):
            strategies.append(rec.get("action", ""))

        return {
            "positive_prompt": prompt_rev["positive_prompt"],
            "negative_prompt": prompt_rev["negative_prompt"],
            "revised_parameters": revised_params,
            "applied_strategies": strategies
        }
