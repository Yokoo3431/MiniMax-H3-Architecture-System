"""Deterministic Studio-owned long-form shot queue contracts for A9.

This module plans and reconciles shot work; it never submits to ComfyUI.
Generation remains an explicit JobAPI action and assembly remains a separate,
resumable CPU delivery stage.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


LONG_FORM_SCHEMA_VERSION = 1
SHOT_QUEUE_STATES = frozenset({
    "PENDING", "PREFLIGHT", "RUNNING", "RESULT_READY", "POSTPROCESSING",
    "READY", "FAILED", "CANCELLED",
})
CONTINUITY_MODES = (
    "INDEPENDENT", "CONTINUE_VISUALLY", "LOCK_PROJECT_IDENTITY",
)
TRANSITION_POLICIES = frozenset({"CUT"})
AUDIO_POLICIES = frozenset({"KEEP_PER_SHOT_CUT", "MUTE"})
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class LongFormError(ValueError):
    """Stable, path-free A9 contract error."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _identity_binding(value: Any, *, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise LongFormError("LONG_FORM_IDENTITY_BINDING_INVALID")
    asset_id = str(value.get("asset_id") or "")
    role = str(value.get("role") or "")
    digest = str(value.get("content_sha256") or "").lower()
    approval = str(value.get("approval_state") or "").upper()
    if (not _ID_RE.fullmatch(asset_id) or not role
            or not _SHA256_RE.fullmatch(digest) or approval != "APPROVED"):
        raise LongFormError(f"LONG_FORM_{field.upper()}_BINDING_INVALID")
    return {"asset_id": asset_id, "role": role,
            "content_sha256": digest, "approval_state": approval}


def normalize_modes(value: Any, *, ordinal: int) -> list[str]:
    if value is None:
        modes = ["INDEPENDENT"]
    elif isinstance(value, str):
        modes = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        modes = list(value)
    else:
        raise LongFormError("LONG_FORM_CONTINUITY_MODES_INVALID")
    normalized = [str(mode).upper() for mode in modes]
    if (not normalized or len(normalized) != len(set(normalized))
            or any(mode not in CONTINUITY_MODES for mode in normalized)):
        raise LongFormError("LONG_FORM_CONTINUITY_MODES_INVALID")
    if "INDEPENDENT" in normalized and len(normalized) > 1:
        raise LongFormError("LONG_FORM_CONTINUITY_MODES_CONFLICT")
    if ordinal == 0 and "CONTINUE_VISUALLY" in normalized:
        raise LongFormError("LONG_FORM_FIRST_SHOT_CANNOT_CONTINUE")
    # Canonical order makes equivalent requests serialize and hash identically.
    return [mode for mode in CONTINUITY_MODES if mode in normalized]


def create_shot_queue(*, project_id: str, director_sequence: Mapping[str, Any],
                      shot_ids: Sequence[str] | None = None,
                      continuity_modes: Mapping[str, Any] | None = None,
                      project_identity_bindings: Sequence[Mapping[str, Any]] = (),
                      target_resolution: Mapping[str, Any] | None = None,
                      target_fps: int = 24, audio_policy: str = "KEEP_PER_SHOT_CUT",
                      transition_policy: str = "CUT",
                      queue_id: str = "long-form") -> dict[str, Any]:
    """Create a deterministic A9 work queue from an existing A7 sequence.

    The queue stores only product identities and snapshots, never filesystem
    paths. A queue may begin with fewer than three shots while being edited;
    assembly enforces the 3-shot minimum.
    """
    if not _ID_RE.fullmatch(str(project_id or "")):
        raise LongFormError("LONG_FORM_PROJECT_ID_INVALID")
    if str(director_sequence.get("project_id") or "") != project_id:
        raise LongFormError("LONG_FORM_CROSS_PROJECT_SEQUENCE")
    sequence_id = str(director_sequence.get("sequence_id") or "")
    if not _ID_RE.fullmatch(sequence_id):
        raise LongFormError("LONG_FORM_DIRECTOR_SEQUENCE_INVALID")
    source_shots = list(director_sequence.get("shots") or [])
    by_id = {str(shot.get("shot_id") or ""): shot for shot in source_shots}
    ordered_ids = ([str(value) for value in shot_ids] if shot_ids is not None
                   else [str(shot.get("shot_id") or "") for shot in source_shots])
    if not 1 <= len(ordered_ids) <= 32 or len(set(ordered_ids)) != len(ordered_ids):
        raise LongFormError("LONG_FORM_SHOT_COUNT_OR_ORDER_INVALID")
    if any(shot_id not in by_id for shot_id in ordered_ids):
        raise LongFormError("LONG_FORM_SHOT_NOT_IN_DIRECTOR_SEQUENCE")
    try:
        fps = int(target_fps)
    except (TypeError, ValueError, OverflowError) as exc:
        raise LongFormError("LONG_FORM_TARGET_FPS_INVALID") from exc
    if fps not in {24, 48, 60}:
        raise LongFormError("LONG_FORM_TARGET_FPS_INVALID")
    transition = str(transition_policy).upper()
    audio = str(audio_policy).upper()
    if transition not in TRANSITION_POLICIES:
        raise LongFormError("LONG_FORM_TRANSITION_POLICY_UNSUPPORTED")
    if audio not in AUDIO_POLICIES:
        raise LongFormError("LONG_FORM_AUDIO_POLICY_UNSUPPORTED")
    resolution = dict(target_resolution or {"width": 1344, "height": 768})
    try:
        width, height = int(resolution["width"]), int(resolution["height"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise LongFormError("LONG_FORM_TARGET_RESOLUTION_INVALID") from exc
    if (width < 64 or height < 64 or width % 2 or height % 2
            or width > 4096 or height > 4096):
        raise LongFormError("LONG_FORM_TARGET_RESOLUTION_INVALID")
    identity = [_identity_binding(item, field="identity")
                for item in project_identity_bindings]
    if len({item["asset_id"] for item in identity}) != len(identity):
        raise LongFormError("LONG_FORM_IDENTITY_BINDINGS_DUPLICATE")

    modes_by_shot = continuity_modes or {}
    items: list[dict[str, Any]] = []
    for ordinal, shot_id in enumerate(ordered_ids):
        source = by_id[shot_id]
        modes = normalize_modes(modes_by_shot.get(shot_id), ordinal=ordinal)
        if "CONTINUE_VISUALLY" in modes and "LOCK_PROJECT_IDENTITY" in modes:
            raise LongFormError("LONG_FORM_CONTINUITY_COMBINATION_UNSUPPORTED")
        if "LOCK_PROJECT_IDENTITY" in modes and not identity:
            raise LongFormError("LONG_FORM_PROJECT_IDENTITY_REQUIRED")
        previous = ordered_ids[ordinal - 1] if ordinal else None
        items.append({
            "shot_id": shot_id,
            "ordinal": ordinal,
            "title": str(source.get("title") or f"镜头 {ordinal + 1}"),
            "director_shot_sha256": stable_sha256({
                key: value for key, value in source.items()
                if key not in {"last_job_id", "compiled_fragment"}
            }),
            "continuity_modes": modes,
            "previous_shot_id": (previous if "CONTINUE_VISUALLY" in modes else None),
            "job_id": str(source.get("last_job_id") or "") or None,
            "state": "PENDING",
            "job_identity": None,
            "result_identity": None,
            "error_code": None,
        })
    return {
        "schema_version": LONG_FORM_SCHEMA_VERSION,
        "project_id": project_id,
        "queue_id": queue_id,
        "director_sequence_id": sequence_id,
        "director_sequence_revision": int(director_sequence.get("revision", 0)),
        "revision": 1,
        "status": "PENDING",
        "target": {"width": width, "height": height, "fps": fps},
        "transition_policy": transition,
        "audio_policy": audio,
        "color_policy": "PRESERVE_SOURCE_COLOR; NO_LOOK_CHANGE",
        "continuity_identity_bindings": identity,
        "shots": items,
        "assembly": None,
    }


def reconcile_shot_queue(queue: Mapping[str, Any],
                         jobs: Mapping[str, Mapping[str, Any]],
                         result_identities: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Reconcile durable shot state from Studio Jobs without submitting work."""
    result = copy.deepcopy(dict(queue))
    shots = result.get("shots")
    if not isinstance(shots, list):
        raise LongFormError("LONG_FORM_QUEUE_INVALID")
    for shot in shots:
        job_id = str(shot.get("job_id") or "")
        if not job_id:
            if shot.get("error_code") == "LONG_FORM_MULTIPLE_JOBS_FOR_SHOT":
                shot.update(state="FAILED", job_identity=None,
                            result_identity=None)
            else:
                shot.update(state="PENDING", job_identity=None,
                            result_identity=None, error_code=None)
            continue
        job = jobs.get(job_id)
        if not isinstance(job, Mapping):
            shot.update(state="FAILED", error_code="LONG_FORM_JOB_NOT_FOUND")
            continue
        if str(job.get("project_id") or "") != str(result.get("project_id") or ""):
            shot.update(state="FAILED", error_code="LONG_FORM_JOB_CROSS_PROJECT")
            continue
        state = str(job.get("state") or "").upper()
        if state in {"PREPARING", "PREFLIGHT", "SUBMITTING",
                     "SUBMISSION_UNKNOWN", "QUEUED"}:
            shot["state"] = "PREFLIGHT"
        elif state in {
                "RUNNING", "GPU_RUNNING", "OBSERVING", "LOADING_MODEL",
                "LOADING_MODELS", "SAMPLING", "DECODING", "ENCODING",
                "FINALIZING", "EXPORTING", "RECONCILING"}:
            shot["state"] = "RUNNING"
        elif state == "COMPLETED":
            identity = result_identities.get(job_id)
            if not isinstance(identity, Mapping) or identity.get("available") is not True:
                shot.update(state="FAILED", error_code="LONG_FORM_RESULT_NOT_AVAILABLE")
                continue
            required = ("job_id", "prompt_id", "workflow_sha256", "runtime_id",
                        "media_sha256")
            if any(not str(identity.get(key) or "").strip() for key in required):
                shot.update(state="FAILED", error_code="LONG_FORM_RESULT_IDENTITY_INCOMPLETE")
                continue
            prior_job = shot.get("job_identity") or {}
            prior_result = shot.get("result_identity") or {}
            if ((prior_job and any(str(prior_job.get(key) or "") != str(identity.get(key) or "")
                                   for key in ("job_id", "prompt_id", "workflow_sha256",
                                               "runtime_id")))
                    or (prior_result and str(prior_result.get("media_sha256") or "").lower()
                        != str(identity.get("media_sha256") or "").lower())):
                shot.update(state="FAILED", error_code="LONG_FORM_RESULT_IDENTITY_CHANGED")
                continue
            shot["state"] = "RESULT_READY"
            shot["job_identity"] = {
                "job_id": str(identity["job_id"]),
                "prompt_id": str(identity["prompt_id"]),
                "workflow_sha256": str(identity["workflow_sha256"]).lower(),
                "runtime_id": str(identity["runtime_id"]),
            }
            shot["result_identity"] = {
                "result_id": str(identity.get("result_id") or f"result:{job_id}"),
                "media_sha256": str(identity["media_sha256"]).lower(),
                "duration_seconds": identity.get("duration_seconds"),
                "width": identity.get("width"), "height": identity.get("height"),
                "fps": identity.get("fps"),
                "audio_stream": bool(identity.get("audio_stream")),
            }
            shot["error_code"] = None
        elif state in {"CANCELLED", "ABORTED"}:
            shot.update(state="CANCELLED", error_code=None)
        elif state in {"FAILED", "GPU_FAILED", "ERROR"}:
            shot.update(state="FAILED", error_code="LONG_FORM_SHOT_JOB_FAILED")
        else:
            shot.update(state="FAILED", error_code="LONG_FORM_JOB_STATE_UNKNOWN")
    states = [str(shot.get("state") or "") for shot in shots]
    assembly = result.get("assembly") or {}
    if assembly.get("status") == "READY":
        status = "READY"
    elif assembly.get("status") == "FAILED":
        status = "ASSEMBLY_FAILED"
    elif all(state in {"RESULT_READY", "POSTPROCESSING", "READY"} for state in states):
        status = "ASSEMBLY_PENDING"
    elif any(state in {"PREFLIGHT", "RUNNING"} for state in states):
        status = "RUNNING"
    elif any(state == "FAILED" for state in states):
        status = "PARTIAL_FAILED"
    elif any(state == "CANCELLED" for state in states):
        status = "PARTIAL_CANCELLED"
    else:
        status = "PENDING"
    result["status"] = status
    return result


def resume_plan(queue: Mapping[str, Any]) -> dict[str, Any]:
    """Return the first incomplete item; completed Jobs are never replayed."""
    shots = list(queue.get("shots") or [])
    for shot in shots:
        state = str(shot.get("state") or "PENDING").upper()
        if state in {"RESULT_READY", "POSTPROCESSING", "READY"}:
            continue
        if state in {"PREFLIGHT", "RUNNING"}:
            return {"action": "WAIT_EXISTING_JOB", "shot_id": shot["shot_id"],
                    "job_id": shot.get("job_id"), "submission_performed": False}
        if state == "FAILED":
            return {"action": "RETRY_FAILED_SHOT_EXPLICITLY", "shot_id": shot["shot_id"],
                    "job_id": shot.get("job_id"), "submission_performed": False}
        if state == "CANCELLED":
            return {"action": "RESTART_CANCELLED_SHOT_EXPLICITLY", "shot_id": shot["shot_id"],
                    "job_id": shot.get("job_id"), "submission_performed": False}
        return {"action": "GENERATE_NEXT_SHOT", "shot_id": shot["shot_id"],
                "job_id": None, "submission_performed": False}
    return {"action": "ASSEMBLE", "shot_id": None, "job_id": None,
            "submission_performed": False}


def compile_continuity_binding(queue: Mapping[str, Any], ordinal: int,
                               predecessor_result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve explicit per-shot continuity inputs from immutable result IDs."""
    shots = list(queue.get("shots") or [])
    if not 0 <= ordinal < len(shots):
        raise LongFormError("LONG_FORM_SHOT_ORDINAL_INVALID")
    shot = shots[ordinal]
    modes = list(shot.get("continuity_modes") or [])
    refs: list[dict[str, Any]] = []
    if "LOCK_PROJECT_IDENTITY" in modes:
        refs.extend(copy.deepcopy(list(queue.get("continuity_identity_bindings") or [])))
    if "CONTINUE_VISUALLY" in modes:
        if ordinal == 0 or not isinstance(predecessor_result, Mapping):
            raise LongFormError("LONG_FORM_PREVIOUS_RESULT_REQUIRED")
        expected_previous = str(shot.get("previous_shot_id") or "")
        previous_shot = shots[ordinal - 1]
        if (expected_previous != str(previous_shot.get("shot_id") or "")
                or str(previous_shot.get("state") or "") not in {"RESULT_READY", "READY"}):
            raise LongFormError("LONG_FORM_PREVIOUS_SHOT_NOT_READY")
        required = ("job_id", "result_id", "media_sha256", "last_frame_asset_id",
                    "last_frame_sha256", "last_frame_idx")
        if any(not str(predecessor_result.get(key) or "").strip() for key in required):
            raise LongFormError("LONG_FORM_PREVIOUS_FRAME_IDENTITY_INCOMPLETE")
        frame_idx = predecessor_result.get("last_frame_idx")
        if (not isinstance(frame_idx, int) or isinstance(frame_idx, bool)
                or frame_idx < 0):
            raise LongFormError("LONG_FORM_PREVIOUS_FRAME_IDENTITY_INCOMPLETE")
        if (not _ID_RE.fullmatch(str(predecessor_result["job_id"]))
                or not _ID_RE.fullmatch(str(predecessor_result["last_frame_asset_id"]))
                or not _SHA256_RE.fullmatch(str(predecessor_result["media_sha256"]).lower())
                or not _SHA256_RE.fullmatch(
                    str(predecessor_result["last_frame_sha256"]).lower())):
            raise LongFormError("LONG_FORM_PREVIOUS_FRAME_IDENTITY_INCOMPLETE")
        refs.append({
            "role": "first_frame",
            "continuity_mode": "CONTINUE_VISUALLY",
            "source_job_id": str(predecessor_result["job_id"]),
            "source_result_id": str(predecessor_result["result_id"]),
            "source_media_sha256": str(predecessor_result["media_sha256"]).lower(),
            "frame_selector": "LAST_DECODED_FRAME",
            "frame_idx": frame_idx,
            "asset_id": str(predecessor_result["last_frame_asset_id"]),
            "content_sha256": str(predecessor_result["last_frame_sha256"]).lower(),
            "approval_state": "DERIVED_WITH_CONTINUITY_CONSENT",
        })
    return {
        "shot_id": str(shot.get("shot_id") or ""),
        "ordinal": ordinal,
        "continuity_modes": modes,
        "reference_bindings": refs,
        "compiler_version": "a9-continuity-v1",
    }


def build_assembly_manifest(queue: Mapping[str, Any]) -> dict[str, Any]:
    """Build deterministic cut-only assembly identity for fully ready shots."""
    shots = list(queue.get("shots") or [])
    if len(shots) < 3:
        raise LongFormError("LONG_FORM_ASSEMBLY_REQUIRES_THREE_SHOTS")
    if any(str(shot.get("state") or "") not in {"RESULT_READY", "READY"}
           for shot in shots):
        raise LongFormError("LONG_FORM_ASSEMBLY_SHOT_NOT_READY")
    identities = []
    for shot in shots:
        job = shot.get("job_identity") or {}
        result = shot.get("result_identity") or {}
        if (not _ID_RE.fullmatch(str(shot.get("shot_id") or ""))
                or not _ID_RE.fullmatch(str(job.get("job_id") or ""))
                or not str(job.get("prompt_id") or "").strip()
                or not str(job.get("runtime_id") or "").strip()
                or not str(result.get("result_id") or "").strip()
                or not _SHA256_RE.fullmatch(str(job.get("workflow_sha256") or "").lower())
                or not _SHA256_RE.fullmatch(str(result.get("media_sha256") or "").lower())):
            raise LongFormError("LONG_FORM_ASSEMBLY_IDENTITY_INCOMPLETE")
        identities.append({
            "shot_id": shot["shot_id"], "ordinal": int(shot["ordinal"]),
            "job_id": job["job_id"], "prompt_id": job["prompt_id"],
            "workflow_sha256": str(job["workflow_sha256"]).lower(),
            "runtime_id": job["runtime_id"],
            "result_id": result["result_id"],
            "media_sha256": str(result["media_sha256"]).lower(),
        })
    if len({item["job_id"] for item in identities}) != len(identities):
        raise LongFormError("LONG_FORM_ASSEMBLY_DUPLICATE_JOB")
    payload = {
        "schema_version": LONG_FORM_SCHEMA_VERSION,
        "project_id": queue.get("project_id"),
        "queue_id": queue.get("queue_id"),
        "director_sequence_id": queue.get("director_sequence_id"),
        "target": copy.deepcopy(queue.get("target") or {}),
        "transition_policy": queue.get("transition_policy"),
        "audio_policy": queue.get("audio_policy"),
        "color_policy": queue.get("color_policy"),
        "shots": identities,
    }
    digest = stable_sha256(payload)
    return {**payload, "assembly_id": "assembly-" + digest[:24],
            "manifest_sha256": digest, "status": "PENDING",
            "postprocess_applied": False}
