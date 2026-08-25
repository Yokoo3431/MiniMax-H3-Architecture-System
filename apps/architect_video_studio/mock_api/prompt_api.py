"""Prompt API (mock, contract-first).

Prompt generation reuses the FROZEN OfficialSkillAdapter.build_prompt()
(read-only; official skill structure verification + provenance included).
There is NO update/edit endpoint: prompts are read-only by contract.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..state_machine.machine import ProjectStateMachine
from .store import StudioStore
from runtime.h3_generation_parameters import normalize_generation_parameters
from runtime.prompt_provenance import (
    generation_parameters_hash,
    prompt_input_hash,
    reference_asset_hash,
)
from runtime.workflow_motion import normalize_camera_motion

FROZEN_WORKFLOWS = (
    "01_Exterior_Hero",
    "02_Day_Night_Transition",
    "03_Material_Detail",
    "04_Drone_Aerial",
    "05_Slow_Walkthrough",
)

CAMERA_BY_WORKFLOW = {
    "01_Exterior_Hero": "slow_push",
    "02_Day_Night_Transition": "static",
    "03_Material_Detail": "static",
    "04_Drone_Aerial": "aerial_reveal",
    "05_Slow_Walkthrough": "walkthrough",
}

PRIORITY_BY_WORKFLOW = {
    "01_Exterior_Hero": "geometry",
    "02_Day_Night_Transition": "lighting",
    "03_Material_Detail": "material",
    "04_Drone_Aerial": "geometry",
    "05_Slow_Walkthrough": "geometry",
}


class PromptAPI:
    def __init__(self, store: StudioStore, adapter=None) -> None:
        self.store = store
        from runtime.prompt_bridge.official_skill_adapter import (
            ArchitectIntent,
            OfficialSkillAdapter,
            ReferenceMetadata,
        )
        self._intent_cls = ArchitectIntent
        self._ref_cls = ReferenceMetadata
        if adapter is None:
            adapter = OfficialSkillAdapter()
        self.adapter = adapter

    def generate_prompt(self, project_id: str,
                        workflow: str | None = None,
                        generation_parameters: Dict[str, Any] | None = None) -> Dict[str, Any]:
        project = self.store.load_project(project_id)
        if project["state"] == "GPU_RUNNING":
            raise ValueError(
                "当前任务正在生成，完成后才能更新 Prompt"
            )
        intent = self.store.load_intent(project_id)
        if intent is None:
            raise ValueError("analyze_intent first")
        if intent.get("requires_user_confirmation"):
            raise ValueError("intent requires user workflow confirmation first")

        workflow = workflow or intent.get("selected_workflow")
        if workflow not in FROZEN_WORKFLOWS:
            raise ValueError(f"workflow {workflow!r} not in frozen set {FROZEN_WORKFLOWS}")

        approved = [r for r in self.store.load_references(project_id).values()
                    if r["state"] == "APPROVED"]
        if not approved:
            raise ValueError("Reference Approval Gate: no approved reference")

        reference_paths = [r["stored_path"] or r["filename"] for r in approved]
        reference_hash = reference_asset_hash(approved)
        camera_motion = normalize_camera_motion(workflow)
        intent_obj = self._intent_cls(
            project_type=project["project_type"],
            video_task=intent.get("selected_video_task"),
            scene=intent.get("natural_language", ""),
            camera_motion=camera_motion,
            amplitude="small",
            speed="slow",
            priority=PRIORITY_BY_WORKFLOW[workflow],
            constraints=["geometry", "material"],
            confidence=float(intent.get("confidence") or 0.0),
            reason=intent.get("reason", ""),
            requires_user_confirmation=False,
        )
        ref_meta = self._ref_cls(
            input_images=reference_paths,
            user_approved=True,
        )
        frame_count = 107 if workflow == "02_Day_Night_Transition" else None
        params = normalize_generation_parameters(generation_parameters)
        prompt = self.adapter.build_prompt(
            intent_obj,
            workflow=workflow,
            reference=ref_meta,
            duration_seconds=params["duration"],
            frame_count=frame_count,
            fps=float(params["fps"]),
        )
        created_at = self.store.timestamp()
        params_hash = generation_parameters_hash(params)
        record = {
            "project_id": project_id,
            "workflow": workflow,
            "mode": prompt["mode"],
            "prompt": prompt["prompt"],
            "alignment": prompt["alignment"],
            "integrated_multimodal_description": prompt["integrated_multimodal_description"],
            "overall_soundscape": prompt["overall_soundscape"],
            "non_diegetic_music": prompt["non_diegetic_music"],
            "verified": prompt["verified"],
            "prompt_hash": prompt["provenance"]["generated_prompt_hash"],
            "provenance": prompt["provenance"],
            "generation_parameters": params,
            "original_intent": intent.get("natural_language", ""),
            "optimized_prompt": prompt["prompt"],
            "workflow_id": workflow,
            "reference_asset_hash": reference_hash,
            "generation_parameters_hash": params_hash,
            "input_hash": prompt_input_hash(
                intent.get("natural_language", ""), workflow,
                reference_hash, params),
            "generated_at": created_at,
            "adapter_version": prompt["provenance"].get("adapter_revision", ""),
            "bridge_version": prompt["provenance"].get("bridge_revision", ""),
            "status": "CURRENT",
            "official_skill_status": "官方 H3 Prompt Skill 已优化",
            "created_at": created_at,
        }
        self.store.save_prompt(project_id, record)

        # A terminal Job is history, not an edit lock on the Study.  Restore
        # the editable Study state before applying the normal prompt transition.
        if project["state"] in ("GPU_FAILED", "QUALITY_FAILED", "COMPLETED"):
            project["state"] = "PROMPT_REVIEW"
            self.store.save_project(project)
        machine = ProjectStateMachine(project["state"])
        if machine.state == "PROMPT_REVIEW":
            machine.transition("show_generation_panel", actor="architect",
                               reason="prompt generated")
        # from USER_CONFIRM (regenerate) stay in USER_CONFIRM
        project["state"] = machine.state
        self.store.save_project(project)
        self.store.append_audit(project_id, {
            "actor": "architect",
            "event": "generate_prompt",
            "from": "PROMPT_REVIEW",
            "to": "USER_CONFIRM",
            "detail": {"workflow": workflow, "prompt_hash": record["prompt_hash"]},
        })
        return record

    def get_prompt(self, project_id: str) -> Dict[str, Any]:
        prompt = self.store.load_prompt(project_id)
        if prompt is None:
            raise KeyError("no prompt record yet")
        return prompt
