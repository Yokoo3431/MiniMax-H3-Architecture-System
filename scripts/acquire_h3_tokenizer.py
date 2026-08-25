"""Acquire the single pinned H3 tokenizer asset without touching weights.

This is an explicit R3 operation. It reuses InstallationService's HTTPS,
resume, size and SHA-256 verification, then atomically promotes only
tokenizer.json into the already selected converted H3 text-encoder directory.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.architect_video_studio.mock_api.installer_service import InstallationService, _sha256
from apps.architect_video_studio.mock_api.store import StudioStore
from runtime.h3_sidecar import load_h3_sidecar_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-root", required=True)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    models_root = Path(args.models_root).expanduser().resolve()
    manifest = load_h3_sidecar_manifest(repo_root)
    source = next(item for item in manifest["files"]
                  if item["path"] == "FL2VA/processor/tokenizer.json")
    target = models_root / "MiniMax-H3" / "FL2VA" / "text_encoder" / "tokenizer.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        actual = _sha256(target)
        if actual == str(source["sha256"]).upper():
            print(f"ALREADY_VALID {target}")
            return 0
        raise RuntimeError("TARGET_EXISTS_HASH_MISMATCH; refusing overwrite")
    if target.is_symlink():
        raise RuntimeError("TARGET_IS_LINK; refusing promotion")

    service = InstallationService(
        StudioStore(repo_root / "userdata" / "system"),
        repo_root=repo_root,
        cache_root=repo_root / "userdata" / "cache" / "downloads",
    )
    item = {
        "component_id": service.H3_SIDECAR_COMPONENT,
        "cache_name": "FL2VA__processor__tokenizer.json",
        "expected_size": int(source["expected_size"]),
        "sha256": str(source["sha256"]).upper(),
    }
    cache_dir = service.cache_root / service.H3_SIDECAR_COMPONENT
    cache_final = cache_dir / item["cache_name"]
    cache_part = cache_dir / (item["cache_name"] + ".part")
    if cache_part.is_file() and cache_part.stat().st_size == int(source["expected_size"]):
        if _sha256(cache_part) == str(source["sha256"]).upper():
            os.replace(cache_part, cache_final)
    cached = service._download_component(
        str(source["source_url"]), item, threading.Event(),
        job={"job_id": "r3-tokenizer", "bytes_downloaded": 0,
             "bytes_total": int(source["expected_size"]), "progress": 0.0},
    )
    installing = target.with_name(target.name + ".installing")
    if installing.exists():
        installing.unlink()
    shutil.copy2(cached, installing)
    if _sha256(installing) != str(source["sha256"]).upper():
        installing.unlink(missing_ok=True)
        raise RuntimeError("TOKENIZER_HASH_MISMATCH_BEFORE_PROMOTION")
    os.replace(installing, target)
    print(f"INSTALLED {target}")
    print(f"SHA256 {_sha256(target)}")
    print(f"BYTES {target.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
