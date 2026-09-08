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

    nodes_by_id = {str(node.get("id")): node for node in result["nodes"]}

    # The API snapshot is authoritative for connections. Native Golden files
    # can be older than the API graph (the 04_Drone_Aerial template omitted
    # the two VAE decode links), so rebuild the top-level link table from every
    # API reference while preserving existing link ids where possible.
    existing_links: dict[tuple[str, int, str, int], list[Any]] = {}
    next_link_id = 1
    for link in result.get("links") or []:
        if not isinstance(link, list) or len(link) < 5:
            continue
        link_id, origin_id, origin_slot, target_id, target_slot = link[:5]
        try:
            key = (str(origin_id), int(origin_slot), str(target_id), int(target_slot))
            existing_links[key] = link
            next_link_id = max(next_link_id, int(link_id) + 1)
        except (TypeError, ValueError):
            continue

    rebuilt_links: list[list[Any]] = []
    for target_id, api_node in api_workflow.items():
        target = nodes_by_id.get(str(target_id))
        if target is None:
            raise WorkflowHandoffError(f"API node {target_id} is missing from UI")
        target_inputs = target.get("inputs") or []
        input_slots = {
            str(slot.get("name")): index
            for index, slot in enumerate(target_inputs)
            if isinstance(slot, Mapping) and slot.get("name") is not None
        }
        for input_name, value in (api_node.get("inputs") or {}).items():
            if not (isinstance(value, list) and len(value) == 2):
                continue
            origin_id = str(value[0])
            try:
                origin_slot = int(value[1])
            except (TypeError, ValueError) as exc:
                raise WorkflowHandoffError(
                    f"API link for {target_id}.{input_name} has an invalid slot") from exc
            if origin_id not in nodes_by_id or origin_slot < 0:
                raise WorkflowHandoffError(
                    f"API link for {target_id}.{input_name} references an invalid origin")
            if input_name not in input_slots:
                raise WorkflowHandoffError(
                    f"UI node {target_id} has no input slot {input_name}")
            target_slot = input_slots[input_name]
            key = (origin_id, origin_slot, str(target_id), target_slot)
            old = existing_links.get(key)
            if old is not None:
                link_id = int(old[0])
                link_type = old[5] if len(old) > 5 else "*"
            else:
                link_id = next_link_id
                next_link_id += 1
                origin = nodes_by_id.get(origin_id)
                origin_outputs = origin.get("outputs") if origin else []
                link_type = "*"
                if isinstance(origin_outputs, list) and origin_slot < len(origin_outputs):
                    link_type = origin_outputs[origin_slot].get("type", "*")
                if link_type == "*" and target_slot < len(target_inputs):
                    link_type = target_inputs[target_slot].get("type", "*")
            rebuilt_links.append([
                link_id, int(origin_id), origin_slot, int(target_id),
                target_slot, link_type,
            ])
    result["links"] = rebuilt_links
    result["last_link_id"] = max((int(link[0]) for link in rebuilt_links), default=0)

    # Some historical Native Golden exports carried stale per-node link
    # fields while their top-level ``links`` table was correct. ComfyUI uses
    # the top-level table during configure; keeping both representations in
    # sync prevents a frontend-version-dependent edge/link mismatch.
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
