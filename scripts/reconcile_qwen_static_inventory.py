"""CPU/meta reconciliation for the frozen and live H3 static inventories.

The frozen side reads only the safetensors header.  The live side constructs
the same Qwen meta architecture used by the pinned loader, applies the
Strategy-A language cast and the 350 Linear replacement, then enumerates the
same direct parameter/buffer slots used by ``_direct_tensor_slots``.  No
checkpoint tensor body, CUDA device, ModelPatcher, or inference is used.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DTYPE_BYTES = {
    "F16": 2,
    "BF16": 2,
    "F32": 4,
    "F64": 8,
    "I8": 1,
    "U8": 1,
    "I16": 2,
    "U16": 2,
    "I32": 4,
    "U32": 4,
    "I64": 8,
    "U64": 8,
    "BOOL": 1,
}
LINEAR_RE = re.compile(
    r"^language_model\.layers\.(\d+)\."
    r"(?:self_attn\.(?:q|k|v|o)_proj|mlp\.(?:gate|up|down)_proj)\."
)
LATER_RE = re.compile(r"^language_model\.layers\.(\d+)")


def read_header(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        raw = stream.read(8)
        if len(raw) != 8:
            raise ValueError("safetensors header length is missing")
        header_bytes = struct.unpack("<Q", raw)[0]
        header = stream.read(header_bytes)
        if len(header) != header_bytes:
            raise ValueError("safetensors header is truncated")
    return json.loads(header.decode("utf-8"))


def normalize(name: str) -> str:
    return name[6:] if name.startswith("model.") else name


def _shape_numel(shape: list[int] | tuple[int, ...]) -> int:
    result = 1
    for value in shape:
        result *= int(value)
    return result


def frozen_inventory(checkpoint: Path) -> dict[str, dict[str, Any]]:
    """Build the header-derived static inventory used by the old analyzer."""

    header = read_header(checkpoint)
    inventory: dict[str, dict[str, Any]] = {}
    for raw_name, info in sorted(header.items()):
        if not isinstance(info, dict) or "shape" not in info or "dtype" not in info:
            continue
        name = normalize(raw_name)
        layer = LATER_RE.match(name)
        if name.startswith("visual."):
            continue
        if name == "lm_head.weight" or (layer and int(layer.group(1)) >= 50):
            continue
        if LINEAR_RE.match(name):
            continue
        if not name.startswith("language_model."):
            continue
        shape = [int(value) for value in info["shape"]]
        numel = _shape_numel(shape)
        checkpoint_dtype = str(info["dtype"])
        if checkpoint_dtype not in DTYPE_BYTES:
            raise ValueError(f"unsupported checkpoint dtype: {checkpoint_dtype}")
        inventory[name] = {
            "name": name,
            "kind": "unknown_from_header",
            "owner_module": name.rsplit(".", 1)[0],
            "owner_class": "unknown_from_header",
            "shape": shape,
            "numel": numel,
            "dtype": "torch.bfloat16",
            "bytes": numel * 2,
            "checkpoint_dtype": checkpoint_dtype,
            "alias_group": "unknown_from_header",
            "included_reason": "header_language_static_after_trim_and_linear_exclusion",
        }
    return inventory


def _import_managed_runtime(runtime_root: Path) -> None:
    comfy_root = runtime_root / "ComfyUI"
    h3_root = comfy_root / "custom_nodes" / "ComfyUI_RH_MinMaxH3"
    if str(comfy_root) not in sys.path:
        sys.path.insert(0, str(comfy_root))
    if str(h3_root) not in sys.path:
        sys.path.insert(0, str(h3_root))


def _meta_qwen_model(component: Path, runtime_root: Path):
    """Construct the pinned INT8 Qwen architecture without checkpoint bodies."""

    _import_managed_runtime(runtime_root)
    import torch
    from accelerate import init_empty_weights
    from transformers import AutoConfig
    from minimax_h3_nodes.runtime.qwen_encoder.helpers import SELECTED_LAYERS
    from minimax_h3_nodes.runtime.qwen_encoder.loading import (
        _qwen_causal_lm_class,
        _swap_lang_linears,
        _validate_qwen_config,
    )
    from minimax_h3_nodes.runtime.model_loader import _require_int8_ops

    config = AutoConfig.from_pretrained(
        str(component), local_files_only=True, trust_remote_code=False
    )
    text_config = _validate_qwen_config(config, component)
    text_config.num_hidden_layers = SELECTED_LAYERS
    text_config.output_hidden_states = False
    text_config.use_cache = False
    config.output_hidden_states = False
    config.use_cache = False
    model_cls = _qwen_causal_lm_class()
    ops = _require_int8_ops(torch.bfloat16)
    # ``load_h3_text_encoder`` defaults to the pinned production backend.  The
    # config often exposes ``None`` before Transformers normalizes it; passing
    # that value back is not equivalent to the production call.
    attention_backend = "sdpa"
    with init_empty_weights():
        try:
            causal_lm = model_cls._from_config(
                config, attn_implementation=attention_backend
            )
        except Exception:
            causal_lm = model_cls(config)
    model = getattr(causal_lm, "model", None)
    if model is None:
        raise RuntimeError("Qwen3VL backbone missing .model")
    language_model = getattr(model, "language_model", None)
    if language_model is None:
        raise RuntimeError("Qwen3VL language_model missing")
    language_model.to(dtype=torch.bfloat16)
    layers = getattr(language_model, "layers", None)
    if layers is None or len(layers) != SELECTED_LAYERS:
        raise RuntimeError("trimmed language layer count mismatch")
    swapped = _swap_lang_linears(layers, ops.Linear, dtype=torch.bfloat16)
    if swapped != SELECTED_LAYERS * 7:
        raise RuntimeError(f"quantized Linear replacement count mismatch: {swapped}")
    language_model.norm = torch.nn.Identity()
    return model


def _is_streaming_linear(module: Any, path: str) -> bool:
    # The meta model has not yet received QuantizedTensor weights, so the
    # runtime helper's weight-type predicate cannot identify these modules at
    # this stage.  Use the pinned seven-projection ownership rule instead; it
    # is the same module set that `_swap_lang_linears` replaces.
    return bool(LINEAR_RE.match(path + ".weight"))


def live_meta_inventory(component: Path, runtime_root: Path) -> dict[str, dict[str, Any]]:
    model = _meta_qwen_model(component, runtime_root)
    roots = [(name, module) for name, module in model.named_children() if name != "visual"]
    excluded: set[int] = set()
    for root_name, root in roots:
        for subpath, module in root.named_modules():
            full_path = root_name if not subpath else f"{root_name}.{subpath}"
            if _is_streaming_linear(module, full_path):
                excluded.add(id(module))
    if len(excluded) != 350:
        raise RuntimeError(f"live meta exclusion count mismatch: {len(excluded)}")

    seen_modules: set[int] = set()
    seen_tensors: dict[int, str] = {}
    inventory: dict[str, dict[str, Any]] = {}
    for root_name, root in roots:
        for subpath, module in root.named_modules():
            module_id = id(module)
            if module_id in seen_modules or module_id in excluded:
                continue
            seen_modules.add(module_id)
            owner = root_name if not subpath else f"{root_name}.{subpath}"
            for collection_name in ("_parameters", "_buffers"):
                collection = getattr(module, collection_name, {})
                for slot, tensor in tuple(collection.items()):
                    if tensor is None:
                        continue
                    name = f"{owner}.{slot}"
                    tensor_id = id(tensor)
                    shape = [int(value) for value in tensor.shape]
                    dtype = str(tensor.dtype)
                    if dtype == "torch.bfloat16":
                        bytes_count = _shape_numel(shape) * 2
                    else:
                        bytes_count = int(tensor.numel()) * int(tensor.element_size())
                    inventory[name] = {
                        "name": name,
                        "kind": "parameter" if collection_name == "_parameters" else "buffer",
                        "owner_module": owner,
                        "owner_class": type(module).__name__,
                        "shape": shape,
                        "numel": int(tensor.numel()),
                        "dtype": dtype,
                        "bytes": bytes_count,
                        "alias_group": seen_tensors.get(tensor_id, f"tensor:{tensor_id}"),
                        "included_reason": "live_direct_slot_outside_350_streaming_linears",
                    }
                    seen_tensors.setdefault(tensor_id, name)
    return inventory


def compare(frozen: dict[str, dict[str, Any]], live: dict[str, dict[str, Any]]) -> dict[str, Any]:
    frozen_names = set(frozen)
    live_names = set(live)
    intersection = frozen_names & live_names
    return {
        "live_minus_frozen": sorted(live_names - frozen_names),
        "frozen_minus_live": sorted(frozen_names - live_names),
        "different_shape": sorted(name for name in intersection if frozen[name]["shape"] != live[name]["shape"]),
        "different_numel": sorted(name for name in intersection if frozen[name]["numel"] != live[name]["numel"]),
        "different_dtype": sorted(name for name in intersection if frozen[name]["dtype"] != live[name]["dtype"]),
        "different_ownership": sorted(
            name
            for name in intersection
            if frozen[name]["kind"] != "unknown_from_header"
            and frozen[name]["kind"] != live[name]["kind"]
        ),
        "frozen_count": len(frozen),
        "live_count": len(live),
        "frozen_bytes": sum(int(row["bytes"]) for row in frozen.values()),
        "live_bytes": sum(int(row["bytes"]) for row in live.values()),
        "frozen_dtype_distribution": dict(Counter(row["dtype"] for row in frozen.values())),
        "live_dtype_distribution": dict(Counter(row["dtype"] for row in live.values())),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--component", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    args = parser.parse_args()
    frozen = frozen_inventory(args.checkpoint.resolve())
    live = live_meta_inventory(args.component.resolve(), args.runtime_root.resolve())
    result = compare(frozen, live)
    result["frozen"] = frozen
    result["live"] = live
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
