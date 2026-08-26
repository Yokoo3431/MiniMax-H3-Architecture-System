"""Explicit, no-GPU MiniMax-H3 model-root contract.

The pinned RH support layer has two separate path contracts:
MINIMAX_H3_MODEL_ROOTS admits release directories such as <models_root>/MiniMax-H3.
MINIMAX_H3_WEIGHTS_ROOTS admits flat selector weight files below the same root.

ComfyUI ordinary extra_model_paths.yaml category mappings do not populate either
variable. This module keeps the adapter process-scoped and resolves the contract
without copying weights or constructing CUDA tensors.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Optional

from runtime.h3_asset_contract import evaluate_h3_asset_contract


H3_MODEL_ROOTS_ENV = "MINIMAX_H3_MODEL_ROOTS"
H3_WEIGHTS_ROOTS_ENV = "MINIMAX_H3_WEIGHTS_ROOTS"
H3_MODEL_ROOT_NAME = "MiniMax-H3"
COMFY_MODEL_PATHS_FILENAME = "architect_video_studio_extra_model_paths.yaml"


class H3ModelRootBridgeError(ValueError):
    """The Runtime-visible H3 bridge is missing or conflicts with user data."""


def h3_model_root_bridge_target(runtime_root: str | Path) -> Path:
    """Return the Runtime-local resolver path for the selected H3 root."""
    return Path(runtime_root).expanduser().resolve() / "ComfyUI" / "models" / H3_MODEL_ROOT_NAME


def h3_model_root_bridge_status(runtime_root: str | Path | None,
                                models_root: str | Path | None) -> dict[str, Any]:
    """Inspect the config-driven bridge without modifying the filesystem."""
    source = canonical_h3_model_root(models_root) if models_root else None
    target = h3_model_root_bridge_target(runtime_root) if runtime_root else None
    result: dict[str, Any] = {
        "status": "NEEDS_PATH" if not source or not target else "MISSING",
        "ready": False,
        "source": str(source) if source else "",
        "target": str(target) if target else "",
        "created": False,
    }
    if source is None or target is None:
        return result
    if not source.is_dir():
        result.update({"status": "SOURCE_MISSING", "reason": f"H3 model root missing: {source}"})
        return result
    if not target.exists():
        return result
    try:
        resolved_source = source.resolve()
        resolved_target = target.resolve()
    except OSError as exc:
        result.update({"status": "ERROR", "reason": str(exc)})
        return result
    if resolved_source == resolved_target:
        result.update({"status": "READY", "ready": True})
        return result
    result.update({
        "status": "CONFLICT",
        "reason": f"Runtime H3 path points to {resolved_target}, expected {resolved_source}",
    })
    return result


def ensure_h3_model_root_bridge(runtime_root: str | Path,
                                models_root: str | Path,
                                *, create: bool = True) -> dict[str, Any]:
    """Ensure the H3 loader's Runtime-local path reaches the selected root.

    This creates only a Windows directory junction. It never copies, moves, or
    deletes model files. A pre-existing real directory or a junction to another
    root is a hard conflict and is never overwritten automatically.
    """
    source = canonical_h3_model_root(models_root)
    target = h3_model_root_bridge_target(runtime_root)
    inspected = h3_model_root_bridge_status(runtime_root, models_root)
    if inspected["ready"]:
        return inspected
    if not source.is_dir():
        raise H3ModelRootBridgeError(f"H3 model root missing: {source}")
    if target.exists():
        raise H3ModelRootBridgeError(inspected.get("reason") or f"H3 bridge conflict: {target}")
    if not create:
        return inspected
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        raise H3ModelRootBridgeError("H3 model root junction requires Windows")
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(target), str(source)],
        capture_output=True, text=True, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "mklink failed").strip()
        raise H3ModelRootBridgeError(f"Could not create H3 model root junction: {detail}")
    verified = h3_model_root_bridge_status(runtime_root, models_root)
    if not verified["ready"]:
        raise H3ModelRootBridgeError(
            f"H3 model root junction was created but verification failed: {verified}"
        )
    verified["status"] = "REPAIRED"
    verified["created"] = True
    return verified


def canonical_h3_model_root(models_root: str | Path) -> Path:
    """Return the only H3 root derived from an explicitly selected Models Root."""
    root = Path(models_root).expanduser().resolve()
    if root.name.casefold() == H3_MODEL_ROOT_NAME.casefold():
        return root
    return root / H3_MODEL_ROOT_NAME


def h3_process_environment(models_root: str | Path | None) -> dict[str, str]:
    """Build child-process-only H3 path variables; never writes global env state."""
    if not models_root:
        return {}
    h3_root = canonical_h3_model_root(models_root)
    value = str(h3_root)
    return {H3_MODEL_ROOTS_ENV: value, H3_WEIGHTS_ROOTS_ENV: value}


def render_comfy_model_paths_config(models_root: str | Path) -> str:
    """Render ComfyUI's category map from the selected Models Root.

    The selected root is deliberately the only machine-specific input.  The
    result is a small generated config passed to the managed ComfyUI process;
    model files are never copied or downloaded by this function.
    """
    root = Path(models_root).expanduser().resolve().as_posix()
    return (
        "architect_video_studio_models:\n"
        f"  base_path: {root}\n"
        "  is_default: true\n"
        "  checkpoints: checkpoints\n"
        "  configs: configs\n"
        "  loras: loras\n"
        "  vae: vae\n"
        "  text_encoders: |\n"
        "    text_encoders\n"
        "    clip\n"
        "  diffusion_models: |\n"
        "    unet\n"
        "    diffusion_models\n"
        "  clip_vision: clip_vision\n"
        "  embeddings: embeddings\n"
        "  diffusers: diffusers\n"
        "  controlnet: |\n"
        "    controlnet\n"
        "    t2i_adapter\n"
    )


def write_comfy_model_paths_config(models_root: str | Path,
                                   destination: str | Path) -> Path:
    """Write the generated ComfyUI path map idempotently and return its path."""
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = render_comfy_model_paths_config(models_root)
    if not target.is_file() or target.read_text(encoding="utf-8") != content:
        target.write_text(content, encoding="utf-8", newline="\n")
    return target


def model_root_trace(models_root: str | Path | None,
                     environ: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Describe deterministic candidates without scanning legacy/test folders."""
    env = environ or os.environ
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    raw = str(env.get(H3_MODEL_ROOTS_ENV, ""))
    for item in raw.split(os.pathsep):
        if item.strip():
            path = Path(item).expanduser().resolve()
            key = str(path).casefold()
            if key not in seen:
                seen.add(key)
                candidates.append({"source": H3_MODEL_ROOTS_ENV,
                                   "path": str(path), "exists": path.is_dir()})

    canonical = None
    if models_root:
        canonical = canonical_h3_model_root(models_root)
        key = str(canonical).casefold()
        if key not in seen:
            candidates.append({"source": "active_models_root",
                               "path": str(canonical),
                               "exists": canonical.is_dir()})
    return {
        "requested": H3_MODEL_ROOT_NAME,
        "canonical_root": str(canonical) if canonical else "",
        "candidates": candidates,
        "weights_root_env": H3_WEIGHTS_ROOTS_ENV,
        "weights_root_configured": bool(env.get(H3_WEIGHTS_ROOTS_ENV)),
    }


_DRY_RUN = r'''
import json, os, sys
from pathlib import Path

native = Path({native!r})
os.chdir(native / "ComfyUI")
sys.path.insert(0, str(native / "ComfyUI" / "custom_nodes" / "ComfyUI_RH_MinMaxH3"))
from minimax_h3_nodes.runtime import components
from minimax_h3_nodes.api import _shared

selectors = {
    # The path-only production preflight must validate the AUTO/12GB-safe
    # contract, not the historical full-INT8 selectors used by old UI tabs.
    "transformer": ("minimax_h3_fl2va_pruned_int8_convrot.safetensors", "transformer"),
    "text_encoder": ("qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "text_encoder"),
    "video_vae": ("minimax_h3_video_vae_fp16.safetensors", "video_vae"),
    "audio_vae": ("minimax_h3_audio_vae_fp32.safetensors", "audio_vae"),
}

def _select_installed(preferred, alternatives, kind):
    roots = [Path(path) for path in components.list_h3_model_root_paths()]
    for name in (preferred, *alternatives):
        for root in roots:
            try:
                if any(
                    path.is_file() and ".download" not in path.parts
                    for path in root.rglob(name)
                ):
                    return name
            except OSError:
                continue
    return preferred

selectors["transformer"] = (
    _select_installed(
        selectors["transformer"][0],
        ("MiniMax-H3-FL2VA-int8_convrot.safetensors",),
        "transformer",
    ),
    "transformer",
)
out = {"candidates": [str(p) for p in components.list_h3_model_root_paths()]}
selector_t = selectors["transformer"][0]
component_hint = _shared._selector_to_component_dirname(
    selector_t, "transformer", "fl2va", model_root="MiniMax-H3")
partition_root, _info, _sigma = _shared._resolve_t2va_release(
    "MiniMax-H3", required_component=component_hint, required_files=("config.json",))
transformer, _ = _shared._resolve_selected_component(
    partition_root, selector_t, keys=("transformer", "dit"), label="DiT",
    partition="fl2va", required_files=("config.json",))
text_encoder, _ = _shared._resolve_selected_component(
    partition_root, selectors["text_encoder"][0],
    keys=("text_encoder", "qwen3vl", "qwen"), label="Text Encoder",
    partition="fl2va", required_files=("config.json",))
video_vae, _ = _shared._resolve_selected_vae_component(
    partition_root, selectors["video_vae"][0], kind="video_vae", partition="fl2va")
audio_vae, _ = _shared._resolve_selected_vae_component(
    partition_root, selectors["audio_vae"][0], kind="audio_vae", partition="fl2va")
tokenizer = components.resolve_component(
    partition_root, ("tokenizer", "processor", "text_encoder"),
    required_files=("tokenizer_config.json",))
processor = components.resolve_component(
    partition_root, ("processor", "text_encoder", "tokenizer"),
    required_files=("preprocessor_config.json",))
def _component_weight(component, name):
    candidates = [component / name, component / "source" / name]
    candidates.extend(path for path in component.rglob(name)
                      if ".download" not in path.parts)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(f"selected {name!r} is not inside {component}")

weights = {
    "transformer": str(_component_weight(transformer, selector_t)),
    "text_encoder": str(_component_weight(text_encoder, selectors["text_encoder"][0])),
    "video_vae": str(_component_weight(video_vae, selectors["video_vae"][0])),
    "audio_vae": str(_component_weight(audio_vae, selectors["audio_vae"][0])),
}
sidecar_sets = {
    "transformer": ["config.json"],
    "text_encoder": ["config.json"],
    "tokenizer": ["tokenizer_config.json", "vocab.json", "merges.txt"],
    "processor": ["preprocessor_config.json"],
    "video_vae": ["config.json"],
    "audio_vae": ["config.json"],
}
locations = {
    "root": partition_root,
    "transformer": transformer,
    "text_encoder": text_encoder,
    "video_vae": video_vae,
    "audio_vae": audio_vae,
    "tokenizer": tokenizer,
    "processor": processor,
}
missing = []
for label, names in sidecar_sets.items():
    base = locations[label]
    absent = [name for name in names if not (base / name).is_file()]
    if absent:
        missing.append({"component": label, "files": absent})
out.update({
    "root": str(partition_root.parent),
    "partition": str(partition_root),
    "components": {name: str(path) for name, path in locations.items()},
    "weights": weights,
    "sidecars": sidecar_sets,
    "missing": missing,
    "ready": not missing and all(Path(path).is_dir() for path in locations.values()),
})
print(json.dumps(out, ensure_ascii=False))
'''


def validate_h3_model_contract(native_root: str | Path | None,
                               models_root: str | Path | None,
                               environ: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Run the pinned resolver's path-only dry-run with CUDA hidden."""
    effective_env = dict(os.environ)
    if environ:
        effective_env.update({str(k): str(v) for k, v in environ.items()})
    effective_env.update(h3_process_environment(models_root))
    trace = model_root_trace(models_root, effective_env)
    bridge = h3_model_root_bridge_status(native_root, models_root)
    trace["bridge"] = bridge
    if not native_root or not models_root:
        return {**trace, "status": "NEEDS_PATH", "ready": False,
                "failure_code": "MODEL_PATH_FAILURE"}
    try:
        asset_contract = evaluate_h3_asset_contract(models_root, Path(__file__).resolve().parents[1])
    except (OSError, TypeError, ValueError) as exc:
        return {**trace, "status": "AUDIT_REQUIRED", "ready": False,
                "failure_code": "MODEL_PATH_FAILURE",
                "asset_contract": {"status": "INCOMPATIBLE_RUNTIME", "ready": False},
                "error": f"H3 asset contract could not be evaluated: {exc}"}
    if not asset_contract["ready"]:
        missing = ", ".join(asset_contract["missing"])
        return {**trace, "status": "CONFIGURATION_REQUIRED", "ready": False,
                "failure_code": "MODEL_PATH_FAILURE", "code": "INCOMPATIBLE_RUNTIME",
                "asset_contract": asset_contract,
                "error": f"required H3 assets are missing: {missing}"}
    python = Path(native_root).expanduser().resolve() / "python_embeded" / "python.exe"
    if not python.is_file():
        return {**trace, "status": "AUDIT_REQUIRED", "ready": False,
                "failure_code": "MODEL_PATH_FAILURE",
                "error": f"managed embedded Python missing: {python}"}
    child_env = effective_env
    child_env["CUDA_VISIBLE_DEVICES"] = ""
    child_env["PYTORCH_NO_CUDA_MEMORY_CACHING"] = "1"
    script = _DRY_RUN.replace("{native!r}", repr(str(Path(native_root).resolve())))
    try:
        completed = subprocess.run(
            [str(python), "-c", script],
            cwd=str(Path(native_root).resolve() / "ComfyUI"),
            env=child_env, capture_output=True, text=True, timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {**trace, "status": "AUDIT_REQUIRED", "ready": False,
                "failure_code": "MODEL_PATH_FAILURE", "error": str(exc)}
    lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
    payload: dict[str, Any] = {}
    if lines:
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError:
            payload = {}
    if completed.returncode != 0 or not payload:
        error = (completed.stderr or completed.stdout or "resolver dry-run failed").strip()
        return {**trace, "status": "CONFIGURATION_REQUIRED", "ready": False,
                "failure_code": "MODEL_PATH_FAILURE", "error": error[-4000:]}
    resolver_ready = bool(payload.get("ready"))
    ready = resolver_ready and bool(bridge["ready"])
    return {**trace, **payload,
            "asset_contract": asset_contract,
            "status": "READY" if ready else "CONFIGURATION_REQUIRED",
            "ready": ready and bool(bridge["ready"]),
            "resolver_ready": resolver_ready,
            "failure_code": "" if ready else "MODEL_PATH_FAILURE"}


__all__ = [
    "H3_MODEL_ROOTS_ENV", "H3_WEIGHTS_ROOTS_ENV", "H3_MODEL_ROOT_NAME",
    "COMFY_MODEL_PATHS_FILENAME", "H3ModelRootBridgeError",
    "canonical_h3_model_root", "h3_model_root_bridge_target",
    "h3_model_root_bridge_status", "ensure_h3_model_root_bridge",
    "h3_process_environment", "render_comfy_model_paths_config",
    "write_comfy_model_paths_config", "model_root_trace",
    "validate_h3_model_contract",
]
