"""Canonical, read-only normalization of Study and Job state.

The persisted project and asset records remain the domain records.  This module
is the single boundary used by the UI and generation gate to present one
consistent Study state, including recovery from a historical failed Job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .store import StudioStore
from runtime.prompt_provenance import is_current_prompt, reference_asset_hash

TERMINAL_JOB_STATES = {"COMPLETED", "FAILED", "GPU_FAILED", "CANCELLED"}


def _latest(records: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    values = list(records)
    return max(values, key=lambda item: item.get("created_at", ""), default=None)


def build_study_state(store: StudioStore, project_id: str) -> Dict[str, Any]:
    project = store.load_project(project_id)
    refs = list(store.load_references(project_id).values())
    intent = store.load_intent(project_id) or {}
    prompt = store.load_prompt(project_id) or {}
    jobs = list(store.load_jobs(project_id).values())

    approved = [r for r in refs if r.get("state") == "APPROVED"]
    reference = _latest(approved) or _latest(refs)
    reference_uploaded = bool(refs)
    reference_preview_ready = bool(
        reference and reference.get("stored_path")
        and Path(reference["stored_path"]).is_file()
    )
    reference_approved = bool(approved)
    selected_workflow = intent.get("selected_workflow")
    approved_hash = reference_asset_hash(approved)
    prompt_ready = is_current_prompt(
        prompt,
        intent=str(intent.get("natural_language") or ""),
        workflow=str(selected_workflow or ""),
        reference_hash=approved_hash,
        parameters=prompt.get("generation_parameters") if prompt else None,
    )
    prompt_confirmed = bool(
        prompt_ready and project.get("state") in {
            "USER_CONFIRM", "GPU_RUNNING", "QUALITY_CHECK", "COMPLETED",
            "GPU_FAILED", "QUALITY_FAILED"
        }
    )
    active_job = _latest(j for j in jobs if j.get("state") not in TERMINAL_JOB_STATES)
    last_job = _latest(jobs)
    intent_ready = bool(intent and not intent.get("requires_user_confirmation"))

    missing = []
    if not reference_uploaded:
        missing.append("上传参考图")
    if not reference_approved:
        missing.append("批准参考图")
    if not intent_ready:
        missing.append("分析并确认意图")
    if not prompt_ready:
        missing.append("生成 Prompt 预览")
    if active_job:
        missing.append("当前任务完成")

    # A historical GPU failure belongs to the Job history.  Once the durable
    # Study gates are satisfied, the Study is ready again.
    if active_job:
        current_state = "GENERATING"
    elif project.get("state") == "COMPLETED":
        # COMPLETED describes the last Job, not a permanently closed Study.
        # Keep the Study ready for another Job with the same approved asset.
        current_state = "READY_TO_GENERATE"
    elif project.get("state") in {"GPU_FAILED", "QUALITY_FAILED"} and not missing:
        current_state = "READY_TO_GENERATE"
    elif not reference_uploaded or not reference_approved:
        current_state = "REFERENCE_PENDING"
    elif not intent:
        current_state = "REFERENCE_APPROVED"
    elif not intent_ready:
        current_state = "PROMPT_REVIEW"
    elif not prompt_ready:
        current_state = "PROMPT_REVIEW"
    else:
        current_state = "READY_TO_GENERATE"

    state = {
        "study_id": project_id,
        "project_id": project_id,
        "selected_workflow": selected_workflow,
        "reference_asset_id": reference.get("id") if reference else None,
        "reference_role": reference.get("role") if reference else None,
        "reference_uploaded": reference_uploaded,
        "reference_preview_ready": reference_preview_ready,
        "reference_approved": reference_approved,
        "reference_preview_url": (
            f"/api/assets/{reference['id']}/content?v={reference.get('sha256') or reference.get('version', 1)}"
            if reference else None
        ),
        "intent_text": intent.get("natural_language"),
        "intent_analysis": intent or None,
        "prompt_ready": prompt_ready,
        "prompt_current": prompt_ready,
        "prompt_status": (prompt.get("status", "CURRENT") if prompt else "MISSING")
        if prompt_ready else ("STALE" if prompt else "MISSING"),
        "prompt_confirmed": prompt_confirmed,
        "generation_status": current_state,
        "current_state": current_state,
        "generate_allowed": bool(not missing and not active_job),
        "gate_reasons": missing,
        "active_job_id": active_job.get("id") if active_job else None,
        "last_job_id": last_job.get("id") if last_job else None,
        "last_job_status": last_job.get("state") if last_job else None,
        "last_job_error": (last_job or {}).get("failure_reason", ""),
        "output_video": (last_job or {}).get("output_video"),
        "internal_project_state": project.get("state"),
        "updated_at": project.get("updated_at"),
    }
    store.save_study_state(project_id, state)
    return state
