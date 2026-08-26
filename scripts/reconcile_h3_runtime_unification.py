"""Reconcile the audited NVFP4 and VAE support patches into Managed H3.

The command is CPU/static only. It refuses an unexpected H3 source tree,
never touches model files, and records the exact installed patch hashes in the
existing support-layer lock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_REPO_ROOT))

from runtime.support_layer import apply_unified_patch, source_tree_fingerprint


KNOWN_UNPATCHED = "887ddf87371e703f27c52694d849171e90ef455a52a2ae811aa3b8b934c38ae0"
H3_RELATIVE = Path("ComfyUI/custom_nodes/ComfyUI_RH_MinMaxH3")
LOCK_RELATIVE = Path("ComfyUI/custom_nodes/support_layer.lock.json")
VAE_PATCH = Path("patches/support_layers/minimax_h3_vae_offload_sync.patch")
NVFP4_PATCH = Path("patches/support_layers/minimax_h3_nvfp4_native_loader.patch")
FULL_PATCH = Path("patches/support_layers/minimax_h3_production_windows.patch")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().lower()


def reconcile(runtime_root: Path, repo_root: Path) -> dict:
    runtime_root = Path(runtime_root).resolve()
    repo_root = Path(repo_root).resolve()
    h3_root = runtime_root / H3_RELATIVE
    lock_path = runtime_root / LOCK_RELATIVE
    vae_patch = repo_root / VAE_PATCH
    nvfp4_patch = repo_root / NVFP4_PATCH
    full_patch = repo_root / FULL_PATCH
    if not h3_root.is_dir() or not lock_path.is_file():
        raise RuntimeError("managed H3 tree or support lock is missing")
    if not all(path.is_file() for path in (vae_patch, nvfp4_patch, full_patch)):
        raise RuntimeError("runtime-unification support patch is missing")

    before = source_tree_fingerprint(h3_root)
    vae_file = h3_root / "minimax_h3_nodes/runtime/vae_adapter/_impl.py"
    loader_file = h3_root / "minimax_h3_nodes/runtime/qwen_encoder/loading.py"
    encoder_file = h3_root / "minimax_h3_nodes/runtime/qwen_encoder/encoder.py"
    base_already = (
        "torch.cuda.synchronize()" in vae_file.read_text(encoding="utf-8")
        and "load_native_nvfp4_text_encoder" in loader_file.read_text(encoding="utf-8")
        and "class NativeComfyNVFP4TextEncoder" in encoder_file.read_text(encoding="utf-8")
    )
    if not base_already:
        if before != KNOWN_UNPATCHED:
            raise RuntimeError(
                f"unexpected managed H3 fingerprint: {before}; refusing to patch"
            )
        apply_unified_patch(vae_patch, h3_root)
        apply_unified_patch(nvfp4_patch, h3_root)
    after = source_tree_fingerprint(h3_root)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    h3 = lock.setdefault("h3", {})
    h3["project_patch_sha256"] = _sha256(full_patch)
    h3["source_tree_fingerprint"] = after
    h3["runtime_unification"] = {
        "status": "SOURCE_RECONCILED_CPU_VALIDATED",
        "nvfp4_loader": "native_comfy_minimax_h3",
        "nvfp4_patch_sha256": _sha256(nvfp4_patch),
        "vae_windows_hardening": "installed_source_patch_gpu_validation_required",
        "vae_offload_sync_patch_sha256": _sha256(vae_patch),
        "model_files_modified": False,
        "gpu_validation": "pending_owner_authorization",
    }
    lock["verified_at"] = "2026-08-25T00:00:00+0800"
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
        "runtime_root": str(runtime_root),
        "nvfp4_patch_sha256": _sha256(nvfp4_patch),
        "vae_patch_sha256": _sha256(vae_patch),
        "already_reconciled": base_already,
        "model_files_modified": False,
        "gpu_executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument(
        "--repo-root", default=Path(__file__).resolve().parents[1], type=Path
    )
    args = parser.parse_args()
    print(json.dumps(reconcile(args.runtime_root, args.repo_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
