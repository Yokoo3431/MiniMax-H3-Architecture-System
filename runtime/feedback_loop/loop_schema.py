"""Closed Loop Schema Dataclasses (V0.7.7).
Defines IterationRecord and ClosedLoopResult.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class IterationRecord:
    iteration_number: int = 1
    video_path: str = ""
    overall_score: float = 82.0
    issues: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration_number,
            "video_path": self.video_path,
            "overall_score": self.overall_score,
            "issues": self.issues,
            "recommendations": self.recommendations
        }

@dataclass
class ClosedLoopResult:
    iterations: int = 2
    initial_score: float = 82.0
    final_score: float = 90.0
    improvement: float = 8.0
    status: str = "improved"
    successful_strategy: List[str] = field(default_factory=list)
    iteration_records: List[IterationRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iterations": self.iterations,
            "initial_score": self.initial_score,
            "final_score": self.final_score,
            "improvement": self.improvement,
            "status": self.status,
            "successful_strategy": self.successful_strategy,
            "iteration_records": [r.to_dict() for r in self.iteration_records]
        }
