"""Workflow-aware A4 quality and architecture-preservation profiles.

This module is a CPU-only, offline source of truth. It describes only values
already accepted by the frozen Golden binder; it does not build or mutate a
workflow graph.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Mapping


QUALITY_PROFILE_VERSION = "a4.1-quality-v2"
PROMPT_PROFILE_VERSION = "a4-architecture-v1"
ARCHITECTURE_PROFILE_VERSION = "a4-architecture-v1"
PROFILE_CONTRACT_VERSION = "a4.1"
H3_NATIVE_FPS = 24
H3_NATIVE_CANVAS_ALIGNMENT = 32
H3_FRAME_GRID_MODULUS = 17
H3_FRAME_GRID_OFFSET = 5
H3_MAX_NATIVE_FRAME_COUNT = 362
H3_MIN_REQUESTED_DURATION_SECONDS = 4.0
H3_MAX_REQUESTED_DURATION_SECONDS = 15.0
H3_MAX_EFFECTIVE_DURATION_SECONDS = H3_MAX_NATIVE_FRAME_COUNT / H3_NATIVE_FPS


def validate_native_canvas(width: int, height: int) -> tuple[int, int]:
    try:
        if isinstance(width, bool) or isinstance(height, bool):
            raise ValueError
        canvas_width, canvas_height = int(width), int(height)
        if canvas_width != width or canvas_height != height:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("native H3 canvas dimensions must be integers") from exc
    if (canvas_width <= 0 or canvas_height <= 0
            or canvas_width % H3_NATIVE_CANVAS_ALIGNMENT
            or canvas_height % H3_NATIVE_CANVAS_ALIGNMENT):
        raise ValueError(
            f"native H3 canvas must be positive and aligned to "
            f"{H3_NATIVE_CANVAS_ALIGNMENT} pixels")
    return canvas_width, canvas_height


def h3_frame_count_for_duration(duration_seconds: float,
                                fps: float = H3_NATIVE_FPS) -> int:
    """Round a requested duration up to H3's native 17k+5 frame lattice."""
    try:
        duration = float(duration_seconds)
        rate = float(fps)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("duration and fps must be numeric") from exc
    if (not math.isfinite(duration)
            or not H3_MIN_REQUESTED_DURATION_SECONDS <= duration
            <= H3_MAX_REQUESTED_DURATION_SECONDS):
        raise ValueError("duration must be between 4 and 15 seconds")
    if not math.isfinite(rate) or not math.isclose(
            rate, H3_NATIVE_FPS, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("native H3 generation is fixed at 24 FPS")
    requested_frames = math.ceil(duration * H3_NATIVE_FPS - 1e-9)
    snapped_frames = requested_frames + (
        H3_FRAME_GRID_OFFSET - requested_frames
    ) % H3_FRAME_GRID_MODULUS
    # Guard against epsilon rounding at a frame boundary: the resolved clip
    # must never be shorter than the exact requested duration.
    while snapped_frames / H3_NATIVE_FPS < duration:
        snapped_frames += H3_FRAME_GRID_MODULUS
    if snapped_frames > H3_MAX_NATIVE_FRAME_COUNT:
        raise ValueError("duration resolves beyond H3's 362-frame native limit")
    return snapped_frames

QUALITY_PROFILE_SPECS: dict[str, dict[str, Any]] = {
    "DRAFT": {
        "id": "DRAFT",
        "label": "DRAFT",
        "availability": "UNAVAILABLE",
        "availability_reason": "Experimental 672×384 profile; not validated for execution.",
        "resolution": "672x384",
        "steps": 21,
        "sampler_mode": "res_multistep",
        "scheduler": "simple",
        "acceleration": "off",
        "duration_min": 4.0,
        "duration_max": 15.0,
        "execution_mode": "H3_NATIVE_EXPERIMENTAL",
        "standard_diff": {},
    },
    "PREVIEW": {
        "id": "PREVIEW",
        "label": "PREVIEW",
        "availability": "READY",
        "availability_reason": "Bound to the existing Golden 832×480 native H3 path; 24 FPS only.",
        "resolution": "832x480",
        "steps": 21,
        "sampler_mode": "res_multistep",
        "scheduler": "simple",
        "acceleration": "off",
        "duration_min": 4.0,
        "duration_max": 15.0,
        "expected_resource_profile": (
            "Lowest expected relative load: fewer pixels and fewer sigma points; "
            "runtime/VRAM are estimates, not measured guarantees."
        ),
        "execution_mode": "NATIVE_H3",
        "standard_diff": {"resolution": {"from": "1344x768", "to": "832x480"},
                          "steps": {"from": 50, "to": 21},
                          "sampler_mode": {"from": "euler", "to": "res_multistep"}},
    },
    "BALANCED": {
        "id": "BALANCED",
        "label": "BALANCED",
        "availability": "UNAVAILABLE",
        "availability_reason": "1024×576 is held until a GPU cost check is recorded.",
        "resolution": "1024x576",
        "steps": 50,
        "sampler_mode": "euler",
        "scheduler": "simple",
        "acceleration": "off",
        "duration_min": 4.0,
        "duration_max": 15.0,
        "execution_mode": "NATIVE_H3",
        "standard_diff": {},
    },
    "STANDARD": {
        "id": "STANDARD",
        "label": "STANDARD · 720p-class",
        "availability": "CANDIDATE_FOR_A4_2",
        "availability_reason": "1248×704 passed controlled A4.2 execution, but Owner review did not establish a meaningful quality/cost separation from NATIVE_HIGH; it remains a candidate and normal execution stays disabled.",
        "resolution": "1248x704",
        "steps": 50,
        "sampler_mode": "euler",
        "scheduler": "simple",
        "acceleration": "off",
        "duration_min": 4.0,
        "duration_max": 15.0,
        "expected_resource_profile": "Product preset pending validation; no cost or quality result is claimed.",
        "execution_mode": "NATIVE_H3",
        "standard_diff": {},
    },
    "NATIVE_HIGH": {
        "id": "NATIVE_HIGH",
        "label": "NATIVE HIGH",
        "availability": "READY",
        "availability_reason": "Existing local native H3 acceptance records validate 1344×768 at 24 FPS; this is not a 2K or post-process claim.",
        "resolution": "1344x768",
        "steps": 50,
        "sampler_mode": "euler",
        "scheduler": "simple",
        "acceleration": "off",
        "duration_min": 4.0,
        "duration_max": 15.0,
        "expected_resource_profile": "Highest current local H3 base-generation canvas; no 2K delivery claim.",
        "execution_mode": "NATIVE_H3",
        "evidence": ["native Golden acceptance at 1344x768/24fps",
                     "A1 comparison records at 1344x768/24fps"],
        "standard_diff": {
            "resolution": {"from": "1248x704", "to": "1344x768"},
        },
    },
    "ULTRA_1080": {
        "id": "ULTRA_1080",
        "label": "ULTRA 1080",
        "availability": "UNAVAILABLE",
        "availability_reason": "1920×1080 is a delivery target and requires a validated post-process pipeline; none is enabled in A4.1.",
        "resolution": "1920x1080",
        "native_resolution": "1344x768",
        "steps": 50,
        "sampler_mode": "euler",
        "scheduler": "simple",
        "acceleration": "off",
        "duration_min": 4.0,
        "duration_max": 15.0,
        "execution_mode": "POST_UPSCALE",
        "postprocess_required": True,
        "upscale_method": None,
        "standard_diff": {},
    },
    "ULTRA_2K": {
        "id": "ULTRA_2K",
        "label": "ULTRA 2K",
        "availability": "UNAVAILABLE",
        "availability_reason": "No 2K execution path is validated; explicitly choose a future execution mode before enablement.",
        "resolution": "aspect-aware-2k",
        "steps": 50,
        "sampler_mode": "euler",
        "scheduler": "simple",
        "acceleration": "off",
        "duration_min": 4.0,
        "duration_max": 15.0,
        "execution_mode": None,
        "execution_modes": ["H3_REGENERATE_2K", "POST_UPSCALE_2K"],
        "mode_required": True,
        "postprocess_required": True,
        "standard_diff": {},
    },
}

LEGACY_QUALITY_ALIASES = {
    "high": "NATIVE_HIGH",
    "diagnostic": "DRAFT",
    "production": "STANDARD",
}

PRESERVATION_SEMANTICS: dict[str, str] = {
    "MASSING_LOCK": "retain the reference building's footprint, volume, height, and silhouette",
    "ROOF_LOCK": "retain the visible roof form, outline, and major roof elements",
    "FACADE_PROPORTION_LOCK": "retain facade proportions and the relative scale of facade bays",
    "OPENING_PATTERN_LOCK": "retain the position, rhythm, and proportions of visible doors and windows",
    "MATERIAL_BOUNDARY_LOCK": "retain material identity and the boundaries between adjacent materials",
    "SITE_RELATION_LOCK": "retain the building's position and orientation relative to visible site elements",
    "LANDSCAPE_RELATION_LOCK": "retain the visible landscape layout and its relationship to the building",
    "REFERENCE_IDENTITY_LOCK": "keep the same referenced building and do not substitute a different design",
}

ARCHITECTURE_PROFILES: dict[str, dict[str, Any]] = {
    "01_Exterior_Hero": {
        "id": "exterior_hero",
        "label": "Exterior architecture",
        "locks": ["MASSING_LOCK", "ROOF_LOCK", "FACADE_PROPORTION_LOCK",
                  "OPENING_PATTERN_LOCK", "MATERIAL_BOUNDARY_LOCK",
                  "SITE_RELATION_LOCK", "LANDSCAPE_RELATION_LOCK",
                  "REFERENCE_IDENTITY_LOCK"],
        "camera_motion": "slow, small-amplitude hero push or arc",
        "material_stability": "keep facade finish and material transitions consistent during the reveal",
        "prompt_clause": (
            "Preserve the reference building's overall massing and roof silhouette, "
            "facade proportions and opening rhythm, material boundaries, and its "
            "placement within the visible site and landscape while allowing only "
            "the selected slow hero-camera movement."
        ),
        "negative_constraints": [
            "Do not add or remove building wings, facade openings, or roof forms."
        ],
        "risks": ["camera parallax may reveal unseen surfaces", "landscape occlusion may obscure facade continuity"],
    },
    "02_Day_Night_Transition": {
        "id": "day_night_transition",
        "label": "Day/night architecture",
        "locks": ["MASSING_LOCK", "ROOF_LOCK", "FACADE_PROPORTION_LOCK",
                  "OPENING_PATTERN_LOCK", "MATERIAL_BOUNDARY_LOCK",
                  "SITE_RELATION_LOCK", "REFERENCE_IDENTITY_LOCK"],
        "camera_motion": "static viewpoint; lighting and sky evolve over time",
        "material_stability": "allow illumination to change while preserving material identity and facade layout",
        "prompt_clause": (
            "Hold the building massing, roofline, facade proportions, opening pattern, "
            "material divisions, and site position stable across the transition; "
            "let daylight, sky tone, and practical lighting change smoothly without "
            "changing the architecture."
        ),
        "negative_constraints": [
            "Do not morph facade elements or add or remove openings and luminaires."
        ],
        "risks": ["illuminated openings may drift in shape", "temporal lighting changes may be mistaken for material changes"],
    },
    "03_Material_Detail": {
        "id": "material_detail",
        "label": "Material and detail",
        "locks": ["FACADE_PROPORTION_LOCK", "OPENING_PATTERN_LOCK",
                  "MATERIAL_BOUNDARY_LOCK", "REFERENCE_IDENTITY_LOCK"],
        "camera_motion": "near-static detail framing with only subtle approach",
        "material_stability": "retain the named finish, grain direction, joint spacing, and adjacent material edges",
        "prompt_clause": (
            "Keep the detail anchored to the same referenced material assembly, "
            "joint spacing, adjacent opening proportions, and material edges; "
            "allow only a subtle camera approach and natural light change."
        ),
        "negative_constraints": [
            "Do not replace the specified material or invent unsupported fine patterns."
        ],
        "risks": ["fine texture may be hallucinated", "close framing may change perceived material scale"],
    },
    "04_Drone_Aerial": {
        "id": "drone_aerial",
        "label": "Site and aerial massing",
        "locks": ["MASSING_LOCK", "ROOF_LOCK", "FACADE_PROPORTION_LOCK",
                  "SITE_RELATION_LOCK", "LANDSCAPE_RELATION_LOCK",
                  "REFERENCE_IDENTITY_LOCK"],
        "camera_motion": "slow aerial rise/reveal within the selected path",
        "material_stability": "maintain roof and facade material regions as the view opens to the site",
        "prompt_clause": (
            "Maintain the reference footprint, roof geometry, building orientation, "
            "and visible relationships among the building, site, and landscape "
            "while the camera makes a slow aerial reveal; do not add new wings, "
            "roads, or site structures."
        ),
        "negative_constraints": [
            "Do not invent unseen roof extensions, roads, or site structures."
        ],
        "risks": ["elevation change may invent unseen roof geometry", "site-scale parallax may distort roads and landscape boundaries"],
    },
    "05_Slow_Walkthrough": {
        "id": "slow_walkthrough",
        "label": "Spatial walkthrough",
        "locks": ["MASSING_LOCK", "OPENING_PATTERN_LOCK",
                  "MATERIAL_BOUNDARY_LOCK", "SITE_RELATION_LOCK",
                  "REFERENCE_IDENTITY_LOCK"],
        "camera_motion": "slow eye-level forward move along the selected circulation path",
        "material_stability": "retain the visible surface palette and transition boundaries as viewpoint changes",
        "prompt_clause": (
            "Preserve the visible room proportions, opening rhythm, material zones, "
            "and circulation direction while the camera advances slowly at eye level; "
            "let perspective evolve along that path without changing the referenced design."
        ),
        "negative_constraints": [
            "Do not pass the camera through solid walls or invent additional rooms."
        ],
        "risks": ["camera travel may pass through walls or openings", "repeated spaces may be hallucinated as new rooms"],
    },
}


def normalize_quality_id(value: Any) -> str:
    quality = str(value or "NATIVE_HIGH").strip().upper()
    quality = LEGACY_QUALITY_ALIASES.get(quality.lower(), quality)
    if quality not in QUALITY_PROFILE_SPECS:
        raise ValueError(
            "quality must be one of DRAFT, PREVIEW, BALANCED, STANDARD, "
            "NATIVE_HIGH, ULTRA_1080, ULTRA_2K")
    return quality


def require_available_quality_profile(quality_id: str, *,
                                      execution_mode: str | None = None,
                                      allow_a4_2_candidate: bool = False
                                      ) -> dict[str, Any]:
    """Fail closed for profiles that have not reached their execution gate."""
    quality = QUALITY_PROFILE_SPECS[quality_id]
    mode = str(execution_mode or "").strip().upper()
    if quality.get("mode_required"):
        if mode not in quality["execution_modes"]:
            raise ValueError(
                "QUALITY_EXECUTION_MODE_REQUIRED: ULTRA_2K requires an explicit "
                "H3_REGENERATE_2K or POST_UPSCALE_2K mode")
    elif (mode and quality.get("execution_mode")
          and mode != str(quality["execution_mode"]).upper()):
        raise ValueError(
            f"QUALITY_EXECUTION_MODE_MISMATCH:{quality_id}: expected "
            f"{quality['execution_mode']}")
    candidate_allowed = (
        allow_a4_2_candidate
        and quality_id == "STANDARD"
        and quality.get("availability") == "CANDIDATE_FOR_A4_2"
    )
    if quality.get("availability") != "READY" and not candidate_allowed:
        raise ValueError(
            f"QUALITY_PROFILE_UNAVAILABLE:{quality_id}: "
            f"{quality.get('availability_reason', 'execution is not validated')}")
    return quality


def resolve_architecture_profile(workflow_id: str) -> dict[str, Any]:
    profile = ARCHITECTURE_PROFILES.get(str(workflow_id))
    if profile is None:
        raise ValueError(f"no A4 architecture profile for workflow: {workflow_id}")
    return {"workflow_id": str(workflow_id), **deepcopy(profile),
            "prompt_profile_version": PROMPT_PROFILE_VERSION,
            "architecture_profile_version": ARCHITECTURE_PROFILE_VERSION}


def resolve_execution_profile(workflow_id: str, quality_profile: Any,
                              *, duration: float = 4.0,
                              fps: int = 24, seed: int = 42,
                              delivery_fps: int = 24,
                              execution_mode: str | None = None,
                              allow_a4_2_candidate: bool = False) -> dict[str, Any]:
    quality_id = normalize_quality_id(quality_profile)
    quality = require_available_quality_profile(
        quality_id, execution_mode=execution_mode,
        allow_a4_2_candidate=allow_a4_2_candidate)
    architecture = resolve_architecture_profile(workflow_id)
    try:
        duration_value = float(duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("duration must be numeric") from exc
    if (not math.isfinite(duration_value)
            or not quality["duration_min"] <= duration_value <= quality["duration_max"]):
        raise ValueError("duration must be between 4 and 15 seconds")
    try:
        fps_value = float(fps)
        delivery_fps_value = float(delivery_fps)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("A4 Golden profiles support 24 fps only") from exc
    if not math.isfinite(fps_value) or not math.isclose(
            fps_value, H3_NATIVE_FPS, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("A4 Golden profiles support 24 fps only")
    if not math.isfinite(delivery_fps_value) or not math.isclose(
            delivery_fps_value, H3_NATIVE_FPS, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(
            "DELIVERY_FPS_UNAVAILABLE: only native 24 FPS is executable; "
            "30/48/60 FPS require a validated post-process pipeline")
    width, height = (int(part) for part in quality["resolution"].split("x"))
    width, height = validate_native_canvas(width, height)
    frame_count = h3_frame_count_for_duration(duration_value, fps_value)
    resolved_duration = round(frame_count / H3_NATIVE_FPS, 6)
    params = {
        "quality": quality_id,
        "resolution": quality["resolution"],
        "width": width,
        "height": height,
        "duration": duration_value,
        "requested_duration_seconds": duration_value,
        "resolved_duration_seconds": resolved_duration,
        "frame_count": frame_count,
        # Retained for trace compatibility; this is the H3 raw frame count,
        # not a latent-slot count.
        "latent_length": frame_count,
        "fps": H3_NATIVE_FPS,
        "steps": int(quality["steps"]),
        "sampler_mode": quality["sampler_mode"],
        "scheduler": quality["scheduler"],
        "denoise": 1.0,
        "acceleration": quality["acceleration"],
        "generation_speed": "standard",
        "seed": int(seed),
        "delivery_fps": 24,
    }
    native_high = QUALITY_PROFILE_SPECS["NATIVE_HIGH"]
    standard_width, standard_height = (
        int(part) for part in native_high["resolution"].split("x"))
    standard_values = {
        "resolution": native_high["resolution"],
        "width": standard_width,
        "height": standard_height,
        "steps": int(native_high["steps"]),
        "sampler_mode": native_high["sampler_mode"],
    }
    overrides = {
        key: {"from": standard_values[key], "to": params[key]}
        for key in standard_values if standard_values[key] != params[key]
    }
    return {
        "contract_version": PROFILE_CONTRACT_VERSION,
        "quality_profile_version": QUALITY_PROFILE_VERSION,
        "prompt_profile_version": PROMPT_PROFILE_VERSION,
        "architecture_profile_version": ARCHITECTURE_PROFILE_VERSION,
        "workflow_id": str(workflow_id),
        "quality_profile": quality_id,
        "requested_quality_profile": quality_id,
        "resolved_execution_profile": quality_id,
        "execution_mode": quality["execution_mode"],
        "availability": quality["availability"],
        "native_generation": {"width": width, "height": height, "fps": 24,
                              "frame_count": frame_count,
                              "duration_seconds": resolved_duration},
        "delivery": {"width": width, "height": height, "fps": 24,
                      "upscale_method": None, "interpolation_method": None,
                      "postprocess_applied": False},
        "architecture_profile": architecture["id"],
        "architecture_profile_label": architecture["label"],
        "final_execution_parameters": params,
        "profile_parameter_overrides": overrides,
    }


def resolve_product_parameters(workflow_id: str,
                               values: Mapping[str, Any] | None = None,
                               *, seed: int | None = None,
                               allow_a4_2_candidate: bool = False
                               ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve the simple Studio contract, ignoring retired internal knobs.

    Only quality, duration, supported fps, and the explicitly supplied seed
    participate. Resolution, sampler, step, and acceleration fields are
    derived from the selected A4 profile so stale UI state cannot override it.
    """
    from runtime.h3_generation_parameters import normalize_generation_parameters

    raw = dict(values or {})
    chosen_seed = raw.get("seed", seed if seed is not None else 42)
    profile = resolve_execution_profile(
        workflow_id,
        raw.get("quality", "NATIVE_HIGH"),
        duration=raw.get("duration", 4.0),
        fps=raw.get("fps", 24),
        seed=chosen_seed,
        delivery_fps=raw.get("delivery_fps", 24),
        execution_mode=raw.get("quality_execution_mode"),
        allow_a4_2_candidate=allow_a4_2_candidate,
    )
    params = normalize_generation_parameters(
        profile["final_execution_parameters"],
        allow_a4_2_candidate=allow_a4_2_candidate)
    return params, profile


def quality_profile_catalog() -> dict[str, Any]:
    profiles = []
    for value in QUALITY_PROFILE_SPECS.values():
        item = deepcopy(value)
        item["available"] = item.get("availability") == "READY"
        item["native_generation_fps"] = 24
        item["delivery_fps_options"] = [
            {"id": "NATIVE_24", "fps": 24, "availability": "READY"},
            {"id": "DELIVERY_30", "fps": 30,
             "availability": "FUTURE_POSTPROCESS"},
            {"id": "SMOOTH_48", "fps": 48,
             "availability": "FUTURE_POSTPROCESS"},
            {"id": "SMOOTH_60", "fps": 60,
             "availability": "FUTURE_POSTPROCESS"},
        ]
        profiles.append(item)
    return {"version": QUALITY_PROFILE_VERSION, "profiles": profiles}


def architecture_profile_catalog() -> dict[str, Any]:
    return {workflow_id: {
        "id": profile["id"],
        "label": profile["label"],
        "locks": list(profile["locks"]),
        "camera_motion": profile["camera_motion"],
    } for workflow_id, profile in ARCHITECTURE_PROFILES.items()}


def workflow_quality_matrix() -> list[dict[str, Any]]:
    return [{
        "workflow_id": workflow_id,
        "quality_profile": quality_id,
        "availability": profile.get("availability"),
        "availability_reason": profile.get("availability_reason"),
        "execution_mode": profile.get("execution_mode"),
        "resolution": profile.get("resolution"),
        "native_generation_fps": 24,
    } for workflow_id in ARCHITECTURE_PROFILES
        for quality_id, profile in QUALITY_PROFILE_SPECS.items()]


def apply_architecture_profile(prompt: str, workflow_id: str) -> str:
    """Insert workflow-specific retention wording inside the H3 description field."""
    text = str(prompt or "")
    profile = resolve_architecture_profile(workflow_id)
    clause = profile["prompt_clause"] + " " + " ".join(
        profile["negative_constraints"])
    if clause in text:
        return text
    marker = "integrated_multimodal_description:"
    start = text.find(marker)
    if start < 0:
        raise ValueError("H3 prompt is missing integrated_multimodal_description")
    boundary = text.find("\n\noverall_soundscape:", start)
    if boundary < 0:
        raise ValueError("H3 prompt is missing overall_soundscape boundary")
    return text[:boundary].rstrip() + " " + clause + text[boundary:]


def actual_execution_parameters(payload: Mapping[str, Any], workflow_id: str,
                                 profile_context: Mapping[str, Any]) -> dict[str, Any]:
    """Read the actual scalar settings from a value-bound Golden API graph."""
    by_type: dict[str, list[Mapping[str, Any]]] = {}
    for node in payload.values():
        if isinstance(node, Mapping):
            by_type.setdefault(str(node.get("class_type") or ""), []).append(node)

    def inputs(node_type: str) -> Mapping[str, Any]:
        matches = by_type.get(node_type, [])
        if len(matches) != 1:
            raise ValueError(f"expected one {node_type} node, found {len(matches)}")
        value = matches[0].get("inputs") or {}
        return value if isinstance(value, Mapping) else {}

    h3 = inputs("MiniMaxH3ImageToVideo")
    noise = inputs("RandomNoise")
    sampler = inputs("KSamplerSelect")
    scheduler = inputs("BasicScheduler")
    video = inputs("CreateVideo")
    width, height = int(h3["width"]), int(h3["height"])
    fps = float(video["fps"])
    frame_count = int(h3["length"])
    if not math.isclose(fps, H3_NATIVE_FPS, rel_tol=0.0, abs_tol=1e-9) or frame_count < 1:
        raise ValueError("bound workflow has invalid fps or latent length")
    if (frame_count - H3_FRAME_GRID_OFFSET) % H3_FRAME_GRID_MODULUS:
        raise ValueError("bound workflow frame count is not on H3's 17k+5 grid")
    duration = round(frame_count / fps, 6)
    final_params = profile_context.get("final_execution_parameters") or {}
    reference_count = sum(
        1 for node in payload.values()
        if isinstance(node, Mapping) and node.get("class_type") == "LoadImage"
    )
    return {
        "quality_profile": profile_context["quality_profile"],
        "architecture_profile": profile_context["architecture_profile"],
        "resolution": f"{width}x{height}",
        "width": width,
        "height": height,
        "duration_seconds": duration,
        "requested_duration_seconds": float(
            final_params.get("requested_duration_seconds",
                            final_params.get("duration", duration))),
        "fps": fps,
        "frame_count": frame_count,
        "latent_length": frame_count,
        "seed": int(noise["noise_seed"]),
        "steps": int(scheduler["steps"]),
        "sampler": str(sampler["sampler_name"]),
        "scheduler": str(scheduler["scheduler"]),
        "denoise": float(scheduler["denoise"]),
        "acceleration": "off",
        "reference_count": reference_count,
    }


__all__ = [
    "ARCHITECTURE_PROFILE_VERSION", "ARCHITECTURE_PROFILES",
    "LEGACY_QUALITY_ALIASES", "PRESERVATION_SEMANTICS",
    "H3_FRAME_GRID_MODULUS", "H3_FRAME_GRID_OFFSET", "H3_MAX_NATIVE_FRAME_COUNT",
    "H3_NATIVE_FPS", "H3_MAX_EFFECTIVE_DURATION_SECONDS",
    "H3_MAX_REQUESTED_DURATION_SECONDS", "H3_MIN_REQUESTED_DURATION_SECONDS",
    "h3_frame_count_for_duration",
    "PROFILE_CONTRACT_VERSION", "PROMPT_PROFILE_VERSION", "QUALITY_PROFILE_SPECS",
    "QUALITY_PROFILE_VERSION", "actual_execution_parameters",
    "apply_architecture_profile", "architecture_profile_catalog",
    "normalize_quality_id", "quality_profile_catalog",
    "require_available_quality_profile",
    "resolve_architecture_profile", "resolve_execution_profile",
    "resolve_product_parameters",
    "workflow_quality_matrix",
]
