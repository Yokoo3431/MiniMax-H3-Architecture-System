"""RC3.3 PATCH2.4-R3 - Windows safe large safetensors load shim (PREAD first, bytes fallback).

Purpose
-------
Official Native ComfyUI (v0.33.1) on Windows intermittently crashes with an
access violation (0xC0000005) while reading large safetensors through the
mmap-backed `safetensors.safe_open -> get_tensor` path inside a long-running
server process (upstream issue Comfy-Org/ComfyUI #15424; `--disable-mmap` is
insufficient because the copy happens only AFTER the mmap read, see #15438).

This module is a minimal, reversible, Native-only compatibility layer:

  - ONLY active when the environment variable H3_WINDOWS_SAFE_LOAD is set
    ("pread" or "bytes").
  - ONLY intercepts Windows + .safetensors/.sft files whose size is at or
    above H3_SAFE_LOAD_MIN_GB (default 8) and whose filename matches the
    allow-list (default: "minimax_h3_fl2va" -> the H3 DiT only).
  - PREFERRED backend: safetensors.torch.load_file(..., backend="pread")
    (no mmap-backed tensor storage).
  - FALLBACK backend: file -> bytes -> safetensors.torch.load(bytes).
  - Preserves the official load_torch_file contract, including
    return_metadata (header parsed without mmap) and device handling.
  - All other loads delegate to the original ComfyUI implementation.

Install location (Native production candidate only):
  <active Native Runtime>/ComfyUI/custom_nodes/windows_safe_load/__init__.py

Legacy RH environment and ComfyUI core are NOT modified.
"""

import json
import os
import platform
import struct
from pathlib import Path

_PATCHED = False


def _read_safetensors_metadata(path):
    """Read only the safetensors header (8-byte length + JSON). No mmap, no tensors."""
    with open(path, "rb") as f:
        (header_len,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(header_len))
    return header.get("metadata")  # None when absent, matching safetensors safe_open.metadata()


def _target_enabled():
    if platform.system() != "Windows":
        return False
    backend = os.environ.get("H3_WINDOWS_SAFE_LOAD", "").strip().lower()
    return backend in ("pread", "bytes")


def _backend():
    return os.environ.get("H3_WINDOWS_SAFE_LOAD", "").strip().lower()


def _min_gb():
    try:
        return float(os.environ.get("H3_SAFE_LOAD_MIN_GB", "8"))
    except ValueError:
        return 8.0


def _allowlist():
    raw = os.environ.get("H3_SAFE_LOAD_ALLOW", "minimax_h3_fl2va")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _is_target(path):
    if not _target_enabled():
        return False
    p = str(path)
    if not (p.lower().endswith(".safetensors") or p.lower().endswith(".sft")):
        return False
    try:
        if Path(p).stat().st_size < _min_gb() * (1024 ** 3):
            return False
    except OSError:
        return False
    name = Path(p).name.lower()
    return any(tok in name for tok in _allowlist())


def _safe_load_state_dict(path, device, backend):
    import safetensors.torch

    if device is None:
        import torch
        device = torch.device("cpu")
    if backend == "pread":
        return safetensors.torch.load_file(str(path), device=device.type, backend="pread")
    # bytes-copy fallback: sequential read -> bytes -> load; release bytes early.
    data = Path(path).read_bytes()
    try:
        return safetensors.torch.load(data)
    finally:
        del data


def _make_wrapper(original):
    def load_torch_file(ckpt, safe_load=False, device=None, return_metadata=False):
        if _is_target(ckpt):
            backend = _backend()
            print(
                "[windows_safe_load] H3_WINDOWS_SAFE_LOAD={} intercepting large safetensors: {}".format(
                    backend, ckpt
                ),
                flush=True,
            )
            sd = _safe_load_state_dict(ckpt, device, backend)
            metadata = None
            if return_metadata:
                metadata = _read_safetensors_metadata(ckpt)
            return (sd, metadata) if return_metadata else sd
        return original(ckpt, safe_load=safe_load, device=device, return_metadata=return_metadata)

    return load_torch_file


def install():
    """Patch comfy.utils.load_torch_file once (idempotent)."""
    global _PATCHED
    if _PATCHED:
        return
    try:
        import comfy.utils
    except Exception as exc:  # pragma: no cover - environment dependent
        print("[windows_safe_load] comfy.utils import failed: {}".format(exc), flush=True)
        return
    comfy.utils.load_torch_file = _make_wrapper(comfy.utils.load_torch_file)
    _PATCHED = True
    state = "ACTIVE({})".format(_backend()) if _target_enabled() else "INACTIVE"
    print("[windows_safe_load] installed - {}".format(state), flush=True)


# ComfyUI custom-node entry points (this module is installed as __init__.py).
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

install()
