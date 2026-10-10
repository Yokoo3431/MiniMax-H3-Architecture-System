"""Studio-owned deterministic shot timeline contracts for MiniMax H3.

Camera values here are prompt instructions, not geometric control signals.
Each shot is compiled as a standalone H3 clip; sequence assembly is deferred
to A9 so the existing H3 frame lattice and Job/Result ownership stay intact.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import uuid
from typing import Any, Iterable, Mapping

from runtime.a4_profiles import H3_NATIVE_FPS, resolve_product_parameters


DIRECTOR_SCHEMA_VERSION = 1
CAMERA_INTENTS = {
    "static": "a locked-off static camera",
    "slow_push": "a slow, restrained camera push-in",
    "pull_back": "a slow camera pull-back",
    "orbit": "a slow, restrained orbit around the architecture",
    "pan": "a controlled horizontal pan",
    "tilt": "a controlled vertical tilt",
    "crane_elevate": "a gradual crane rise revealing the architecture",
    "descending_aerial": "a controlled descending aerial view",
    "dolly_lateral": "a slow lateral dolly move",
    "approach": "a measured approach toward the architecture",
    "reveal": "a gradual reveal of the architecture",
    "controlled_drone": "a slow, stable drone-style camera move",
}
CAMERA_INTENT_LABELS = {
    "static": "固定镜头", "slow_push": "缓慢推进", "pull_back": "缓慢拉远",
    "orbit": "环绕", "pan": "水平摇镜", "tilt": "垂直摇镜",
    "crane_elevate": "升降揭示", "descending_aerial": "下降航拍",
    "dolly_lateral": "横向移动", "approach": "接近建筑", "reveal": "逐步揭示",
    "controlled_drone": "平稳无人机镜头",
}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
_TEXT_LIMITS = {
    "title": 120, "composition_intent": 600,
    "preservation_intent": 600, "action_intent": 1200,
    "audio_intent": 600, "prompt_fragment": 1800,
}
_EDITABLE_RETAKE_FIELDS = frozenset({
    "camera_intent", "composition_intent", "preservation_intent",
    "action_intent", "audio_intent", "prompt_fragment", "guide_asset_ids",
})


class DirectorTimelineError(ValueError):
    """A malformed, stale, or ungrounded Director timeline request."""


def _clean_text(value: Any, field: str, *, required: bool = False) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).replace("\r\n", "\n").strip()
    if "\x00" in text or len(text) > _TEXT_LIMITS[field]:
        raise DirectorTimelineError(f"DIRECTOR_{field.upper()}_INVALID")
    if required and not text:
        raise DirectorTimelineError(f"DIRECTOR_{field.upper()}_REQUIRED")
    return text


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def new_shot(*, title: str = "新镜头", ordinal: int = 0) -> dict[str, Any]:
    return {
        "shot_id": f"shot-{uuid.uuid4().hex[:16]}",
        "ordinal": int(ordinal),
        "title": title,
        "duration_seconds": 4.0,
        "camera_intent": "static",
        "composition_intent": "",
        "preservation_intent": "保持建筑主体、体量、轮廓与场地关系稳定，不新增或重构建筑元素。",
        "action_intent": "",
        "reference_asset_ids": [],
        "guide_asset_ids": [],
        "audio_intent": "",
        "generation_settings": {"quality": "NATIVE_HIGH", "fps": H3_NATIVE_FPS,
                                "seed": None},
        "runtime_requirement": "production",
        "prompt_fragment": "",
        "compiled_fragment": "",
        "lineage": None,
        "last_job_id": None,
    }


def normalize_sequence(sequence: Mapping[str, Any], project_id: str) -> dict[str, Any]:
    if not isinstance(sequence, Mapping):
        raise DirectorTimelineError("DIRECTOR_SEQUENCE_INVALID")
    owner = str(sequence.get("project_id") or project_id)
    if owner != project_id:
        raise DirectorTimelineError("DIRECTOR_CROSS_PROJECT_SEQUENCE")
    seq_id = str(sequence.get("sequence_id") or f"sequence-{uuid.uuid4().hex[:16]}")
    if not _ID_RE.fullmatch(seq_id):
        raise DirectorTimelineError("DIRECTOR_SEQUENCE_ID_INVALID")
    shots_in = sequence.get("shots") or []
    if not isinstance(shots_in, list) or len(shots_in) > 32:
        raise DirectorTimelineError("DIRECTOR_SHOT_COUNT_INVALID")
    seen: set[str] = set()
    shots: list[dict[str, Any]] = []
    for ordinal, source in enumerate(shots_in):
        if not isinstance(source, Mapping):
            raise DirectorTimelineError("DIRECTOR_SHOT_INVALID")
        shot_id = str(source.get("shot_id") or f"shot-{uuid.uuid4().hex[:16]}")
        if not _ID_RE.fullmatch(shot_id) or shot_id in seen:
            raise DirectorTimelineError("DIRECTOR_SHOT_ID_INVALID")
        seen.add(shot_id)
        camera = str(source.get("camera_intent") or "static")
        if camera not in CAMERA_INTENTS:
            raise DirectorTimelineError("DIRECTOR_CAMERA_INTENT_INVALID")
        try:
            duration = float(source.get("duration_seconds", 4.0))
        except (TypeError, ValueError) as exc:
            raise DirectorTimelineError("DIRECTOR_DURATION_INVALID") from exc
        if not math.isfinite(duration) or not 4.0 <= duration <= 15.0:
            raise DirectorTimelineError("DIRECTOR_DURATION_INVALID")
        refs = _string_ids(source.get("reference_asset_ids") or [], "DIRECTOR_REFERENCE_IDS_INVALID")
        guides = _string_ids(source.get("guide_asset_ids") or [], "DIRECTOR_GUIDE_IDS_INVALID")
        settings = source.get("generation_settings") or {}
        if not isinstance(settings, Mapping):
            raise DirectorTimelineError("DIRECTOR_GENERATION_SETTINGS_INVALID")
        quality = str(settings.get("quality") or "NATIVE_HIGH")
        if quality not in {"PREVIEW", "NATIVE_HIGH"}:
            raise DirectorTimelineError("DIRECTOR_QUALITY_PROFILE_UNAVAILABLE")
        fps = settings.get("fps", H3_NATIVE_FPS)
        try:
            fps_value = float(fps)
        except (TypeError, ValueError, OverflowError) as exc:
            raise DirectorTimelineError("DIRECTOR_NATIVE_FPS_UNSUPPORTED") from exc
        if fps_value != H3_NATIVE_FPS:
            raise DirectorTimelineError("DIRECTOR_NATIVE_FPS_UNSUPPORTED")
        seed = settings.get("seed")
        if seed is not None:
            seed = _normalize_seed(seed)
        runtime = str(source.get("runtime_requirement") or "production")
        if runtime not in {"production", "experimental", "any"}:
            raise DirectorTimelineError("DIRECTOR_RUNTIME_REQUIREMENT_INVALID")
        shot = {
            "shot_id": shot_id,
            "ordinal": ordinal,
            "title": _clean_text(source.get("title") or f"镜头 {ordinal + 1}", "title", required=True),
            "duration_seconds": duration,
            "camera_intent": camera,
            "camera_intent_type": "PROMPT_CAMERA_INTENT",
            "composition_intent": _clean_text(source.get("composition_intent"), "composition_intent"),
            "preservation_intent": _clean_text(source.get("preservation_intent"), "preservation_intent"),
            "action_intent": _clean_text(source.get("action_intent"), "action_intent"),
            "reference_asset_ids": refs,
            "guide_asset_ids": guides,
            "audio_intent": _clean_text(source.get("audio_intent"), "audio_intent"),
            "generation_settings": {"quality": quality, "fps": H3_NATIVE_FPS,
                                    "seed": seed},
            "runtime_requirement": runtime,
            "prompt_fragment": _clean_text(source.get("prompt_fragment"), "prompt_fragment"),
            "compiled_fragment": str(source.get("compiled_fragment") or ""),
            "lineage": _normalize_lineage(source.get("lineage")),
            "last_job_id": str(source.get("last_job_id") or "") or None,
        }
        shots.append(shot)
    return {
        "schema_version": DIRECTOR_SCHEMA_VERSION,
        "project_id": project_id,
        "sequence_id": seq_id,
        "revision": max(0, int(sequence.get("revision", 0))),
        "title": _clean_text(sequence.get("title") or "建筑分镜", "title", required=True),
        "shots": shots,
    }


def resolve_shot_timing(duration_seconds: Any, quality: Any,
                        workflow_id: str) -> dict[str, Any]:
    """Return authoritative H3 frame-lattice timing for a Director shot.

    The frontend may display this response, but must not independently
    reproduce the 17k+5 frame calculation. The same profile resolver is used
    by ``compile_shot`` immediately before execution.
    """
    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DirectorTimelineError("DIRECTOR_DURATION_INVALID") from exc
    profile_id = str(quality or "NATIVE_HIGH")
    if not workflow_id:
        raise DirectorTimelineError("DIRECTOR_WORKFLOW_REQUIRED")
    try:
        params, profile = resolve_product_parameters(
            workflow_id,
            {"duration": duration, "quality": profile_id,
             "fps": H3_NATIVE_FPS},
            seed=42)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DirectorTimelineError("DIRECTOR_TIMING_PROFILE_UNAVAILABLE") from exc
    return {
        "available": True,
        "workflow_id": workflow_id,
        "quality_profile": profile["quality_profile"],
        "native_generation_fps": H3_NATIVE_FPS,
        "requested_duration_seconds": float(params["requested_duration_seconds"]),
        "resolved_frame_count": int(params["frame_count"]),
        "effective_duration_seconds": float(params["resolved_duration_seconds"]),
    }


def _string_ids(items: Iterable[Any], error_code: str) -> list[str]:
    if not isinstance(items, (list, tuple)):
        raise DirectorTimelineError(error_code)
    values = [str(item) for item in items]
    if any(not _ID_RE.fullmatch(item) for item in values) or len(values) != len(set(values)):
        raise DirectorTimelineError(error_code)
    return values


def _normalize_seed(value: Any) -> int:
    if isinstance(value, bool):
        raise DirectorTimelineError("DIRECTOR_SEED_INVALID")
    if isinstance(value, int):
        seed = value
    elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
        seed = int(value)
    elif isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        seed = int(value.strip())
    else:
        raise DirectorTimelineError("DIRECTOR_SEED_INVALID")
    if seed < 0 or seed > 2**63 - 1:
        raise DirectorTimelineError("DIRECTOR_SEED_INVALID")
    return seed


def _normalize_lineage(lineage: Any) -> dict[str, Any] | None:
    if lineage is None:
        return None
    if not isinstance(lineage, Mapping):
        raise DirectorTimelineError("DIRECTOR_LINEAGE_INVALID")
    source_job_id = str(lineage.get("source_job_id") or "")
    source_result_id = str(lineage.get("source_result_id") or "")
    if not _ID_RE.fullmatch(source_job_id) or not source_result_id.startswith("result:"):
        raise DirectorTimelineError("DIRECTOR_LINEAGE_INVALID")
    changed = sorted({str(v) for v in lineage.get("changed_fields", [])})
    unchanged = sorted({str(v) for v in lineage.get("unchanged_fields", [])})
    if not set(changed) <= _EDITABLE_RETAKE_FIELDS or set(changed) & set(unchanged):
        raise DirectorTimelineError("DIRECTOR_LINEAGE_FIELDS_INVALID")
    return {
        "source_job_id": source_job_id,
        "source_result_id": source_result_id,
        "retake_reason": _clean_text(lineage.get("retake_reason"), "prompt_fragment", required=True)[:500],
        "changed_fields": changed,
        "unchanged_fields": unchanged,
        "source_workflow_sha256": str(lineage.get("source_workflow_sha256") or ""),
    }


def compile_shot(base_prompt: Mapping[str, Any], shot: Mapping[str, Any],
                 generation_parameters: Mapping[str, Any], *,
                 workflow_id: str, project_id: str,
                 references: Mapping[str, Mapping[str, Any]],
                 guide_frames: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Compile one immutable standalone shot prompt and provenance record."""
    prompt_text = str(base_prompt.get("prompt") or "").strip()
    if not prompt_text:
        raise DirectorTimelineError("DIRECTOR_BASE_PROMPT_MISSING")
    if not str(shot.get("action_intent") or "").strip():
        raise DirectorTimelineError("DIRECTOR_ACTION_INTENT_REQUIRED")
    allowed_ref_ids = {
        str(item.get("asset_id") or "")
        for item in (base_prompt.get("reference_bindings") or [])
        if isinstance(item, Mapping)
    }
    selected_ref_ids = list(shot.get("reference_asset_ids") or [])
    ordered_bound_ids = [
        str(item.get("asset_id") or "")
        for item in (base_prompt.get("reference_bindings") or [])
        if isinstance(item, Mapping)
    ]
    if selected_ref_ids != ordered_bound_ids:
        raise DirectorTimelineError("DIRECTOR_REFERENCE_SELECTION_MISMATCH")
    ref_bindings = []
    for asset_id in selected_ref_ids:
        ref = references.get(str(asset_id))
        if not ref:
            raise DirectorTimelineError("DIRECTOR_REFERENCE_MISSING")
        if str(ref.get("project_id") or project_id) != project_id:
            raise DirectorTimelineError("DIRECTOR_REFERENCE_CROSS_PROJECT")
        if str(ref.get("state") or "").upper() != "APPROVED":
            raise DirectorTimelineError("DIRECTOR_REFERENCE_NOT_APPROVED")
        if asset_id not in allowed_ref_ids:
            raise DirectorTimelineError("DIRECTOR_REFERENCE_NOT_BOUND_TO_PROMPT")
        ref_bindings.append({
            "asset_id": asset_id, "role": ref.get("role"),
            "content_sha256": ref.get("sha256"),
            "approval_state": "APPROVED",
        })
    project_guide_ids = [str(item.get("guide_id") or "") for item in guide_frames]
    selected_guides = [str(item) for item in shot.get("guide_asset_ids") or []]
    if selected_guides != project_guide_ids:
        raise DirectorTimelineError("DIRECTOR_GUIDE_SELECTION_UNSUPPORTED")
    shot_duration = float(shot["duration_seconds"])
    shot_quality = str((shot.get("generation_settings") or {}).get(
        "quality") or "NATIVE_HIGH")
    try:
        requested_duration = float(generation_parameters.get("duration", shot_duration))
    except (TypeError, ValueError, OverflowError) as exc:
        raise DirectorTimelineError("DIRECTOR_SETTINGS_MISMATCH") from exc
    requested_quality = str(generation_parameters.get("quality") or shot_quality)
    if (not math.isclose(requested_duration, shot_duration, rel_tol=0.0, abs_tol=1e-9)
            or requested_quality != shot_quality):
        raise DirectorTimelineError("DIRECTOR_SETTINGS_MISMATCH")
    raw_parameters = dict(generation_parameters)
    frozen_seed = (shot.get("generation_settings") or {}).get("seed")
    requested_seed = raw_parameters.get("seed")
    if frozen_seed is not None and requested_seed is not None:
        if _normalize_seed(requested_seed) != _normalize_seed(frozen_seed):
            raise DirectorTimelineError("DIRECTOR_SETTINGS_MISMATCH")
    if frozen_seed is not None:
        raw_parameters["seed"] = _normalize_seed(frozen_seed)
    elif requested_seed is not None:
        raw_parameters["seed"] = _normalize_seed(requested_seed)
    else:
        raw_parameters["seed"] = 42
    raw_parameters.update({"duration": shot_duration, "quality": shot_quality,
                           "fps": H3_NATIVE_FPS})
    params, profile = resolve_product_parameters(
        workflow_id, raw_parameters, seed=int(raw_parameters["seed"]))
    duration = float(params["resolved_duration_seconds"])
    camera = CAMERA_INTENTS[str(shot["camera_intent"])]
    clauses = [str(shot.get("action_intent") or "").strip()]
    if shot.get("composition_intent"):
        clauses.append("Composition: " + str(shot["composition_intent"]).strip())
    clauses.append("Camera: " + camera + " (prompt intent; not geometric camera control)")
    if shot.get("preservation_intent"):
        clauses.append("Preserve: " + str(shot["preservation_intent"]).strip())
    if shot.get("audio_intent"):
        clauses.append("Audio: " + str(shot["audio_intent"]).strip())
    if shot.get("prompt_fragment"):
        clauses.append(str(shot["prompt_fragment"]).strip())
    local_timeline = (
        f"[{0.0:.2f}s–{duration:.2f}s] " + " ".join(clauses))
    section = "Director shot: " + str(shot.get("title") or "") + "\nTimeline:\n" + local_timeline
    compiled_prompt = prompt_text.rstrip() + "\n\n" + section
    updated_prompt = dict(base_prompt)
    updated_prompt["prompt"] = compiled_prompt
    updated_prompt["prompt_hash"] = hashlib.sha256(compiled_prompt.encode("utf-8")).hexdigest()
    updated_prompt["director_compilation"] = {
        "schema_version": DIRECTOR_SCHEMA_VERSION,
        "camera_intent_type": "PROMPT_CAMERA_INTENT",
        "shot_id": shot["shot_id"],
        "compiled_fragment": section,
    }
    sequence_sha = stable_sha256({
        key: value for key, value in shot.items()
        if key not in {"compiled_fragment", "last_job_id"}
    })
    provenance = {
        "schema_version": DIRECTOR_SCHEMA_VERSION,
        "project_id": project_id,
        "shot_id": shot["shot_id"],
        "ordinal": int(shot["ordinal"]),
        "shot_sha256": sequence_sha,
        "camera_intent": shot["camera_intent"],
        "camera_intent_type": "PROMPT_CAMERA_INTENT",
        "requested_duration_seconds": float(params["requested_duration_seconds"]),
        "resolved_frame_count": int(params["frame_count"]),
        "effective_duration_seconds": duration,
        "native_generation_fps": H3_NATIVE_FPS,
        "reference_bindings": ref_bindings,
        "guide_asset_ids": selected_guides,
        "quality_profile": profile["quality_profile"],
        "runtime_requirement": shot["runtime_requirement"],
        "compiled_fragment_sha256": hashlib.sha256(section.encode("utf-8")).hexdigest(),
        "lineage": shot.get("lineage"),
    }
    return {
        "prompt": updated_prompt,
        "generation_parameters": params,
        "profile": profile,
        "compiled_fragment": section,
        "provenance": provenance,
    }
