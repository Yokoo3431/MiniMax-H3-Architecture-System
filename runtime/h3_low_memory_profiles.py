"""Deterministic MiniMax-H3 deployment profiles.

This module is deliberately CPU/static only.  It selects filenames and
launcher policy; it never imports torch, opens a checkpoint, downloads an
asset, or creates a CUDA tensor.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_CONFIG = REPO_ROOT / "configs" / "h3_runtime_profiles.json"
MODEL_MANIFEST = REPO_ROOT / "models" / "manifest.json"

COMPATIBILITY = "COMPATIBILITY"
BALANCED = "BALANCED"
QUALITY = "QUALITY"
AUTO = "AUTO"

_ALIASES = {
    "H3_LOW": COMPATIBILITY,
    "H3_STANDARD": COMPATIBILITY,
    "H3_PRO": QUALITY,
}


def detect_hardware_facts(*, timeout_seconds: int = 5) -> dict[str, Any]:
    """Read only the facts needed for AUTO profile selection.

    This does not import torch, load a model, or allocate CUDA memory. Missing
    facts remain unknown and the selector conservatively chooses COMPATIBILITY.
    """
    facts: dict[str, Any] = {
        "gpu_vram_gb": None,
        "system_ram_gb": None,
        "source": [],
        "errors": [],
    }
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
        if result.returncode == 0:
            first = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
            if first:
                facts["gpu_vram_gb"] = round(float(first.split()[0]) / 1024.0, 2)
                facts["source"].append("nvidia-smi")
        else:
            facts["errors"].append("nvidia-smi returned a non-zero exit code")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        facts["errors"].append(f"nvidia-smi: {type(exc).__name__}")

    try:
        if os.name == "nt":
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                facts["system_ram_gb"] = round(status.ullTotalPhys / (1024 ** 3), 2)
                facts["source"].append("GlobalMemoryStatusEx")
        elif hasattr(os, "sysconf"):
            facts["system_ram_gb"] = round(
                (os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")) / (1024 ** 3), 2,
            )
            facts["source"].append("sysconf")
    except (AttributeError, OSError, TypeError, ValueError):
        facts["errors"].append("system memory probe failed")
    return facts


def load_profile_config(path: str | Path = PROFILE_CONFIG) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def select_profile(*, gpu_vram_gb: Any = None, system_ram_gb: Any = None,
                   requested: str = AUTO) -> str:
    """Select a safe profile from hardware facts without probing the GPU.

    Unknown hardware intentionally selects COMPATIBILITY: it is the only
    profile that never asks for the heavier 27GB text encoder.
    """
    requested_key = str(requested or AUTO).strip().upper()
    requested_key = _ALIASES.get(requested_key, requested_key)
    if requested_key in {COMPATIBILITY, BALANCED, QUALITY}:
        return requested_key
    if requested_key != AUTO:
        raise ValueError(f"unknown H3 deployment profile: {requested}")

    vram = _number(gpu_vram_gb)
    ram = _number(system_ram_gb)
    if vram is None or ram is None:
        return COMPATIBILITY
    if vram <= 16.0 or ram <= 32.0:
        return COMPATIBILITY
    if vram >= 24.0 and ram >= 64.0:
        return QUALITY
    return BALANCED


def profile_spec(profile: str = AUTO, *, gpu_vram_gb: Any = None,
                 system_ram_gb: Any = None,
                 config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    data = dict(config or load_profile_config())
    selected = select_profile(gpu_vram_gb=gpu_vram_gb,
                              system_ram_gb=system_ram_gb,
                              requested=profile)
    spec = dict((data.get("profiles") or {}).get(selected) or {})
    if not spec:
        raise ValueError(f"profile {selected} is not defined")
    spec["profile"] = selected
    return spec


def model_selection(profile: str = AUTO, *, gpu_vram_gb: Any = None,
                    system_ram_gb: Any = None,
                    config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    spec = profile_spec(profile, gpu_vram_gb=gpu_vram_gb,
                        system_ram_gb=system_ram_gb, config=config)
    selection = dict(spec.get("models") or {})
    selection["profile"] = spec["profile"]
    selection["runtime_flags"] = list(spec.get("runtime_flags") or [])
    selection["text_encoder_format"] = spec.get("text_encoder_format", "unknown")
    selection["text_encoder_loader"] = spec.get("text_encoder_loader", "unknown")
    selection["dit_format"] = spec.get("dit_format", "unknown")
    selection["workflow_backend"] = spec.get("workflow_backend", "runninghub")
    selection["resolution"] = spec.get("resolution", "1024x576")
    selection["memory_policy"] = spec.get("memory_policy", "conservative")
    return selection


def validate_profile_loader_contract(selection: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the selected model format against its actual loader contract.

    NVFP4 is handled by Comfy's native MiniMax H3 CLIP loader.  The pinned
    RunningHub Qwen path is intentionally INT8/ConvRot-only and must never be
    allowed to receive an NVFP4 checkpoint.
    """
    fmt = str(selection.get("text_encoder_format") or "unknown").lower()
    loader = str(selection.get("text_encoder_loader") or "unknown").lower()
    filename = str(selection.get("text_encoder") or "")
    compatible = True
    reason = ""
    if fmt == "nvfp4_awq" or "nvfp4" in filename.lower():
        compatible = loader == "native_comfy_minimax_h3"
        reason = "NVFP4 requires native Comfy MiniMax H3 CLIP loading"
    elif fmt == "int8_convrot" or "int8" in filename.lower() or "convrot" in filename.lower():
        compatible = loader == "runninghub_int8_convrot"
        reason = "INT8 ConvRot requires the RunningHub INT8 loader"
    if not compatible:
        return {
            "ready": False,
            "code": "PROFILE_LOADER_INCOMPATIBLE",
            "format": fmt,
            "loader": loader,
            "model": filename,
            "reason": reason,
        }
    return {
        "ready": True,
        "code": "PROFILE_LOADER_COMPATIBLE",
        "format": fmt,
        "loader": loader,
        "model": filename,
        "reason": reason or "profile loader contract is compatible",
    }


def resolve_available_selection(selection: Mapping[str, Any],
                                models_root: str | Path | None) -> dict[str, Any]:
    """Resolve profile filenames against an already-installed H3 root.

    This is a filename-only compatibility check. If a compatibility install
    has the verified full INT8 DiT but not the preferred pruned DiT, the
    existing full DiT is used as an explicit degraded selection. The heavy
    INT8 text encoder is never used as a compatibility fallback.
    """
    result = dict(selection)
    if not models_root:
        result["loader_contract"] = validate_profile_loader_contract(result)
        return result
    root = Path(models_root).expanduser().resolve()
    if root.name.casefold() != "minimax-h3".casefold():
        root = root / "MiniMax-H3"

    def exists(name: str) -> bool:
        if not name:
            return False
        return any((candidate / name).is_file() for candidate in (
            root, root / "FL2VA" / "transformer",
            root / "FL2VA" / "text_encoder", root / "FL2VA" / "video_vae",
            root / "FL2VA" / "audio_vae"))

    preferred = str(result.get("transformer") or "")
    if preferred and not exists(preferred):
        fallback = str(result.get("transformer_fallback") or "")
        if fallback and exists(fallback):
            result["requested_transformer"] = preferred
            result["transformer"] = fallback
            result["selection_note"] = (
                "preferred pruned DiT missing; reused existing full INT8 DiT"
            )
    result["missing_preferred_assets"] = [
        name for name in (str(selection.get("transformer") or ""),
                          str(selection.get("text_encoder") or ""))
        if name and not exists(name)
    ]
    result["loader_contract"] = validate_profile_loader_contract(result)
    return result


def profile_runtime_flags(profile: str = AUTO, *, gpu_vram_gb: Any = None,
                          system_ram_gb: Any = None) -> list[str]:
    return list(profile_spec(profile, gpu_vram_gb=gpu_vram_gb,
                              system_ram_gb=system_ram_gb).get("runtime_flags") or [])


def missing_selected_assets(selection: Mapping[str, Any],
                            available: Mapping[str, bool] | None = None) -> list[str]:
    """Return missing selected filenames when a caller supplies scan results."""
    if available is None:
        return []
    return [str(name) for name in selection.values()
            if isinstance(name, str) and name.endswith(".safetensors")
            and not bool(available.get(name, False))]


__all__ = [
    "AUTO", "BALANCED", "COMPATIBILITY", "QUALITY", "load_profile_config",
    "detect_hardware_facts", "missing_selected_assets", "model_selection", "profile_runtime_flags",
    "profile_spec", "resolve_available_selection",
    "select_profile", "validate_profile_loader_contract",
]
