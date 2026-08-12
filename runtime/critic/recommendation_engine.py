"""Recommendation Engine (V0.7.6).
Generates actionable correction strategies targeting Prompt, Workflow, Model Registry, Acceleration Profile, and Memory Layer.
"""

from typing import List
from runtime.critic.critic_schema import CriticIssue, Recommendation

class RecommendationEngine:
    """Generates actionable recommendations based on failure classification."""

    def generate_recommendations(self, issues: List[CriticIssue]) -> List[Recommendation]:
        recommendations = []

        for issue in issues:
            cat = issue.category
            if cat == "geometry_failure":
                recommendations.append(Recommendation(
                    action="increase geometry_lock weight",
                    target="prompt_rule",
                    suggestion="add strict structural preservation constraint, preserve facade grid"
                ))
            elif cat == "material_failure":
                recommendations.append(Recommendation(
                    action="apply material LoRA weight bump",
                    target="model_registry",
                    suggestion="bump concrete_realism_v1 LoRA weight to 0.85"
                ))
            elif cat == "camera_failure":
                recommendations.append(Recommendation(
                    action="inject 35mm tilt-shift lens constraint",
                    target="prompt_engine",
                    suggestion="specify steady tripod 35mm architectural tilt-shift lens perspective"
                ))
            elif cat == "lighting_failure":
                recommendations.append(Recommendation(
                    action="enforce 3500K interior warm glow",
                    target="workflow_preset",
                    suggestion="lock lighting model to dusk twilight with 3500K warm interior illumination"
                ))
            elif cat == "architectural_intent_failure":
                recommendations.append(Recommendation(
                    action="retrieve high-score memory case",
                    target="memory_layer",
                    suggestion="inject historical memory strategy from architectural knowledge graph"
                ))

        if not recommendations:
            recommendations.append(Recommendation(
                action="maintain current strategy",
                target="h3_orchestrator",
                suggestion="generation meets architectural intent criteria; no revision required"
            ))

        return recommendations
