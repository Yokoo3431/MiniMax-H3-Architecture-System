"""Central, CPU-only capability and estimation contract for Studio jobs.

The Golden graphs remain immutable here.  This module describes the values the
existing binders are allowed to inject and provides the same validation to the
API, tests, and frontend metadata endpoint.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping

from runtime.h3_generation_parameters import normalize_generation_parameters


WORKFLOW_CAPABILITIES: dict[str, dict[str, Any]] = {
    "01_Exterior_Hero": {"mode": "I2VA", "references": 1},
    "02_Day_Night_Transition": {"mode": "FL2VA", "references": 2},
    "03_Material_Detail": {"mode": "I2VA", "references": 1},
    "04_Drone_Aerial": {"mode": "I2VA", "references": 1},
    "05_Slow_Walkthrough": {"mode": "I2VA", "references": 1},
}

# These are the currently verified Golden/Runtime values.  In particular,
# 30fps is deliberately not exposed until the H3 frame-grid contract proves it.
FPS_OPTIONS = (24,)
RESOLUTION_OPTIONS = ("832x480", "1024x576", "1344x768")
SAMPLER_OPTIONS = ("euler", "res_multistep")
STEPS_RANGE = (2, 100)
DURATION_RANGE = (4.0, 15.0)
# The frozen Native Golden graphs have no acceleration input.  Keep the
# capability honest: Standard is the only value that changes no hidden graph
# contract; Auto/Cache modes remain available only in legacy diagnostic APIs.
ACCELERATION_OPTIONS = ("standard",)
_ETA_BOOTSTRAP = Path(__file__).resolve().parent.parent / "configs" / "eta_historical_success.json"


def _bootstrap_history() -> list[dict[str, Any]]:
    """Load owner-validated historical timings, never private job data."""
    try:
        payload = json.loads(_ETA_BOOTSTRAP.read_text(encoding="utf-8"))
        return list(payload.get("successful_runs", []))
    except (OSError, ValueError, TypeError):
        return []


def capability_matrix() -> dict[str, dict[str, Any]]:
    """Return a serializable copy for the API/UI without mutable internals."""
    return {
        workflow: {
            **capability,
            "fps": list(FPS_OPTIONS),
            "resolutions": list(RESOLUTION_OPTIONS),
            "duration": {"min": DURATION_RANGE[0], "max": DURATION_RANGE[1]},
            "steps": {"min": STEPS_RANGE[0], "max": STEPS_RANGE[1]},
            "samplers": list(SAMPLER_OPTIONS),
            "acceleration": list(ACCELERATION_OPTIONS),
        }
        for workflow, capability in WORKFLOW_CAPABILITIES.items()
    }


def validate_workflow_parameters(workflow_id: str,
                                 values: Mapping[str, Any] | None = None,
                                 *, seed: int | None = None) -> dict[str, Any]:
    """Normalize H3 values and enforce the selected Golden's capability row."""
    if workflow_id not in WORKFLOW_CAPABILITIES:
        raise ValueError(f"unknown workflow: {workflow_id}")
    normalized = normalize_generation_parameters(values, seed=seed)
    if int(normalized["fps"]) not in FPS_OPTIONS:
        raise ValueError(f"{workflow_id} does not support fps {normalized['fps']}")
    if normalized["resolution"] not in RESOLUTION_OPTIONS:
        raise ValueError(f"{workflow_id} does not support {normalized['resolution']}")
    if normalized["sampler_mode"] not in SAMPLER_OPTIONS:
        raise ValueError(f"{workflow_id} does not support sampler {normalized['sampler_mode']}")
    if normalized["generation_speed"] not in ACCELERATION_OPTIONS:
        raise ValueError(f"{workflow_id} does not support acceleration {normalized['generation_speed']}")
    return normalized


def lifecycle_state(stage: str | None, *, terminal: str | None = None) -> str:
    """Map internal event labels to one shared product lifecycle."""
    if terminal == "SUCCEEDED":
        return "SUCCEEDED"
    if terminal == "FAILED":
        return "FAILED"
    return {
        "准备参考图": "CREATED",
        "加载 H3 模型": "QUEUED",
        "分析提示词": "ENCODING",
        "编码参考图": "ENCODING",
        "视频采样": "RUNNING",
        "同步 ComfyUI 任务": "RUNNING",
        "视频解码": "DECODING",
        "保存视频": "FINALIZING",
        "执行工作流": "RUNNING",
        "生成中": "RUNNING",
    }.get(str(stage or ""), "RUNNING")


STAGE_WEIGHTS = {
    "PREPARING": (0.0, 10.0),
    "ENCODING": (10.0, 20.0),
    "SAMPLING": (20.0, 90.0),
    "RUNNING": (20.0, 90.0),
    "DECODING": (90.0, 97.0),
    "FINALIZING": (97.0, 100.0),
}


def weighted_progress(stage: str | None, step: Any = None,
                      total_steps: Any = None,
                      supplied: Any = None) -> float | None:
    """Use authoritative step progress, otherwise keep progress unknown."""
    name = str(stage or "").upper()
    if name in ("SUCCEEDED", "COMPLETED"):
        return 100.0
    bounds = STAGE_WEIGHTS.get(name)
    if bounds is None:
        return None if supplied is None else max(0.0, min(100.0, float(supplied)))
    fraction = None
    try:
        if step is not None and total_steps is not None and float(total_steps) > 0:
            fraction = max(0.0, min(1.0, float(step) / float(total_steps)))
        elif supplied is not None:
            # Comfy's percentage is authoritative, but map it into the stage
            # range when the event is a stage-level signal.
            raw = max(0.0, min(100.0, float(supplied))) / 100.0
            fraction = raw
    except (TypeError, ValueError):
        return None
    if fraction is None:
        return bounds[0] if name in ("PREPARING", "ENCODING", "DECODING", "FINALIZING") else None
    return round(bounds[0] + (bounds[1] - bounds[0]) * fraction, 2)


def estimate_generation_range(history: Iterable[Mapping[str, Any]],
                              *, workflow_id: str, duration: float,
                              fps: int, resolution: str, steps: int,
                              cold_start: bool = False) -> dict[str, Any]:
    """Estimate a range from successful job durations, never from a fixed ETA."""
    samples: list[float] = []
    seen: set[str] = set()
    for item in list(_bootstrap_history()) + list(history):
        if item.get("state") not in ("COMPLETED", "SUCCEEDED"):
            continue
        if item.get("workflow") != workflow_id:
            continue
        evidence_id = str(item.get("evidence_id") or "")
        if evidence_id and evidence_id in seen:
            continue
        if evidence_id:
            seen.add(evidence_id)
        try:
            elapsed = float(item.get("elapsed"))
            if elapsed > 0:
                samples.append(elapsed)
        except (TypeError, ValueError):
            continue
    if not samples:
        return {"min_seconds": None, "max_seconds": None,
                "lower_bound_seconds": None, "upper_bound_seconds": None,
                "confidence": "insufficient", "evidence_count": 0,
                "estimate_basis": "没有可匹配的成功记录", "label": "暂无可靠估算"}
    median = statistics.median(samples)
    pixels = {"832x480": 832 * 480, "1024x576": 1024 * 576,
              "1344x768": 1344 * 768}.get(resolution, 1024 * 576)
    baseline_pixels = 1024 * 576
    factor = (float(duration) * float(fps)) / (4.0 * 24.0)
    factor *= pixels / baseline_pixels
    factor *= max(0.5, float(steps) / 50.0)
    if cold_start:
        factor *= 1.20
    estimate = max(1.0, median * factor)
    lower = round(estimate * 0.85)
    upper = round(estimate * 1.15)
    return {"min_seconds": lower, "max_seconds": upper,
            "lower_bound_seconds": lower, "upper_bound_seconds": upper,
            "confidence": "history" if len(samples) >= 3 else "limited",
            "evidence_count": len(samples), "sample_count": len(samples),
            "estimate_basis": "当前设备配置 + 已验证成功记录 + 分辨率/帧数/步数修正",
            "label": "历史数据充足" if len(samples) >= 3 else "数据较少，时间仅供参考"}


__all__ = ["ACCELERATION_OPTIONS", "DURATION_RANGE", "FPS_OPTIONS",
           "RESOLUTION_OPTIONS", "SAMPLER_OPTIONS", "STEPS_RANGE",
           "WORKFLOW_CAPABILITIES", "capability_matrix",
           "estimate_generation_range", "lifecycle_state", "weighted_progress",
           "validate_workflow_parameters"]
