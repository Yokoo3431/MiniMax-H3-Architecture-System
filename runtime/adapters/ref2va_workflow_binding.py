"""Additive compiler for the official native MiniMax H3 Ref2VA node.

The frozen Golden graph is only the structural base.  This module operates on
its copied API payload, swaps the conditioning contract in the execution copy,
and adds deterministic image loaders/slots.  It does not submit work and does
not modify any Golden workflow file.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Mapping

from runtime.reference_contract import (
    REF2VA_DEFAULT_IMAGE_SIZE, build_ref2va_reference_plan,
)

REF2VA_NODE = "MiniMaxH3ReferenceToVideo"
REF2VA_MODEL = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"


class Ref2VAWorkflowError(ValueError):
    """A requested A6 graph cannot be represented by the live native schema."""


def _node(payload: Mapping[str, Any], class_type: str) -> tuple[str, dict[str, Any]]:
    matches = [(str(key), value) for key, value in payload.items()
               if isinstance(value, Mapping) and value.get("class_type") == class_type]
    if len(matches) != 1:
        raise Ref2VAWorkflowError(
            f"REF2VA_GRAPH_NODE_COUNT:{class_type}:{len(matches)}")
    return matches[0][0], matches[0][1]


def _is_link(value: Any) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and isinstance(value[0], str) and isinstance(value[1], int))


def _enum_options(object_info: Mapping[str, Any], node_type: str,
                  field: str) -> list[str]:
    spec = (((object_info.get(node_type) or {}).get("input") or {})
            .get("required") or {}).get(field)
    if not isinstance(spec, (list, tuple)) or not spec:
        return []
    if (len(spec) > 1 and isinstance(spec[1], Mapping)
            and isinstance(spec[1].get("options"), (list, tuple))):
        return [str(value) for value in spec[1]["options"]
                if isinstance(value, str)]
    values: list[str] = []
    pending = [spec[0]]
    while pending:
        value = pending.pop(0)
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
        elif isinstance(value, str):
            values.append(value)
    return values


def _max_numeric_node_id(payload: Mapping[str, Any]) -> int:
    values = [int(key) for key in payload if str(key).isdigit()]
    return max(values, default=0)


def compile_ref2va_workflow(
        base_payload: Mapping[str, Any], references: list[Mapping[str, Any]],
        object_info: Mapping[str, Any], *, project_id: str,
        runtime_id: str, video_vae_available: bool = True,
        audio_vae_available: bool = False,
        reference_image_size: str = REF2VA_DEFAULT_IMAGE_SIZE,
        checkpoint: str = REF2VA_MODEL) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile an image-only Ref2VA graph and return its audit-safe slot plan.

    Native video/audio roles are represented by the typed reference contract,
    but this first A6 compiler intentionally refuses them until the product has
    safe media ingest/probing and a tested loader path for those modalities.
    """
    try:
        plan = build_ref2va_reference_plan(
            references, object_info, project_id=project_id, runtime_id=runtime_id,
            video_vae_available=video_vae_available,
            audio_vae_available=audio_vae_available,
            reference_image_size=reference_image_size)
    except ValueError as exc:
        raise Ref2VAWorkflowError(str(exc)) from exc
    if any(binding["media_type"] != "image" for binding in plan["bindings"]):
        raise Ref2VAWorkflowError(
            "REF2VA_MEDIA_INGEST_NOT_READY: video/audio reference loaders are not enabled")

    schema = object_info.get(REF2VA_NODE) or {}
    schema_inputs = schema.get("input") or {}
    required = schema_inputs.get("required") or {}
    optional = schema_inputs.get("optional") or {}
    if not {"clip", "prompt", "width", "height", "length",
            "ref_image_size"}.issubset(required):
        raise Ref2VAWorkflowError("REF2VA_SCHEMA_REQUIRED_INPUT_MISMATCH")
    if reference_image_size not in _enum_options(
            object_info, REF2VA_NODE, "ref_image_size"):
        raise Ref2VAWorkflowError(
            f"REF2VA_IMAGE_SIZE_UNAVAILABLE:{reference_image_size}")
    if "ref_images" not in optional or "vae" not in optional:
        raise Ref2VAWorkflowError("REF2VA_SCHEMA_IMAGE_OR_VAE_INPUT_MISSING")
    if list(schema.get("output") or [])[:2] != ["CONDITIONING", "LATENT"]:
        raise Ref2VAWorkflowError("REF2VA_SCHEMA_OUTPUT_MISMATCH")

    model_choices = _enum_options(object_info, "UNETLoader", "unet_name")
    if checkpoint not in model_choices:
        raise Ref2VAWorkflowError("REF2VA_CHECKPOINT_UNAVAILABLE")
    vae_choices = _enum_options(object_info, "VAELoader", "vae_name")
    if not any("video_vae" in value.lower() for value in vae_choices):
        raise Ref2VAWorkflowError("REF2VA_VIDEO_VAE_UNAVAILABLE")

    graph = copy.deepcopy(dict(base_payload))
    old_id, old_node = _node(graph, "MiniMaxH3ImageToVideo")
    h3_inputs = old_node.get("inputs") or {}
    clip_link = h3_inputs.get("clip")
    vae_link = h3_inputs.get("vae")
    if not _is_link(clip_link) or not _is_link(vae_link):
        raise Ref2VAWorkflowError("REF2VA_BASE_CLIP_OR_VIDEO_VAE_LINK_MISSING")
    if not video_vae_available:
        raise Ref2VAWorkflowError("REF2VA_VIDEO_VAE_REQUIRED_FOR_IMAGE_REFERENCES")

    unet_id, unet = _node(graph, "UNETLoader")
    unet_inputs = unet.setdefault("inputs", {})
    unet_inputs["unet_name"] = checkpoint

    # Remove the Golden image-conditioning node and all image loaders in the
    # execution copy.  Recreate LoadImage slots in a stable, role-sorted order.
    for node_id in [key for key, node in graph.items()
                    if node.get("class_type") in {"MiniMaxH3ImageToVideo", "LoadImage"}]:
        del graph[node_id]
    max_id = _max_numeric_node_id(graph)
    slot_links: dict[str, list[Any]] = {}
    load_nodes: list[str] = []
    for index, binding in enumerate(plan["bindings"]):
        reference = next((item for item in references
                          if str(item.get("id") or item.get("asset_id") or "")
                          == binding["asset_id"]), None)
        if reference is None:
            raise Ref2VAWorkflowError("REF2VA_ASSET_BINDING_LOST")
        filename = Path(str(reference.get("path_or_ref") or
                             reference.get("filename") or "")).name
        if not filename or filename in {".", ".."}:
            raise Ref2VAWorkflowError("REF2VA_ASSET_FILENAME_MISSING")
        loader_id = str(max_id + index + 1)
        graph[loader_id] = {
            "class_type": "LoadImage",
            "inputs": {"image": filename},
            "_meta": {"title": f"A6 approved reference {index + 1}"},
        }
        load_nodes.append(loader_id)
        slot_links[binding["native_input"]] = [loader_id, 0]

    prompt = str((old_node.get("inputs") or {}).get("prompt") or "")
    new_inputs = {
        "clip": clip_link,
        "vae": vae_link,
        "prompt": prompt,
        "width": (old_node.get("inputs") or {}).get("width"),
        "height": (old_node.get("inputs") or {}).get("height"),
        "length": (old_node.get("inputs") or {}).get("length"),
        "ref_image_size": reference_image_size,
        **slot_links,
    }
    if any(value is None for key, value in new_inputs.items()
           if key in {"width", "height", "length"}):
        raise Ref2VAWorkflowError("REF2VA_BASE_GENERATION_PARAMETERS_MISSING")
    graph[old_id] = {
        "class_type": REF2VA_NODE,
        "inputs": new_inputs,
        "_meta": {"title": "MiniMax H3 Reference to Video (A6)"},
    }
    unet_inputs["unet_name"] = checkpoint

    expected_declarations = [
        (binding["prompt_tag"], binding["role"])
        for binding in plan["bindings"]
    ]
    subject_definitions = prompt.split("\n\n", 1)[0]
    declaration_pattern = re.compile(
        r"(?P<tag><(?:Picture|Video|Audio)\s+[1-9][0-9]*>) is the "
        r"[^()\n]+ \((?P<role>[a-z][a-z0-9_]*)\)\."
    )
    declarations = [
        (match.group("tag"), match.group("role"))
        for match in declaration_pattern.finditer(subject_definitions)
    ]
    header_tags = re.findall(
        r"<(?:Picture|Video|Audio)\s+[1-9][0-9]*>", subject_definitions)
    declared_tags = [tag for tag, _ in declarations]
    expected_tags = [tag for tag, _ in expected_declarations]
    if (not subject_definitions.startswith("subject_definitions:")
            or header_tags != declared_tags or declared_tags != expected_tags):
        raise Ref2VAWorkflowError(
            "REF2VA_PROMPT_TAG_BINDING_MISMATCH")
    if declarations != expected_declarations:
        raise Ref2VAWorkflowError("REF2VA_PROMPT_ROLE_BINDING_MISMATCH")
    plan["graph"] = {
        "conditioning_node_id": old_id,
        "unet_node_id": unet_id,
        "load_image_node_ids": load_nodes,
        "ref2va_checkpoint": checkpoint,
    }
    return graph, plan


__all__ = ["REF2VA_MODEL", "REF2VA_NODE", "Ref2VAWorkflowError",
           "compile_ref2va_workflow"]
