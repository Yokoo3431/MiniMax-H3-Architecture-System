"""A4.1 reference-role contract shared by the Studio state and Job gates."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Mapping


REFERENCE_ROLES = (
    "first_frame",
    "last_frame",
    "identity_reference",
    "style_reference",
    "material_reference",
    "site_reference",
    "motion_reference_video",
    "camera_reference_video",
    "audio_reference",
    "timeline_guide",
)
ACTIVE_REFERENCE_ROLES = ("first_frame", "last_frame")
DAY_NIGHT_WORKFLOW = "02_Day_Night_Transition"


def required_reference_roles(workflow_id: str | None) -> tuple[str, ...]:
    return (("first_frame", "last_frame") if workflow_id == DAY_NIGHT_WORKFLOW
            else ("first_frame",))


def resolve_selected_references(project_id: str, project: Mapping[str, Any],
                               references: Mapping[str, Mapping[str, Any]],
                               workflow_id: str | None, *,
                               require_approved: bool = True,
                               reference_root: str | Path | None = None
                               ) -> list[dict[str, Any]]:
    """Return role-ordered selected assets, rejecting ambiguous or stale identity.

    Legacy projects with only ``current_reference_asset_id`` remain valid for
    single-reference workflows. Day/Night never infers either endpoint from
    upload history and requires two separately selected asset IDs.
    """
    required = required_reference_roles(workflow_id)
    root = Path(reference_root).resolve() if reference_root is not None else None
    selected = project.get("selected_reference_asset_ids")
    selected = selected if isinstance(selected, Mapping) else {}
    selected_ids = [selected.get(role) for role in required]
    if required and required[0] == "first_frame" and not selected_ids[0]:
        selected_ids[0] = project.get("current_reference_asset_id")
    if (len(selected_ids) > 1 and all(isinstance(value, str) and value.strip()
                                      for value in selected_ids)
            and len({value.strip() for value in selected_ids}) != len(selected_ids)):
        raise ValueError(
            "REFERENCE_DUPLICATE_ASSET_ID: first and last frames must be distinct")
    ids: list[str] = []
    result: list[dict[str, Any]] = []
    for role in required:
        asset_id = selected.get(role)
        if not asset_id and role == "first_frame":
            asset_id = project.get("current_reference_asset_id")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ValueError(f"REFERENCE_ROLE_REQUIRED:{role}")
        asset_id = asset_id.strip()
        record = references.get(asset_id)
        if not isinstance(record, Mapping):
            raise ValueError(f"REFERENCE_NOT_FOUND:{role}")
        if str(record.get("project_id") or "") != str(project_id):
            raise ValueError(f"REFERENCE_CROSS_PROJECT:{role}")
        if record.get("role") != role:
            raise ValueError(f"REFERENCE_ROLE_MISMATCH:{role}")
        if require_approved and record.get("state") != "APPROVED":
            raise ValueError(f"REFERENCE_NOT_APPROVED:{role}")
        stored_path = record.get("stored_path")
        expected_hash = str(record.get("sha256") or "").strip().lower()
        if stored_path and root is not None:
            path = Path(str(stored_path)).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"REFERENCE_PATH_OUTSIDE_STORE:{role}")
            if not path.is_file():
                raise ValueError(f"REFERENCE_ASSET_MISSING:{role}")
            if not expected_hash:
                raise ValueError(f"REFERENCE_HASH_MISSING:{role}")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest().lower() != expected_hash:
                raise ValueError(f"REFERENCE_STALE_CONTENT:{role}")
        ids.append(asset_id)
        result.append(dict(record))
    if len(set(ids)) != len(ids):
        raise ValueError("REFERENCE_DUPLICATE_ASSET_ID: first and last frames must be distinct")
    if len(result) > 1:
        hashes = [str(item.get("sha256") or "").strip().lower() for item in result]
        if hashes[0] and hashes[1] and hashes[0] == hashes[1]:
            raise ValueError(
                "REFERENCE_DUPLICATE_CONTENT: first and last frames must be distinct approved images")
    return result


def reference_bindings(references: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project only privacy-safe reference identity fields into provenance."""
    return [{
        "asset_id": str(item.get("id") or item.get("asset_id") or ""),
        "project_id": str(item.get("project_id") or item.get("study_id") or ""),
        "role": str(item.get("role") or ""),
        "sha256": item.get("sha256"),
        "approval_state": str(item.get("state") or item.get("approval_state") or ""),
    } for item in references]


def validate_guide_frames(value: Any) -> list[dict[str, Any]]:
    """Validate the future-only metadata shape; this never binds a Comfy node."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("guide_frames must be an array")
    normalized: list[dict[str, Any]] = []
    for index, frame in enumerate(value):
        if not isinstance(frame, Mapping):
            raise ValueError(f"guide_frames[{index}] must be an object")
        asset_id = str(frame.get("asset_id") or "").strip()
        role = str(frame.get("role") or "")
        approval = str(frame.get("approval_state") or "").upper()
        if not asset_id:
            raise ValueError(f"guide_frames[{index}].asset_id is required")
        if role not in REFERENCE_ROLES:
            raise ValueError(f"guide_frames[{index}].role is not a supported reference role")
        if approval not in {"PENDING", "APPROVED", "REJECTED"}:
            raise ValueError(f"guide_frames[{index}].approval_state is invalid")
        try:
            raw_time = frame.get("time_seconds")
            raw_index = frame.get("frame_index")
            if isinstance(raw_time, bool) or isinstance(raw_index, bool):
                raise ValueError("boolean is not a guide time or frame index")
            at_seconds = float(raw_time)
            if isinstance(raw_index, int):
                frame_index = raw_index
            elif (isinstance(raw_index, float) and math.isfinite(raw_index)
                  and raw_index.is_integer()):
                frame_index = int(raw_index)
            else:
                raise ValueError("frame index must be an integer")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"guide_frames[{index}] requires time_seconds and frame_index") from exc
        if not math.isfinite(at_seconds) or at_seconds < 0 or frame_index < 0:
            raise ValueError(f"guide_frames[{index}] time and frame index must be non-negative")
        normalized.append({"asset_id": asset_id, "role": role,
                           "time_seconds": at_seconds, "frame_index": frame_index,
                           "approval_state": approval})
    return normalized


__all__ = [
    "ACTIVE_REFERENCE_ROLES", "DAY_NIGHT_WORKFLOW", "REFERENCE_ROLES",
    "reference_bindings", "required_reference_roles",
    "resolve_selected_references", "validate_guide_frames",
]
