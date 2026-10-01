"""A5 timeline-guide resolution, provenance validation and native graph compiler.

The canonical Golden graph remains an immutable base.  This module compiles
approved, single-image ``timeline_guide`` anchors into an execution-only clone
using ComfyUI's native ``MiniMaxH3AddGuide`` node.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping

NATIVE_H3_FPS = 24
GUIDE_ROLE = "timeline_guide"
ROUNDING_POLICY = "microframe_normalized_decimal_half_up"
GUIDE_PROMPT_COMPILER_VERSION = "a5.2-storyboard-timing-v1"
GUIDE_PROMPT_MARKER = "Storyboard guide timing (A5.2):"
GUIDE_PROMPT_END_MARKER = "End storyboard guide timing (A5.2)."
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ADD_GUIDE_INPUTS = {"positive", "latent", "frame_idx", "vae", "image"}


class GuideFrameError(ValueError):
    """A guide timeline or native graph failed a fail-closed validation."""


def _decimal_time(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise GuideFrameError("GUIDE_TIME_INVALID: time must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise GuideFrameError("GUIDE_TIME_INVALID: time must be a finite number") from exc
    if not result.is_finite() or result < 0 or result > Decimal("3600"):
        raise GuideFrameError("GUIDE_TIME_INVALID: time must be finite and between 0 and 3600 seconds")
    return result


def resolve_guide_time(time_seconds: Any, *, fps: int,
                       target_frame_count: int) -> int:
    """Resolve seconds to a frame using explicit decimal half-up rounding.

    Frame zero and the final valid frame are reserved for workflow boundary
    references.  Timeline guides must be strictly interior anchors.
    """
    if isinstance(fps, bool) or not isinstance(fps, int) or fps <= 0:
        raise GuideFrameError("GUIDE_FPS_INVALID: native FPS must be a positive integer")
    if (isinstance(target_frame_count, bool)
            or not isinstance(target_frame_count, int) or target_frame_count < 2):
        raise GuideFrameError("GUIDE_TARGET_FRAME_COUNT_INVALID")
    seconds = _decimal_time(time_seconds)
    # JSON/browser float serialization can represent an intended half-frame
    # boundary as 0.4999999999999999. Normalize the scaled value to 1e-6 of a
    # frame before applying the declared half-up tie break.
    scaled = (seconds * fps).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    index = int(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if index < 0 or index >= target_frame_count:
        raise GuideFrameError(
            f"GUIDE_OUT_OF_RANGE: frame {index} outside 0..{target_frame_count - 1}")
    if index == 0:
        raise GuideFrameError("GUIDE_FIRST_FRAME_COLLISION: frame 0 belongs to first_frame")
    if index == target_frame_count - 1:
        raise GuideFrameError(
            "GUIDE_LAST_FRAME_COLLISION: final frame is reserved for the timeline boundary")
    return index


def compile_timeline_guide_prompt(prompt: str, guides: list[Mapping[str, Any]], *,
                                  fps: int = NATIVE_H3_FPS) -> dict[str, Any]:
    """Add deterministic shot-timing language for native guide conditioning.

    ``MiniMaxH3AddGuide`` attaches an image condition to a frame; it does not
    describe the intended cut or camera path in the text prompt.  The additive
    prompt contract makes each guide's intended cut time explicit while
    preserving the architect-authored prompt verbatim.
    """
    source = str(prompt or "")
    source_digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if not guides:
        return {
            "prompt": source,
            "compiler_version": None,
            "source_prompt_sha256": source_digest,
            "execution_prompt_sha256": source_digest,
            "guide_frame_indexes": [],
        }
    if isinstance(fps, bool) or not isinstance(fps, int) or fps <= 0:
        raise GuideFrameError("GUIDE_PROMPT_FPS_INVALID")
    if not source.strip():
        raise GuideFrameError("GUIDE_PROMPT_SOURCE_MISSING")

    section_header = next((header for header in (
        "integrated_multimodal_description:", "detailed_description:")
        if header in source), None)
    if section_header is None:
        raise GuideFrameError("GUIDE_PROMPT_DESCRIPTION_SECTION_MISSING")
    section_start = source.index(section_header)
    section_end = source.find("\n\noverall_soundscape:", section_start)
    if section_end < 0:
        raise GuideFrameError("GUIDE_PROMPT_DESCRIPTION_SECTION_UNTERMINATED")

    resolved: list[tuple[int, int, str]] = []
    for position, guide in enumerate(guides, start=1):
        if not isinstance(guide, Mapping):
            raise GuideFrameError(f"GUIDE_PROMPT_ROW_INVALID:{position}")
        ordinal = guide.get("ordinal", position)
        frame_index = guide.get("resolved_frame_idx")
        if isinstance(ordinal, bool) or ordinal != position:
            raise GuideFrameError("GUIDE_PROMPT_ORDER_INVALID")
        if (isinstance(frame_index, bool) or not isinstance(frame_index, int)
                or frame_index <= 0):
            raise GuideFrameError(f"GUIDE_PROMPT_FRAME_INVALID:{position}")
        if resolved and frame_index <= resolved[-1][1]:
            raise GuideFrameError("GUIDE_PROMPT_FRAME_ORDER_INVALID")
        seconds = (Decimal(frame_index) / Decimal(fps)).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP)
        resolved.append((position, frame_index, f"{seconds:.3f}"))

    description = source[section_start:section_end]
    # Recompiling an already compiled prompt is idempotent: replace only a
    # complete compiler-owned suffix. A user-authored phrase that happens to
    # equal the start marker is never truncated.
    marker_at = description.rfind(GUIDE_PROMPT_MARKER)
    end_at = description.rfind(GUIDE_PROMPT_END_MARKER)
    if marker_at >= 0 and end_at >= marker_at and not description[
            end_at + len(GUIDE_PROMPT_END_MARKER):].strip():
        description = description[:marker_at].rstrip()

    lines = [
        GUIDE_PROMPT_MARKER,
        "Treat these timestamps as intended storyboard shot boundaries. "
        "Native image guidance anchors frames but does not guarantee exact "
        "cuts or a continuous camera path.",
        "Aim to hold the current composition until each listed boundary, then "
        "switch to the image composition anchored at that frame. Avoid "
        "revealing a later guide composition early.",
        "Across shots preserve the same building identity, massing, roofline, "
        "facade organization, materials, and site context; do not redesign "
        "the architecture to reach a guide.",
    ]
    lines.extend(
        f"Intended cut to timeline guide {ordinal} at {seconds} seconds "
        f"(frame {frame_index})."
        for ordinal, frame_index, seconds in resolved
    )
    lines.append(GUIDE_PROMPT_END_MARKER)
    compiled_section = description + "\n\n" + "\n".join(lines)
    compiled_prompt = source[:section_start] + compiled_section + source[section_end:]
    if len(compiled_prompt) > 7000:
        raise GuideFrameError("GUIDE_PROMPT_EXCEEDS_LIMIT")
    return {
        "prompt": compiled_prompt,
        "compiler_version": GUIDE_PROMPT_COMPILER_VERSION,
        "source_prompt_sha256": source_digest,
        "execution_prompt_sha256": hashlib.sha256(
            compiled_prompt.encode("utf-8")).hexdigest(),
        "guide_frame_indexes": [frame_index for _, frame_index, _ in resolved],
    }


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def guide_comfy_filename(binding: Mapping[str, Any]) -> str:
    """Return a safe deterministic filename encoding asset and content identity."""
    source = str(binding.get("filename") or "")
    suffix = Path(source).suffix.lower()
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        raise GuideFrameError("GUIDE_IMAGE_UNSUPPORTED: use one single supported image")
    identity = "\0".join((
        str(binding.get("asset_id") or ""),
        str(binding.get("role") or ""),
        str(binding.get("content_sha256") or "").upper(),
    ))
    token = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"avs_guide_{token}{suffix}"


def resolve_guide_bindings(project_id: str, guide_frames: Any,
                           references_by_id: Mapping[str, Mapping[str, Any]], *,
                           target_frame_count: int, fps: int = NATIVE_H3_FPS,
                           workflow_id: str | None = None,
                           reference_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Resolve persisted timeline rows against approved project assets.

    The returned records are execution-ready, but paths remain internal and
    must never be copied into a public Study or execution trace.
    """
    if guide_frames is None:
        guide_frames = []
    if not isinstance(guide_frames, list):
        raise GuideFrameError("GUIDE_LIST_INVALID: guide_frames must be a list")
    root = Path(reference_root).resolve() if reference_root is not None else None
    if not guide_frames:
        return []

    result: list[dict[str, Any]] = []
    previous_time: Decimal | None = None
    previous_index: int | None = None
    seen_assets: set[str] = set()
    for position, raw in enumerate(guide_frames, start=1):
        if not isinstance(raw, Mapping):
            raise GuideFrameError(f"GUIDE_ROW_INVALID:{position}")
        asset_id = str(raw.get("asset_id") or "").strip()
        if not asset_id:
            raise GuideFrameError(f"GUIDE_ASSET_MISSING:{position}")
        if asset_id in seen_assets:
            raise GuideFrameError(f"GUIDE_DUPLICATE_ASSET:{position}")
        seen_assets.add(asset_id)
        role = str(raw.get("role") or "")
        if role != GUIDE_ROLE:
            raise GuideFrameError(f"GUIDE_ROLE_INVALID:{position}")
        ordinal = raw.get("ordinal")
        if isinstance(ordinal, bool) or ordinal != position:
            raise GuideFrameError("GUIDE_ORDER_INVALID: rows must have contiguous 1-based ordinals")
        seconds = _decimal_time(raw.get("requested_time_seconds", raw.get("time_seconds")))
        if previous_time is not None and seconds <= previous_time:
            raise GuideFrameError("GUIDE_ORDER_INVALID: guide times must be strictly increasing")
        frame_idx = resolve_guide_time(
            seconds, fps=fps, target_frame_count=target_frame_count)
        if previous_index is not None and frame_idx <= previous_index:
            raise GuideFrameError("GUIDE_FRAME_COLLISION: guides resolve to the same or earlier frame")
        previous_time, previous_index = seconds, frame_idx

        record = references_by_id.get(asset_id)
        if not isinstance(record, Mapping):
            raise GuideFrameError(f"GUIDE_ASSET_NOT_FOUND:{position}")
        if str(record.get("project_id") or "") != str(project_id):
            raise GuideFrameError(f"GUIDE_CROSS_PROJECT:{position}")
        if record.get("role") != GUIDE_ROLE:
            raise GuideFrameError(f"GUIDE_ASSET_ROLE_MISMATCH:{position}")
        if str(record.get("state") or "").upper() != "APPROVED":
            raise GuideFrameError(f"GUIDE_NOT_APPROVED:{position}")
        stored_path = record.get("stored_path")
        if not stored_path:
            raise GuideFrameError(f"GUIDE_ASSET_FILE_MISSING:{position}")
        path = Path(str(stored_path)).resolve()
        if root is not None and not _inside(path, root):
            raise GuideFrameError(f"GUIDE_ASSET_PATH_OUTSIDE_STUDY:{position}")
        if not path.is_file():
            raise GuideFrameError(f"GUIDE_ASSET_FILE_MISSING:{position}")
        content_sha = str(record.get("sha256") or "").strip().upper()
        if len(content_sha) != 64:
            raise GuideFrameError(f"GUIDE_ASSET_HASH_MISSING:{position}")
        actual_sha = _sha256(path)
        if actual_sha != content_sha:
            raise GuideFrameError(f"GUIDE_ASSET_STALE_CONTENT:{position}")
        expected_sha = str(raw.get("content_sha256") or "").strip().upper()
        if expected_sha and expected_sha != actual_sha:
            raise GuideFrameError(f"GUIDE_ASSET_SHA_MISMATCH:{position}")
        approval = str(record.get("state") or "").upper()
        recorded_approval = str(raw.get("approval_state") or approval).upper()
        if recorded_approval != "APPROVED":
            raise GuideFrameError(f"GUIDE_APPROVAL_EVIDENCE_INVALID:{position}")
        source_identity = (f"reference:{asset_id}:v{int(record.get('version') or 1)}:"
                           f"sha256:{actual_sha}")
        expected_source = str(raw.get("source_identity") or "")
        if expected_source and expected_source != source_identity:
            raise GuideFrameError(f"GUIDE_SOURCE_IDENTITY_STALE:{position}")
        suffix = Path(str(record.get("filename") or path.name)).suffix.lower()
        if suffix not in SUPPORTED_IMAGE_SUFFIXES:
            raise GuideFrameError(f"GUIDE_IMAGE_UNSUPPORTED:{position}:single image required")
        result.append({
            "guide_id": str(raw.get("guide_id") or f"guide-{position}"),
            "asset_id": asset_id,
            "project_id": str(project_id),
            "role": role,
            "requested_time_seconds": float(seconds),
            "resolved_frame_idx": frame_idx,
            "ordinal": position,
            "approval_evidence": {
                "state": approval,
                "approved_at": str(record.get("approved_at") or ""),
            },
            "approval_state": approval,
            "content_sha256": actual_sha,
            "source_identity": source_identity,
            "filename": str(record.get("filename") or path.name),
            "path_or_ref": str(path),
            "comfy_filename": guide_comfy_filename({
                "asset_id": asset_id, "role": role,
                "content_sha256": actual_sha,
                "filename": str(record.get("filename") or path.name),
            }),
        })
    return result


def _required_inputs(node_info: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    inputs = node_info.get("input") or {}
    required = set((inputs.get("required") or {}).keys())
    optional = set((inputs.get("optional") or {}).keys())
    return required, optional


def compile_native_guides(base_payload: Mapping[str, Any], guides: list[Mapping[str, Any]], *,
                          object_info: Mapping[str, Any],
                          target_frame_count: int) -> dict[str, Any]:
    """Compile deterministic AddGuide nodes into a clone of a bound API graph."""
    payload = copy.deepcopy(dict(base_payload))
    if not guides:
        return payload
    node_info = object_info.get("MiniMaxH3AddGuide")
    if not isinstance(node_info, Mapping):
        raise GuideFrameError(
            "GUIDE_RUNTIME_UNAVAILABLE: MiniMaxH3AddGuide is not registered")
    required, optional = _required_inputs(node_info)
    if not {"positive", "latent", "frame_idx"}.issubset(required):
        raise GuideFrameError("GUIDE_NODE_SCHEMA_INCOMPATIBLE: missing required inputs")
    if "image" not in optional or "vae" not in optional:
        raise GuideFrameError("GUIDE_NODE_SCHEMA_INCOMPATIBLE: image/VAE path unavailable")

    h3_nodes = [(str(node_id), node) for node_id, node in payload.items()
                if node.get("class_type") == "MiniMaxH3ImageToVideo"]
    guider_nodes = [(str(node_id), node) for node_id, node in payload.items()
                    if node.get("class_type") == "BasicGuider"]
    if len(h3_nodes) != 1 or len(guider_nodes) != 1:
        raise GuideFrameError("GUIDE_BASE_GRAPH_INCOMPATIBLE: expected one H3 and BasicGuider")
    h3_id, h3 = h3_nodes[0]
    guider_id, guider = guider_nodes[0]
    h3_inputs = h3.get("inputs") or {}
    if int(h3_inputs.get("length", -1)) != int(target_frame_count):
        raise GuideFrameError("GUIDE_TARGET_FRAME_COUNT_MISMATCH: graph length differs")
    vae_link = h3_inputs.get("vae")
    latent_link = [h3_id, 1]
    conditioning_link = [h3_id, 0]
    if not (isinstance(vae_link, list) and len(vae_link) == 2):
        raise GuideFrameError("GUIDE_VIDEO_VAE_REQUIRED: base graph has no video VAE")

    numeric_ids = [int(node_id) for node_id in payload if str(node_id).isdigit()]
    next_id = max(numeric_ids, default=0) + 1
    previous_frame_idx = 0
    for position, guide in enumerate(guides, start=1):
        if str(guide.get("role") or "") != GUIDE_ROLE:
            raise GuideFrameError(f"GUIDE_ROLE_INVALID:{position}")
        frame_idx = int(guide.get("resolved_frame_idx", -1))
        if not 0 < frame_idx < target_frame_count - 1:
            raise GuideFrameError(f"GUIDE_FRAME_INVALID:{position}")
        if frame_idx <= previous_frame_idx:
            raise GuideFrameError("GUIDE_FRAME_COLLISION: guides must be strictly chronological")
        previous_frame_idx = frame_idx
        if int(guide.get("ordinal", position)) != position:
            raise GuideFrameError("GUIDE_ORDER_INVALID: ordinals must be contiguous and 1-based")
        if not str(guide.get("asset_id") or ""):
            raise GuideFrameError(f"GUIDE_ASSET_MISSING:{position}")
        digest = str(guide.get("content_sha256") or "").upper()
        if len(digest) != 64 or any(char not in "0123456789ABCDEF" for char in digest):
            raise GuideFrameError(f"GUIDE_ASSET_HASH_MISSING:{position}")
        if str(guide.get("approval_state") or "").upper() != "APPROVED":
            raise GuideFrameError(f"GUIDE_NOT_APPROVED:{position}")
        approval_evidence = guide.get("approval_evidence")
        if not isinstance(approval_evidence, Mapping) or str(
                approval_evidence.get("state") or "").upper() != "APPROVED":
            raise GuideFrameError(f"GUIDE_APPROVAL_EVIDENCE_INVALID:{position}")
        filename = str(guide.get("comfy_filename") or "")
        if not filename or Path(filename).name != filename:
            raise GuideFrameError(f"GUIDE_COMFY_FILENAME_INVALID:{position}")
        expected_filename = guide_comfy_filename({
            "asset_id": guide["asset_id"], "role": GUIDE_ROLE,
            "content_sha256": digest, "filename": guide.get("filename", filename),
        })
        if filename != expected_filename:
            raise GuideFrameError(f"GUIDE_COMFY_FILENAME_IDENTITY_MISMATCH:{position}")
        source_identity = str(guide.get("source_identity") or "")
        if (not source_identity.startswith(f"reference:{guide['asset_id']}:v")
                or f"sha256:{digest}" not in source_identity):
            raise GuideFrameError(f"GUIDE_SOURCE_IDENTITY_INVALID:{position}")
        image_id, add_id = str(next_id), str(next_id + 1)
        next_id += 2
        payload[image_id] = {
            "class_type": "LoadImage", "inputs": {"image": filename}}
        payload[add_id] = {
            "class_type": "MiniMaxH3AddGuide",
            "inputs": {
                "positive": conditioning_link,
                "latent": latent_link,
                "vae": copy.deepcopy(vae_link),
                "image": [image_id, 0],
                "frame_idx": frame_idx,
            },
        }
        conditioning_link = [add_id, 0]
    guider.setdefault("inputs", {})["conditioning"] = conditioning_link
    if not isinstance(guider.get("inputs", {}).get("conditioning"), list):
        raise GuideFrameError("GUIDE_COMPILER_BINDING_FAILED")
    return payload


def canonical_execution_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "ADD_GUIDE_INPUTS", "GUIDE_PROMPT_COMPILER_VERSION", "GUIDE_PROMPT_END_MARKER",
    "GUIDE_PROMPT_MARKER",
    "GUIDE_ROLE", "GuideFrameError", "NATIVE_H3_FPS", "ROUNDING_POLICY",
    "canonical_execution_sha256", "compile_native_guides",
    "compile_timeline_guide_prompt", "guide_comfy_filename",
    "resolve_guide_bindings", "resolve_guide_time",
]
