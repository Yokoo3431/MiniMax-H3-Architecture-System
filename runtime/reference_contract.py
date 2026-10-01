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
REF2VA_CONTENT_ROLES = (
    "identity_reference", "style_reference", "material_reference",
    "site_reference", "motion_reference_video", "camera_reference_video",
    "audio_reference",
)

# Role order is product data, not a ComfyUI node/socket ordering.  The native
# Ref2VA adapter groups these deterministically by media family and then uses
# this order within each family.  Timeline guides remain in the separate A5
# AddGuide contract and are never silently converted into Ref2VA references.
REF2VA_ROLE_ORDER = (
    "first_frame", "last_frame", "identity_reference", "style_reference",
    "material_reference", "site_reference", "motion_reference_video",
    "camera_reference_video", "audio_reference",
)
REF2VA_ROLE_MEDIA = {
    "first_frame": "image",
    "last_frame": "image",
    "identity_reference": "image",
    "style_reference": "image",
    "material_reference": "image",
    "site_reference": "image",
    "motion_reference_video": "video",
    "camera_reference_video": "video",
    "audio_reference": "audio",
}
REF2VA_MEDIA_INPUTS = {
    "image": ("ref_images", "ref_image_"),
    "video": ("ref_videos", "ref_video_"),
    "audio": ("ref_audios", "ref_audio_"),
}
REF2VA_PROMPT_TAGS = {"image": "Picture", "video": "Video", "audio": "Audio"}
REF2VA_DEFAULT_IMAGE_SIZE = "match"


def _content_sha256(reference: Mapping[str, Any], role: str) -> str:
    digest = str(reference.get("sha256") or reference.get("content_sha256") or "")
    digest = digest.strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"REF2VA_CONTENT_SHA256_INVALID:{role}")
    return digest


def _safe_source_identity(reference: Mapping[str, Any], digest: str) -> str:
    """Keep only path-free content identities in execution provenance."""
    value = str(reference.get("source_identity") or "").strip()
    prefix = "sha256:"
    if value.lower().startswith(prefix):
        candidate = value[len(prefix):].strip().lower()
        if len(candidate) == 64 and all(char in "0123456789abcdef" for char in candidate):
            if candidate == digest:
                return f"{prefix}{digest}"
    return f"{prefix}{digest}"


def _source_identity_matches_content(reference: Mapping[str, Any], digest: str) -> bool:
    """Report a match only when the supplied source identity is that digest."""
    value = str(reference.get("source_identity") or "").strip()
    prefix = "sha256:"
    if not value.lower().startswith(prefix):
        return False
    candidate = value[len(prefix):].strip().lower()
    return (len(candidate) == 64
            and all(char in "0123456789abcdef" for char in candidate)
            and candidate == digest)


def required_reference_roles(workflow_id: str | None) -> tuple[str, ...]:
    return (("first_frame", "last_frame") if workflow_id == DAY_NIGHT_WORKFLOW
            else ("first_frame",))


def selected_ref2va_roles(selected_reference_asset_ids: Mapping[str, Any] | None
                          ) -> tuple[str, ...]:
    """Return selected A6 content roles; endpoint and timeline roles stay separate."""
    selected = (selected_reference_asset_ids
                if isinstance(selected_reference_asset_ids, Mapping) else {})
    return tuple(role for role in REF2VA_CONTENT_ROLES if selected.get(role))


def ref2va_media_type(reference: Mapping[str, Any]) -> str:
    """Resolve a typed Ref2VA family without trusting a user-supplied mismatch."""
    role = str(reference.get("role") or "")
    if role == "timeline_guide":
        raise ValueError("REF2VA_TIMELINE_GUIDE_USES_ADDGUIDE")
    if role in ACTIVE_REFERENCE_ROLES:
        raise ValueError("REF2VA_ENDPOINT_ROLE_REQUIRES_ENDPOINT_CONDITIONING")
    expected = REF2VA_ROLE_MEDIA.get(role)
    actual = str(reference.get("media_type") or expected or "").lower()
    if expected is None:
        raise ValueError(f"REF2VA_ROLE_UNSUPPORTED:{role or 'missing'}")
    if actual != expected:
        raise ValueError(f"REF2VA_ROLE_MEDIA_MISMATCH:{role}")
    return expected


def order_ref2va_references(references: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return stable family/role order; input/UI insertion order is irrelevant."""
    family_order = {"image": 0, "video": 1, "audio": 2}
    role_order = {role: index for index, role in enumerate(REF2VA_ROLE_ORDER)}
    normalized = [dict(item) for item in references]
    for item in normalized:
        ref2va_media_type(item)
    return sorted(normalized, key=lambda item: (
        family_order[ref2va_media_type(item)],
        role_order[str(item.get("role") or "")],
        str(item.get("id") or item.get("asset_id") or ""),
    ))


def ref2va_schema_capabilities(object_info: Mapping[str, Any]) -> dict[str, Any]:
    """Read dynamic slot maxima from live Comfy object_info, never guessed locally."""
    node = object_info.get("MiniMaxH3ReferenceToVideo")
    if not isinstance(node, Mapping):
        return {"available": False, "reason": "REF2VA_NODE_UNAVAILABLE",
                "node": "MiniMaxH3ReferenceToVideo", "limits": {}}
    inputs = node.get("input") or {}
    optional = inputs.get("optional") or {}
    required = inputs.get("required") or {}
    limits: dict[str, int | None] = {}
    for family, (field, _prefix) in REF2VA_MEDIA_INPUTS.items():
        spec = optional.get(field)
        maximum = None
        if isinstance(spec, (list, tuple)) and len(spec) > 1 and isinstance(spec[1], Mapping):
            template = spec[1].get("template") or {}
            try:
                maximum = int(template["max"])
            except (KeyError, TypeError, ValueError):
                maximum = None
        limits[family] = maximum
    paired_audio = optional.get("ref_video_audios")
    paired_audio_maximum = None
    if isinstance(paired_audio, (list, tuple)) and len(paired_audio) > 1:
        try:
            paired_audio_maximum = int(
                paired_audio[1]["template"]["max"])
        except (KeyError, TypeError, ValueError):
            paired_audio_maximum = None
    required_names = {str(name) for name in required}
    required_ok = {"clip", "prompt", "width", "height", "length",
                   "ref_image_size"}.issubset(
        required_names)
    slots_ok = all(limits[family] is not None for family in ("image", "video", "audio"))
    return {
        "available": bool(required_ok and slots_ok),
        "reason": "" if required_ok and slots_ok else "REF2VA_SCHEMA_INCOMPLETE",
        "node": "MiniMaxH3ReferenceToVideo",
        "limits": limits,
        "paired_video_audio_limit": paired_audio_maximum,
        # Comfy core versions have moved these sockets between required and
        # optional without changing their names. Report presence separately
        # from optionality so capability checks don't mistake a required VAE
        # input for a missing one.
        "video_vae_input": "vae" in required or "vae" in optional,
        "video_vae_required": "vae" in required,
        "audio_vae_input": "audio_vae" in required or "audio_vae" in optional,
        "audio_vae_required": "audio_vae" in required,
        "outputs": list(node.get("output") or []),
        "prompt_tags": dict(REF2VA_PROMPT_TAGS),
    }


def build_ref2va_reference_plan(
        references: list[Mapping[str, Any]], object_info: Mapping[str, Any], *,
        project_id: str, runtime_id: str, video_vae_available: bool,
        audio_vae_available: bool = False) -> dict[str, Any]:
    """Validate and assign deterministic native slots for a Ref2VA execution."""
    if runtime_id != "experimental-h3-8190":
        raise ValueError("REF2VA_EXPERIMENTAL_RUNTIME_REQUIRED")
    schema = ref2va_schema_capabilities(object_info)
    if not schema.get("available"):
        raise ValueError(str(schema.get("reason") or "REF2VA_SCHEMA_UNAVAILABLE"))
    if not references:
        raise ValueError("REF2VA_REFERENCE_REQUIRED")
    if any(str(item.get("role") or "") in ACTIVE_REFERENCE_ROLES
           for item in references):
        raise ValueError("REF2VA_ENDPOINT_ROLE_REQUIRES_ENDPOINT_CONDITIONING")
    ordered = order_ref2va_references(references)
    counts = {family: 0 for family in REF2VA_MEDIA_INPUTS}
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    per_role: dict[str, int] = {}
    bindings: list[dict[str, Any]] = []
    limits = schema["limits"]
    for item in ordered:
        role = str(item.get("role") or "")
        media_type = ref2va_media_type(item)
        if str(item.get("project_id") or item.get("study_id") or "") != str(project_id):
            raise ValueError(f"REF2VA_CROSS_PROJECT:{role}")
        approval = str(item.get("state") or item.get("approval_state") or "").upper()
        if approval != "APPROVED":
            raise ValueError(f"REF2VA_NOT_APPROVED:{role}")
        asset_id = str(item.get("id") or item.get("asset_id") or "").strip()
        if not asset_id:
            raise ValueError(f"REF2VA_IDENTITY_INCOMPLETE:{role}")
        digest = _content_sha256(item, role)
        if asset_id in seen_ids:
            raise ValueError("REF2VA_DUPLICATE_ASSET")
        if digest in seen_hashes:
            raise ValueError("REF2VA_DUPLICATE_CONTENT")
        seen_ids.add(asset_id)
        seen_hashes.add(digest)
        per_role[role] = per_role.get(role, 0) + 1
        if role in {"camera_reference_video", "motion_reference_video"} and per_role[role] > 1:
            raise ValueError(f"REF2VA_ROLE_CARDINALITY_EXCEEDED:{role}")
        limits_for_family = limits.get(media_type)
        if limits_for_family is None:
            raise ValueError(f"REF2VA_SCHEMA_LIMIT_UNKNOWN:{media_type}")
        counts[media_type] += 1
        if counts[media_type] > int(limits_for_family):
            raise ValueError(f"REF2VA_LIMIT_EXCEEDED:{media_type}:{limits_for_family}")
        if media_type in {"image", "video"} and not video_vae_available:
            raise ValueError("REF2VA_VIDEO_VAE_REQUIRED_FOR_VISUAL_REFERENCES")
        if media_type == "audio" and not audio_vae_available:
            raise ValueError("REF2VA_AUDIO_VAE_REQUIRED_FOR_AUDIO_REFERENCE")
        family_ordinal = counts[media_type]
        field, prefix = REF2VA_MEDIA_INPUTS[media_type]
        source_identity = _safe_source_identity(item, digest)
        source_identity_matches_content = _source_identity_matches_content(
            item, digest)
        bindings.append({
            "asset_id": asset_id,
            "project_id": str(project_id),
            "role": role,
            "media_type": media_type,
            "ordinal": family_ordinal,
            "approval_state": approval,
            "content_sha256": digest,
            "source_identity": source_identity,
            "requested_fidelity": REF2VA_DEFAULT_IMAGE_SIZE,
            "native_slot_index": family_ordinal - 1,
            "native_input": f"{field}.{prefix}{family_ordinal - 1}",
            "prompt_tag": f"<{REF2VA_PROMPT_TAGS[media_type]} {family_ordinal}>",
            "runtime_compatibility": "experimental-h3-8190",
            "validation_evidence": {
                "approved": True,
                "content_sha256_present": True,
                "source_identity_matches_content": source_identity_matches_content,
                "project_match": True,
            },
        })
    return {
        "schema_version": 1,
        "runtime_id": runtime_id,
        "backend": "comfyui",
        "node": schema["node"],
        "limits": dict(limits),
        "counts": counts,
        "reference_image_size": REF2VA_DEFAULT_IMAGE_SIZE,
        "bindings": bindings,
        "required_vaes": {
            "video": any(item["media_type"] in {"image", "video"}
                          for item in bindings),
            "audio": any(item["media_type"] == "audio" for item in bindings),
        },
    }


def resolve_selected_references(project_id: str, project: Mapping[str, Any],
                               references: Mapping[str, Mapping[str, Any]],
                               workflow_id: str | None, *,
                               require_approved: bool = True,
                               reference_root: str | Path | None = None,
                               include_ref2va_roles: bool = False
                               ) -> list[dict[str, Any]]:
    """Return role-ordered selected assets, rejecting ambiguous or stale identity.

    Legacy projects with only ``current_reference_asset_id`` remain valid for
    single-reference workflows. Day/Night never infers either endpoint from
    upload history and requires two separately selected asset IDs.
    """
    if include_ref2va_roles and workflow_id == DAY_NIGHT_WORKFLOW:
        raise ValueError("REF2VA_DAY_NIGHT_ENDPOINT_MODE_UNSUPPORTED")
    # Ref2VA is an alternate conditioning mode, not an additive decoration on
    # I2VA/FL2VA. Its generic Picture slots cannot preserve exact endpoint
    # semantics, so only typed A6 content roles enter this execution contract.
    required = (() if include_ref2va_roles
                else required_reference_roles(workflow_id))
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
    if include_ref2va_roles:
        for role in REF2VA_CONTENT_ROLES:
            asset_id = selected.get(role)
            if not isinstance(asset_id, str) or not asset_id.strip():
                continue
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
            result.append(dict(record))
            ids.append(asset_id)
        result = order_ref2va_references(result)

    if not result and include_ref2va_roles:
        raise ValueError("REF2VA_REFERENCE_REQUIRED")
    if len(set(ids)) != len(ids):
        raise ValueError("REFERENCE_DUPLICATE_ASSET_ID: selected references must be distinct")
    if len(result) > 1:
        hashes = [str(item.get("sha256") or "").strip().lower() for item in result]
        nonempty_hashes = [value for value in hashes if value]
        if len(nonempty_hashes) != len(set(nonempty_hashes)):
            raise ValueError(
                "REFERENCE_DUPLICATE_CONTENT: selected reference roles must use distinct approved assets")
    return result


def reference_bindings(references: list[Mapping[str, Any]], *,
                       ref2va: bool = False) -> list[dict[str, Any]]:
    """Project only privacy-safe reference identity fields into provenance."""
    ordered = order_ref2va_references(references) if ref2va else references
    bindings = [{
        "asset_id": str(item.get("id") or item.get("asset_id") or ""),
        "project_id": str(item.get("project_id") or item.get("study_id") or ""),
        "role": str(item.get("role") or ""),
        "sha256": item.get("sha256"),
        "approval_state": str(item.get("state") or item.get("approval_state") or ""),
    } for item in ordered]
    if not ref2va:
        return bindings
    ordinals = {family: 0 for family in REF2VA_MEDIA_INPUTS}
    for item, binding in zip(ordered, bindings):
        family = ref2va_media_type(item)
        digest = _content_sha256(item, str(item.get("role") or ""))
        ordinals[family] += 1
        field, prefix = REF2VA_MEDIA_INPUTS[family]
        ordinal = ordinals[family]
        binding.update({
            "media_type": family,
            "ordinal": ordinal,
            "content_sha256": digest,
            "source_identity": _safe_source_identity(item, digest),
            "requested_fidelity": REF2VA_DEFAULT_IMAGE_SIZE,
            "native_slot_index": ordinal - 1,
            "native_input": f"{field}.{prefix}{ordinal - 1}",
            "prompt_tag": f"<{REF2VA_PROMPT_TAGS[family]} {ordinal}>",
            "runtime_compatibility": "experimental-h3-8190",
            "validation_evidence": {
                "approved": str(item.get("state") or item.get(
                    "approval_state") or "").upper() == "APPROVED",
                "content_sha256_present": True,
                "source_identity_matches_content": _source_identity_matches_content(
                    item, digest),
            },
        })
    return bindings


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
            raw_time = frame.get("time_seconds", frame.get("requested_time_seconds"))
            raw_index = frame.get("frame_index", frame.get("resolved_frame_idx"))
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
    "REF2VA_CONTENT_ROLES", "REF2VA_MEDIA_INPUTS", "REF2VA_ROLE_MEDIA",
    "REF2VA_ROLE_ORDER",
    "build_ref2va_reference_plan", "order_ref2va_references",
    "ref2va_media_type", "ref2va_schema_capabilities",
    "reference_bindings", "required_reference_roles",
    "resolve_selected_references", "selected_ref2va_roles",
    "validate_guide_frames",
]
