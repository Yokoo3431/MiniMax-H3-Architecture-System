"""Architect Video Studio state machines (PATCH2.6-B).

Implements the PATCH2.6A_State_Machine design:

Project: CREATED -> REFERENCE_PENDING -> REFERENCE_APPROVED -> INTENT_ANALYSIS
         -> PROMPT_REVIEW -> USER_CONFIRM -> GPU_RUNNING -> QUALITY_CHECK
         -> COMPLETED

Exceptions: REFERENCE_REJECTED, PROMPT_NEEDS_CONFIRMATION, GPU_FAILED,
QUALITY_FAILED.

Job: CREATED -> PREPARING -> LOADING_MODEL -> SAMPLING -> ENCODING
     -> EXPORTING -> COMPLETED, with GPU_FAILED.

Illegal transitions raise IllegalTransitionError. Every transition is recorded
in an audit history (actor / event / from / to / timestamp / reason).
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional


class IllegalTransitionError(RuntimeError):
    """Raised when a state machine is asked to perform an illegal transition."""


class _BaseMachine:
    name = "base"
    initial = "CREATED"
    # state -> {event: target_state}
    ALLOWED: Dict[str, Dict[str, str]] = {}

    def __init__(self, initial: Optional[str] = None) -> None:
        self.state = initial or self.initial
        if self.state not in self.ALLOWED:
            raise ValueError(f"Unknown initial state {self.state!r} for {self.name}")
        self.history: List[dict] = []

    def can(self, event: str) -> bool:
        return event in self.ALLOWED.get(self.state, {})

    def expected_target(self, event: str) -> Optional[str]:
        return self.ALLOWED.get(self.state, {}).get(event)

    def transition(self, event: str, actor: str = "system",
                   reason: str = "", _now: Optional[float] = None) -> str:
        target = self.expected_target(event)
        if target is None:
            raise IllegalTransitionError(
                f"{self.name}: illegal transition {self.state!r} --{event}--> ? "
                f"(allowed events: {sorted(self.ALLOWED.get(self.state, {}))})"
            )
        before = self.state
        self.state = target
        self.history.append({
            "at": _now if _now is not None else time.time(),
            "actor": actor,
            "event": event,
            "from": before,
            "to": target,
            "reason": reason,
        })
        return target

    def transition_to(self, target: str, actor: str = "system",
                      reason: str = "") -> str:
        """Transition by finding the event that maps current state -> target."""
        for event, dest in self.ALLOWED.get(self.state, {}).items():
            if dest == target:
                return self.transition(event, actor=actor, reason=reason)
        raise IllegalTransitionError(
            f"{self.name}: no event from {self.state!r} to {target!r}"
        )


class ProjectStateMachine(_BaseMachine):
    name = "project"
    initial = "CREATED"
    ALLOWED: Dict[str, Dict[str, str]] = {
        "CREATED": {"upload_reference": "REFERENCE_PENDING"},
        "REFERENCE_PENDING": {
            "approve": "REFERENCE_APPROVED",
            "reject": "REFERENCE_REJECTED",
        },
        "REFERENCE_REJECTED": {"upload_new": "REFERENCE_PENDING"},
        "REFERENCE_APPROVED": {"analyze_intent": "INTENT_ANALYSIS"},
        "INTENT_ANALYSIS": {
            "intent_high_confidence": "PROMPT_REVIEW",
            "intent_ambiguous": "PROMPT_NEEDS_CONFIRMATION",
        },
        "PROMPT_NEEDS_CONFIRMATION": {
            "user_selects_workflow": "PROMPT_REVIEW",
            "user_edits_intent": "INTENT_ANALYSIS",
        },
        "PROMPT_REVIEW": {
            "show_generation_panel": "USER_CONFIRM",
            "regenerate_prompt": "PROMPT_REVIEW",
        },
        "USER_CONFIRM": {
            "confirm_generate": "GPU_RUNNING",
            "request_changes": "PROMPT_REVIEW",
        },
        "GPU_RUNNING": {
            "succeeded": "QUALITY_CHECK",
            "failed": "GPU_FAILED",
        },
        "GPU_FAILED": {
            "retry_approved": "USER_CONFIRM",
        },
        "QUALITY_CHECK": {
            "quality_pass": "COMPLETED",
            "quality_fail": "QUALITY_FAILED",
        },
        "QUALITY_FAILED": {
            "user_reviewed": "USER_CONFIRM",
        },
        "COMPLETED": {},
    }


class JobStateMachine(_BaseMachine):
    name = "job"
    initial = "CREATED"
    ALLOWED: Dict[str, Dict[str, str]] = {
        "CREATED": {"start": "PREPARING"},
        "PREPARING": {"progress": "LOADING_MODEL", "fail": "GPU_FAILED"},
        "LOADING_MODEL": {"progress": "SAMPLING", "fail": "GPU_FAILED"},
        "SAMPLING": {"progress": "ENCODING", "fail": "GPU_FAILED"},
        "ENCODING": {"progress": "EXPORTING", "fail": "GPU_FAILED"},
        "EXPORTING": {"progress": "COMPLETED", "fail": "GPU_FAILED"},
        "COMPLETED": {},
        "GPU_FAILED": {},  # no auto retry
    }

    # Simulated stage boundaries (seconds after job start).
    STAGE_AT = {
        "PREPARING": 0.0,
        "LOADING_MODEL": 1.0,
        "SAMPLING": 2.0,
        "ENCODING": 3.0,
        "EXPORTING": 4.0,
        "COMPLETED": 5.0,
    }

    @staticmethod
    def state_for_elapsed(elapsed: float) -> str:
        if elapsed >= JobStateMachine.STAGE_AT["COMPLETED"]:
            return "COMPLETED"
        current = "PREPARING"
        for state, threshold in JobStateMachine.STAGE_AT.items():
            if elapsed >= threshold:
                current = state
        return current
