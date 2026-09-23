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
from .job_state import (
    RECONCILIATION_GRACE_SECONDS, is_job_active, is_job_terminal,
    normalize_terminal_record,
)
from runtime.reference_contract import (
    reference_bindings, required_reference_roles, resolve_selected_references,
)


def _job_age_seconds(job: Dict[str, Any]) -> float:
    from .job_state import job_age_seconds
    return job_age_seconds(job)


def converge_stale_reconciliation(store: StudioStore, project_id: str) -> bool:
    """Close unrecoverable, old reconciliation records without a prompt id."""
    jobs = store.load_jobs(project_id)
    changed = False
    for job in jobs.values():
        if job.get("state") != "RECONCILING" or job.get("prompt_id"):
            continue
        if _job_age_seconds(job) < RECONCILIATION_GRACE_SECONDS:
            continue
        job["state"] = "SUBMISSION_LOST"
        job["lifecycle_state"] = "SUBMISSION_LOST"
        job["submission_state"] = "SUBMISSION_LOST"
        job["failure_code"] = job.get("failure_code") or "COMFY_COMMUNICATION_TIMEOUT"
        job["error_category"] = job.get("error_category") or "COMFY_COMMUNICATION_TIMEOUT"
        job["failure_reason"] = "未能在重试窗口内确认 ComfyUI 已接受任务"
        job["user_message"] = "任务提交未被 ComfyUI 确认，可重新生成"
        job["finished_at"] = job.get("finished_at") or store.timestamp()
        job["terminal_normalized_at"] = job["finished_at"]
        job["reconciliation_terminal_reason"] = "no prompt_id or durable accepted submission after grace period"
        stages = list(job.get("stages") or [])
        if "SUBMISSION_LOST" not in stages:
            stages.append("SUBMISSION_LOST")
        job["stages"] = stages
        job["updated_at"] = store.timestamp()
        changed = True
    if changed:
        store.save_jobs(project_id, jobs)
    return changed

def _latest(records: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    values = list(records)
    return max(values, key=lambda item: item.get("created_at", ""), default=None)


def build_study_state(store: StudioStore, project_id: str) -> Dict[str, Any]:
    project = store.load_project(project_id)
    converge_stale_reconciliation(store, project_id)
    refs = list(store.load_references(project_id).values())
    intent = store.load_intent(project_id) or {}
    prompt = store.load_prompt(project_id) or {}
    jobs_by_id = store.load_jobs(project_id)
    jobs = list(jobs_by_id.values())
    normalized = False
    for job in jobs:
        if is_job_terminal(job):
            normalized = normalize_terminal_record(job, store.timestamp()) or normalized
    if normalized:
        store.save_jobs(project_id, jobs_by_id)

    selected_workflow = intent.get("selected_workflow")
    required_roles = required_reference_roles(selected_workflow)
    refs_by_id = {str(item.get("id")): item for item in refs if item.get("id")}
    selected_ids = project.get("selected_reference_asset_ids")
    selected_ids = selected_ids if isinstance(selected_ids, dict) else {}
    selected_records: list[Dict[str, Any]] = []
    reference_slots: list[Dict[str, Any]] = []
    slot_problems: list[str] = []
    role_labels = {"first_frame": "首帧", "last_frame": "末帧"}
    for role in required_roles:
        asset_id = selected_ids.get(role)
        if not asset_id and role == "first_frame":
            asset_id = project.get("current_reference_asset_id")
        record = refs_by_id.get(str(asset_id)) if asset_id else None
        if record:
            selected_records.append(record)
        label = role_labels.get(role, role)
        if not asset_id:
            slot_problems.append(f"上传{label}")
        elif not record:
            slot_problems.append(f"重新选择{label}（引用已失效）")
        elif str(record.get("project_id") or "") != str(project_id):
            slot_problems.append(f"重新选择{label}（项目不匹配）")
        elif record.get("role") != role:
            slot_problems.append(f"重新选择{label}（用途不匹配）")
        elif record.get("state") != "APPROVED":
            slot_problems.append(f"批准{label}")
        stored = record.get("stored_path") if record else None
        preview_ready = bool(stored and Path(stored).is_file())
        reference_slots.append({
            "role": role,
            "asset_id": str(asset_id) if asset_id else None,
            "filename": record.get("filename") if record else None,
            "approval_state": record.get("state") if record else "MISSING",
            "approved": bool(record and record.get("state") == "APPROVED"
                             and record.get("role") == role
                             and str(record.get("project_id") or "") == str(project_id)),
            "preview_ready": preview_ready,
            "preview_url": (
                f"/api/assets/{record['id']}/content?v={record.get('sha256') or record.get('version', 1)}"
                if record and preview_ready else None),
        })
    try:
        current_refs = resolve_selected_references(
            project_id, project, refs_by_id, selected_workflow,
            require_approved=True, reference_root=store.input_dir(project_id))
        reference_error = None
    except ValueError as exc:
        current_refs = []
        reference_error = str(exc)
    reference = next((item for item in selected_records
                      if item.get("role") == "first_frame"), None)
    reference_uploaded = any(slot["asset_id"] for slot in reference_slots)
    reference_preview_ready = bool(
        reference and reference.get("stored_path")
        and Path(reference["stored_path"]).is_file())
    reference_approved = len(current_refs) == len(required_roles)
    if reference_error and "DUPLICATE" in reference_error:
        slot_problems.append("首帧和末帧必须是不同的图像")
    approved_hash = reference_asset_hash(current_refs)
    prompt_ready = is_current_prompt(
        prompt,
        intent=str(intent.get("natural_language") or ""),
        workflow=str(selected_workflow or ""),
        reference_hash=approved_hash,
        parameters=prompt.get("generation_parameters") if prompt else None,
        provider=prompt.get("prompt_engine_provider") if prompt else None,
    ) and reference_approved
    prompt_confirmed = bool(
        prompt_ready and project.get("state") in {
            "USER_CONFIRM", "GPU_RUNNING", "QUALITY_CHECK", "COMPLETED",
            "GPU_FAILED", "QUALITY_FAILED"
        }
    )
    active_job = _latest(j for j in jobs if is_job_active(j))
    last_job = _latest(jobs)
    intent_ready = bool(intent and not intent.get("requires_user_confirmation"))

    missing = list(dict.fromkeys(slot_problems))
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
        "current_reference_asset_id": reference.get("id") if reference else None,
        "reference_role": reference.get("role") if reference else None,
        "required_reference_roles": list(required_roles),
        "reference_slots": reference_slots,
        "reference_bindings": reference_bindings(selected_records),
        "reference_error": reference_error,
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
