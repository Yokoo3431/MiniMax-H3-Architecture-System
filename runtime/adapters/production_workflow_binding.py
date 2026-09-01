"""Project-owned production workflow binding for the frozen H3 contract.

This module builds ComfyUI API payloads without submitting them.  It never
reads browser history and never mutates workflow JSON.  The small, validated
RH H3 graph is used as the payload template while the registry remains the
source of truth for the five user-facing workflow identities.
"""

from __future__ import annotations

import json
import os
import shutil
import hashlib
from pathlib import Path
from typing import Any, Mapping

from runtime.adapters.runtime_adapter import REPO_ROOT
from runtime.support_layer import FROZEN_NODE_NAMES
from runtime.h3_generation_parameters import normalize_generation_parameters
from runtime.h3_low_memory_profiles import (
    AUTO, model_selection, resolve_available_selection, select_profile,
    validate_profile_loader_contract,
)


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


def canonical_workflow_sha256(payload: Mapping[str, Any]) -> str:
    """Hash the exact API graph that is about to cross the /prompt boundary."""
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _link(node: str, output: int = 0) -> list:
    return [str(node), output]


def _model_contract(profile: str = "COMPATIBILITY", *,
                    gpu_vram_gb: Any = None,
                    system_ram_gb: Any = None) -> dict:
    baseline = json.loads((REPO_ROOT / "configs" / "native_production_baseline.json").read_text(encoding="utf-8"))
    selection = model_selection(profile, gpu_vram_gb=gpu_vram_gb,
                                system_ram_gb=system_ram_gb)
    contract = {key: value.get("filename")
                for key, value in baseline.get("models", {}).items()}
    contract.update({
        "dit": selection["transformer"],
        "text_encoder": selection["text_encoder"],
        "video_vae": selection["video_vae"],
        "audio_vae": selection["audio_vae"],
    })
    return contract


def production_model_contract(profile: str = "COMPATIBILITY", *,
                              gpu_vram_gb: Any = None,
                              system_ram_gb: Any = None) -> dict:
    """Return the frozen project model filenames for audit/trace metadata."""
    return dict(_model_contract(profile, gpu_vram_gb=gpu_vram_gb,
                                system_ram_gb=system_ram_gb))


def _request_model_selection(request: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    requested = (request.get("h3_profile") or request.get("model_profile")
                 or request.get("hardware_profile") or AUTO)
    hardware = request.get("hardware") or {}
    vram = request.get("gpu_vram_gb", hardware.get("gpu_vram_gb"))
    ram = request.get("system_ram_gb", hardware.get("system_ram_gb"))
    selected = select_profile(requested=str(requested), gpu_vram_gb=vram,
                              system_ram_gb=ram)
    selection = model_selection(selected, gpu_vram_gb=vram,
                                system_ram_gb=ram)
    return selected, resolve_available_selection(
        selection,
        request.get("models_root") or os.environ.get("H3_MODELS_ROOT")
        or os.environ.get("MINIMAX_H3_MODEL_ROOTS"),
    )


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
    """Bind the registered Golden API graph without rebuilding topology."""
    if workflow_id not in CANONICAL_WORKFLOWS:
        raise ProductionBindingError(f"unknown production workflow: {workflow_id}")
    try:
        from runtime.adapters.golden_workflow_binding import bind_golden_workflow
        return bind_golden_workflow(request, workflow_id)
    except ProductionBindingError:
        raise
    except (ValueError, KeyError, OSError) as exc:
        raise ProductionBindingError(str(exc)) from exc


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
