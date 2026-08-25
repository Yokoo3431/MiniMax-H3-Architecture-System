"""Apply the audited Strategy A support patch to an existing managed H3 tree.

This is a deterministic support-layer reconciliation tool. It refuses an
unexpected source fingerprint, never touches model files, and is intentionally
separate from GPU/model loading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.support_layer import apply_unified_patch, source_tree_fingerprint


BASE_FINGERPRINT = "dc284a81848d7ac1759361c3e668c9bb23635a775d779b63f3356e6b04a57a6c"
PARTIAL_CANDIDATE_FINGERPRINT = "1dfa5dd836e30275e3fd31e5f4011042fbb1c2130905504611b04c038bc2635b"
FINAL_FINGERPRINT = "abd60d555fc6197a9b6e283f9e83379ac7143fb42469a20b6ef74bff6a0d737b"
MARGIN_FINAL_FINGERPRINT = "407325e1cdc31d9ed5b6c23f5a2a1f746a8292add9f302155dbecee3a57936bb"
BOUNDARY_FINAL_FINGERPRINT = "2ba065a0f5d68471cd621c87b458088b9dc4ee67e5d56abe7b360ecb662cd713"
HEADROOM_FINAL_FINGERPRINT = "7bddba2e20e87c4eda7fd4f13109eca57e66c5b46548ca406fa054e008da6c69"
FULL_PATCH = Path("patches/support_layers/minimax_h3_production_windows.patch")
INCREMENTAL_PATCH = Path("patches/support_layers/minimax_h3_strategy_a_incremental.patch")
IMPORT_INCREMENTAL_PATCH = Path("patches/support_layers/minimax_h3_strategy_a_import_incremental.patch")
MARGIN_PATCH = Path("patches/support_layers/minimax_h3_static_transfer_margin_incremental.patch")
BOUNDARY_PATCH = Path("patches/support_layers/minimax_h3_language_boundary_instrumentation_incremental.patch")
HEADROOM_PATCH = Path("patches/support_layers/minimax_h3_static_transfer_headroom_incremental.patch")
LOCK_RELATIVE = Path("ComfyUI/custom_nodes/support_layer.lock.json")
H3_RELATIVE = Path("ComfyUI/custom_nodes/ComfyUI_RH_MinMaxH3")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def reconcile(runtime_root: Path, repo_root: Path) -> dict:
    runtime_root = runtime_root.resolve()
    repo_root = repo_root.resolve()
    h3_root = runtime_root / H3_RELATIVE
    lock_path = runtime_root / LOCK_RELATIVE
    patch_path = repo_root / INCREMENTAL_PATCH
    import_patch_path = repo_root / IMPORT_INCREMENTAL_PATCH
    margin_patch_path = repo_root / MARGIN_PATCH
    boundary_patch_path = repo_root / BOUNDARY_PATCH
    headroom_patch_path = repo_root / HEADROOM_PATCH
    full_patch_path = repo_root / FULL_PATCH
    if not h3_root.is_dir() or not lock_path.is_file():
        raise RuntimeError("managed H3 tree or support lock is missing")
    if not all(path.is_file() for path in (
        patch_path, import_patch_path, margin_patch_path, boundary_patch_path,
        headroom_patch_path, full_patch_path
    )):
        raise RuntimeError("source-controlled H3 support patch is missing")

    before = source_tree_fingerprint(h3_root)
    expected_after = FINAL_FINGERPRINT
    strategy_reconciled = False
    if before == BASE_FINGERPRINT:
        apply_unified_patch(patch_path, h3_root)
        strategy_reconciled = True
    elif before == PARTIAL_CANDIDATE_FINGERPRINT:
        apply_unified_patch(import_patch_path, h3_root)
        strategy_reconciled = True
    elif before == FINAL_FINGERPRINT:
        apply_unified_patch(margin_patch_path, h3_root)
        expected_after = MARGIN_FINAL_FINGERPRINT
    elif before == MARGIN_FINAL_FINGERPRINT:
        apply_unified_patch(boundary_patch_path, h3_root)
        expected_after = BOUNDARY_FINAL_FINGERPRINT
    elif before == BOUNDARY_FINAL_FINGERPRINT:
        apply_unified_patch(headroom_patch_path, h3_root)
        expected_after = HEADROOM_FINAL_FINGERPRINT
    else:
        # A second invocation must not reapply hunks. Require the lock to
        # describe the observed tree, then fail closed for human review.
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        recorded = lock.get("h3", {}).get("source_tree_fingerprint")
        if recorded != before:
            raise RuntimeError(f"unexpected managed H3 fingerprint: {before}")
        raise RuntimeError("Strategy A is already applied; refusing duplicate reconciliation")

    if strategy_reconciled:
        strategy_after = source_tree_fingerprint(h3_root)
        if strategy_after != FINAL_FINGERPRINT:
            raise RuntimeError(
                f"Strategy A reconciliation produced unexpected fingerprint: {strategy_after}"
            )
        apply_unified_patch(margin_patch_path, h3_root)
        expected_after = MARGIN_FINAL_FINGERPRINT

    if expected_after == MARGIN_FINAL_FINGERPRINT:
        apply_unified_patch(boundary_patch_path, h3_root)
        expected_after = BOUNDARY_FINAL_FINGERPRINT
    if expected_after == BOUNDARY_FINAL_FINGERPRINT:
        apply_unified_patch(headroom_patch_path, h3_root)
        expected_after = HEADROOM_FINAL_FINGERPRINT

    after = source_tree_fingerprint(h3_root)
    if after != expected_after:
        raise RuntimeError(f"Strategy A patch produced unexpected fingerprint: {after}")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    h3 = lock.setdefault("h3", {})
    h3["project_patch_sha256"] = _sha256(full_patch_path).lower()
    h3["source_tree_fingerprint"] = after
    h3["strategy_a"] = {
        "status": "CPU_META_CANDIDATE_IMPLEMENTED",
        "target_dtype": "bfloat16",
        "scope": "ordinary language static tensors only",
        "visual_dtype": "preserved_fp32",
        "quantized_linear_contract": "preserved_350",
        "incremental_patch_sha256": _sha256(patch_path).lower(),
        "import_incremental_patch_sha256": _sha256(import_patch_path).lower(),
        "static_transfer_margin_patch_sha256": _sha256(margin_patch_path).lower(),
        "language_boundary_instrumentation_patch_sha256": _sha256(boundary_patch_path).lower(),
        "static_transfer_headroom_patch_sha256": _sha256(headroom_patch_path).lower(),
        "static_transfer_headroom": {
            "status": "CPU_STATIC_POLICY_IMPLEMENTED",
            "method": "ModelPatcher.partially_unload",
            "target_bytes": "static_storage_bytes + TE_GPU_HEADROOM",
            "requested_bytes": "min(loaded_size, target_bytes)",
            "before_static_transfer": True,
            "preserves_strategy_a": True,
        },
        "language_boundary_instrumentation": {
            "status": "OBSERVATIONAL_CPU_VALIDATED",
            "markers": [
                "LANGLOAD-01 BEFORE_LOAD_MODELS_GPU",
                "LANGLOAD-02 AFTER_LOAD_MODELS_GPU",
                "LANGLOAD-03 BEFORE_MOVE_STATIC",
                "LANGLOAD-04 AFTER_MOVE_STATIC",
            ],
            "preserves_original_traceback": True,
            "separates_pre_and_post_rollback_state": True,
        },
        "runtime_consumer_validation": "pending_human_authorized_gpu_gate",
    }
    h3["memory_policy"] = {
        "status": "CPU_META_POLICY_IMPLEMENTED",
        "name": "static_transfer_safety_margin",
        "formula": "max(0, fp32_equivalent_static_bytes - actual_static_storage_bytes)",
        "applies_when": "H3_LANGUAGE_STATIC_TARGET_DTYPE == bfloat16",
        "preserves": [
            "350 quantized Linears",
            "visual FP32",
            "Comfy ModelPatcher partial loading",
            "load_models_gpu before static transfer",
        ],
        "gpu_validation": "pending_human_authorized_gpu_gate",
        "patch_sha256": _sha256(margin_patch_path).lower(),
    }
    lock["verified_at"] = "2026-08-20T00:00:00+0800"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=lock_path.parent, delete=False
    ) as stream:
        json.dump(lock, stream, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(lock_path)
    return {
        "before_fingerprint": before,
        "after_fingerprint": after,
        "full_patch_sha256": _sha256(full_patch_path),
        "incremental_patch_sha256": _sha256(patch_path),
        "import_incremental_patch_sha256": _sha256(import_patch_path),
        "static_transfer_margin_patch_sha256": _sha256(margin_patch_path),
        "language_boundary_instrumentation_patch_sha256": _sha256(boundary_patch_path),
        "static_transfer_headroom_patch_sha256": _sha256(headroom_patch_path),
        "runtime_root": str(runtime_root),
        "model_files_modified": False,
        "gpu_executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.runtime_root, args.repo_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
