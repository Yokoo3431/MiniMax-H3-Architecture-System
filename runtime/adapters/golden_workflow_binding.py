"""Single-source Golden workflow loading and value-only binding.

Golden files are ComfyUI API graphs captured from the validated Native H3
path.  This module deliberately does not create nodes, links, or loader
topology.  It only copies a registered graph and changes the small set of
request values allowed by the registry.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from runtime.adapters.runtime_adapter import REPO_ROOT
from runtime.yaml_compat import safe_load
from runtime.h3_generation_parameters import normalize_generation_parameters


REGISTRY_PATH = REPO_ROOT / "production_workflows" / "golden_workflow_registry.yaml"
GOLDEN_ROOT = REPO_ROOT / "production_workflows" / "golden"


class GoldenWorkflowError(ValueError):
    """A Golden workflow or value-only binding violates its contract."""


def load_golden_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.is_file():
        raise GoldenWorkflowError(f"Golden workflow registry missing: {REGISTRY_PATH}")
    value = safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    workflows = value.get("workflows") if isinstance(value, dict) else None
    if not isinstance(workflows, dict):
        raise GoldenWorkflowError("Golden workflow registry has no workflows mapping")
    return value


def golden_entry(workflow_id: str) -> dict[str, Any]:
    entry = load_golden_registry().get("workflows", {}).get(workflow_id)
    if not isinstance(entry, dict):
        raise GoldenWorkflowError(f"Golden workflow is not registered: {workflow_id}")
    return entry


def golden_path(workflow_id: str) -> Path:
    path = REPO_ROOT / str(golden_entry(workflow_id)["golden_path"])
    if not path.is_file():
        raise GoldenWorkflowError(f"Golden workflow file missing: {path}")
    return path


def _is_link(value: Any) -> bool:
    return (isinstance(value, list) and len(value) == 2
            and isinstance(value[0], str) and isinstance(value[1], int))


def golden_structure_hash(payload: Mapping[str, Any]) -> str:
    """Hash node IDs/types and graph links, excluding mutable scalar values."""
    structure = []
    for node_id in sorted(payload, key=str):
        node = payload[node_id]
        inputs = node.get("inputs") or {}
        links = {key: value for key, value in sorted(inputs.items())
                 if _is_link(value)}
        structure.append({"id": str(node_id), "class_type": node.get("class_type"),
                          "links": links})
    encoded = json.dumps(structure, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _node(payload: dict[str, Any], class_type: str) -> tuple[str, dict[str, Any]]:
    matches = [(str(node_id), node) for node_id, node in payload.items()
               if node.get("class_type") == class_type]
    if len(matches) != 1:
        raise GoldenWorkflowError(
            f"Golden graph must contain exactly one {class_type}; got {len(matches)}")
    return matches[0]


def _load_images(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return sorted([(str(node_id), node) for node_id, node in payload.items()
                   if node.get("class_type") == "LoadImage"],
                  key=lambda item: int(item[0]) if item[0].isdigit() else item[0])


def validate_golden_workflow(workflow_id: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    entry = golden_entry(workflow_id)
    graph = dict(payload) if payload is not None else json.loads(
        golden_path(workflow_id).read_text(encoding="utf-8"))
    expected_refs = int(entry["required_reference_count"])
    images = _load_images(graph)
    errors: list[str] = []
    if len(images) != expected_refs:
        errors.append(f"reference node count {len(images)} != {expected_refs}")
    if entry.get("mode") == "FL2VA" and expected_refs != 2:
        errors.append("FL2VA Golden must require first and last references")
    if entry.get("mode") == "I2VA" and expected_refs != 1:
        errors.append("I2VA Golden must require exactly one reference")
    required = {"LoadImage", "CLIPLoader", "UNETLoader", "VAELoader",
                "MiniMaxH3ImageToVideo", "SaveVideo"}
    present = {node.get("class_type") for node in graph.values()}
    missing = sorted(required - present)
    if missing:
        errors.append("missing node types: " + ", ".join(missing))
    if "RHMiniMaxH3TextEncoderLoader" in present:
        errors.append("RH text encoder loader is forbidden in Native Golden graph")
    expected_structure = entry.get("base_structure_hash")
    actual_structure = golden_structure_hash(graph)
    if expected_structure and expected_structure != actual_structure:
        errors.append(f"structure hash {actual_structure} != {expected_structure}")
    return {"workflow_id": workflow_id, "ready": not errors,
            "errors": errors, "node_count": len(graph),
            "structure_hash": actual_structure,
            "base_sha256": canonical_payload_sha256(graph)}


def bind_golden_workflow(request: Mapping[str, Any], workflow_id: str) -> dict[str, Any]:
    entry = golden_entry(workflow_id)
    graph = json.loads(golden_path(workflow_id).read_text(encoding="utf-8"))
    validation = validate_golden_workflow(workflow_id, graph)
    if not validation["ready"]:
        raise GoldenWorkflowError("; ".join(validation["errors"]))

    refs = list(request.get("reference_assets") or [])
    expected_refs = int(entry["required_reference_count"])
    if len(refs) != expected_refs:
        raise GoldenWorkflowError(
            f"{workflow_id} requires {expected_refs} reference asset(s); got {len(refs)}")
    params = normalize_generation_parameters(request.get("generation_parameters"))
    prompt_payload = request.get("prompt_payload") or {}
    prompt = str(prompt_payload.get("prompt") or "").strip()
    if not prompt:
        raise GoldenWorkflowError("current optimized prompt is empty")
    ref_names = [Path(str(ref.get("path_or_ref") or "reference.png")).name
                 for ref in refs]
    images = _load_images(graph)
    for index, (_, node) in enumerate(images):
        node.setdefault("inputs", {})["image"] = ref_names[index]

    h3_id, h3 = _node(graph, "MiniMaxH3ImageToVideo")
    h3_inputs = h3.setdefault("inputs", {})
    h3_inputs.update({"prompt": prompt, "width": params["width"],
                      "height": params["height"],
                      "length": int(round(float(params["duration"]) * params["fps"])) + 11})
    noise_id, noise = _node(graph, "RandomNoise")
    noise.setdefault("inputs", {})["noise_seed"] = int(params["seed"])
    sampler_id, sampler = _node(graph, "KSamplerSelect")
    sampler.setdefault("inputs", {})["sampler_name"] = params["sampler_mode"]
    scheduler_id, scheduler = _node(graph, "BasicScheduler")
    scheduler.setdefault("inputs")["steps"] = int(params["steps"])
    video_id, video = _node(graph, "CreateVideo")
    video.setdefault("inputs", {})["fps"] = float(params["fps"])
    save_id, save = _node(graph, "SaveVideo")
    save.setdefault("inputs", {})["filename_prefix"] = (
        f"video/{workflow_id}_C2B_{int(params['seed'])}")

    after = validate_golden_workflow(workflow_id, graph)
    if not after["ready"]:
        raise GoldenWorkflowError("bound Golden graph invalid: " + "; ".join(after["errors"]))
    if after["structure_hash"] != validation["structure_hash"]:
        raise GoldenWorkflowError("GOLDEN_WORKFLOW_STRUCTURE_MUTATION")
    return graph


__all__ = ["GoldenWorkflowError", "bind_golden_workflow", "canonical_payload_sha256",
           "golden_entry", "golden_path", "golden_structure_hash",
           "load_golden_registry", "validate_golden_workflow"]
