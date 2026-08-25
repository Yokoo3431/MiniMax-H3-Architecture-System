"""Intent API (mock, contract-first).

Classification reuses the FROZEN OfficialSkillAdapter.classify_intent()
(read-only; no prompt authored here).
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..state_machine.machine import ProjectStateMachine
from .store import StudioStore


class IntentAPI:
    def __init__(self, store: StudioStore, adapter=None) -> None:
        self.store = store
        if adapter is None:
            from runtime.prompt_bridge.official_skill_adapter import OfficialSkillAdapter
            adapter = OfficialSkillAdapter()
        self.adapter = adapter

    def analyze_intent(self, project_id: str, natural_language: str) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        if project["state"] != "REFERENCE_APPROVED":
            raise ValueError(
                f"analyze_intent requires REFERENCE_APPROVED; project is {project['state']}"
            )
        if not (natural_language or "").strip():
            raise ValueError("natural_language is required")

        result = self.adapter.classify_intent(natural_language)
        intent = {
            "project_id": project_id,
            "natural_language": natural_language,
            "selected_workflow": result["selected_workflow"],
            "selected_video_task": result["selected_video_task"],
            "confidence": result["confidence"],
            "reason": result["reason"],
            "requires_user_confirmation": result["requires_user_confirmation"],
            "candidate_workflows": result["candidate_workflows"],
            "created_at": self.store.timestamp(),
        }
        self.store.save_intent(project_id, intent)

        machine = ProjectStateMachine(project["state"])
        if result["requires_user_confirmation"]:
            machine.transition("analyze_intent", actor="architect",
                               reason="intent analysis")
            machine.transition("intent_ambiguous", actor="architect",
                               reason=result["reason"])
        else:
            machine.transition("analyze_intent", actor="architect",
                               reason="intent analysis")
            machine.transition("intent_high_confidence", actor="architect",
                               reason=result["reason"])
        project["state"] = machine.state
        project["intent_confirmed"] = not result["requires_user_confirmation"]
        self.store.save_project(project)
        self.store.append_audit(project_id, {
            "actor": "architect",
            "event": "analyze_intent",
            "from": "REFERENCE_APPROVED",
            "to": project["state"],
            "detail": {
                "confidence": result["confidence"],
                "requires_user_confirmation": result["requires_user_confirmation"],
                "candidates": result["candidate_workflows"],
            },
        })
        return intent

    def confirm_workflow(self, project_id: str, workflow: str) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        if project["state"] != "PROMPT_NEEDS_CONFIRMATION":
            raise ValueError(
                f"confirm_workflow requires PROMPT_NEEDS_CONFIRMATION; project is {project['state']}"
            )
        intent = self.store.load_intent(project_id)
        if intent is None:
            raise ValueError("no intent record; analyze_intent first")
        if workflow not in (intent.get("candidate_workflows") or []):
            raise ValueError(
                f"workflow {workflow!r} is not one of the offered candidates: "
                f"{intent.get('candidate_workflows')}"
            )
        intent["selected_workflow"] = workflow
        intent["selected_video_task"] = self._video_task_for(workflow)
        intent["requires_user_confirmation"] = False
        self.store.save_intent(project_id, intent)

        machine = ProjectStateMachine("PROMPT_NEEDS_CONFIRMATION")
        machine.transition("user_selects_workflow", actor="architect",
                           reason=f"user selected {workflow}")
        project["state"] = machine.state
        project["intent_confirmed"] = True
        self.store.save_project(project)
        self.store.append_audit(project_id, {
            "actor": "architect",
            "event": "user_selects_workflow",
            "from": "PROMPT_NEEDS_CONFIRMATION",
            "to": "PROMPT_REVIEW",
            "detail": {"workflow": workflow},
        })
        return intent

    def get_intent(self, project_id: str) -> Dict[str, Any]:
        intent = self.store.load_intent(project_id)
        if intent is None:
            raise KeyError("no intent record yet")
        return intent

    def select_workflow(self, project_id: str, workflow: str) -> Dict[str, Any]:
        """Persist a deliberate workflow change and invalidate stale Prompt data."""
        project = self.store.load_project(project_id)
        if project["state"] not in {"PROMPT_REVIEW", "USER_CONFIRM", "GPU_FAILED"}:
            raise ValueError(
                f"select_workflow requires PROMPT_REVIEW/USER_CONFIRM/GPU_FAILED; "
                f"project is {project['state']}"
            )
        intent = self.store.load_intent(project_id)
        if intent is None:
            raise ValueError("no intent record; analyze_intent first")
        frozen = {
            "01_Exterior_Hero", "02_Day_Night_Transition", "03_Material_Detail",
            "04_Drone_Aerial", "05_Slow_Walkthrough",
        }
        if workflow not in frozen:
            raise ValueError(f"workflow {workflow!r} is not frozen")
        if intent.get("selected_workflow") != workflow:
            intent["selected_workflow"] = workflow
            intent["selected_video_task"] = self._video_task_for(workflow)
            intent["requires_user_confirmation"] = False
            self.store.save_intent(project_id, intent)
            self.store.clear_prompt(project_id)
            self.store.append_audit(project_id, {
                "actor": "architect", "event": "select_workflow",
                "from": project["state"], "to": project["state"],
                "detail": {"workflow": workflow, "invalidated_prompt": True},
            })
        return intent

    @staticmethod
    def _video_task_for(workflow: str) -> str:
        return {
            "01_Exterior_Hero": "exterior_hero",
            "02_Day_Night_Transition": "day_night_transition",
            "03_Material_Detail": "material_detail",
            "04_Drone_Aerial": "drone_aerial",
            "05_Slow_Walkthrough": "slow_walkthrough",
        }[workflow]
