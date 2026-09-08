"""Build a ComfyUI UI workflow from an immutable Job API snapshot.

Jobs persist the exact API graph sent to ``/prompt``. ComfyUI's graph editor
needs the UI workflow shape (nodes, links, and widget values), so the handoff
uses the matching Native Golden UI template for topology and copies only the
snapshot's actual inputs into it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from ._paths import REPO_ROOT


_WIDGET_INPUTS: dict[str, dict[str, int]] = {
    "LoadImage": {"image": 0},
    "CLIPLoader": {"clip_name": 0, "type": 1},
    "UNETLoader": {"unet_name": 0, "weight_dtype": 1},
    "VAELoader": {"vae_name": 0},
    "MiniMaxH3ImageToVideo": {
        "prompt": 0, "width": 1, "height": 2, "length": 3,
    },
    "KSamplerSelect": {"sampler_name": 0},
    "BasicScheduler": {"scheduler": 0, "steps": 1, "denoise": 2},
    "RandomNoise": {"noise_seed": 0},
    "CreateVideo": {"fps": 0},
    "SaveVideo": {"filename_prefix": 0, "format": 1, "codec": 2},
}


class WorkflowHandoffError(ValueError):
    """Raised when a Job snapshot cannot be represented as a UI workflow."""


def _template_path(workflow_id: str) -> Path:
    native = REPO_ROOT / "workflows" / f"{workflow_id}_NATIVE_GOLDEN.json"
    if native.is_file():
        return native
    fallback = REPO_ROOT / "workflows" / f"{workflow_id}.json"
    if fallback.is_file():
        return fallback
    raise WorkflowHandoffError(f"UI workflow template missing: {workflow_id}")


def build_ui_workflow(workflow_id: str, api_workflow: Mapping[str, Any], *,
                      job_id: str = "", snapshot_id: str = "",
                      workflow_hash: str = "") -> dict[str, Any]:
    """Return a UI graph whose serialized prompt matches ``api_workflow``."""
    if not isinstance(api_workflow, Mapping) or not api_workflow:
        raise WorkflowHandoffError("Job workflow snapshot is empty")
    template = json.loads(_template_path(workflow_id).read_text(encoding="utf-8"))
    nodes = template.get("nodes")
    if not isinstance(nodes, list):
        raise WorkflowHandoffError("UI workflow template has no nodes")

    expected_ids = {str(key) for key in api_workflow}
    template_ids = {str(node.get("id")) for node in nodes}
    if expected_ids != template_ids:
        raise WorkflowHandoffError(
            f"workflow topology mismatch: API={sorted(expected_ids)} "
            f"UI={sorted(template_ids)}")

    result = copy.deepcopy(template)
    for node in result["nodes"]:
        node_id = str(node.get("id"))
        api_node = api_workflow.get(node_id)
        if not isinstance(api_node, Mapping):
            raise WorkflowHandoffError(f"API node {node_id} is missing")
        node_type = str(node.get("type") or "")
        if str(api_node.get("class_type") or "") != node_type:
            raise WorkflowHandoffError(
                f"node {node_id} type mismatch: UI={node_type} "
                f"API={api_node.get('class_type')}")
        inputs = api_node.get("inputs")
        if not isinstance(inputs, Mapping):
            raise WorkflowHandoffError(f"API node {node_id} inputs are invalid")
        values = node.get("widgets_values")
        if not isinstance(values, list):
            values = []
        values = list(values)
        for input_name, index in _WIDGET_INPUTS.get(node_type, {}).items():
            if input_name in inputs:
                while len(values) <= index:
                    values.append(None)
                values[index] = copy.deepcopy(inputs[input_name])
        node["widgets_values"] = values

    # Some historical Native Golden exports carried stale per-node link
    # fields while their top-level ``links`` table was correct. ComfyUI uses
    # the top-level table during configure; keeping both representations in
    # sync prevents a frontend-version-dependent edge/link mismatch.
    nodes_by_id = {str(node.get("id")): node for node in result["nodes"]}
    for node in result["nodes"]:
        for input_slot in node.get("inputs") or []:
            input_slot["link"] = None
        for output_slot in node.get("outputs") or []:
            output_slot["links"] = []
    for link in result.get("links") or []:
        if not isinstance(link, list) or len(link) < 5:
            raise WorkflowHandoffError("UI workflow contains an invalid link")
        link_id, origin_id, origin_slot, target_id, target_slot = link[:5]
        origin = nodes_by_id.get(str(origin_id))
        target = nodes_by_id.get(str(target_id))
        if origin is None or target is None:
            raise WorkflowHandoffError(f"UI workflow link {link_id} references a missing node")
        target_inputs = target.setdefault("inputs", [])
        while len(target_inputs) <= int(target_slot):
            target_inputs.append({"name": f"input_{target_slot}", "type": "*", "link": None})
        target_inputs[int(target_slot)]["link"] = link_id
        origin_outputs = origin.setdefault("outputs", [])
        while len(origin_outputs) <= int(origin_slot):
            origin_outputs.append({"name": f"output_{origin_slot}", "type": "*", "links": []})
        origin_outputs[int(origin_slot)].setdefault("links", []).append(link_id)

    extra = dict(result.get("extra") or {})
    extra["architect_video_studio_h3"] = {
        "job_id": str(job_id),
        "snapshot_id": str(snapshot_id),
        "workflow_id": str(workflow_id),
        "workflow_hash": str(workflow_hash),
    }
    result["extra"] = extra
    return result


__all__ = ["WorkflowHandoffError", "build_ui_workflow"]
