"""Architectural Critic Schema Dataclasses (V0.7.6).
Defines CriticResult, CriticIssue, CriticScore, and Recommendation.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class CriticScore:
    overall_score: float = 95.0
    architectural_intent_accuracy: float = 95.0
    geometry_consistency: float = 95.0
    camera_quality: float = 95.0
    material_realism: float = 95.0
    lighting_quality: float = 95.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "overall_score": self.overall_score,
            "dimensions": {
                "architectural_intent_accuracy": self.architectural_intent_accuracy,
                "geometry_consistency": self.geometry_consistency,
                "camera_quality": self.camera_quality,
                "material_realism": self.material_realism,
                "lighting_quality": self.lighting_quality
            }
        }

@dataclass
class CriticIssue:
    category: str = "geometry_failure"
    severity: str = "medium"
    description: str = "Building facade geometry shows minor deformation during pan"

    def to_dict(self) -> Dict[str, str]:
        return {
            "category": self.category,
            "severity": self.severity,
            "description": self.description
        }

@dataclass
class Recommendation:
    action: str = "increase geometry_lock weight"
    target: str = "prompt_rule"
    suggestion: str = "add strict structural preservation constraint"

    def to_dict(self) -> Dict[str, str]:
        return {
            "action": self.action,
            "target": self.target,
            "suggestion": self.suggestion
        }

@dataclass
class CriticResult:
    score: CriticScore = field(default_factory=CriticScore)
    issues: List[CriticIssue] = field(default_factory=list)
    recommendations: List[Recommendation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        res = self.score.to_dict()
        res["issues"] = [i.to_dict() for i in self.issues]
        res["recommendations"] = [r.to_dict() for r in self.recommendations]
        return res
