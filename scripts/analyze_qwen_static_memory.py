"""CPU-only static Qwen language-memory inventory.

The analyzer reads only the safetensors header and does not import Torch,
CUDA, ComfyUI, or the H3 loader.  It classifies the direct language tensors
that are outside the 350 streamable quantized Linear modules, matching the
classification used by the pinned H3 ``_direct_tensor_slots`` path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct


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
LINEAR_LEAVES = {
    "weight", "bias", "weight_scale", "weight_scale_2",
    "comfy_quant", "input_scale",
}
LINEAR_RE = re.compile(
    r"^language_model\.layers\.(\d+)\."
    r"(?:self_attn\.(?:q|k|v|o)_proj|mlp\.(?:gate|up|down)_proj)\."
    r"(.+)$"
)
LATER_RE = re.compile(r"^language_model\.layers\.(\d+)\.")


def _runtime_rotary_shape(checkpoint: Path) -> list[int]:
    """Derive the pinned Qwen text rotary buffer shape from local config."""

    config_path = checkpoint.parent / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    head_dim = int(config["text_config"]["head_dim"])
    if head_dim <= 0 or head_dim % 2:
        raise ValueError(f"invalid Qwen text head_dim: {head_dim}")
    return [head_dim // 2]


def read_header(path: Path) -> dict:
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


def group_for(local: str) -> str:
    if local.startswith("language_model.embed_tokens."):
        return "language_embeddings"
    if local.startswith("language_model.layers."):
        rest = local.split(".", 3)[3]
        if ".norm." in f".{rest}" or rest.endswith("norm.weight"):
            return "language_layer_norms"
        if ".rotary_emb." in f".{rest}":
            return "language_rotary_buffers"
        return "language_layer_static"
    if local.startswith("language_model."):
        return "language_static_other"
    return "non_language_or_excluded"


def analyze(path: Path, *, runtime_contract: bool = False) -> dict:
    header = read_header(path)
    rows = []
    excluded = {
        "visual": 0,
        "quantized_linear": 0,
        "later_layer_or_lm_head": 0,
        "other": 0,
        "runtime_removed_language_norm": 0,
    }
    for name, info in sorted(header.items()):
        if not isinstance(info, dict) or "shape" not in info or "dtype" not in info:
            continue
        local = normalize(name)
        layer_match = LATER_RE.match(local)
        if local.startswith("visual."):
            excluded["visual"] += 1
            continue
        if local == "lm_head.weight" or (layer_match and int(layer_match.group(1)) >= 50):
            excluded["later_layer_or_lm_head"] += 1
            continue
        linear_match = LINEAR_RE.match(local)
        if linear_match and linear_match.group(2) in LINEAR_LEAVES:
            excluded["quantized_linear"] += 1
            continue
        if not local.startswith("language_model."):
            excluded["other"] += 1
            continue
        if runtime_contract and local == "language_model.norm.weight":
            # The pinned loader replaces language_model.norm with Identity
            # after the streamed checkpoint assignment, so this checkpoint
            # key is not a live direct slot in the wrapper inventory.
            excluded["runtime_removed_language_norm"] += 1
            continue
        dtype = str(info["dtype"])
        checkpoint_bytes_per_element = DTYPE_BYTES.get(dtype)
        if checkpoint_bytes_per_element is None:
            raise ValueError(f"unsupported dtype in header: {dtype}")
        elements = 1
        for dimension in info["shape"]:
            elements *= int(dimension)
        # _from_config creates ordinary non-Linear parameters as FP32 meta
        # tensors in the pinned loader. _stream_load_quantized_backbone casts
        # floating checkpoint values to the target parameter dtype. Strategy A
        # is a source-controlled BF16 target candidate for this same set.
        target_dtype = "F32"
        target_bytes = elements * DTYPE_BYTES[target_dtype]
        candidate_target_dtype = "BF16"
        candidate_target_bytes = elements * DTYPE_BYTES[candidate_target_dtype]
        rows.append({
            "name": name,
            "local_name": local,
            "owner_group": group_for(local),
            "checkpoint_dtype": dtype,
            "target_dtype_from_pinned_loader": target_dtype,
            "strategy_a_candidate_target_dtype": candidate_target_dtype,
            "shape": [int(x) for x in info["shape"]],
            "elements": elements,
            "checkpoint_bytes": elements * checkpoint_bytes_per_element,
            "estimated_target_bytes": target_bytes,
            "strategy_a_candidate_bytes": candidate_target_bytes,
            "expected_target_device": "cuda during load_for_inference",
            "classification": "STATIC_DIRECT_TENSOR",
        })

    if runtime_contract:
        rotary_shape = _runtime_rotary_shape(path)
        rotary_elements = 1
        for dimension in rotary_shape:
            rotary_elements *= dimension
        rotary_bytes = rotary_elements * DTYPE_BYTES["BF16"]
        for local in (
            "language_model.rotary_emb.inv_freq",
            "language_model.rotary_emb.original_inv_freq",
        ):
            rows.append({
                "name": local,
                "local_name": local,
                "owner_group": "language_rotary_buffers",
                "checkpoint_dtype": None,
                "target_dtype_from_pinned_loader": "BF16",
                "strategy_a_candidate_target_dtype": "BF16",
                "shape": rotary_shape,
                "elements": rotary_elements,
                "checkpoint_bytes": 0,
                "estimated_target_bytes": rotary_elements * DTYPE_BYTES["F32"],
                "strategy_a_candidate_bytes": rotary_bytes,
                "expected_target_device": "cuda during load_for_inference",
                "classification": "RUNTIME_GENERATED_STATIC_BUFFER",
            })
        excluded["runtime_generated_buffers"] = 2

    groups = {}
    for row in rows:
        group = groups.setdefault(row["owner_group"], {
            "owner_group": row["owner_group"],
            "tensor_count": 0,
            "elements": 0,
            "checkpoint_bytes": 0,
            "estimated_target_bytes": 0,
            "checkpoint_dtypes": {},
            "target_dtypes": {},
            "strategy_a_candidate_dtypes": {},
            "strategy_a_candidate_bytes": 0,
            "expected_target_device": "cuda during load_for_inference",
            "names": [],
        })
        group["tensor_count"] += 1
        group["elements"] += row["elements"]
        group["checkpoint_bytes"] += row["checkpoint_bytes"]
        group["estimated_target_bytes"] += row["estimated_target_bytes"]
        group["checkpoint_dtypes"][row["checkpoint_dtype"]] = group["checkpoint_dtypes"].get(row["checkpoint_dtype"], 0) + 1
        group["target_dtypes"][row["target_dtype_from_pinned_loader"]] = group["target_dtypes"].get(row["target_dtype_from_pinned_loader"], 0) + 1
        group["strategy_a_candidate_dtypes"][row["strategy_a_candidate_target_dtype"]] = group["strategy_a_candidate_dtypes"].get(row["strategy_a_candidate_target_dtype"], 0) + 1
        group["strategy_a_candidate_bytes"] += row["strategy_a_candidate_bytes"]
        group["names"].append(row["local_name"])

    return {
        "schema_version": 1,
        "analysis": "CPU_STATIC_HEADER_PLUS_PINNED_RUNTIME_CONTRACT" if runtime_contract else "CPU_STATIC_HEADER_ONLY",
        "runtime_contract": runtime_contract,
        "checkpoint": str(path),
        "checkpoint_size_bytes": path.stat().st_size,
        "no_tensor_bodies_loaded": True,
        "no_torch_or_cuda_import": True,
        "selected_layers": 50,
        "quantized_linear_contract": 350,
        "static_tensor_count": len(rows),
        "static_estimated_target_bytes": sum(row["estimated_target_bytes"] for row in rows),
        "strategy_a_candidate_target_dtype": "BF16",
        "strategy_a_candidate_bytes": sum(row["strategy_a_candidate_bytes"] for row in rows),
        "static_checkpoint_bytes": sum(row["checkpoint_bytes"] for row in rows),
        "groups": [groups[key] for key in sorted(groups)],
        "tensors": rows,
        "excluded_header_entries": excluded,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument(
        "--runtime-contract",
        action="store_true",
        help="apply the pinned post-trim runtime ownership contract",
    )
    args = parser.parse_args()
    print(json.dumps(analyze(args.checkpoint.resolve(), runtime_contract=args.runtime_contract), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
