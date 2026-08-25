"""Project-owned production workflow binding for the frozen H3 contract.

This module builds ComfyUI API payloads without submitting them.  It never
reads browser history and never mutates workflow JSON.  The small, validated
RH H3 graph is used as the payload template while the registry remains the
source of truth for the five user-facing workflow identities.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from runtime.adapters.runtime_adapter import REPO_ROOT
from runtime.support_layer import FROZEN_NODE_NAMES
from runtime.h3_generation_parameters import normalize_generation_parameters


REGISTRY_PATH = REPO_ROOT / "configs" / "production_workflow_registry.json"
TEMPLATE_PATH = REPO_ROOT / "workflows" / "04_Drone_Aerial.json"
CANONICAL_WORKFLOWS = tuple([
    "01_Exterior_Hero", "02_Day_Night_Transition", "03_Material_Detail",
    "04_Drone_Aerial", "05_Slow_Walkthrough",
])

_UI_MODEL_INPUTS = {
    "LoadImage": ("image", 0),
    "UNETLoader": ("unet_name", 0),
    "CLIPLoader": ("clip_name", 0),
    "VAELoader": ("vae_name", 0),
}


class ProductionBindingError(ValueError):
    """Raised when a production payload cannot satisfy the frozen contract."""


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _link(node: str, output: int = 0) -> list:
    return [str(node), output]


def _model_contract() -> dict:
    baseline = json.loads((REPO_ROOT / "configs" / "native_production_baseline.json").read_text(encoding="utf-8"))
    return {key: value.get("filename") for key, value in baseline.get("models", {}).items()}


def production_model_contract() -> dict:
    """Return the frozen project model filenames for audit/trace metadata."""
    return dict(_model_contract())


def _object_info_options(object_info: Mapping[str, Any], node_type: str,
                         input_name: str) -> list[str]:
    spec = object_info.get(node_type) or {}
    required = (spec.get("input") or {}).get("required") or {}
    value = required.get(input_name)
    if isinstance(value, list) and value and isinstance(value[0], list):
        return [str(item) for item in value[0]]
    return []


def validate_ui_workflow_model_bindings(workflow_path: str | Path,
                                        object_info: Mapping[str, Any]) -> dict:
    """Validate saved workflow widget values against live ComfyUI enums.

    ComfyUI returns category-relative filenames (not ``category/name`` paths)
    for these widgets.  This catches stale values before a user opens or
    submits a workflow.
    """
    path = Path(workflow_path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"workflow": path.name, "ready": False,
                "errors": [f"workflow unreadable: {exc}"]}
    errors: list[dict[str, str]] = []
    for node in document.get("nodes", []):
        node_type = str(node.get("type") or "")
        contract = _UI_MODEL_INPUTS.get(node_type)
        if contract is None:
            continue
        input_name, widget_index = contract
        widget_values = node.get("widgets_values") or []
        actual = str(widget_values[widget_index]) if len(widget_values) > widget_index else ""
        options = _object_info_options(object_info, node_type, input_name)
        if node_type not in object_info:
            errors.append({"node": node_type, "input": input_name,
                           "value": actual, "reason": "node_not_registered"})
        elif not options or actual not in options:
            errors.append({"node": node_type, "input": input_name,
                           "value": actual,
                           "reason": "value_not_in_live_comfyui_enum"})
    return {"workflow": path.name, "ready": not errors, "errors": errors}


def validate_all_ui_workflow_model_bindings(object_info: Mapping[str, Any]) -> dict:
    results = {}
    for workflow_id in CANONICAL_WORKFLOWS:
        results[workflow_id] = validate_ui_workflow_model_bindings(
            REPO_ROOT / "workflows" / f"{workflow_id}.json", object_info)
    return {"ready": all(item["ready"] for item in results.values()),
            "workflows": results}


def build_production_payload(request: Mapping[str, Any], workflow_id: str) -> dict:
    registry = load_registry().get("workflows", {})
    entry = registry.get(workflow_id)
    if not entry or workflow_id not in CANONICAL_WORKFLOWS:
        raise ProductionBindingError(f"unknown production workflow: {workflow_id}")
    refs = list(request.get("reference_assets") or [])
    mode = entry["input_mode"]
    expected_refs = 2 if mode == "FL2VA" else 1
    if len(refs) != expected_refs:
        raise ProductionBindingError(f"{workflow_id} requires {expected_refs} reference asset(s)")
    if not TEMPLATE_PATH.is_file():
        raise ProductionBindingError(f"production payload template missing: {TEMPLATE_PATH}")

    try:
        params = normalize_generation_parameters(request.get("generation_parameters"))
    except ValueError as exc:
        raise ProductionBindingError(str(exc)) from exc
    width, height = params["width"], params["height"]
    fps = float(params["fps"])
    duration = float(params["duration"])
    seed = int(params["seed"])
    prompt = str((request.get("prompt_payload") or {}).get("prompt") or "")
    names = [Path(str(ref.get("path_or_ref") or "reference.png")).name for ref in refs]
    # This is an API-format graph, not a saved UI workflow.  Node classes and
    # links are explicit so a browser graph cannot influence Studio execution.
    payload = {
        "1": {"class_type": "LoadImage", "inputs": {"image": names[0]}},
        "2": {"class_type": "RHMiniMaxH3ModelLoader", "inputs": {
            "partition": "FL2VA", "model_root": "MiniMax-H3", "dtype": "auto",
            "transformer_path": "MiniMax-H3-FL2VA-int8_convrot.safetensors",
        }},
        "3": {"class_type": "RHMiniMaxH3TextEncoderLoader", "inputs": {
            "model_root": "MiniMax-H3", "dtype": "auto",
            "text_encoder_path": "qwen3-vl-32b-int8_convrot.safetensors",
        }},
        "4": {"class_type": "RHMiniMaxH3VAELoader", "inputs": {
            "model_root": "MiniMax-H3",
            "video_vae_path": "MiniMax-H3-video_vae.safetensors",
            "audio_vae_path": "MiniMax-H3-audio_vae.safetensors",
        }},
        "5": {"class_type": "RHMiniMaxH3FL2VAFirstFrameCondition", "inputs": {
            "first_frame": _link("1"),
        }},
        "6": {"class_type": "RHMiniMaxH3FL2VATarget", "inputs": {
            "keyframes": _link("5"), "aspect_ratio": params["aspect_ratio"],
            "duration_seconds": duration, "width": width, "height": height,
        }},
        "7": {"class_type": "RHMiniMaxH3FL2VAEncode", "inputs": {
            "h3_text_encoder": _link("3"), "h3_vae_bundle": _link("4"),
            "target": _link("6"), "keyframes": _link("5"), "prompt": prompt,
        }},
        "8": {"class_type": "RHMiniMaxH3EmptyAVLatent", "inputs": {
            "target": _link("6"),
        }},
        "9": {"class_type": "RHMiniMaxH3DualSigmaSampler", "inputs": {
            "h3_model": _link("2"), "conditioning": _link("7"),
            "av_latent": _link("8"), "seed": seed,
            "sigma_points": params["sigma_points"],
            "video_shift": 12.0, "audio_shift": 3.0, "accel": params["accel"],
            "denoise_video": True, "sampler_mode": params["sampler_mode"],
            "cache_dit_rdt": params["cache_dit_rdt"],
            "cache_dit_mc": params["cache_dit_mc"],
            "cache_dit_warmup": params["cache_dit_warmup"],
            "velocity_stride": params["velocity_stride"],
            "allow_accel_with_res_multistep": params["allow_accel_with_res_multistep"],
        }},
        "10": {"class_type": "RHMiniMaxH3DecodeAV", "inputs": {
            "h3_vae_bundle": _link("4"), "sampled_av_latent": _link("9"),
        }},
        "11": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": _link("10"), "frame_rate": fps, "loop_count": 0,
            "filename_prefix": f"video/{workflow_id}_C2B_{seed}",
            "format": "video/h264-mp4", "pingpong": False, "save_output": True,
        }},
    }
    if mode == "FL2VA":
        payload["12"] = {"class_type": "LoadImage", "inputs": {"image": names[1]}}
        payload["5"]["inputs"]["last_frame"] = _link("12")
    return payload


def unknown_node_types(payload: Mapping[str, Any], object_info: Mapping[str, Any]) -> list[str]:
    return sorted({node.get("class_type") for node in payload.values()
                   if node.get("class_type") not in object_info})


def validate_production_payload(payload: Mapping[str, Any], object_info: Mapping[str, Any]) -> dict:
    unknown = unknown_node_types(payload, object_info)
    present = {node.get("class_type") for node in payload.values()}
    return {
        "unknown_node_types": unknown,
        "missing_required_nodes": [],
        "payload_node_types": sorted(present),
        "ready": not unknown,
    }


def validate_frozen_capability(object_info: Mapping[str, Any]) -> dict:
    missing = sorted(set(FROZEN_NODE_NAMES) - set(object_info))
    return {"missing_required_nodes": missing, "ready": not missing}


def build_all_production_payloads(requests: Mapping[str, Mapping[str, Any]]) -> dict:
    return {workflow_id: build_production_payload(requests[workflow_id], workflow_id)
            for workflow_id in CANONICAL_WORKFLOWS}


def deploy_production_collection(runtime_root: Path) -> list[Path]:
    """Refresh only the five named files in the isolated production collection.

    This deliberately refuses validation roots and never touches archive/user
    workflow directories.  The caller must supply the explicitly selected
    active Runtime; there is no folder discovery or fallback.
    """
    root = Path(runtime_root).resolve()
    if "validation" in {part.lower() for part in root.parts}:
        raise ProductionBindingError("validation Runtime cannot receive production workflows")
    registry = load_registry()["workflows"]
    target = root / "ComfyUI" / "user" / "default" / "workflows" / "ARCHITECTURE_PRODUCTION"
    target.mkdir(parents=True, exist_ok=True)
    # R2A previously placed this exact source under a diagnostic filename in
    # the same dedicated collection.  Remove only that known duplicate; user
    # history and ARCHIVE_RC2 are outside this target and untouched.
    stale = target / "04_Drone_Aerial_GOLDEN.json"
    golden_source = REPO_ROOT / "workflows/04_Drone_Aerial.json"
    if stale.is_file() and golden_source.is_file() and stale.read_bytes() == golden_source.read_bytes():
        stale.unlink()
    deployed: list[Path] = []
    for workflow_id in CANONICAL_WORKFLOWS:
        source = REPO_ROOT / registry[workflow_id]["canonical_source"]
        destination = target / f"{workflow_id}.json"
        if not source.is_file():
            raise ProductionBindingError(f"canonical workflow source missing: {source}")
        shutil.copy2(source, destination)
        deployed.append(destination)
    return deployed


__all__ = [
    "CANONICAL_WORKFLOWS", "ProductionBindingError", "build_all_production_payloads",
    "build_production_payload", "deploy_production_collection", "load_registry", "unknown_node_types",
    "production_model_contract",
    "validate_ui_workflow_model_bindings", "validate_all_ui_workflow_model_bindings",
    "validate_frozen_capability", "validate_production_payload",
]
