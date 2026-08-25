"""Small, deterministic product-boundary helpers.

These helpers deliberately do not inspect models or touch CUDA.  They keep
progress, asset cache identity, and crash classification in one place so the
Studio UI does not infer state from a browser tab or a clock alone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping


COMFY_NATIVE_CRASH_CODES = frozenset({0xC0000005, 3221225477})


def classify_comfy_exit(exit_code: int | None) -> str:
    """Return a product category for a ComfyUI child exit."""
    if exit_code is not None and int(exit_code) in COMFY_NATIVE_CRASH_CODES:
        return "COMFYUI_NATIVE_CRASH"
    return "COMFYUI_CRASHED"


def map_comfy_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Map an optional Comfy event to the small Studio progress contract.

    A percentage is returned only when Comfy supplied an authoritative value
    or sampling step.  Unknown progress is represented by ``None`` rather
    than a guessed clock-based percentage.
    """
    name = str(event.get("type") or event.get("event") or "").lower()
    data = event.get("data") if isinstance(event.get("data"), Mapping) else event
    stage_map = {
        "execution_start": ("准备参考图", "PREPARING"),
        "execution_cached": ("加载 H3 模型", "LOADING_MODEL"),
        "executing": ("执行工作流", "EXECUTING"),
        "progress": ("视频采样", "SAMPLING"),
        "progress_state": ("视频采样", "SAMPLING"),
        "progress_text": ("执行工作流", "EXECUTING"),
        "executed": ("视频解码", "DECODING"),
        "execution_success": ("保存视频", "EXPORTING"),
        "execution_error": ("生成失败", "FAILED"),
    }
    stage, state = stage_map.get(name, (None, None))
    current = data.get("value", data.get("step")) if isinstance(data, Mapping) else None
    total = data.get("max", data.get("total_steps")) if isinstance(data, Mapping) else None
    progress = data.get("progress") if isinstance(data, Mapping) else None
    if progress is None and current is not None and total:
        try:
            progress = float(current) / float(total) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            progress = None
    if progress is not None:
        try:
            progress = max(0.0, min(100.0, float(progress)))
        except (TypeError, ValueError):
            progress = None
    return {
        "event": name or "unknown",
        "state": state or "EXECUTING",
        "stage": stage or "执行工作流",
        "progress": progress,
        "step": current,
        "total_steps": total,
        "message": str(data.get("text") or data.get("message") or "") if isinstance(data, Mapping) else "",
    }


def estimate_eta(elapsed: float, progress: float | None,
                 minimum_samples: int = 2) -> float | None:
    """Estimate ETA only from an authoritative percentage.

    The caller may use ``minimum_samples`` to suppress estimates until enough
    rolling samples have been collected.  Returning ``None`` is intentional.
    """
    del minimum_samples  # reserved for the rolling-window caller
    if progress is None or progress <= 0 or progress >= 100:
        return None
    return max(0.0, float(elapsed) * (100.0 - float(progress)) / float(progress))


def asset_cache_token(asset: Mapping[str, Any]) -> str:
    """Return a stable short cache token for an uploaded asset record."""
    value = str(asset.get("sha256") or asset.get("version") or asset.get("id") or "")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def unique_comfy_filename(asset: Mapping[str, Any], source: Path) -> str:
    """Return a safe per-asset filename for ComfyUI's input directory."""
    asset_id = "".join(c for c in str(asset.get("id") or "asset") if c.isalnum() or c in "-_" )
    digest = str(asset.get("sha256") or "")[:12].lower()
    if len(digest) < 12:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    suffix = source.suffix.lower() or ".png"
    return f"avs_{asset_id or 'asset'}_{digest}{suffix}"

