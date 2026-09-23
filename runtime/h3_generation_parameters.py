"""Single source of truth for the user-facing MiniMax-H3 controls.

The Studio may present friendly labels, but every accepted value maps to a
real field consumed by the pinned RH MiniMax-H3 sampler.  This module is pure
CPU validation and is safe to use from the UI API, prompt builder, and payload
builder without importing CUDA or loading a model.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from runtime.a4_profiles import (
    QUALITY_PROFILE_SPECS,
    h3_frame_count_for_duration,
    normalize_quality_id,
)


VIDEO_TYPES = (
    ("01_Exterior_Hero", "Exterior Hero"),
    ("02_Day_Night_Transition", "Day / Night Transition"),
    ("03_Material_Detail", "Material Detail"),
    ("04_Drone_Aerial", "Drone Aerial"),
    ("05_Slow_Walkthrough", "Slow Walkthrough"),
)
VIDEO_TYPE_LABELS = dict(VIDEO_TYPES)
VIDEO_TYPE_IDS = tuple(item[0] for item in VIDEO_TYPES)

RESOLUTION_PRESETS = {
    "832x480": (832, 480),
    "1024x576": (1024, 576),
    "1344x768": (1344, 768),
}
ASPECT_RATIOS = ("auto", "16:9", "9:16", "1:1")
QUALITY_PROFILES = {
    profile_id: {
        "sigma_points": int(spec["steps"]),
        "sampler_mode": str(spec["sampler_mode"]),
        "default_resolution": str(spec["resolution"]),
    }
    for profile_id, spec in QUALITY_PROFILE_SPECS.items()
    if spec.get("availability") == "READY"
}

ACCELERATION_MODES = {
    "standard": "off",
    "auto": "auto",
    "velocity-cache": "manual-velocity",
    "cache-dit": "manual-cache-dit",
}


class H3ParameterError(ValueError):
    """Raised when a user parameter cannot be represented by the H3 contract."""


def _text(value: Any, default: str) -> str:
    return str(default if value is None else value).strip().lower()


def _resolution(value: Any) -> str:
    text = _text(value, "") .replace("×", "x").replace(" ", "")
    if text not in RESOLUTION_PRESETS:
        raise H3ParameterError(
            f"resolution must be one of {', '.join(RESOLUTION_PRESETS)}")
    return text


def normalize_generation_parameters(values: Mapping[str, Any] | None = None,
                                    *, seed: int | None = None) -> dict[str, Any]:
    """Validate and expand friendly controls into the production H3 contract."""
    raw = dict(values or {})
    raw_quality = _text(raw.get("quality"), "NATIVE_HIGH")
    try:
        quality = normalize_quality_id(raw_quality)
    except ValueError as exc:
        raise H3ParameterError(str(exc)) from exc
    if quality not in QUALITY_PROFILES:
        spec = QUALITY_PROFILE_SPECS[quality]
        raise H3ParameterError(
            f"QUALITY_PROFILE_UNAVAILABLE:{quality}: "
            f"{spec.get('availability_reason', 'execution is not validated')}")

    try:
        duration = float(raw.get("duration", 4.0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise H3ParameterError("duration must be a number") from exc
    if not math.isfinite(duration) or not 4.0 <= duration <= 15.0:
        raise H3ParameterError("duration must be between 4 and 15 seconds")
    try:
        frame_count = h3_frame_count_for_duration(duration, 24)
    except ValueError as exc:
        raise H3ParameterError(str(exc)) from exc
    resolved_duration = round(frame_count / 24, 6)

    try:
        fps_value = float(raw.get("fps", 24))
    except (TypeError, ValueError, OverflowError) as exc:
        raise H3ParameterError("fps must be 24") from exc
    if not math.isfinite(fps_value) or not math.isclose(
            fps_value, 24.0, rel_tol=0.0, abs_tol=1e-9):
        raise H3ParameterError("current H3 Golden workflows support 24 fps only")
    fps = 24

    try:
        delivery_fps_value = float(raw.get("delivery_fps", 24))
    except (TypeError, ValueError, OverflowError) as exc:
        raise H3ParameterError("delivery_fps must be 24") from exc
    if not math.isfinite(delivery_fps_value) or not math.isclose(
            delivery_fps_value, 24.0, rel_tol=0.0, abs_tol=1e-9):
        raise H3ParameterError(
            "DELIVERY_FPS_UNAVAILABLE: 30/48/60 FPS require a validated post-process pipeline")
    delivery_fps = 24

    resolution = _resolution(raw.get("resolution") or QUALITY_PROFILES[quality]["default_resolution"])
    width, height = RESOLUTION_PRESETS[resolution]
    aspect_ratio = _text(raw.get("aspect_ratio"), "auto")
    if aspect_ratio not in ASPECT_RATIOS:
        raise H3ParameterError("aspect_ratio must be auto, 16:9, 9:16, or 1:1")

    speed = _text(raw.get("generation_speed") or raw.get("acceleration"), "standard")
    speed = {"standard": "standard", "auto accelerated": "auto",
             "auto_accelerated": "auto", "auto-accelerated": "auto"}.get(speed, speed)
    if speed not in ("standard", "auto"):
        raise H3ParameterError("generation_speed must be standard or auto")

    velocity_cache = bool(raw.get("velocity_cache", False))
    cache_dit = bool(raw.get("cache_dit", False))
    if velocity_cache and cache_dit:
        raise H3ParameterError("velocity-cache and Cache-DiT cannot be enabled together")
    advanced_accel = "velocity-cache" if velocity_cache else "cache-dit" if cache_dit else None
    accel = ACCELERATION_MODES[advanced_accel or speed]

    try:
        steps = int(raw.get("steps") or QUALITY_PROFILES[quality]["sigma_points"])
    except (TypeError, ValueError) as exc:
        raise H3ParameterError("steps must be an integer") from exc
    if steps < 2 or steps > 100:
        raise H3ParameterError("steps must be between 2 and 100 sigma points")
    sampler_mode = _text(raw.get("sampler_mode"), QUALITY_PROFILES[quality]["sampler_mode"])
    if sampler_mode not in ("euler", "res_multistep"):
        raise H3ParameterError("sampler_mode must be euler or res_multistep")

    try:
        final_seed = int(raw.get("seed", seed if seed is not None else 42))
    except (TypeError, ValueError) as exc:
        raise H3ParameterError("seed must be an integer") from exc
    if final_seed < 0:
        raise H3ParameterError("seed must be non-negative")

    normalized = {
        "resolution": resolution,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "fps": fps,
        "native_generation_fps": 24,
        "delivery_fps": delivery_fps,
        "duration": duration,
        "requested_duration_seconds": duration,
        "resolved_duration_seconds": resolved_duration,
        "frame_count": frame_count,
        "quality": quality,
        "seed": final_seed,
        "generation_speed": "auto" if speed == "auto" else "standard",
        "sampler_mode": sampler_mode,
        "steps": steps,
        "sigma_points": steps,
        "accel": accel,
        "velocity_cache": velocity_cache,
        "cache_dit": cache_dit,
        "velocity_stride": int(raw.get("velocity_stride", 4)),
        "cache_dit_rdt": float(raw.get("cache_dit_rdt", 0.08)),
        "cache_dit_mc": int(raw.get("cache_dit_mc", 2)),
        "cache_dit_warmup": int(raw.get("cache_dit_warmup", 4)),
        "allow_accel_with_res_multistep": bool(raw.get("allow_accel_with_res_multistep", False)),
    }
    if normalized["velocity_stride"] < 1:
        raise H3ParameterError("velocity_stride must be at least 1")
    if normalized["cache_dit_mc"] < 1 or normalized["cache_dit_warmup"] < 0:
        raise H3ParameterError("Cache-DiT limits are invalid")
    if not 0.0 < normalized["cache_dit_rdt"] <= 1.0:
        raise H3ParameterError("cache_dit_rdt must be between 0 and 1")
    if sampler_mode == "res_multistep" and accel != "off" \
            and not normalized["allow_accel_with_res_multistep"]:
        raise H3ParameterError(
            "加速与 res_multistep 组合需要在高级设置中明确允许")
    return normalized


__all__ = [
    "ACCELERATION_MODES", "ASPECT_RATIOS", "H3ParameterError",
    "QUALITY_PROFILES", "RESOLUTION_PRESETS", "VIDEO_TYPE_IDS",
    "VIDEO_TYPE_LABELS", "VIDEO_TYPES", "normalize_generation_parameters",
]
