"""Static contracts for isolated Advanced Product Layer workflows.

Advanced graphs are deliberately outside the production workflow registry.
This module validates an experimental API/UI pair without submitting jobs or
changing the five Golden V1 assets.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from apps.architect_video_studio.mock_api.workflow_handoff import build_ui_workflow
from runtime.adapters.runtime_adapter import REPO_ROOT


ADVANCED_REGISTRY_PATH = REPO_ROOT / "configs" / "advanced_workflow_registry.json"
ADVANCED_WORKFLOW_ID = "06_Advanced_Architecture_Camera_V2"
ADVANCED_API_PATH = REPO_ROOT / "production_workflows" / "advanced" / f"{ADVANCED_WORKFLOW_ID}.json"
ADVANCED_UI_PATH = REPO_ROOT / "workflows" / f"{ADVANCED_WORKFLOW_ID}_NATIVE_GOLDEN.json"
SUPPORTED_ADVANCED_NODE_TYPES = {
    "LoadImage", "CLIPLoader", "UNETLoader", "VAELoader",
    "MiniMaxH3ImageToVideo", "KSamplerSelect", "BasicScheduler",
    "RandomNoise", "BasicGuider", "SamplerCustomAdvanced", "VAEDecode",
    "VAEDecodeAudio", "CreateVideo", "SaveVideo",
}


class AdvancedWorkflowError(ValueError):
    """Raised when an experimental graph violates its static contract."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdvancedWorkflowError(f"workflow unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise AdvancedWorkflowError(f"workflow root must be an object: {path.name}")
    return value


def load_advanced_registry() -> dict[str, Any]:
    registry = _load_json(ADVANCED_REGISTRY_PATH)
    workflows = registry.get("workflows")
    if not isinstance(workflows, dict) or ADVANCED_WORKFLOW_ID not in workflows:
        raise AdvancedWorkflowError("advanced workflow registry entry missing")
    return registry


def load_advanced_api_workflow() -> dict[str, Any]:
    return _load_json(ADVANCED_API_PATH)


def load_advanced_ui_workflow() -> dict[str, Any]:
    return _load_json(ADVANCED_UI_PATH)


def canonical_advanced_workflow_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _api_links(payload: Mapping[str, Any]) -> list[tuple[str, int, str, str]]:
    links: list[tuple[str, int, str, str]] = []
    for target_id, node in payload.items():
        if not isinstance(node, Mapping):
            continue
        for input_name, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and len(value) == 2:
                try:
                    links.append((str(value[0]), int(value[1]), str(target_id), str(input_name)))
                except (TypeError, ValueError) as exc:
                    raise AdvancedWorkflowError("API link slot is invalid") from exc
    return links


def validate_advanced_workflow(*, object_info: Mapping[str, Any] | None = None) -> dict[str, Any]:
    registry = load_advanced_registry()
    entry = registry["workflows"][ADVANCED_WORKFLOW_ID]
    api = load_advanced_api_workflow()
    ui = load_advanced_ui_workflow()
    errors: list[str] = []
    expected_ids = {str(index) for index in range(1, 16)}
    if set(map(str, api)) != expected_ids:
        errors.append("API node IDs must be 1..15")
    types = {str(node.get("class_type")) for node in api.values() if isinstance(node, Mapping)}
    unknown = sorted(types - SUPPORTED_ADVANCED_NODE_TYPES)
    if unknown:
        errors.append("unsupported node types: " + ", ".join(unknown))
    if len(api) != 15:
        errors.append(f"node count {len(api)} != 15")
    links = _api_links(api)
    required_links = {
        ("4", 0, "12", "vae"),
        ("5", 0, "13", "vae"),
    }
    if not required_links.issubset(set(links)):
        errors.append("required video/audio VAE decode links are incomplete")
    if len(links) != 18:
        errors.append(f"semantic link count {len(links)} != 18")
    if entry.get("production_selector_enabled") is not False:
        errors.append("experimental workflow must remain outside production selector")
    if entry.get("classification") not in (None, "EXPERIMENTAL_V2"):
        errors.append("invalid experimental classification")
    if object_info is not None:
        missing = sorted(types - set(object_info))
        if missing:
            errors.append("missing live Comfy node types: " + ", ".join(missing))
    try:
        rebuilt = build_ui_workflow(ADVANCED_WORKFLOW_ID, api,
                                    workflow_hash=canonical_advanced_workflow_sha256(api))
    except (ValueError, KeyError, OSError) as exc:
        errors.append(f"UI reconstruction failed: {exc}")
        rebuilt = {}
    ui_nodes = ui.get("nodes") if isinstance(ui.get("nodes"), list) else []
    if {str(node.get("id")) for node in ui_nodes if isinstance(node, Mapping)} != expected_ids:
        errors.append("UI node IDs do not match API")
    if len(ui.get("links") or []) != 18:
        errors.append("UI template must contain 18 links including both VAE decode paths")
    if rebuilt and len(rebuilt.get("links") or []) != 18:
        errors.append("rebuilt UI workflow does not contain 18 links")
    return {
        "workflow_id": ADVANCED_WORKFLOW_ID,
        "ready": not errors,
        "errors": errors,
        "classification": "EXPERIMENTAL_V2",
        "node_count": len(api),
        "link_count": len(links),
        "workflow_sha256": canonical_advanced_workflow_sha256(api),
        "ui_rebuilt": bool(rebuilt),
    }


def comparable_api_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return immutable copies for the A/B change-budget test/report."""
    golden_path = REPO_ROOT / "production_workflows" / "golden" / "04_Drone_Aerial.json"
    golden = _load_json(golden_path)
    advanced = load_advanced_api_workflow()
    return copy.deepcopy(golden), copy.deepcopy(advanced)


__all__ = [
    "ADVANCED_API_PATH", "ADVANCED_REGISTRY_PATH", "ADVANCED_UI_PATH",
    "ADVANCED_WORKFLOW_ID", "AdvancedWorkflowError", "canonical_advanced_workflow_sha256",
    "comparable_api_pair", "load_advanced_api_workflow", "load_advanced_registry",
    "load_advanced_ui_workflow", "validate_advanced_workflow",
]
