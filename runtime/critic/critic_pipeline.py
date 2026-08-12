"""Critic Pipeline Engine (V0.7.6).
Combines ArchitectureCritic -> FailureClassifier -> RecommendationEngine -> Feedback Package.
"""

from runtime.critic.architecture_critic import ArchitectureCriticEngine
from runtime.critic.failure_classifier import FailureClassifier
from runtime.critic.recommendation_engine import RecommendationEngine
from runtime.critic.critic_schema import CriticResult

class CriticPipeline:
    """Main Critic Pipeline running full evaluation and feedback generation."""

    def __init__(self):
        self.critic = ArchitectureCriticEngine()
        self.classifier = FailureClassifier()
        self.recommender = RecommendationEngine()

    def run_critic_pipeline(
        self,
        video_path: str,
        original_image: str,
        task: str,
        prompt_score: float = 95.0
    ) -> dict:
        issues = self.classifier.classify_task_and_video(task, video_path, prompt_score)
        has_geom = any(i.category == "geometry_failure" for i in issues)
        score = self.critic.evaluate_generation(task, prompt_score, has_geometry_issue=has_geom)
        recommendations = self.recommender.generate_recommendations(issues)

        critic_res = CriticResult(
            score=score,
            issues=issues,
            recommendations=recommendations
        )

        return {
            "critic_result": critic_res.to_dict(),
            "revision_strategy": {
                "target_module": recommendations[0].target if recommendations else "h3_orchestrator",
                "recommended_action": recommendations[0].action if recommendations else "maintain"
            },
            "memory_feedback": {
                "update_prepared": True,
                "feedback_score": score.overall_score
            }
        }
